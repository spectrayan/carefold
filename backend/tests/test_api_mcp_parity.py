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

"""Comprehensive 1:1 API <-> MCP parity, governed DB-operator routing, and FHIR toolbox tests (#344)."""

from __future__ import annotations

import ast
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, FastAPI, Query
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import event, select
import yaml

import carefold  # noqa: F401
from carefold.api.router import create_api_router
from carefold.clinical.db_hooks import CAREFOLD_DB_TOOLS_YAML, register_carefold_db_toolbox
from carefold.clinical.mcp_parity import (
    ALIAS_ROUTE_MAP,
    TRANSPORT_ONLY_ENDPOINT_ALLOWLIST,
    ParityViolationError,
    SchemaParityViolationError,
    get_endpoint_mcp_parity_registry,
    verify_fastapi_mcp_parity,
    verify_rest_mcp_schema_parity,
)
from carefold.db.models import HealthResource, HealthResourceVersion, Note
from carefold.engine.tool_registry import create_default_registry
from carefold.errors import YarvelleError
from carefold.main import create_app
from yarvelle_core.api.deps import DEFAULT_STEWARD_USER, get_current_user
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.db.models import Approval, AuditEventRecord, Connection, Profile, ProfileAccess, User
from yarvelle_core.db.session import get_db
from yarvelle_core.engine.tool_registry import ToolSpec, ToolSpecRegistry
from yarvelle_core.schemas.tool_spec import RESERVED_TOOL_CONTEXT_PARAMS
from yarvelle_core.tools.mcp_db_toolbox import McpDatabaseToolbox, get_db_toolbox

CAREFOLD_SRC = Path(__file__).resolve().parents[1] / "src" / "carefold"


# ============================================================================
# 1. Automated Route-to-MCP Parity Contract Tests (AC #1 & AC #5)
# ============================================================================


def test_all_carefold_fastapi_routes_have_1_to_1_mcp_tool_or_documented_transport_allowlist() -> None:
    report = verify_fastapi_mcp_parity()
    assert report.canonical_domain_routes == 153
    assert report.alias_routes == len(ALIAS_ROUTE_MAP)
    assert report.transport_allowlisted_routes == len(TRANSPORT_ONLY_ENDPOINT_ALLOWLIST)
    assert (
        report.canonical_domain_routes
        + report.alias_routes
        + report.transport_allowlisted_routes
        + report.unversioned_mirror_routes
        == report.total_inspected_routes
    )

    # Confirm all domain surfaces explicitly called out in #344 have registered MCP tools
    reg = create_default_registry()
    required_domain_tools = (
        "activity_list_timeline",
        "activity_undo_event",
        "handover_get_viewer_sections",
        "handover_update_viewer_sections",
        "handover_execute_teen_handover",
        "companion_list_devices",
        "companion_revoke_device",
        "companion_pair_initiate",
        "companion_pair_complete",
        "companion_list_reminders",
        "companion_sync_records",
        "routines_list",
        "routines_create",
        "routines_update",
        "routines_run",
        "coordinated_verify_audit_chain",
        "coordinated_discover_smart_slots",
        "coordinated_zocdoc_preview",
        "coordinated_send_email_draft",
        "connectors_get_v2_catalog",
        "approvals_list",
        "approvals_get",
        "approvals_decide",
        "memory_recall",
        "memory_get_status",
        "memory_get",
        "memory_put",
        "memory_delete",
        "memory_delete_all",
        "vitals_create",
        "vitals_list",
        "vitals_get_trends",
        "appointments_create",
        "appointments_list",
        "notes_create_profile_typed",
        "notes_extract_profile_adhoc",
        "reminders_create",
        "preventive_get_checklist",
        "prep_pack_generate",
        "imports_stage_batch",
        "school_forms_create",
        "connections_list",
        "profiles_create",
        "attachments_list",
        "email_drafts_create",
        "search_profile_records",
        "agents_list",
        "skills_list",
        "audit_list_events",
        "models_list",
        "chat_get_threads",
        "fhir_get_capabilities",
        "fhir_r4_search_resources",
        "fhir_read_resource",
        "fhir_upsert_resource",
    )
    for tool_name in required_domain_tools:
        spec = reg.get(tool_name)
        assert spec is not None, f"Expected '{tool_name}' in default ToolSpecRegistry"
        assert callable(spec.executor)


