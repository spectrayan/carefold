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

"""CI shadow-drift guard and fail-closed require_pack_scope contract tests (#339)."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
import uuid

from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import text
import yarvelle_core
from yarvelle_core.api.deps import get_current_user, get_db
from yarvelle_core.api.errors import ProblemDetailsRoute, register_error_handlers
from yarvelle_core.api.router import PackRouterContractError, mount_router_contributions
from yarvelle_core.api.scope_guard import iter_api_routes, route_scope_guards
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.pack.spec import RouterContribution

import carefold
from carefold.api.router import api_router, create_api_router
from carefold.db.models import Profile, ProfileAccess, User
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.routers import get_health_router_contributions

CAREFOLD_SRC = Path(carefold.__file__).resolve().parent
YARVELLE_CORE_SRC = Path(yarvelle_core.__file__).resolve().parent

# Explicit documented Carefold host/pack overrides that intentionally specialize core paths.
PACK_OVERRIDE_ALLOWLIST: Dict[str, str] = {
    "__init__.py": "Carefold host brand configuration and get_health_pack_spec() entry point.",
    "agents/registry.py": "Carefold specialist agent registry with clinical care_stages and fallback routing.",
    "api/chat.py": "Carefold SSE chat endpoint wiring CarefoldAgentExecutionService and checkpoint key events.",
    "api/connections.py": "Carefold healthcare connector endpoints (Epic SMART, Withings, Zocdoc, SMART v2).",
    "api/reminders.py": "Carefold clinical reminder endpoints accepting medication/vitals/appointment categories.",
    "api/router.py": "Carefold composite API router mounting core + 10 health pack contributions.",
    "companion/__init__.py": "Carefold companion pairing and HealthKit/Health Connect sync package.",
    "companion/pairing.py": "Carefold companion device pairing backed by Carefold CompanionDevice model.",
    "config.py": "Carefold host Settings resolving CAREFOLD_* environment variables and carefold.db.",
    "conformance/layers/layer_03_fts5.py": "Carefold conformance layer verifying health pack FTS5 scope isolation.",
    "conformance/layers/layer_08_api.py": "Carefold conformance layer verifying health pack API scope isolation.",
    "connectors/lifecycle.py": "Carefold connector manifest registry including Epic SMART, Withings, and Zocdoc.",
    "connectors/starters/calendar.py": "Carefold clinic-hours calendar starter masking titles as Medical Appointment.",
    "connectors/sync.py": "Carefold clinical connector sync pipeline staging FHIR/vitals import records.",
    "db/models.py": "Carefold ORM composition attaching 7 health relationships and ScopeGrant bridge.",
    "db/session.py": "Carefold dual-chain Alembic runner executing core + health_migrations.",
    "engine/agent_factory.py": "Carefold agent factory attaching ClinicalSafetyMiddleware.",
    "engine/graph.py": "Carefold LangGraph specialist execution graph facade.",
    "engine/runner.py": "Carefold streaming agent runner wrapping CarefoldAgentExecutionService.",
    "loaders/agent_loader.py": "Carefold agent loader injecting care_stages and CLINICAL SCOPE guardrails.",
    "loaders/frontmatter.py": "Carefold frontmatter verifier checking 3 mandatory non-clinical intended-use clauses.",
    "middleware/skills.py": "Carefold ProgressiveSkillsMiddleware enforcing clinical skill boundary checks.",
    "migration/runtime_migrator.py": "Carefold first-launch migrator moving legacy workspace/carefold.db to ~/.carefold.",
    "packaging/service.py": "Carefold launchd/systemd/Task Scheduler service templates for com.spectrayan.carefold.",
    "search/chunker.py": "Carefold ClinicalChunker partitioning clinical section headers onto StructuralChunker.",
    "tools/__init__.py": "Carefold get_health_tool_specs() registry exporting 20 clinical and FHIR ToolSpecs.",
    "tools/web_search.py": "Carefold web search wrapper layering clinical MRN redaction onto core PII sanitization.",
    "workflows/nodes/agent_execution_node.py": "Carefold agent execution node with clinical domain default and coordinator fallback.",
    "workflows/nodes/response_synthesizer_node.py": "Carefold consultation agenda synthesizer reconciling clinical specialist outputs.",
    "workflows/nodes/skill_generator_node.py": "Carefold skill generator enforcing healthcare non-clinical boundary patterns.",
    "workflows/nodes/tool_node.py": "Carefold tool execution node resolving specialist agent directories.",
}


def test_no_unshimmed_yarvelle_core_shadow_modules() -> None:
    """Every overlapping carefold/*.py path must be a <40-line yarvelle_core shim or documented pack override."""
    assert len(PACK_OVERRIDE_ALLOWLIST) <= 32
    for rel_path, reason in PACK_OVERRIDE_ALLOWLIST.items():
        assert reason.strip(), f"Allowlist entry '{rel_path}' must document a non-empty reason."
        assert (CAREFOLD_SRC / rel_path).is_file(), f"Stale allowlist entry '{rel_path}' does not exist."

    cf_files = {str(p.relative_to(CAREFOLD_SRC)): p for p in CAREFOLD_SRC.rglob("*.py")}
    yc_files = {str(p.relative_to(YARVELLE_CORE_SRC)): p for p in YARVELLE_CORE_SRC.rglob("*.py")}
    overlapping = sorted(set(cf_files) & set(yc_files))

    shimmed_count = 0
    violations: list[str] = []
    for rel in overlapping:
        text_content = cf_files[rel].read_text(encoding="utf-8")
        line_count = len(text_content.splitlines())
        imports_core = "yarvelle_core" in text_content
        if line_count < 40 and imports_core:
            shimmed_count += 1
        elif rel not in PACK_OVERRIDE_ALLOWLIST:
            violations.append(f"{rel} ({line_count} lines, imports_yarvelle_core={imports_core})")

    assert not violations, f"Unshimmed yarvelle_core shadow modules detected: {violations}"
    assert shimmed_count >= 190, f"Expected >=190 thin yarvelle_core shims, found {shimmed_count}"


def test_no_meta_path_hooks_or_private_yarvelle_core_mutations() -> None:
    """No carefold module may manipulate sys.meta_path or mutate private _* attributes on yarvelle_core."""
    meta_path_hits: list[str] = []
    private_mutations: list[str] = []

    for py_file in sorted(CAREFOLD_SRC.rglob("*.py")):
        rel = str(py_file.relative_to(CAREFOLD_SRC))
        src = py_file.read_text(encoding="utf-8")
        if "meta_path" in src:
            meta_path_hits.append(rel)

        tree = ast.parse(src, filename=rel)
        yc_aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "yarvelle_core" or alias.name.startswith("yarvelle_core."):
                        yc_aliases.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "yarvelle_core" or node.module.startswith("yarvelle_core.")
            ):
                for alias in node.names:
                    yc_aliases.add(alias.asname or alias.name)

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr.startswith("_")
                        and isinstance(target.value, ast.Name)
                        and target.value.id in yc_aliases
                    ):
                        private_mutations.append(f"{rel}:{node.lineno} ({target.value.id}.{target.attr})")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in yc_aliases
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and node.args[1].value.startswith("_")
            ):
                private_mutations.append(f"{rel}:{node.lineno} (setattr {node.args[0].id}.{node.args[1].value})")

    assert not meta_path_hits, f"Forbidden sys.meta_path hooks found in: {meta_path_hits}"
    assert not private_mutations, f"Forbidden private yarvelle_core mutations found: {private_mutations}"


@pytest.mark.asyncio
async def test_dual_migration_chain_without_forked_core_migrations(tmp_path: Path) -> None:
    """Forked carefold/db/migrations is retired; init_db runs core 0014 + health_0002 chains."""
    assert not (CAREFOLD_SRC / "db" / "migrations").exists()

    db_file = tmp_path / "dual_chain_test.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file}")
    try:
        await init_db(engine)
        async with engine.connect() as conn:
            core_revs = {
                r[0] for r in (await conn.execute(text("SELECT version_num FROM alembic_version"))).fetchall()
            }
            health_revs = {
                r[0] for r in (await conn.execute(text("SELECT version_num FROM alembic_version_health"))).fetchall()
            }
        assert "0014_neutralize_profile_columns" in core_revs
        assert "health_0002_fhir_ehr_repository" in health_revs
    finally:
        await engine.dispose()


def test_pack_router_contract_rejects_unguarded_pack_contributions() -> None:
    """Unscoped pack RouterContributions fail closed at mount time; all 10 Carefold health routers carry guards."""
    dummy = APIRouter()

    @dummy.get("/unsafe")
    async def _unsafe() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(PackRouterContractError):
        create_api_router([RouterContribution(dummy, pack_id="health", scope=None)])

    health_contribs = get_health_router_contributions()
    assert len(health_contribs) == 10
    health_paths = {
        getattr(r, "path", "")
        for c in health_contribs
        for r in c.router.routes
        if getattr(r, "path", "")
    }
    matched_guarded_paths: set[str] = set()
    for route in iter_api_routes(api_router.routes):
        if route.path in health_paths:
            guards = route_scope_guards(route)
            if any(pack_id == "health" and scope == "health.clinical" for scope, _lvl, pack_id in guards):
                matched_guarded_paths.add(route.path)

    assert matched_guarded_paths == health_paths


@pytest.mark.asyncio
async def test_require_pack_scope_fails_closed_for_insufficient_scope_and_missing_profile(tmp_path: Path) -> None:
    """Pack routes mounted via mount_router_contributions deny paperwork-only viewers and missing profile_id."""
    db_file = tmp_path / "pack_scope_guard.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file}")
    await init_db(engine)
    factory = get_session_factory(engine)

    now = datetime.now(timezone.utc)
    owner_id = str(uuid.uuid4())
    viewer_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())

    async with factory() as session:
        session.add_all(
            [
                User(id=owner_id, email="owner@example.com", username="owner", hashed_password="x", role="steward", status="active"),
                User(id=viewer_id, email="viewer@example.com", username="viewer", hashed_password="x", role="member", status="active"),
                Profile(id=profile_id, user_id=owner_id, name="Patient One", relationship="self", role="self", is_primary=True),
            ]
        )
        await session.flush()
        session.add(
            ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=profile_id,
                user_id=viewer_id,
                access_level="view_paperwork",
                granted_by=owner_id,
                granted_at=now,
            )
        )
        await session.commit()

    active_user = {"user": UserProfile(
        id=viewer_id, email="viewer@example.com", username="viewer", role="member", status="active", created_at=now, updated_at=now
    )}

    # Also mount a require_profile=True health test route without profile_id in path to verify 400 fail-closed
    no_pid_router = APIRouter(route_class=ProblemDetailsRoute)

    @no_pid_router.get("/pack-ping")
    async def _pack_ping() -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    register_error_handlers(app)
    composite = create_api_router(
        [
            *get_health_router_contributions(),
            RouterContribution(no_pid_router, pack_id="health", scope="health.clinical", level="read", require_profile=True),
        ]
    )
    app.include_router(composite, prefix="/api/v1")

    async def _override_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: active_user["user"]

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Missing profile_id on require_profile=True pack route -> 400 YRV-100-004
            r_missing = await client.get("/api/v1/pack-ping")
            assert r_missing.status_code == 400
            assert r_missing.headers["content-type"].startswith("application/problem+json")
            assert r_missing.json()["code"] == "YRV-100-004"

            # 2. view_paperwork viewer hitting health.clinical vitals route -> 403 YRV-300-008
            r_denied = await client.get(f"/api/v1/profiles/{profile_id}/vitals")
            assert r_denied.status_code == 403
            assert r_denied.headers["content-type"].startswith("application/problem+json")
            assert r_denied.json()["code"] == "YRV-300-008"

            # 3. Steward owner hitting the same route -> 200 OK
            active_user["user"] = UserProfile(
                id=owner_id, email="owner@example.com", username="owner", role="steward", status="active", created_at=now, updated_at=now
            )
            r_ok = await client.get(f"/api/v1/profiles/{profile_id}/vitals")
            assert r_ok.status_code == 200
    finally:
        await engine.dispose()
