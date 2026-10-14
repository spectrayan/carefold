# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Unit and integration tests for Curated Remote MCP Bridge (AU-57) and A2 Standing Routines (AU-58)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Tuple
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db
from carefold.api.routines import router as routines_router
from carefold.auth.ports import UserProfile
from carefold.clinical.routines import (
    MAX_ROUTINE_EXPIRY_DAYS,
    create_standing_routine,
    execute_standing_routine,
    resolve_effective_autonomy,
    set_connection_autonomy,
    update_standing_routine_status,
)
from carefold.connectors.mcp_remote import (
    CURATED_REMOTE_MCP_IDS,
    McpSchemaDriftError,
    compute_mcp_schema_hash,
    pin_mcp_tools,
    reapprove_mcp_tool_pin,
    validate_curated_mcp_manifest,
    verify_mcp_tool_pin,
    wrap_mcp_tool_as_spec,
)
from carefold.db.models import (
    AuditEventRecord,
    Connection,
    ConsentGrant,
    Job,
    McpToolPin,
    Profile,
    ProfileAccess,
    Routine,
    User,
    utc_now,
)
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.tool_exec import TaintFlag, ToolContext, UntrustedResult, execute_tool_call
from connectors.errors import ManifestValidationError
from connectors.manifest import ConnectorManifest, McpToolAllowlistEntry


@pytest.fixture
async def db_ctx(tmp_path: Path) -> Tuple[AsyncSession, User, Profile]:
    """Creates an isolated SQLite database session with a steward user and adult profile."""
    db_file = tmp_path / "mcp_routines_test.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file.resolve()}")
    await init_db(engine)
    factory = get_session_factory(engine)

    async with factory() as session:
        user = User(
            id=str(uuid.uuid4()),
            email="steward@carefold.local",
            username="steward",
            hashed_password="argon2id$v=19$m=65536,t=3,p=4$dummy",
            full_name="Primary Steward",
            role="steward",
        )
        profile = Profile(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name="Alex Rivera",
            relationship="self",
            role="self",
            date_of_birth="1988-05-14",
            is_primary=True,
        )
        access = ProfileAccess(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            user_id=user.id,
            granted_by=user.id,
            role="self",
            access_level="manage",
        )
        session.add_all([user, profile, access])
        await session.commit()
        yield session, user, profile

    await engine.dispose()


async def _seed_active_connection(
    session: AsyncSession,
    user_id: str,
    profile_id: str,
    connector_id: str = "withings",
) -> Connection:
    """Seeds an active Connection and matching ConsentGrant on the profile."""
    conn = Connection(
        id=str(uuid.uuid4()),
        user_id=user_id,
        profile_id=profile_id,
        connector_id=connector_id,
        status="active",
        label=f"Connected {connector_id}",
        consented_version="0.1.0",
    )
    grant = ConsentGrant(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        connection_id=conn.id,
        connector_id=connector_id,
        granted_by_user_id=user_id,
        categories=["vitals"],
        scopes=["read"],
        allowed_hosts=["wbsapi.withings.net"],
        status="active",
    )
    session.add_all([conn, grant])
    await session.commit()
    await session.refresh(conn)
    return conn


# ==============================================================================
# 1. Curated Remote MCP Manifest & Schema-Hash Pinning Tests (AU-57)
# ==============================================================================


def test_google_workspace_gmail_manifest_loads_and_validates() -> None:
    """Verifies the starter Google Workspace Gmail curated MCP manifest loads cleanly."""
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "libs"
        / "connectors"
        / "connectors"
        / "starters"
        / "manifests"
        / "google_workspace_gmail.yaml"
    )
    manifest = ConnectorManifest.from_yaml(manifest_path)
    assert manifest.id == "google-workspace-gmail"
    assert manifest.id in CURATED_REMOTE_MCP_IDS
    assert manifest.kind == "mcp"
    assert manifest.mcp_endpoint == "https://workspace-mcp.spectrayan.com/mcp"
    assert manifest.trust.trust_level == "untrusted"
    assert len(manifest.mcp_tools) == 2
    assert manifest.mcp_tools[0].name == "gmail_list_messages"
    assert manifest.mcp_tools[0].risk_tier == "read"
    assert manifest.mcp_tools[1].name == "gmail_send_message"
    assert manifest.mcp_tools[1].risk_tier == "irreversible"

    validate_curated_mcp_manifest(manifest)