def test_parity_verifier_fails_closed_when_unmapped_domain_endpoint_added() -> None:
    test_app = create_app()
    rogue_router = APIRouter()

    @rogue_router.post("/profiles/{profile_id}/vitals/unmapped-calibration")
    async def rogue_calibrate(profile_id: str) -> Dict[str, Any]:
        return {"profile_id": profile_id, "calibrated": True}

    test_app.include_router(rogue_router, prefix="/api/v1")

    with pytest.raises(
        ParityViolationError,
        match=r"POST /api/v1/profiles/\{profile_id\}/vitals/unmapped-calibration",
    ):
        verify_fastapi_mcp_parity(app=test_app)


# ============================================================================
# 2. Automated REST <-> MCP Schema Parity Contract Tests (AC #2 & AC #5)
# ============================================================================


def test_all_153_rest_and_mcp_tool_schemas_match_without_drift() -> None:
    verified = verify_rest_mcp_schema_parity()
    assert len(verified) == 153

    reg = create_default_registry()
    for contract in get_endpoint_mcp_parity_registry().values():
        spec = reg.get(contract.spec.tool_name)
        assert spec is not None
        props = set((spec.parameters or {}).get("properties", {}).keys())
        assert not (props & RESERVED_TOOL_CONTEXT_PARAMS), (
            f"Tool '{spec.name}' leaked reserved context params into inputSchema: "
            f"{props & RESERVED_TOOL_CONTEXT_PARAMS}"
        )


def test_schema_parity_verifier_fails_closed_on_rest_or_mcp_schema_divergence() -> None:
    base_reg = create_default_registry()

    def _clone_registry_with_mutated_spec(target_name: str, new_params: Dict[str, Any]) -> ToolSpecRegistry:
        mutated_reg = ToolSpecRegistry()
        for item in base_reg.list_all():
            if item.name == target_name:
                mutated_reg.register(
                    ToolSpec(
                        name=item.name,
                        description=item.description,
                        parameters=new_params,
                        risk_tier=item.risk_tier,
                        trust=item.trust,
                        scopes=item.scopes,
                        data_flows=item.data_flows,
                        executor=item.executor,
                    )
                )
            else:
                mutated_reg.register(item)
        return mutated_reg

    vitals_spec = base_reg.get("vitals_create")
    assert vitals_spec is not None

    # Case A: Missing property on MCP tool
    missing_prop_params = copy.deepcopy(vitals_spec.parameters)
    missing_prop_params["properties"].pop("source_type", None)
    with pytest.raises(SchemaParityViolationError, match=r"vitals_create.*property mismatch"):
        verify_rest_mcp_schema_parity(registry=_clone_registry_with_mutated_spec("vitals_create", missing_prop_params))

    # Case B: Required-fields drift
    req_drift_params = copy.deepcopy(vitals_spec.parameters)
    req_drift_params["required"] = ["vitals", "source_type"]
    with pytest.raises(SchemaParityViolationError, match=r"vitals_create.*required mismatch"):
        verify_rest_mcp_schema_parity(registry=_clone_registry_with_mutated_spec("vitals_create", req_drift_params))

    # Case C: Property type/default drift
    type_drift_params = copy.deepcopy(vitals_spec.parameters)
    type_drift_params["properties"]["source_type"] = {"type": "integer", "default": 99}
    with pytest.raises(SchemaParityViolationError, match=r"vitals_create\.source_type.*schema mismatch"):
        verify_rest_mcp_schema_parity(registry=_clone_registry_with_mutated_spec("vitals_create", type_drift_params))

    # Case D: REST route adds a new query parameter without updating declarative MCP YAML
    drifted_app = FastAPI()
    drifted_app.include_router(create_api_router(), prefix="/api/v1")
    override_router = APIRouter()

    @override_router.get("/profiles/{profile_id}/activity")
    async def drifted_activity(
        profile_id: str,
        limit: int = Query(default=50),
        untracked_filter: str = Query(default="all"),
    ) -> Dict[str, Any]:
        return {"profile_id": profile_id, "limit": limit, "untracked_filter": untracked_filter}

    drifted_app.include_router(override_router, prefix="/api/v1")
    with pytest.raises(SchemaParityViolationError, match=r"activity_list_timeline.*untracked_filter"):
        verify_rest_mcp_schema_parity(app=drifted_app, registry=base_reg)


