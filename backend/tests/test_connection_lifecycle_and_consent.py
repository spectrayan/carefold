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

"""Unit and API tests for Connection Lifecycle, Sync Engine, 4-Step Revoke Cascade & Consent Matrix (AU-52, AU-53)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.api.connections import router as connections_router
from carefold.api.deps import get_current_user, get_db
from carefold.auth.ports import UserProfile
from carefold.connectors.lifecycle import (
    check_scope_and_terms_compatibility,
    check_under_13_connection_guard,
    get_profile_data_flows,
    grant_connector_consent,
    record_sync_failure,
    revoke_connection,
)
from carefold.connectors.oauth import store_connection_tokens
from carefold.connectors.sync import run_connection_sync
from carefold.db.base import Base
from carefold.db.models import (
    AuditEventRecord,
    Connection,
    ConsentGrant,
    Credential,
    HealthResource,
    Job,
    Profile,
    SyncRun,
    User,
    utc_now,
)
from connectors.base import NormalisedRecord, Page, StreamSpec, ToolContext
from connectors.http import ScopedHttp


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides an isolated in-memory SQLite AsyncSession for lifecycle and consent tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session

    await engine.dispose()


class _StubSyncConnector:
    """In-memory test connector supporting mixed valid and malformed records for quarantine verification."""

    def __init__(self, raw_records: List[Dict[str, Any]], should_fail: Optional[Exception] = None) -> None:
        self._raw_records = raw_records
        self._should_fail = should_fail

    def streams(self) -> List[StreamSpec]:
        return [StreamSpec(name="measures", read_mode="incremental", primary_key=["id"])]

    async def fetch(
        self,
        ctx: ToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        if self._should_fail is not None:
            raise self._should_fail
        return Page(
            stream=stream,
            records=list(self._raw_records),
            next_cursor="cursor_next_100",
            has_more=False,
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        out: List[NormalisedRecord] = []
        for rec in page.records:
            if rec.get("corrupted"):
                raise ValueError("Malformed upstream measurement record: missing numeric value")
            data = {
                "resourceType": "Observation",
                "code": rec["code"],
                "value": rec["value"],
                "unit": rec.get("unit", "mmHg"),
            }
            raw_hash = hashlib.sha256(
                json.dumps(data, sort_keys=True).encode("utf-8")
            ).hexdigest()
            out.append(
                NormalisedRecord(
                    id=str(rec["id"]),
                    stream=page.stream,
                    profile_id="prof-sync",
                    source="withings",
                    record_type="observation",
                    timestamp=datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc),
                    data=data,
                    raw_hash=raw_hash,
                )
            )
        return out


@pytest.mark.asyncio
async def test_six_state_connection_lifecycle_transitions(db_session: AsyncSession) -> None:
    """Verifies pending_auth -> active -> 3 failures -> degraded -> success -> active -> invalid_grant -> needs_reauth."""
    kek = os.urandom(32)
    user = User(id="u-life-1", email="life@example.com", username="life", hashed_password="pw")
    profile = Profile(id="p-life-1", user_id=user.id, name="Primary")
    conn = Connection(
        id="c-life-1",
        user_id=user.id,
        profile_id=profile.id,
        connector_id="withings",
        status="pending_auth",
    )
    db_session.add_all([user, profile, conn])
    await db_session.commit()
    assert conn.status == "pending_auth"

    # 1. Storing tokens transitions pending_auth -> active
    await store_connection_tokens(
        session=db_session,
        profile_id=profile.id,
        connection_id=conn.id,
        user_id=user.id,
        token_payload={"access_token": "tok_1", "refresh_token": "ref_1"},
        kek=kek,
    )
    await grant_connector_consent(
        session=db_session,
        profile_id=profile.id,
        connector_id="withings",
        categories=["vitals"],
        scopes=["user.metrics"],
        allowed_hosts=["wbsapi.withings.net", "account.withings.com"],
        granted_by_user_id=user.id,
        connection_id=conn.id,
    )
    await db_session.refresh(conn)
    assert conn.status == "active"
    assert conn.consecutive_failures == 0

    # 2. Three consecutive transient failures transition active -> degraded (DESIGN §5.5)
    st1 = await record_sync_failure(db_session, conn, "network_error", "Timeout 1")
    assert st1 == "active"
    assert conn.consecutive_failures == 1

    st2 = await record_sync_failure(db_session, conn, "network_error", "Timeout 2")
    assert st2 == "active"
    assert conn.consecutive_failures == 2

    st3 = await record_sync_failure(db_session, conn, "network_error", "Timeout 3")
    assert st3 == "degraded"
    assert conn.consecutive_failures == 3

    # 3. Successful sync recovers degraded -> active and resets consecutive_failures = 0
    stub_ok = _StubSyncConnector(
        raw_records=[{"id": "obs-1", "code": "85354-9", "value": 120}]
    )
    sync_run = await run_connection_sync(
        session=db_session,
        connection_id=conn.id,
        connector=stub_ok,
        kek=kek,
    )
    assert sync_run.status == "succeeded"
    await db_session.refresh(conn)
    assert conn.status == "active"
    assert conn.consecutive_failures == 0

    # 4. OAuth invalid_grant transitions active -> needs_reauth immediately
    st_reauth = await record_sync_failure(
        db_session,
        conn,
        "invalid_grant",
        "Refresh token revoked",
    )
    assert st_reauth == "needs_reauth"
    assert conn.status == "needs_reauth"


@pytest.mark.asyncio
async def test_scope_host_expansion_reconsent_and_ai_use_prohibited(
    db_session: AsyncSession,
) -> None:
    """Verifies scope/host expansion triggers needs_reauth and ai_use_allowed=False revokes connection."""
    user = User(id="u-compat-1", email="compat@example.com", username="compat", hashed_password="pw")
    profile = Profile(id="p-compat-1", user_id=user.id, name="Compat")
    conn = Connection(
        id="c-compat-1",
        user_id=user.id,
        profile_id=profile.id,
        connector_id="withings",
        status="active",
        consented_version="0.1.0",
    )
    db_session.add_all([user, profile, conn])
    await db_session.commit()

    await grant_connector_consent(
        session=db_session,
        profile_id=profile.id,
        connector_id="withings",
        categories=["vitals"],
        scopes=["user.metrics"],
        allowed_hosts=["wbsapi.withings.net"],
        granted_by_user_id=user.id,
        connection_id=conn.id,
        connector_version="0.1.0",
    )

    # Matching scopes and hosts -> compatible
    ok, reason = await check_scope_and_terms_compatibility(
        session=db_session,
        connection=conn,
        manifest_version="0.1.0",
        required_scopes=["user.metrics"],
        required_hosts=["wbsapi.withings.net"],
        ai_use_allowed=True,
    )
    assert ok is True
    assert reason is None

    # Scope expansion -> transitions to needs_reauth
    ok_scope, reason_scope = await check_scope_and_terms_compatibility(
        session=db_session,
        connection=conn,
        manifest_version="0.2.0",
        required_scopes=["user.metrics", "user.activity.write"],
        required_hosts=["wbsapi.withings.net"],
        ai_use_allowed=True,
    )
    assert ok_scope is False
    assert reason_scope == "reconsent_required"
    assert conn.status == "needs_reauth"

    # Host expansion -> transitions to needs_reauth
    conn.status = "active"
    ok_host, reason_host = await check_scope_and_terms_compatibility(
        session=db_session,
        connection=conn,
        manifest_version="0.2.0",
        required_scopes=["user.metrics"],
        required_hosts=["wbsapi.withings.net", "telemetry.thirdparty.example"],
        ai_use_allowed=True,
    )
    assert ok_host is False
    assert reason_host == "reconsent_required"
    assert conn.status == "needs_reauth"

    # Vendor terms disallowing AI use -> transitions to revoked
    ok_ai, reason_ai = await check_scope_and_terms_compatibility(
        session=db_session,
        connection=conn,
        manifest_version="0.3.0",
        required_scopes=["user.metrics"],
        required_hosts=["wbsapi.withings.net"],
        ai_use_allowed=False,
    )
    assert ok_ai is False
    assert reason_ai == "ai_use_prohibited"
    assert conn.status == "revoked"
    assert "prohibit AI use" in (conn.status_message or "")


def test_under_13_connection_guard_enforcement() -> None:
    """Verifies under-13 pediatric profile connection guard (E12.2)."""
    child_profile = Profile(
        id="p-child-10",
        name="Leo",
        relationship="child",
        date_of_birth="2020-05-10",
    )
    check_under_13_connection_guard(child_profile, user_role="guardian")
    check_under_13_connection_guard(child_profile, user_role="steward")

    with pytest.raises(PermissionError, match="under-13"):
        check_under_13_connection_guard(child_profile, user_role="viewer")

    with pytest.raises(PermissionError, match="under-13"):
        check_under_13_connection_guard(child_profile, user_role="child")


@pytest.mark.asyncio
async def test_run_connection_sync_idempotent_upsert_and_per_record_quarantine(
    db_session: AsyncSession,
) -> None:
    """Verifies per-record quarantine (DESIGN §15) and idempotent HealthResource upserts during sync."""
    user = User(id="u-sync-1", email="sync@example.com", username="sync", hashed_password="pw")
    profile = Profile(id="p-sync-1", user_id=user.id, name="SyncUser")
    conn = Connection(
        id="c-sync-1",
        user_id=user.id,
        profile_id=profile.id,
        connector_id="withings",
        status="active",
    )
    db_session.add_all([user, profile, conn])
    await db_session.commit()

    await grant_connector_consent(
        session=db_session,
        profile_id=profile.id,
        connector_id="withings",
        categories=["vitals"],
        scopes=["user.metrics"],
        allowed_hosts=["wbsapi.withings.net", "account.withings.com"],
        granted_by_user_id=user.id,
        connection_id=conn.id,
    )

    # Batch with 2 valid records and 1 malformed record
    mixed_connector = _StubSyncConnector(
        raw_records=[
            {"id": "rec-bp-1", "code": "8480-6", "value": 118},
            {"id": "rec-bad-2", "corrupted": True},
            {"id": "rec-hr-3", "code": "8867-4", "value": 68},
        ]
    )

    run1 = await run_connection_sync(
        session=db_session,
        connection_id=conn.id,
        connector=mixed_connector,
    )
    assert run1.status == "partial"
    assert run1.records_fetched == 3
    assert run1.records_upserted == 2
    assert run1.records_quarantined == 1
    assert conn.sync_cursor == "cursor_next_100"

    # Re-running with updated value on rec-bp-1 must idempotently upsert (still 2 total rows)
    updated_connector = _StubSyncConnector(
        raw_records=[
            {"id": "rec-bp-1", "code": "8480-6", "value": 122},
            {"id": "rec-hr-3", "code": "8867-4", "value": 68},
        ]
    )
    run2 = await run_connection_sync(
        session=db_session,
        connection_id=conn.id,
        connector=updated_connector,
    )
    assert run2.status == "succeeded"
    assert run2.records_quarantined == 0
    assert run2.records_upserted == 2

    hr_res = await db_session.execute(
        select(HealthResource).where(
            HealthResource.profile_id == profile.id,
            HealthResource.source_type == "connector",
            HealthResource.source_ref == conn.id,
        )
    )
    resources = list(hr_res.scalars().all())
    assert len(resources) == 2
    by_source_id = {r.source_id: r for r in resources}
    assert by_source_id["rec-bp-1"].data["value"] == 122

    # Verify index_doc Job was enqueued
    job_res = await db_session.execute(
        select(Job).where(Job.profile_id == profile.id, Job.kind == "index_doc")
    )
    assert len(list(job_res.scalars().all())) >= 1


@pytest.mark.asyncio
async def test_four_step_revoke_connection_cascade(db_session: AsyncSession) -> None:
    """Verifies the 4-step revoke cascade (Titan S2): consents revoked, sync jobs cancelled, credentials shredded, optional data deletion."""
    kek = os.urandom(32)
    user = User(id="u-rev-1", email="rev@example.com", username="rev", hashed_password="pw")
    profile = Profile(id="p-rev-1", user_id=user.id, name="RevokeUser")
    conn = Connection(
        id="c-rev-1",
        user_id=user.id,
        profile_id=profile.id,
        connector_id="withings",
        status="active",
    )
    sync_job = Job(
        id="j-sync-rev-1",
        profile_id=profile.id,
        connection_id=conn.id,
        kind="sync",
        next_run_at=utc_now(),
        status="pending",
    )
    imported_hr = HealthResource(
        id="hr-rev-1",
        profile_id=profile.id,
        resource_type="observation",
        source_type="connector",
        source_ref=conn.id,
        source_id="ext-1",
        data={"resourceType": "Observation", "value": 120},
        effective_at=utc_now(),
    )
    db_session.add_all([user, profile, conn, sync_job, imported_hr])
    await db_session.commit()

    await store_connection_tokens(
        session=db_session,
        profile_id=profile.id,
        connection_id=conn.id,
        user_id=user.id,
        token_payload={"access_token": "tok_secret", "refresh_token": "ref_secret"},
        kek=kek,
    )
    await grant_connector_consent(
        session=db_session,
        profile_id=profile.id,
        connector_id="withings",
        categories=["vitals"],
        scopes=["user.metrics"],
        allowed_hosts=["wbsapi.withings.net"],
        granted_by_user_id=user.id,
        connection_id=conn.id,
    )

    # First revoke with delete_imported_data=False: keeps HealthResource, shreds Credential & cancels Job
    res_keep = await revoke_connection(
        session=db_session,
        profile_id=profile.id,
        connection_id=conn.id,
        actor_user_id=user.id,
        delete_imported_data=False,
    )
    assert res_keep["status"] == "revoked"
    assert res_keep["consents_revoked"] == 1
    assert res_keep["jobs_cancelled"] == 1
    assert res_keep["credentials_deleted"] == 1
    assert res_keep["resources_deleted"] == 0

    cred_check = await db_session.execute(
        select(Credential).where(Credential.connection_id == conn.id)
    )
    assert cred_check.scalar_one_or_none() is None

    job_check = await db_session.execute(
        select(Job).where(Job.connection_id == conn.id, Job.kind == "sync")
    )
    assert job_check.scalar_one_or_none() is None

    hr_check_1 = await db_session.execute(
        select(HealthResource).where(HealthResource.source_ref == conn.id)
    )
    assert hr_check_1.scalar_one_or_none() is not None

    # Second revoke with delete_imported_data=True: purges HealthResource and sets status='deleted'
    res_purge = await revoke_connection(
        session=db_session,
        profile_id=profile.id,
        connection_id=conn.id,
        actor_user_id=user.id,
        delete_imported_data=True,
    )
    assert res_purge["status"] == "deleted"
    assert res_purge["resources_deleted"] == 1

    hr_check_2 = await db_session.execute(
        select(HealthResource).where(HealthResource.source_ref == conn.id)
    )
    assert hr_check_2.scalar_one_or_none() is None

    audit_check = await db_session.execute(
        select(AuditEventRecord).where(
            AuditEventRecord.profile_id == profile.id,
            AuditEventRecord.event == "connection_revoked",
        )
    )
    audits = list(audit_check.scalars().all())
    assert len(audits) == 2
    assert audits[0].risk == "irreversible"


@pytest.mark.asyncio
async def test_connections_rest_api_and_cross_profile_isolation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies FastAPI endpoints for catalog, connections, oauth-callback, sync, sync-runs, consents, data-flows, revoke, and cross-profile isolation."""
    kek_hex = os.urandom(32).hex()
    monkeypatch.setenv("CAREFOLD_MASTER_KEY", kek_hex)

    user_alice = User(id="u-api-alice", email="alice@example.com", username="alice", hashed_password="pw")
    user_bob = User(id="u-api-bob", email="bob@example.com", username="bob", hashed_password="pw")
    prof_alice = Profile(id="p-api-alice", user_id=user_alice.id, name="Alice")
    prof_bob = Profile(id="p-api-bob", user_id=user_bob.id, name="Bob")
    db_session.add_all([user_alice, user_bob, prof_alice, prof_bob])
    await db_session.commit()

    now_utc = utc_now()
    current_actor = {
        "user": UserProfile(
            id=user_alice.id,
            username="alice",
            email="alice@example.com",
            role="steward",
            created_at=now_utc,
            updated_at=now_utc,
        )
    }

    app = FastAPI()
    app.include_router(connections_router, prefix="/api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _override_user() -> UserProfile:
        return current_actor["user"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. GET /api/v1/connectors/catalog
        cat_resp = await client.get("/api/v1/connectors/catalog")
        assert cat_resp.status_code == 200
        cat_data = cat_resp.json()
        connector_ids = {c["id"] for c in cat_data["connectors"]}
        assert {"withings", "google-calendar", "caldav", "epic-smart"}.issubset(connector_ids)

        # 2. POST /api/v1/profiles/{profile_id}/connections
        create_resp = await client.post(
            f"/api/v1/profiles/{prof_alice.id}/connections",
            json={
                "connector_id": "withings",
                "label": "Alice Withings Scale",
                "categories": ["vitals"],
                "scopes": ["user.metrics"],
                "purpose": "sync_and_assist",
                "terms_version": "1.0.0",
                "client_id": "byo-withings-client",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        conn_id = created["connection"]["id"]
        state_token = created["state"]
        assert created["connection"]["status"] == "pending_auth"
        assert "code_challenge=" in created["authorization_url"]
        assert created["redirect_uri"] == "http://127.0.0.1:8000/api/v1/oauth/callback"

        # 3. POST /api/v1/profiles/{profile_id}/connections/{connection_id}/oauth-callback
        cb_resp = await client.post(
            f"/api/v1/profiles/{prof_alice.id}/connections/{conn_id}/oauth-callback",
            json={
                "code": "auth_code_xyz",
                "state": state_token,
            },
        )
        assert cb_resp.status_code == 200
        assert cb_resp.json()["connection"]["status"] == "active"

        # 4. POST /api/v1/profiles/{profile_id}/connections/{connection_id}/sync
        sync_resp = await client.post(
            f"/api/v1/profiles/{prof_alice.id}/connections/{conn_id}/sync"
        )
        assert sync_resp.status_code == 200
        assert sync_resp.json()["sync_run"]["status"] == "succeeded"

        # 5. GET /api/v1/profiles/{profile_id}/connections/{connection_id}/sync-runs
        runs_resp = await client.get(
            f"/api/v1/profiles/{prof_alice.id}/connections/{conn_id}/sync-runs"
        )
        assert runs_resp.status_code == 200
        assert len(runs_resp.json()["sync_runs"]) == 1

        # 6. GET /api/v1/profiles/{profile_id}/consents
        consents_resp = await client.get(f"/api/v1/profiles/{prof_alice.id}/consents")
        assert consents_resp.status_code == 200
        assert len(consents_resp.json()["consents"]) == 1
        assert consents_resp.json()["consents"][0]["connector_id"] == "withings"

        # 7. GET /api/v1/profiles/{profile_id}/data-flows
        flows_resp = await client.get(f"/api/v1/profiles/{prof_alice.id}/data-flows")
        assert flows_resp.status_code == 200
        flows = flows_resp.json()
        assert flows["profile_id"] == prof_alice.id
        assert flows["model_provider"]["is_local"] is True
        assert flows["search_provider"]["phi_sanitiser_enabled"] is True
        assert len(flows["connections"]) == 1
        assert flows["connections"][0]["connector_id"] == "withings"

        # 8. Cross-profile isolation: Bob cannot read or revoke Alice's connection
        current_actor["user"] = UserProfile(
            id=user_bob.id,
            username="bob",
            email="bob@example.com",
            role="steward",
            created_at=now_utc,
            updated_at=now_utc,
        )
        bob_list = await client.get(f"/api/v1/profiles/{prof_alice.id}/connections")
        assert bob_list.status_code == 403

        bob_revoke = await client.post(
            f"/api/v1/profiles/{prof_alice.id}/connections/{conn_id}/revoke",
            json={"delete_imported_data": True},
        )
        assert bob_revoke.status_code == 403

        # 9. Alice revokes her connection
        current_actor["user"] = UserProfile(
            id=user_alice.id,
            username="alice",
            email="alice@example.com",
            role="steward",
            created_at=now_utc,
            updated_at=now_utc,
        )
        alice_revoke = await client.post(
            f"/api/v1/profiles/{prof_alice.id}/connections/{conn_id}/revoke",
            json={"delete_imported_data": False},
        )
        assert alice_revoke.status_code == 200
        assert alice_revoke.json()["status"] == "revoked"