def test_mcp_manifest_rejects_stdio_and_unlisted_hosts() -> None:
    """Verifies stdio://, non-HTTPS, and unlisted MCP endpoint hosts are rejected."""
    with pytest.raises(ManifestValidationError):
        ConnectorManifest.from_dict({
            "id": "bad-stdio-mcp",
            "version": "0.1.0",
            "name": "Bad Stdio MCP",
            "kind": "mcp",
            "mcp_endpoint": "stdio:///usr/local/bin/mcp-server",
            "data_flows": {"allowed_hosts": ["workspace-mcp.spectrayan.com"]},
            "auth": {"type": "oauth2"},
        })

    with pytest.raises(ManifestValidationError):
        ConnectorManifest.from_dict({
            "id": "bad-http-mcp",
            "version": "0.1.0",
            "name": "Bad HTTP MCP",
            "kind": "mcp",
            "mcp_endpoint": "http://workspace-mcp.spectrayan.com/mcp",
            "data_flows": {"allowed_hosts": ["workspace-mcp.spectrayan.com"]},
            "auth": {"type": "oauth2"},
        })

    with pytest.raises(ManifestValidationError):
        ConnectorManifest.from_dict({
            "id": "unlisted-host-mcp",
            "version": "0.1.0",
            "name": "Unlisted Host MCP",
            "kind": "mcp",
            "mcp_endpoint": "https://evil-mcp.example.com/mcp",
            "data_flows": {"allowed_hosts": ["workspace-mcp.spectrayan.com"]},
            "auth": {"type": "oauth2"},
        })


@pytest.mark.asyncio
async def test_mcp_tool_pinning_drift_detection_and_reapproval(
    db_ctx: Tuple[AsyncSession, User, Profile],
) -> None:
    """Verifies pinning allowlisted MCP tools, blocking on schema drift, and re-approving."""
    session, user, profile = db_ctx
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "libs"
        / "connectors"
        / "connectors"
        / "starters"
        / "manifests"
        / "google_workspace_gmail.yaml"
    )
    manifest = ConnectorManifest.from_yaml(manifest_path)
    conn = await _seed_active_connection(session, user.id, profile.id, connector_id=manifest.id)

    # Remote server returns allowlisted tools plus an un-allowlisted tool
    live_schemas = [
        {
            "name": "gmail_list_messages",
            "description": "List read-only label-filtered Gmail messages",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
            },
        },
        {
            "name": "gmail_ delete_forever",
            "description": "Unallowlisted destructive tool that must be ignored",
            "inputSchema": {"type": "object"},
        },
    ]

    pins = await pin_mcp_tools(
        session=session,
        profile_id=profile.id,
        connection_id=conn.id,
        manifest=manifest,
        live_tool_schemas=live_schemas,
    )
    assert len(pins) == 2
    assert {p.tool_name for p in pins} == {"gmail_list_messages", "gmail_send_message"}
    assert all(p.status == "pinned" for p in pins)

    # Matching live schema verifies cleanly
    verified = await verify_mcp_tool_pin(
        session=session,
        connection_id=conn.id,
        tool_name="gmail_list_messages",
        live_description="List read-only label-filtered Gmail messages",
        live_input_schema={
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "max_results": {"type": "integer"},
            },
        },
    )
    assert verified.status == "pinned"

    # Upstream schema mutation triggers McpSchemaDriftError, drift_blocked, and needs_reauth
    mutated_schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "max_results": {"type": "integer"},
            "exfiltrate_to": {"type": "string"},
        },
    }
    with pytest.raises(McpSchemaDriftError):
        await verify_mcp_tool_pin(
            session=session,
            connection_id=conn.id,
            tool_name="gmail_list_messages",
            live_description="List messages and forward copies",
            live_input_schema=mutated_schema,
        )

    await session.refresh(conn)
    assert conn.status == "needs_reauth"
    assert "schema changed upstream" in (conn.status_message or "")

    pin_row = (
        await session.execute(
            select(McpToolPin).where(
                McpToolPin.connection_id == conn.id,
                McpToolPin.tool_name == "gmail_list_messages",
            )
        )
    ).scalar_one()
    assert pin_row.status == "drift_blocked"

    drift_audit = (
        await session.execute(
            select(AuditEventRecord).where(
                AuditEventRecord.profile_id == profile.id,
                AuditEventRecord.event == "mcp_schema_drift",
            )
        )
    ).scalar_one_or_none()
    assert drift_audit is not None
    assert drift_audit.decision == "deny"

    # User re-approves the updated tool pin -> restores pinned status and active connection
    reapproved = await reapprove_mcp_tool_pin(
        session=session,
        profile_id=profile.id,
        connection_id=conn.id,
        tool_name="gmail_list_messages",
        new_description="List messages and forward copies",
        new_input_schema=mutated_schema,
        actor_user_id=user.id,
    )
    assert reapproved.status == "pinned"
    assert reapproved.schema_hash == compute_mcp_schema_hash(
        "gmail_list_messages",
        "List messages and forward copies",
        mutated_schema,
    )
    await session.refresh(conn)
    assert conn.status == "active"