# ============================================================================
# 3. Governed DB Routing & User-Intended HTTP Mutation Guard (AC #3)
# ============================================================================


def _extract_http_error_code(resp: Any) -> str | None:
    body = resp.json()
    if isinstance(body, dict):
        if body.get("error_code"):
            return str(body["error_code"])
        if body.get("cfd_code"):
            return str(body["cfd_code"])
        if body.get("code"):
            return str(body["code"])
        issues = body.get("issue")
        if isinstance(issues, list) and issues:
            coding = ((issues[0] or {}).get("details") or {}).get("coding") or []
            if coding and isinstance(coding[0], dict) and coding[0].get("code"):
                return str(coding[0]["code"])
        if resp.status_code == 422 and isinstance(body.get("detail"), list):
            return "YRV-100-003"
    return None


def test_ast_zero_raw_orm_sessions_in_carefold_tools_and_tool_registry() -> None:
    forbidden_call_names = {"get_session_factory", "async_sessionmaker", "AsyncSession"}
    forbidden_orm_methods = {"add", "add_all", "commit", "delete", "flush"}

    targets = sorted((CAREFOLD_SRC / "tools").glob("*.py")) + [
        CAREFOLD_SRC / "engine" / "tool_registry.py"
    ]
    assert len(targets) >= 11

    for py_file in targets:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("sqlalchemy"), (
                        f"{py_file.name} imports sqlalchemy directly ('{alias.name}')"
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not mod.startswith("sqlalchemy"), (
                    f"{py_file.name} imports from sqlalchemy directly ('{mod}')"
                )
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in forbidden_call_names, (
                        f"{py_file.name} invokes raw DB session constructor '{node.func.id}()'"
                    )
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in forbidden_call_names, (
                        f"{py_file.name} invokes raw DB session constructor '.{node.func.attr}()'"
                    )
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id in {"session", "db"}:
                    assert node.attr not in forbidden_orm_methods, (
                        f"{py_file.name} performs direct ORM '{node.value.id}.{node.attr}(...)' bypassing McpDatabaseToolbox"
                    )


@pytest.mark.asyncio
async def test_runtime_all_agent_db_reads_and_writes_route_through_mcp_database_toolbox(
    async_db_session_factory: Any,
    profile_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_carefold_db_toolbox()
    profile = await profile_factory(profile_id="prof-gov-344", name="Maya Steward", relationship="self")

    recorded_calls: List[Tuple[str, str]] = []
    orig_execute = McpDatabaseToolbox.execute

    async def _spy_execute(self: McpDatabaseToolbox, tool_name: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        cfg = self.get_tool_config(tool_name)
        tier = cfg.risk_tier if cfg is not None else "unknown"
        recorded_calls.append((tool_name, tier))
        return await orig_execute(self, tool_name, *args, **kwargs)

    monkeypatch.setattr(McpDatabaseToolbox, "execute", _spy_execute)

    reg = create_default_registry()
    ctx = SimpleNamespace(
        profile_id=profile.id,
        user_id=DEFAULT_STEWARD_USER.id,
        session_factory=async_db_session_factory,
    )

    now = datetime.now(timezone.utc)
    start_iso = (now + timedelta(days=3)).isoformat()
    end_iso = (now + timedelta(days=3, hours=1)).isoformat()

    # Exercise both legacy pack tools and new 1:1 API parity MCP wrappers
    await reg.get("record_vitals").executor({"vitals_data": {"heart_rate": 72}}, ctx)
    await reg.get("create_appointment").executor(
        {"title": "Primary Care Checkup", "start_time": start_iso, "end_time": end_iso},
        ctx,
    )
    await reg.get("create_typed_note").executor(
        {"title": "Visit Questions", "content": "Ask about vitamin D.", "type": "question"},
        ctx,
    )
    await reg.get("fhir_search_resources").executor({"resource_type": "Observation"}, ctx)
    await reg.get("vitals_create").executor({"vitals": {"systolic": 118, "diastolic": 76}}, ctx)
    await reg.get("activity_list_timeline").executor({"limit": 10}, ctx)

    executed_tool_names = [name for name, _ in recorded_calls]
    assert "carefold_domain_write" in executed_tool_names
    assert "carefold_domain_read" in executed_tool_names
    assert len(recorded_calls) >= 6

    tiers_by_tool = dict(recorded_calls)
    assert tiers_by_tool["carefold_domain_read"] == "read"
    assert tiers_by_tool["carefold_domain_write"] == "write_local"


@pytest.mark.asyncio
async def test_http_mutation_routes_reject_agent_principals_with_yrv_300_013(
    async_db_session_factory: Any,
    profile_factory: Any,
) -> None:
    profile = await profile_factory(profile_id="prof-http-guard-344", name="Guard User")
    app = create_app()

    async def _override_get_db():
        async with async_db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: DEFAULT_STEWARD_USER

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Agent principal attempting HTTP POST/PUT/PATCH/DELETE is blocked with 403 YRV-300-013
        for principal in ("agent", "db-operator", "mcp_agent"):
            resp = await client.post(
                f"/api/v1/profiles/{profile.id}/vitals",
                headers={"X-Carefold-Principal": principal},
                json={"vitals": {"heart_rate": 75}},
            )
            assert resp.status_code == 403, resp.text
            assert _extract_http_error_code(resp) == "YRV-300-013"

        # User-intended HTTP POST without agent principal succeeds
        ok_resp = await client.post(
            f"/api/v1/profiles/{profile.id}/vitals",
            json={"vitals": {"heart_rate": 75}},
        )
        assert ok_resp.status_code in (200, 201), ok_resp.text


# ============================================================================
# 4. Shared Schema, Auth Isolation, Behavioral & Error-Code Parity (AC #1 & #2)
# ============================================================================


@pytest.mark.asyncio
async def test_behavioral_auth_and_error_code_parity_across_domain_surfaces(
    async_db_session_factory: Any,
) -> None:
    register_carefold_db_toolbox()
    reg = create_default_registry()

    now_utc = datetime.now(timezone.utc)
    alice = UserProfile(
        id="user-alice-344",
        email="alice@carefold.local",
        username="alice344",
        full_name="Alice",
        role="member",
        created_at=now_utc,
        updated_at=now_utc,
    )
    bob = UserProfile(
        id="user-bob-344",
        email="bob@carefold.local",
        username="bob344",
        full_name="Bob",
        role="member",
        created_at=now_utc,
        updated_at=now_utc,
    )
    paperwork_viewer = UserProfile(
        id="user-paperwork-344",
        email="billing@carefold.local",
        username="billing344",
        full_name="Paperwork Helper",
        role="member",
        created_at=now_utc,
        updated_at=now_utc,
    )
    child_user = UserProfile(
        id="user-child-344",
        email="child@carefold.local",
        username="child344",
        full_name="Child User",
        role="member",
        created_at=now_utc,
        updated_at=now_utc,
    )

    child_dob = f"{now_utc.year - 8}-05-01"
    async with async_db_session_factory() as session:
        for u in (alice, bob, paperwork_viewer, child_user):
            session.add(
                User(
                    id=u.id,
                    email=u.email,
                    username=u.username,
                    full_name=u.full_name,
                    role=u.role,
                    hashed_password="x",
                )
            )
        prof_alice = Profile(
            id="prof-alice-344",
            user_id=alice.id,
            name="Alice Primary",
            relationship="self",
            date_of_birth="1988-05-01",
            is_primary=True,
        )
        prof_teen = Profile(
            id="prof-child-344",
            user_id=alice.id,
            name="Young Child",
            relationship="child",
            date_of_birth=child_dob,
            is_primary=False,
        )
        session.add_all([prof_alice, prof_teen])
        await session.flush()
        session.add(
            ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=prof_alice.id,
                user_id=paperwork_viewer.id,
                role="viewer",
                access_level="view_paperwork",
            )
        )
        for conn_idx, conn_type in enumerate(("epic_smart", "apple_health"), start=1):
            session.add(
                Connection(
                    id=f"conn-alice-344-{conn_idx}",
                    user_id=alice.id,
                    profile_id=prof_alice.id,
                    connector_id=conn_type,
                    status="active",
                    config_json="{}",
                    consecutive_failures=0,
                    autonomy_level="A2",
                )
            )
        undo_event = AuditEventRecord(
            id="evt-undo-344",
            ts=now_utc,
            actor_user_id=alice.id,
            principal="user",
            profile_id=prof_alice.id,
            event="tool.executed",
            tool="fhir_get_capabilities",
            risk="read",
            detail_redacted="{}",
        )
        pending_approval = Approval(
            id="appr-344-1",
            profile_id=prof_alice.id,
            run_id="run-344-1",
            tool_name="zocdoc_book_appointment",
            args_redacted={"provider_id": "p1"},
            payload_hash="sha256:test344",
            risk_tier="irreversible",
            status="pending",
            expires_at=now_utc + timedelta(hours=24),
        )
        session.add_all([undo_event, pending_approval])
        await session.commit()

    active_http_user = {"user": alice}
    app = create_app()

    async def _override_get_db():
        async with async_db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: active_http_user["user"]

    def _ctx(user: UserProfile, profile_id: str | None = "prof-alice-344", principal: str = "user") -> Any:
        return SimpleNamespace(
            user_id=user.id,
            user=user,
            profile_id=profile_id,
            principal=principal,
            session_factory=async_db_session_factory,
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Cross-profile isolation (Bob -> Alice's profile) emits identical YRV-300-007 on REST & MCP
        active_http_user["user"] = bob
        rest_denied = await client.get("/api/v1/profiles/prof-alice-344/activity")
        assert rest_denied.status_code == 403
        with pytest.raises(YarvelleError) as mcp_denied:
            await reg.get("activity_list_timeline").executor({}, _ctx(bob, "prof-alice-344"))
        assert _extract_http_error_code(rest_denied) == mcp_denied.value.code == "YRV-300-007"

        # 2. Non-existent profile emits identical YRV-500-002 on REST & MCP
        active_http_user["user"] = alice
        rest_missing = await client.get("/api/v1/profiles/prof-does-not-exist/vitals")
        assert rest_missing.status_code == 404
        with pytest.raises(YarvelleError) as mcp_missing:
            await reg.get("vitals_list").executor({}, _ctx(alice, "prof-does-not-exist"))
        assert _extract_http_error_code(rest_missing) == mcp_missing.value.code == "YRV-500-002"

        # 3. Paperwork-only viewer reading clinical notes emits identical CFD-300-003 on REST & MCP
        active_http_user["user"] = paperwork_viewer
        rest_pw = await client.get("/api/v1/profiles/prof-alice-344/notes")
        assert rest_pw.status_code == 403
        with pytest.raises(YarvelleError) as mcp_pw:
            await reg.get("notes_list_profile_typed").executor({}, _ctx(paperwork_viewer, "prof-alice-344"))
        assert _extract_http_error_code(rest_pw) == mcp_pw.value.code == "CFD-300-003"

        active_http_user["user"] = alice

        # 4. Activity timeline + undo non-undoable error parity
        rest_act = await client.get("/api/v1/profiles/prof-alice-344/activity")
        mcp_act = await reg.get("activity_list_timeline").executor({}, _ctx(alice))
        assert rest_act.status_code == 200
        assert rest_act.json()["total"] == mcp_act["total"]

        rest_undo_err = await client.post("/api/v1/profiles/prof-alice-344/activity/evt-undo-344/undo")
        with pytest.raises(YarvelleError) as mcp_undo_err:
            await reg.get("activity_undo_event").executor({"event_id": "evt-undo-344"}, _ctx(alice))
        assert _extract_http_error_code(rest_undo_err) == mcp_undo_err.value.code

        # 5. Notes: ad-hoc extraction (AdhocNoteExtractRequest) + invalid note category CFD-100-014
        sample_avs = "Diagnosis: Essential hypertension. Start Lisinopril 10 mg daily. Follow up in 4 weeks."
        rest_ext = await client.post(
            "/api/v1/profiles/prof-alice-344/notes/extract",
            json={"content": sample_avs},
        )
        mcp_ext = await reg.get("notes_extract_profile_adhoc").executor(
            {"content": sample_avs},
            _ctx(alice),
        )
        assert rest_ext.status_code == 200
        assert rest_ext.json()["disclaimer"] == mcp_ext["disclaimer"]
        assert rest_ext.json()["extracted_items_count"] == mcp_ext["extracted_items_count"]

        rest_bad_note = await client.post(
            "/api/v1/profiles/prof-alice-344/notes",
            json={"title": "Bad Type", "content": "Body", "type": "not_a_valid_type"},
        )
        with pytest.raises(YarvelleError) as mcp_bad_note:
            await reg.get("notes_create_profile_typed").executor(
                {"title": "Bad Type", "content": "Body", "type": "not_a_valid_type"},
                _ctx(alice),
            )
        assert _extract_http_error_code(rest_bad_note) == mcp_bad_note.value.code == "YRV-100-003"

        # 5b. Clinical validation error parity: systolic <= diastolic emits identical CFD-100-002 on REST & MCP
        rest_bad_bp = await client.post(
            "/api/v1/profiles/prof-alice-344/vitals",
            json={"vitals": {"systolic": 80, "diastolic": 95}},
        )
        with pytest.raises(YarvelleError) as mcp_bad_bp:
            await reg.get("vitals_create").executor(
                {"vitals": {"systolic": 80, "diastolic": 95}},
                _ctx(alice),
            )
        assert _extract_http_error_code(rest_bad_bp) == mcp_bad_bp.value.code == "CFD-100-002"

        # 6. Handover: viewer sections read parity + invalid decision CFD-100-010 parity + MCP teen handover
        rest_sec = await client.get(
            f"/api/v1/profiles/prof-alice-344/access/{paperwork_viewer.id}/sections"
        )
        mcp_sec = await reg.get("handover_get_viewer_sections").executor(
            {"target_user_id": paperwork_viewer.id},
            _ctx(alice, "prof-alice-344"),
        )
        assert rest_sec.status_code == 200
        assert rest_sec.json() == mcp_sec

        rest_ho_err = await client.post(
            "/api/v1/profiles/prof-child-344/handover",
            json={"teen_user_id": child_user.id, "connection_decisions": {"conn-x": "invalid_decision"}},
        )
        with pytest.raises(YarvelleError) as mcp_ho_err:
            await reg.get("handover_execute_teen_handover").executor(
                {"teen_user_id": child_user.id, "connection_decisions": {"conn-x": "invalid_decision"}},
                _ctx(alice, "prof-child-344"),
            )
        assert _extract_http_error_code(rest_ho_err) == mcp_ho_err.value.code

        mcp_ho_ok = await reg.get("handover_execute_teen_handover").executor(
            {"teen_user_id": child_user.id},
            _ctx(alice, "prof-child-344"),
        )
        assert mcp_ho_ok.get("new_owner_user_id") == child_user.id or mcp_ho_ok.get("profile_id") == "prof-child-344"

        # 7. Companion pairing & device listing parity
        mcp_pair = await reg.get("companion_pair_initiate").executor(
            {
                "device_name": "Alice Watch",
                "cert_fingerprint_sha256": "a" * 64,
            },
            _ctx(alice),
        )
        assert "pairing_code" in mcp_pair
        rest_devices = await client.get("/api/v1/profiles/prof-alice-344/companion/devices")
        mcp_devices = await reg.get("companion_list_devices").executor({}, _ctx(alice))
        assert rest_devices.status_code == 200
        assert rest_devices.json()["devices"] == mcp_devices["devices"]

        # 8. Routines & Coordinated care parity
        mcp_routine = await reg.get("routines_create").executor(
            {
                "name": "Weekly Med Review",
                "tool_name": "vitals_list",
                "rrule": "FREQ=WEEKLY;BYDAY=MO",
            },
            _ctx(alice),
        )
        rest_routines = await client.get("/api/v1/profiles/prof-alice-344/routines")
        assert rest_routines.status_code == 200
        routine_list = (
            rest_routines.json()
            if isinstance(rest_routines.json(), list)
            else rest_routines.json().get("routines") or rest_routines.json().get("items") or []
        )
        assert any(r["id"] == mcp_routine["id"] for r in routine_list)

        rest_verify = await client.get("/api/v1/profiles/prof-alice-344/audit/verify")
        mcp_verify = await reg.get("coordinated_verify_audit_chain").executor({}, _ctx(alice))
        assert rest_verify.status_code == 200
        assert rest_verify.json() == mcp_verify

        slot_payload = {
            "specialty_filter": "Cardiology",
            "busy_windows": [],
        }
        rest_slots = await client.post(
            "/api/v1/profiles/prof-alice-344/scheduling/smart-slots",
            json=slot_payload,
        )
        mcp_slots = await reg.get("coordinated_discover_smart_slots").executor(slot_payload, _ctx(alice))
        assert rest_slots.status_code == 200
        assert rest_slots.json() == mcp_slots

        # 9. Approvals: agent principal CANNOT self-approve (YRV-300-013), human steward CAN decide
        mcp_pending = await reg.get("approvals_list").executor({}, _ctx(alice))
        pending_items = (
            mcp_pending if isinstance(mcp_pending, list) else mcp_pending.get("items") or mcp_pending.get("approvals") or []
        )
        assert any(item["id"] == "appr-344-1" for item in pending_items)

        with pytest.raises(YarvelleError) as agent_self_approve:
            await reg.get("approvals_decide").executor(
                {"approval_id": "appr-344-1", "decision": "approve"},
                _ctx(alice, principal="agent"),
            )
        assert agent_self_approve.value.code == "YRV-300-013"

        steward_decided = await reg.get("approvals_decide").executor(
            {"approval_id": "appr-344-1", "decision": "reject"},
            _ctx(alice, principal="user"),
        )
        assert steward_decided["status"] == "rejected"

        # 10. Memory status/put/get/recall/delete parity
        await reg.get("memory_put").executor(
            {"key": "preferred_pharmacy", "value": "Oak Street Pharmacy"},
            _ctx(alice),
        )
        rest_mem = await client.get(
            "/api/v1/memory/preferred_pharmacy",
            params={"profile_id": "prof-alice-344"},
        )
        mcp_mem = await reg.get("memory_get").executor({"key": "preferred_pharmacy"}, _ctx(alice))
        assert rest_mem.status_code == 200
        assert rest_mem.json() == mcp_mem


# ============================================================================
# 5. FHIR Toolbox Cleanup: Zero-SQL Capabilities & Upsert Invariants (AC #4)
# ============================================================================


@pytest.mark.asyncio
async def test_fhir_get_capabilities_executes_zero_sql_and_is_absent_from_db_tools_yaml(
    async_db_session_factory: Any,
) -> None:
    register_carefold_db_toolbox()

    raw_yaml = yaml.safe_load(CAREFOLD_DB_TOOLS_YAML.read_text(encoding="utf-8"))
    assert "fhir_get_capabilities" not in (raw_yaml.get("tools") or {})
    for ts_name, ts_tools in (raw_yaml.get("toolsets") or {}).items():
        assert "fhir_get_capabilities" not in ts_tools, f"Found dummy SQL tool in toolset '{ts_name}'"

    toolbox = get_db_toolbox()
    assert "fhir_get_capabilities" not in toolbox.manifest.tools

    async_engine = async_db_session_factory.kw["bind"]
    sql_statements: List[str] = []

    def _on_before_cursor_execute(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        sql_statements.append(statement)

    event.listen(async_engine.sync_engine, "before_cursor_execute", _on_before_cursor_execute)
    try:
        reg = create_default_registry()
        cap_spec = reg.get("fhir_get_capabilities")
        assert cap_spec is not None and cap_spec.executor is not None
        cap = await cap_spec.executor({}, SimpleNamespace(profile_id=None, user_id=None))
    finally:
        event.remove(async_engine.sync_engine, "before_cursor_execute", _on_before_cursor_execute)

    assert sql_statements == [], f"Expected zero SQL statements for fhir_get_capabilities, got: {sql_statements}"
    assert cap["resourceType"] == "CapabilityStatement"
    assert cap["fhirVersion"] == "4.0.1"


@pytest.mark.asyncio
async def test_fhir_upsert_resource_enforces_identical_versioning_etag_if_match_412_idempotency_and_dedup(
    async_db_session_factory: Any,
    profile_factory: Any,
) -> None:
    register_carefold_db_toolbox()
    profile = await profile_factory(profile_id="prof-fhir-344", name="FHIR Patient", relationship="self")

    reg = create_default_registry()
    upsert_exec = reg.get("fhir_upsert_resource").executor
    create_exec = reg.get("fhir_create_resource").executor
    ctx = SimpleNamespace(
        profile_id=profile.id,
        user_id=DEFAULT_STEWARD_USER.id,
        session_factory=async_db_session_factory,
    )

    obs_v1 = {
        "resourceType": "Observation",
        "id": "obs-hba1c-344",
        "status": "final",
        "subject": {"reference": f"Patient/{profile.id}"},
        "code": {
            "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}],
            "text": "Hemoglobin A1c",
        },
        "effectiveDateTime": "2026-05-01T09:00:00Z",
        "valueQuantity": {"value": 5.6, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"},
    }

    # 1. Missing confirmation fails closed with CFD-700-001 (428)
    with pytest.raises(YarvelleError) as unconfirmed_err:
        await upsert_exec(
            {"resource_type": "Observation", "id": "obs-hba1c-344", "resource": obs_v1, "confirmed": False},
            ctx,
        )
    assert unconfirmed_err.value.code == "CFD-700-001"

    # 2. Initial confirmed creation -> version 1, weak ETag W/"1"
    created = await upsert_exec(
        {
            "resource_type": "Observation",
            "id": "obs-hba1c-344",
            "resource": obs_v1,
            "confirmed": True,
            "idempotency_key": "idem-obs-create-1",
        },
        ctx,
    )
    assert created["action"] == "created"
    assert created["etag"] == 'W/"1"'
    assert created["resource"]["meta"]["versionId"] == "1"

    # 3. Idempotency-Key replay returns cached result without bumping version
    obs_different = copy.deepcopy(obs_v1)
    obs_different["valueQuantity"]["value"] = 6.9
    replayed = await upsert_exec(
        {
            "resource_type": "Observation",
            "id": "obs-hba1c-344",
            "resource": obs_different,
            "confirmed": True,
            "idempotency_key": "idem-obs-create-1",
        },
        ctx,
    )
    assert replayed["etag"] == 'W/"1"'
    assert replayed["resource"]["valueQuantity"]["value"] == 5.6

    # 4. Repository deduplication: creating an identical Observation without id strong-merges
    # into the existing HealthResource row (action="updated", version 2, zero duplicate HealthResource rows).
    obs_dup_unkeyed = copy.deepcopy(obs_v1)
    obs_dup_unkeyed.pop("id", None)
    deduped = await create_exec(
        {"resource_type": "Observation", "resource": obs_dup_unkeyed, "confirmed": True},
        ctx,
    )
    assert deduped["action"] == "updated"
    assert deduped["etag"] == 'W/"2"'
    assert deduped["resource"]["id"] == "obs-hba1c-344"

    # 5. Update with matching If-Match W/"2" -> version 3, weak ETag W/"3"
    obs_v3 = copy.deepcopy(obs_v1)
    obs_v3["valueQuantity"]["value"] = 5.4
    updated = await upsert_exec(
        {
            "resource_type": "Observation",
            "id": "obs-hba1c-344",
            "resource": obs_v3,
            "if_match": 'W/"2"',
            "confirmed": True,
        },
        ctx,
    )
    assert updated["action"] == "updated"
    assert updated["etag"] == 'W/"3"'
    assert updated["resource"]["meta"]["versionId"] == "3"

    # 6. Stale If-Match W/"1" fails closed with 412 CFD-500-011 on BOTH MCP and REST
    obs_v4 = copy.deepcopy(obs_v1)
    obs_v4["valueQuantity"]["value"] = 5.2
    with pytest.raises(YarvelleError) as stale_mcp_err:
        await upsert_exec(
            {
                "resource_type": "Observation",
                "id": "obs-hba1c-344",
                "resource": obs_v4,
                "if_match": 'W/"1"',
                "confirmed": True,
            },
            ctx,
        )
    assert stale_mcp_err.value.code == "CFD-500-011"
    assert stale_mcp_err.value.http_status == 412

    app = create_app()

    async def _override_get_db():
        async with async_db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: DEFAULT_STEWARD_USER

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        stale_rest = await client.put(
            "/api/v1/fhir/r4/Observation/obs-hba1c-344",
            params={"profile_id": profile.id, "confirmed": "true"},
            headers={"If-Match": 'W/"1"', "Accept": "application/problem+json"},
            json=obs_v4,
        )
        assert stale_rest.status_code == 412
        assert _extract_http_error_code(stale_rest) == "CFD-500-011"

    # Verify single deduplicated HealthResource row and 3 immutable HealthResourceVersion rows (no phantom version 4)
    async with async_db_session_factory() as session:
        hr_rows = (
            await session.execute(
                select(HealthResource).where(
                    HealthResource.profile_id == profile.id,
                    HealthResource.resource_type == "Observation",
                )
            )
        ).scalars().all()
        assert len(hr_rows) == 1
        versions = (
            await session.execute(
                select(HealthResourceVersion).where(
                    HealthResourceVersion.resource_id == hr_rows[0].id,
                )
            )
        ).scalars().all()
        assert len(versions) == 3
        assert [v.operation for v in sorted(versions, key=lambda x: x.version_id)] == [
            "create",
            "merge",
            "update",
        ]
