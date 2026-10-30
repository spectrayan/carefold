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

"""Behavioral and security tests for MCP DB Toolbox integration in Carefold.

Validates:
- Reserved context parameter isolation (`RESERVED_CONTEXT_PARAMS` never exposed in LLM schemas)
- Fail-closed `ToolContext` and `profile_id` validation
- Native declarative SQL execution via `yarvelle_core.tools.mcp_db_toolbox` with tenant isolation
- Clinical domain hook logic (`record_vital_reading` FHIR R4 LOINC + acute red-flag detection,
  and `upsert_clinical_note` upsert + workspace markdown mirroring)
- Dynamic AST-sandboxed tools (`db_inspect_schema`, `db_execute_query`, `db_mutate_records`)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.db.base import Base
from carefold.db.models import Job, Note, Profile
import carefold.db.session as db_session_mod
from carefold.tools.mcp_db_toolbox import (
    RESERVED_CONTEXT_PARAMS,
    get_db_toolbox,
)
from yarvelle_core.tools.sql_ast_sandbox import SqlSecurityError


@pytest_asyncio.fixture
async def isolated_db_toolbox_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Create an isolated SQLite database and patch `get_session_factory` for MCP DB tool tests."""
    db_file = tmp_path / "test_mcp_toolbox.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(db_session_mod, "get_session_factory", lambda: factory)
    import carefold.tools.mcp_db_toolbox as toolbox_mod

    monkeypatch.setattr(toolbox_mod, "get_session_factory", lambda: factory)

    async with factory() as session:
        session.add(
            Profile(
                id="prof-alice",
                name="Alice",
                relationship="self",
                role="self",
                is_primary=True,
                preferred_locale="en-US",
            )
        )
        session.add(
            Profile(
                id="prof-bob",
                name="Bob",
                relationship="child",
                role="guardian",
                is_primary=False,
                preferred_locale="es-ES",
            )
        )
        await session.commit()

    yield factory
    await engine.dispose()


class TestMcpDbToolboxSchemaInvariants:
    """Verifies LLM JSON schema sanitization independent of specific tool counts."""

    def test_reserved_context_parameters_never_exposed_in_json_schema(self) -> None:
        toolbox = get_db_toolbox()
        assert len(toolbox.manifest.tools) > 0
        for name, cfg in toolbox.manifest.tools.items():
            schema = cfg.to_json_schema()
            props = set(schema.get("properties", {}).keys())
            assert props.isdisjoint(RESERVED_CONTEXT_PARAMS), (
                f"Tool '{name}' leaked reserved context parameters into JSON schema: "
                f"{props & RESERVED_CONTEXT_PARAMS}"
            )
            assert len(cfg.compute_pin_hash(name)) == 64