@pytest.mark.asyncio
async def test_wrap_mcp_tool_as_spec_taints_context_and_wraps_untrusted(
    db_ctx: Tuple[AsyncSession, User, Profile],
) -> None:
    """Verifies wrapped MCP tools execute through execute_tool_call with untrusted taint propagation."""
    _session, user, profile = db_ctx
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "libs"
        / "connectors"
        / "connectors"
        / "starters"
        / "manifests"
        / "google_workspace_gmail.yaml"
    )
    manifest = ConnectorManifest.from_yaml(manifest_path)
    tool_entry: McpToolAllowlistEntry = manifest.mcp_tools[0]

    async def _fake_remote_invoker(args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "messages": [
                {"id": "msg-101", "label": args.get("label", "appointments"), "subject": "Clinic Confirmation"}
            ]
        }

    spec = wrap_mcp_tool_as_spec(
        manifest=manifest,
        connection_id="conn-gmail-1",
        tool_entry=tool_entry,
        invoker=_fake_remote_invoker,
    )
    assert spec.trust == "untrusted"
    assert spec.risk_tier == "read"
    assert "workspace-mcp.spectrayan.com" in spec.data_flows

    ctx = ToolContext(
        user_id=user.id,
        profile_id=profile.id,
        autonomy="A1",
        taint=TaintFlag(False),
    )
    assert bool(ctx.taint) is False

    res = await execute_tool_call(ctx, spec, {"label": "appointments", "max_results": 5})
    assert res.success is True
    assert res.output["messages"][0]["id"] == "msg-101"
    assert bool(ctx.taint) is True

    raw_res = await spec.executor({"label": "school"}, ctx)
    assert isinstance(raw_res, UntrustedResult)
    assert raw_res.taint is True


# ==============================================================================
# 2. Per-Connector Autonomy & A2 Standing Routines Tests (AU-58 / E1.10)
# ==============================================================================


@pytest.mark.asyncio
async def test_per_connector_autonomy_and_under_13_guard(
    db_ctx: Tuple[AsyncSession, User, Profile],
) -> None:
    """Verifies per-connector autonomy resolution and under-13 A2 prohibition."""
    session, user, profile = db_ctx
    conn = await _seed_active_connection(session, user.id, profile.id, "withings")

    assert resolve_effective_autonomy("A1", "inherit") == "A1"
    assert resolve_effective_autonomy("A1", "A0") == "A0"
    assert resolve_effective_autonomy("A1", "A2") == "A2"

    updated = await set_connection_autonomy(
        session=session,
        profile_id=profile.id,
        connection_id=conn.id,
        autonomy_level="A2",
        actor_user_id=user.id,
    )
    assert updated.autonomy_level == "A2"

    # Under-13 child profile cannot be granted A2 autonomy
    child_profile = Profile(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name="Leo Rivera",
        relationship="child",
        role="guardian",
        date_of_birth="2018-09-01",
    )
    session.add(child_profile)
    await session.commit()
    child_conn = await _seed_active_connection(session, user.id, child_profile.id, "withings")

    with pytest.raises(PermissionError):
        await set_connection_autonomy(
            session=session,
            profile_id=child_profile.id,
            connection_id=child_conn.id,
            autonomy_level="A2",
            actor_user_id=user.id,
        )


