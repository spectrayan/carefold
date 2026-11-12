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

"""End-to-end integration tests exercising Carefold against current yarvelle-core contracts.

Validates:
- Declarative `yarvelle.tools/v1` `ToolSpecLoader` core + pack loading and real async execution
- `McpDatabaseToolbox` declarative SQL + clinical hooks + `assist_db` toolset + `SqlAstSandbox`
- Unified `ErrorCatalog` (`CFD-*` + `YRV-*`) and FastAPI RFC 7807 `application/problem+json`
- Pack-scoped Handlebars prompt template overrides (`pack_id="health"` vs domain-neutral core)
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.testclient import TestClient
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import carefold  # noqa: F401 — ensures health pack resources & CFD catalog are registered
from carefold.db.base import Base
from carefold.db.models import Profile
import carefold.db.session as cf_db_session
from carefold.main import create_app
from carefold.tools.mcp_db_toolbox import get_db_toolbox
import yarvelle_core.db.session as yc_db_session
from yarvelle_core.errors import (
    PROBLEM_JSON_MEDIA_TYPE,
    ErrorCatalogRegistrationError,
    YarvelleError,
    get_error_catalog,
    register_pack_error_catalog,
)
from yarvelle_core.resources.loader import get_resource_loader as get_core_resource_loader
from yarvelle_core.schemas.tool_spec import HandlerToolBinding
from yarvelle_core.tools.spec_loader import ToolSpecLoader, ToolSpecValidationError
from yarvelle_core.tools.sql_ast_sandbox import SqlSecurityError


def sync_invalid_handler(args: dict, ctx: object = None) -> dict:
    """Deliberately synchronous function used to test fail-closed handler validation."""
    return {"ok": False}


@pytest_asyncio.fixture
async def isolated_sqlite_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Creates an isolated SQLite database wired to both carefold and yarvelle_core session factories."""
    db_path = tmp_path / "local_core_mcp.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(cf_db_session, "get_session_factory", lambda: factory)
    monkeypatch.setattr(yc_db_session, "get_session_factory", lambda: factory)
    import carefold.tools.appointments as appt_tools_mod
    import carefold.tools.mcp_db_toolbox as toolbox_mod

    monkeypatch.setattr(appt_tools_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(toolbox_mod, "get_session_factory", lambda: factory)

    async with factory() as session:
        session.add(
            Profile(
                id="prof-mcp-test",
                name="Maya",
                relationship="self",
                role="self",
                is_primary=True,
                preferred_locale="en-US",
            )
        )
        await session.commit()

    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_declarative_tool_spec_loader_executes_pack_and_core_tools(
    tmp_path: Path,
    isolated_sqlite_env: async_sessionmaker[AsyncSession],
) -> None:
    """Verifies ToolSpecLoader loads core + health pack YAML specs and awaits bound Carefold handlers."""
    loader = ToolSpecLoader()
    core_tools = loader.load_core_tools()
    assert len(core_tools) >= 7
    for bound in core_tools:
        if isinstance(bound.spec.binding, HandlerToolBinding):
            assert bound.executor is not None
            assert inspect.iscoroutinefunction(bound.executor)

    pack_tools_yaml = tmp_path / "appointments.yaml"
    pack_tools_yaml.write_text(
        """apiVersion: yarvelle.tools/v1
kind: ToolSet
pack_id: health
tools:
  - name: create_appointment
    category: appointments
    risk_tier: write_local
    trust: trusted
    data_sensitivity: restricted
    context_params: [profile_id, user_id]
    description: Create a clinical appointment in the active patient profile.
    input_schema:
      type: object
      required: [title, start_time, end_time]
      properties:
        title:
          type: string
        start_time:
          type: string
        end_time:
          type: string
    binding:
      kind: handler
      entrypoint: carefold.tools.appointments:execute_create_appointment
  - name: list_appointments
    category: appointments
    risk_tier: read
    trust: trusted
    data_sensitivity: restricted
    context_params: [profile_id, user_id]
    description: List clinical appointments for the active patient profile.
    input_schema:
      type: object
      properties:
        status:
          type: string
    binding:
      kind: handler
      entrypoint: carefold.tools.appointments:execute_list_appointments
""",
        encoding="utf-8",
    )

    loader.register_pack_source("health", pack_tools_yaml)

    only_core = {t.spec.name for t in loader.load_enabled_tools(enabled_packs=[])}
    with_health = {t.spec.name: t for t in loader.load_enabled_tools(enabled_packs=["health"])}

    assert "create_appointment" not in only_core
    assert "create_appointment" in with_health
    assert "list_appointments" in with_health

    ctx = SimpleNamespace(
        profile_id="prof-mcp-test",
        user_id="user-1",
        locale="en-US",
        workspace_dir=str(tmp_path),
    )
    create_exec = with_health["create_appointment"].executor
    list_exec = with_health["list_appointments"].executor
    assert create_exec is not None and list_exec is not None

    created = await create_exec(
        {
            "title": "Cardiology Follow-up",
            "start_time": "2026-12-01T14:00:00Z",
            "end_time": "2026-12-01T14:45:00Z",
        },
        ctx,
    )
    assert created.success is True
    assert created.output["title"] == "Cardiology Follow-up"

    listed = await list_exec({}, ctx)
    assert listed.success is True
    assert listed.output["total"] == 1
    assert listed.output["appointments"][0]["title"] == "Cardiology Follow-up"

    bad_yaml = tmp_path / "invalid_sync.yaml"
    bad_yaml.write_text(
        f"""apiVersion: yarvelle.tools/v1
kind: ToolSet
pack_id: health
tools:
  - name: invalid_sync_tool
    category: test
    risk_tier: read
    trust: trusted
    data_sensitivity: internal
    description: Invalid synchronous handler test.
    input_schema:
      type: object
      properties: {{}}
    binding:
      kind: handler
      entrypoint: {__name__}:sync_invalid_handler
""",
        encoding="utf-8",
    )
    with pytest.raises(ToolSpecValidationError, match="async coroutine function"):
        loader.load_file(bad_yaml, default_pack_id="health", resolve_handlers=True)


@pytest.mark.asyncio
async def test_mcp_db_toolbox_executes_declarative_tools_and_sandboxes_sql(
    tmp_path: Path,
    isolated_sqlite_env: async_sessionmaker[AsyncSession],
) -> None:
    """Verifies McpDatabaseToolbox runs Carefold clinical DB tools and enforces SqlAstSandbox."""
    toolbox = get_db_toolbox()
    assert "assist_db" in toolbox.manifest.toolsets
    assert "upsert_clinical_note" in toolbox.manifest.toolsets["assist_db"]
    assert "record_vital_reading" in toolbox.manifest.toolsets["assist_db"]

    ctx = SimpleNamespace(
        profile_id="prof-mcp-test",
        user_id="user-1",
        locale="en-US",
        workspace_root=tmp_path,
    )

    note_res = await toolbox.execute_tool(
        "upsert_clinical_note",
        {
            "slug": "cardio-visit-plan",
            "title": "Cardiology Visit Questions",
            "note_type": "visit",
            "content": "- Ask about home blood pressure log trends",
        },
        ctx,
    )
    assert note_res["status"] == "ok"
    assert note_res["record"]["slug"] == "cardio-visit-plan"

    notes_list = await toolbox.execute_tool("list_clinical_notes", {"limit": 10}, ctx)
    assert notes_list["count"] == 1
    assert notes_list["records"][0]["slug"] == "cardio-visit-plan"

    vital_res = await toolbox.execute_tool(
        "record_vital_reading",
        {
            "vital_type": "blood_pressure",
            "systolic": 122,
            "diastolic": 78,
            "unit": "mmHg",
            "effective_at": "2026-11-11T15:00:00Z",
        },
        ctx,
    )
    assert vital_res["status"] == "ok"
    assert vital_res["fhir_resource"]["resourceType"] == "Observation"
    assert vital_res["red_flags"] == []

    vitals_list = await toolbox.execute_tool("list_vital_readings", {"limit": 10}, ctx)
    assert vitals_list["count"] == 1
    assert vitals_list["records"][0]["profile_id"] == "prof-mcp-test"

    schema_info = await toolbox.execute_tool("db_inspect_schema", {}, ctx)
    assert "notes" in str(schema_info)

    with pytest.raises((SqlSecurityError, ValueError)):
        await toolbox.execute_tool(
            "db_execute_query",
            {"query": "DROP TABLE notes"},
            ctx,
        )


def test_cfd_error_catalog_and_problem_details_handler(tmp_path: Path) -> None:
    """Verifies CFD-* and YRV-* catalog resolution, prefix isolation, and RFC 7807 responses."""
    catalog = get_error_catalog()
    cfd_spec = catalog.resolve("CFD-300-001")
    assert cfd_spec.slug == "clinical_consent_required"
    assert cfd_spec.http_status == 403
    assert catalog.resolve("clinical_consent_required").code == "CFD-300-001"

    yrv_spec = catalog.resolve("YRV-100-002")
    assert yrv_spec.code == "YRV-100-002"

    illegal_yrv_yaml = tmp_path / "illegal_yrv.yaml"
    illegal_yrv_yaml.write_text(
        """apiVersion: yarvelle.errors/v1
kind: ErrorCatalog
prefix: YRV
codes:
  - code: YRV-999-001
    slug: illegal_override
    http_status: 500
    title: Illegal
    message_template: "Not allowed"
""",
        encoding="utf-8",
    )
    with pytest.raises(ErrorCatalogRegistrationError):
        register_pack_error_catalog("rogue-pack", "YRV", illegal_yrv_yaml)

    app = create_app()
    probe_router = APIRouter()

    @probe_router.get("/__test/cfd-problem")
    async def raise_cfd_error() -> dict:
        raise YarvelleError("CFD-300-001", context={"agent_id": "heart-care-coordinator"})

    app.include_router(probe_router)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/__test/cfd-problem")

    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    payload = resp.json()
    assert payload["type"] == "https://errors.carefold.dev/cfd-300-001"
    assert payload["status"] == 403
    assert payload["code"] == "CFD-300-001"
    assert "heart-care-coordinator" in payload["detail"]


def test_pack_scoped_handlebars_prompt_overrides() -> None:
    """Verifies pack_id='health' renders Carefold medical prompts while pack_id=None stays neutral."""
    loader = get_core_resource_loader()

    health_skills = loader.render_template(
        "skills_middleware",
        {"skills_list": "- cardiology-prep: Cardiology visit preparation"},
        pack_id="health",
    )
    core_skills = loader.render_template(
        "skills_middleware",
        {"skills_list": "- generic-skill: Generic workspace skill"},
        pack_id=None,
    )
    assert "Carefold Clinical Skill Catalog" in health_skills
    assert "Carefold Clinical Skill Catalog" not in core_skills

    health_planner = loader.render_template(
        "db_query_planner",
        {"schema_summary": "health_resources(id, profile_id, data)", "question": "latest BP"},
        pack_id="health",
    )
    core_planner = loader.render_template(
        "db_query_planner",
        {"schema_summary": "notes(id, profile_id, title)", "question": "latest note"},
        pack_id=None,
    )
    assert "Carefold" in health_planner
    assert "Carefold" not in core_planner

    health_tier1 = loader.render_template(
        "tier1_domain_classifier",
        {"domains": "- health: Clinical records and vitals"},
        pack_id="health",
    )
    core_tier1 = loader.render_template(
        "tier1_domain_classifier",
        {"domains": "- household: Shared calendars and lists"},
        pack_id=None,
    )
    assert "Carefold Tier-1 Clinical" in health_tier1
    assert "Carefold Tier-1 Clinical" not in core_tier1