@pytest.mark.asyncio
class TestMcpDbToolboxLogicAndSecurity:
    """Verifies native YAML SQL execution, clinical hooks, dynamic AST tools, and tenant isolation."""

    async def test_missing_profile_id_fails_closed(
        self, isolated_db_toolbox_env: async_sessionmaker[AsyncSession]
    ) -> None:
        toolbox = get_db_toolbox()
        any_read_tool = next(
            name for name, cfg in toolbox.manifest.tools.items() if cfg.risk_tier == "read"
        )
        with pytest.raises(ValueError, match="ToolContext is required"):
            await toolbox.execute_tool(any_read_tool, {}, None)

        empty_ctx = SimpleNamespace(profile_id="   ")
        with pytest.raises(ValueError, match="profile_id is required"):
            await toolbox.execute_tool(any_read_tool, {}, empty_ctx)

    async def test_upsert_clinical_note_and_native_sql_reads_enforce_tenant_isolation(
        self,
        isolated_db_toolbox_env: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        toolbox = get_db_toolbox()
        alice_ctx = SimpleNamespace(
            profile_id="prof-alice", locale="en-US", workspace_root=tmp_path
        )
        bob_ctx = SimpleNamespace(
            profile_id="prof-bob", locale="es-ES", workspace_root=tmp_path
        )

        # Spoofed profile_id in LLM arguments must be ignored in favor of ToolContext.profile_id
        save_res = await toolbox.execute_tool(
            "upsert_clinical_note",
            {
                "profile_id": "prof-bob",
                "slug": "urology-visit-plan",
                "title": "Urology Visit Plan",
                "note_type": "visit",
                "content": "## Questions for Urologist\n1. PSA trend review",
                "tags_json": '["urology", "prep"]',
            },
            alice_ctx,
        )
        assert save_res["status"] == "ok"
        assert save_res["record"]["profile_id"] == "prof-alice"
        assert save_res["record"]["operation"] == "created"
        assert (tmp_path / "notes" / "urology-visit-plan.md").is_file()

        # Native declarative SQL read (`list_clinical_notes` / `get_clinical_note`) isolates profiles
        bob_list = await toolbox.execute_tool("list_clinical_notes", {}, bob_ctx)
        assert bob_list["count"] == 0

        alice_list = await toolbox.execute_tool("list_clinical_notes", {}, alice_ctx)
        assert alice_list["count"] == 1
        assert alice_list["records"][0]["slug"] == "urology-visit-plan"

        alice_detail = await toolbox.execute_tool(
            "get_clinical_note",
            {"slug": "urology-visit-plan"},
            alice_ctx,
        )
        assert alice_detail["count"] == 1
        assert "PSA trend review" in alice_detail["records"][0]["content"]

        # Upsert existing note updates in place and enqueues search indexing job
        update_res = await toolbox.execute_tool(
            "upsert_clinical_note",
            {
                "slug": "urology-visit-plan",
                "title": "Urology Visit Plan (Updated)",
                "note_type": "visit",
                "content": "Updated checklist content",
            },
            alice_ctx,
        )
        assert update_res["record"]["operation"] == "updated"

        async with isolated_db_toolbox_env() as session:
            jobs = (
                await session.execute(
                    select(Job).where(
                        Job.profile_id == "prof-alice", Job.kind == "index_doc"
                    )
                )
            ).scalars().all()
            assert len(jobs) >= 1
            notes = (
                await session.execute(
                    select(Note).where(Note.profile_id == "prof-alice")
                )
            ).scalars().all()
            assert len(notes) == 1
            assert notes[0].title == "Urology Visit Plan (Updated)"

    async def test_record_vital_reading_synthesizes_fhir_and_detects_red_flags(
        self,
        isolated_db_toolbox_env: async_sessionmaker[AsyncSession],
    ) -> None:
        toolbox = get_db_toolbox()
        alice_ctx = SimpleNamespace(profile_id="prof-alice", locale="en-US")

        vital_res = await toolbox.execute_tool(
            "record_vital_reading",
            {
                "vital_type": "blood_pressure",
                "systolic": 186,
                "diastolic": 124,
                "unit": "mmHg",
            },
            alice_ctx,
        )
        assert vital_res["status"] == "ok"
        assert vital_res["fhir_resource"]["resourceType"] == "Observation"
        assert len(vital_res["red_flags"]) >= 1

        # Native declarative SQL read (`list_vital_readings`) returns the persisted row
        listed = await toolbox.execute_tool(
            "list_vital_readings", {"limit": 10}, alice_ctx
        )
        assert listed["count"] == 1
        assert listed["records"][0]["profile_id"] == "prof-alice"

    async def test_native_declarative_sql_crud_execution(
        self,
        isolated_db_toolbox_env: async_sessionmaker[AsyncSession],
    ) -> None:
        toolbox = get_db_toolbox()
        alice_ctx = SimpleNamespace(profile_id="prof-alice", locale="en-US")
        bob_ctx = SimpleNamespace(profile_id="prof-bob", locale="es-ES")

        appt_res = await toolbox.execute_tool(
            "create_appointment_record",
            {
                "title": "Urology Follow-up",
                "provider_name": "Dr. Patel",
                "specialty": "Urology",
                "start_time": "2026-11-01T14:00:00Z",
                "preparation_notes": "Bring prior ultrasound report",
            },
            alice_ctx,
        )
        assert appt_res["status"] == "ok"
        assert appt_res["record"]["title"] == "Urology Follow-up"

        assert (
            await toolbox.execute_tool("list_appointment_records", {}, alice_ctx)
        )["count"] == 1
        assert (
            await toolbox.execute_tool("list_appointment_records", {}, bob_ctx)
        )["count"] == 0

        prev_res = await toolbox.execute_tool(
            "update_preventive_record",
            {
                "rule_id": "uspstf-blood-pressure-screening",
                "status": "completed",
                "notes": "Checked at clinic",
            },
            alice_ctx,
        )
        assert prev_res["status"] == "ok"
        prevs = await toolbox.execute_tool("list_preventive_records", {}, alice_ctx)
        assert prevs["count"] == 1
        assert prevs["records"][0]["rule_id"] == "uspstf-blood-pressure-screening"

    async def test_dynamic_m_schema_and_ast_sandbox_queries(
        self,
        isolated_db_toolbox_env: async_sessionmaker[AsyncSession],
    ) -> None:
        toolbox = get_db_toolbox()

        schema_res = toolbox.inspect_schema(table_names=["notes", "appointments"])
        assert schema_res["status"] == "ok"
        assert {t["table"] for t in schema_res["tables"]} == {"notes", "appointments"}
        assert "notes" in schema_res["m_schema"]

        mut_res = await toolbox.execute_dynamic_mutation(
            operation="INSERT",
            statement=(
                "INSERT INTO notes (slug, title, type, content) "
                "VALUES (:slug, :title, :type, :content)"
            ),
            parameters={
                "slug": "dynamic-visit-prep",
                "title": "Dynamic Visit Prep",
                "type": "visit",
                "content": "Bring medication list",
            },
            profile_id="prof-alice",
        )
        assert mut_res["status"] == "ok"

        alice_rows = await toolbox.execute_dynamic_query(
            statement="SELECT slug, title FROM notes WHERE slug = :slug",
            parameters={"slug": "dynamic-visit-prep"},
            profile_id="prof-alice",
        )
        assert alice_rows["count"] == 1

        bob_rows = await toolbox.execute_dynamic_query(
            statement="SELECT slug, title FROM notes WHERE slug = :slug OR 1=1",
            parameters={"slug": "dynamic-visit-prep"},
            profile_id="prof-bob",
        )
        assert bob_rows["count"] == 0

        with pytest.raises(SqlSecurityError):
            await toolbox.execute_dynamic_mutation(
                operation="DELETE",
                statement="DROP TABLE notes",
                profile_id="prof-alice",
            )