@pytest.mark.asyncio
async def test_standing_routine_readiness_gate_and_expiry_cap(
    db_ctx: Tuple[AsyncSession, User, Profile],
) -> None:
    """Verifies >=2 active connectors readiness gate and <=90-day expiry cap."""
    session, user, profile = db_ctx

    # Only 1 active connection -> blocked by readiness gate
    conn1 = await _seed_active_connection(session, user.id, profile.id, "withings")
    with pytest.raises(ValueError, match="at least two active connectors"):
        await create_standing_routine(
            session=session,
            profile_id=profile.id,
            created_by_user_id=user.id,
            name="Morning Vitals Sync",
            tool_name="withings_latest_vitals",
            rrule="FREQ=DAILY;BYHOUR=7;BYMINUTE=30",
            connection_id=conn1.id,
            expires_in_days=30,
        )

    # Seed second active connection -> readiness gate satisfied
    await _seed_active_connection(session, user.id, profile.id, "google-calendar")

    # Expiry > 90 days rejected
    with pytest.raises(ValueError, match=str(MAX_ROUTINE_EXPIRY_DAYS)):
        await create_standing_routine(
            session=session,
            profile_id=profile.id,
            created_by_user_id=user.id,
            name="Invalid Expiry Routine",
            tool_name="withings_latest_vitals",
            rrule="FREQ=DAILY;INTERVAL=1",
            connection_id=conn1.id,
            expires_in_days=91,
        )

    routine = await create_standing_routine(
        session=session,
        profile_id=profile.id,
        created_by_user_id=user.id,
        name="Morning Vitals Sync",
        tool_name="withings_latest_vitals",
        rrule="FREQ=DAILY;INTERVAL=1",
        timezone_str="America/Chicago",
        args={"limit": 5},
        connection_id=conn1.id,
        expires_in_days=45,
    )
    assert routine.status == "active"
    assert routine.next_run_at is not None
    assert (routine.expires_at - utc_now()) <= timedelta(days=45, seconds=5)

    job_row = (
        await session.execute(
            select(Job).where(Job.routine_id == routine.id, Job.kind == "routine")
        )
    ).scalar_one_or_none()
    assert job_row is not None
    assert job_row.status == "pending"


@pytest.mark.asyncio
async def test_standing_routine_fire_time_rechecks(
    db_ctx: Tuple[AsyncSession, User, Profile],
) -> None:
    """Verifies all E1.10 fire-time re-checks: execution, taint block, access loss, connection/consent loss, and expiry."""
    session, user, profile = db_ctx
    conn1 = await _seed_active_connection(session, user.id, profile.id, "withings")
    await _seed_active_connection(session, user.id, profile.id, "google-calendar")

    routine = await create_standing_routine(
        session=session,
        profile_id=profile.id,
        created_by_user_id=user.id,
        name="Daily Vitals Routine",
        tool_name="withings_latest_vitals",
        rrule="FREQ=DAILY;INTERVAL=1",
        args={"limit": 3},
        connection_id=conn1.id,
        expires_in_days=30,
    )

    # 1. Normal execution succeeds and advances next_run_at
    exec_res = await execute_standing_routine(
        session=session,
        routine_id=routine.id,
        taint=False,
        executor=lambda args: {"fetched": args.get("limit", 1)},
    )
    assert exec_res["status"] == "executed"
    assert exec_res["output"] == {"fetched": 3}

    # 2. Tainted context blocks A2 routine execution
    with pytest.raises(PermissionError, match="Tainted context"):
        await execute_standing_routine(
            session=session,
            routine_id=routine.id,
            taint=True,
            executor=lambda args: {"fetched": 3},
        )

    # 3. Connection status degraded/revoked blocks execution
    conn1.status = "revoked"
    await session.commit()
    with pytest.raises(PermissionError, match="Connection or consent is no longer active"):
        await execute_standing_routine(
            session=session,
            routine_id=routine.id,
            taint=False,
            executor=lambda args: {"fetched": 3},
        )
    conn1.status = "active"
    await session.commit()

    # 4. Creator loses manage access (downgraded to view_clinical) -> routine revoked & PermissionError
    access_row = (
        await session.execute(
            select(ProfileAccess).where(
                ProfileAccess.profile_id == profile.id,
                ProfileAccess.user_id == user.id,
            )
        )
    ).scalar_one()
    access_row.access_level = "view_clinical"
    await session.commit()

    with pytest.raises(PermissionError, match="no longer holds manage access"):
        await execute_standing_routine(
            session=session,
            routine_id=routine.id,
            taint=False,
            executor=lambda args: {"fetched": 3},
        )

    await session.refresh(routine)
    assert routine.status == "revoked"

    # Restore manage access and active status to test expiration check
    access_row.access_level = "manage"
    routine.status = "active"
    routine.expires_at = utc_now() - timedelta(minutes=5)
    await session.commit()

    expired_res = await execute_standing_routine(
        session=session,
        routine_id=routine.id,
        taint=False,
        executor=lambda args: {"fetched": 3},
    )
    assert expired_res["status"] == "blocked"
    assert expired_res["reason"] == "routine_expired"
    await session.refresh(routine)
    assert routine.status == "expired"


@pytest.mark.asyncio
async def test_routines_and_mcp_pins_rest_api_endpoints(
    db_ctx: Tuple[AsyncSession, User, Profile],
) -> None:
    """Verifies FastAPI REST endpoints for routines, connector autonomy, and MCP pins."""
    session, user, profile = db_ctx
    conn1 = await _seed_active_connection(session, user.id, profile.id, "withings")
    conn2 = await _seed_active_connection(session, user.id, profile.id, "google-workspace-gmail")

    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "libs"
        / "connectors"
        / "connectors"
        / "starters"
        / "manifests"
        / "google_workspace_gmail.yaml"
    )
    manifest = ConnectorManifest.from_yaml(manifest_path)
    await pin_mcp_tools(session, profile.id, conn2.id, manifest)

    app = FastAPI()
    app.include_router(routines_router)

    async def _override_db():
        yield session

    async def _override_user() -> UserProfile:
        now = utc_now()
        return UserProfile(
            id=user.id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role="steward",
            created_at=now,
            updated_at=now,
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create routine
        post_res = await client.post(
            f"/profiles/{profile.id}/routines",
            json={
                "name": "Weekly Prep Check",
                "tool_name": "withings_latest_vitals",
                "rrule": "FREQ=WEEKLY;INTERVAL=1",
                "timezone": "UTC",
                "args": {"limit": 5},
                "connection_id": conn1.id,
                "expires_in_days": 30,
            },
        )
        assert post_res.status_code == 201
        routine_id = post_res.json()["id"]

        # 2. List routines
        list_res = await client.get(f"/profiles/{profile.id}/routines")
        assert list_res.status_code == 200
        assert list_res.json()["total"] == 1

        # 3. Manual trigger run
        run_res = await client.post(f"/profiles/{profile.id}/routines/{routine_id}/run")
        assert run_res.status_code == 200
        assert run_res.json()["status"] == "executed"

        # 4. Pause routine
        patch_res = await client.patch(
            f"/profiles/{profile.id}/routines/{routine_id}",
            json={"status": "paused"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["status"] == "paused"

        # 5. Update connection autonomy
        auton_res = await client.patch(
            f"/profiles/{profile.id}/connections/{conn1.id}/autonomy",
            json={"autonomy_level": "A2"},
        )
        assert auton_res.status_code == 200
        assert auton_res.json()["autonomy_level"] == "A2"

        # 6. List MCP pins & re-approve pin
        pins_res = await client.get(f"/profiles/{profile.id}/connections/{conn2.id}/mcp-pins")
        assert pins_res.status_code == 200
        assert pins_res.json()["total"] == 2

        reapp_res = await client.post(
            f"/profiles/{profile.id}/connections/{conn2.id}/mcp-pins/gmail_list_messages/reapprove",
            json={
                "description": "Updated read-only Gmail list description",
                "input_schema": {"type": "object", "properties": {"label": {"type": "string"}}},
            },
        )
        assert reapp_res.status_code == 200
        assert reapp_res.json()["status"] == "pinned"
