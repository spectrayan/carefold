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

"""Unit and integration tests for the declarative MCP Toolbox for Databases (mcp_db_toolbox)."""

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
from carefold.engine.tool_registry import create_default_registry
from carefold.tools.mcp_db_toolbox import (
    DEFAULT_DB_TOOLS_YAML_PATH,
    RESERVED_CONTEXT_PARAMS,
    get_db_toolbox,
)
from carefold.workflows.nodes.agent_execution_node import AgentExecutionNode


@pytest_asyncio.fixture
async def isolated_db_toolbox_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Creates an isolated SQLite database and patches get_session_factory for MCP DB tool tests."""
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


class TestMcpDbToolboxManifestAndSchemas:
    """Verifies YAML manifest structure, toolsets, and LLM schema sanitization."""

    def test_manifest_loads_all_declared_tools_and_toolsets(self) -> None:
        assert DEFAULT_DB_TOOLS_YAML_PATH.is_file()
        toolbox = get_db_toolbox()
        tool_names = set(toolbox.list_tool_names())
        expected = {
            "upsert_clinical_note",
            "list_clinical_notes",
            "get_clinical_note",
            "record_vital_reading",
            "list_vital_readings",
            "create_appointment_record",
            "list_appointment_records",
            "create_profile_reminder",
            "list_profile_reminders",
            "update_preventive_record",
            "list_preventive_records",
            "create_email_draft_record",
        }
        assert expected.issubset(tool_names)

        assert "upsert_clinical_note" in toolbox.get_toolset("clinical_assist_db")
        assert "record_vital_reading" in toolbox.get_toolset("clinical_assist_db")
        assert "create_email_draft_record" in toolbox.get_toolset("navigation_db")
        assert "record_vital_reading" in toolbox.get_toolset("wellness_db")

    def test_reserved_context_parameters_never_exposed_in_json_schema(self) -> None:
        toolbox = get_db_toolbox()
        for name, cfg in toolbox.manifest.tools.items():
            schema = cfg.to_json_schema()
            props = set(schema.get("properties", {}).keys())
            assert props.isdisjoint(RESERVED_CONTEXT_PARAMS), (
                f"Tool '{name}' leaked reserved context parameters into JSON schema: {props & RESERVED_CONTEXT_PARAMS}"
            )
            pin_hash = cfg.compute_pin_hash(name)
            assert len(pin_hash) == 64

    def test_registered_in_default_tool_registry(self) -> None:
        reg = create_default_registry()
        for name in (
            "upsert_clinical_note",
            "list_clinical_notes",
            "record_vital_reading",
            "create_appointment_record",
            "create_profile_reminder",
            "update_preventive_record",
            "create_email_draft_record",
        ):
            spec = reg.get(name)
            assert spec is not None
            assert spec.metadata.get("source") == "mcp_db_toolbox"
            tool_def = spec.to_tool_definition()
            assert tool_def["name"] == name
            assert "properties" in tool_def["parameters"]


@pytest.mark.asyncio
class TestMcpDbToolboxExecutionAndSecurity:
    """Verifies parameterized SQL execution, domain hooks, and cross-profile tenant isolation."""

    async def test_missing_profile_id_fails_closed(self, isolated_db_toolbox_env: async_sessionmaker[AsyncSession]) -> None:
        toolbox = get_db_toolbox()
        with pytest.raises(ValueError, match="ToolContext is required"):
            await toolbox.execute_tool("list_clinical_notes", {}, None)

        empty_ctx = SimpleNamespace(profile_id="   ")
        with pytest.raises(ValueError, match="profile_id is required"):
            await toolbox.execute_tool("list_clinical_notes", {}, empty_ctx)

    async def test_upsert_and_query_clinical_note_with_tenant_isolation(
        self,
        isolated_db_toolbox_env: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        toolbox = get_db_toolbox()
        alice_ctx = SimpleNamespace(profile_id="prof-alice", locale="en-US", workspace_root=tmp_path)
        bob_ctx = SimpleNamespace(profile_id="prof-bob", locale="es-ES", workspace_root=tmp_path)

        # Attempt to spoof profile_id in args -> must be ignored and bound to alice_ctx.profile_id
        save_res = await toolbox.execute_tool(
            "upsert_clinical_note",
            {
                "profile_id": "prof-bob",
                "slug": "urology-visit-plan",
                "title": "Urology Visit Plan",
                "note_type": "visit",
                "content": "## Questions for Urologist\n1. PSA trend review\n2. Kidney ultrasound follow-up",
                "tags_json": '["urology", "prep"]',
            },
            alice_ctx,
        )
        assert save_res["status"] == "saved"
        assert save_res["note"]["profile_id"] == "prof-alice"
        assert save_res["note"]["slug"] == "urology-visit-plan"
        assert save_res["note"]["operation"] == "created"
        assert (tmp_path / "notes" / "urology-visit-plan.md").is_file()

        # Verify Bob cannot see Alice's note
        bob_list = await toolbox.execute_tool("list_clinical_notes", {}, bob_ctx)
        assert bob_list["count"] == 0

        # Verify Alice can list and fetch her note
        alice_list = await toolbox.execute_tool("list_clinical_notes", {}, alice_ctx)
        assert alice_list["count"] == 1
        assert alice_list["items"][0]["slug"] == "urology-visit-plan"

        alice_detail = await toolbox.execute_tool(
            "get_clinical_note",
            {"slug": "urology-visit-plan"},
            alice_ctx,
        )
        assert alice_detail["note"] is not None
        assert "PSA trend review" in alice_detail["note"]["content"]

        # Update existing note on conflict
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
        assert update_res["note"]["operation"] == "updated"
        assert update_res["note"]["title"] == "Urology Visit Plan (Updated)"

        # Verify index_doc job was enqueued in DB
        async with isolated_db_toolbox_env() as session:
            jobs = (
                await session.execute(
                    select(Job).where(Job.profile_id == "prof-alice", Job.kind == "index_doc")
                )
            ).scalars().all()
            assert len(jobs) >= 1
            notes = (
                await session.execute(select(Note).where(Note.profile_id == "prof-alice"))
            ).scalars().all()
            assert len(notes) == 1

    async def test_record_and_list_vital_readings_with_red_flag_detection(
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
        assert vital_res["status"] == "recorded"
        assert vital_res["fhir_resource"]["resourceType"] == "Observation"
        assert len(vital_res["red_flags"]) >= 1

        listed = await toolbox.execute_tool("list_vital_readings", {"limit": 10}, alice_ctx)
        assert listed["count"] == 1
        assert listed["items"][0]["profile_id"] == "prof-alice"

    async def test_appointments_reminders_preventive_and_email_drafts(
        self,
        isolated_db_toolbox_env: async_sessionmaker[AsyncSession],
    ) -> None:
        toolbox = get_db_toolbox()
        alice_ctx = SimpleNamespace(profile_id="prof-alice", locale="en-US")

        # 1. Appointment
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
        assert appt_res["status"] == "saved"
        assert appt_res["record"]["title"] == "Urology Follow-up"

        appts = await toolbox.execute_tool("list_appointment_records", {}, alice_ctx)
        assert appts["count"] == 1

        # 2. Reminder
        rem_res = await toolbox.execute_tool(
            "create_profile_reminder",
            {
                "title": "Complete pre-visit urinalysis lab",
                "next_due_at": "2026-10-28T09:00:00Z",
                "category": "prep",
            },
            alice_ctx,
        )
        assert rem_res["status"] == "saved"

        rems = await toolbox.execute_tool("list_profile_reminders", {}, alice_ctx)
        assert rems["count"] == 1

        # 3. Preventive Record
        prev_res = await toolbox.execute_tool(
            "update_preventive_record",
            {
                "rule_id": "uspstf-blood-pressure-screening",
                "status": "completed",
                "notes": "Checked at clinic",
            },
            alice_ctx,
        )
        assert prev_res["status"] == "saved"

        prevs = await toolbox.execute_tool("list_preventive_records", {}, alice_ctx)
        assert prevs["count"] == 1
        assert prevs["items"][0]["rule_id"] == "uspstf-blood-pressure-screening"

        # 4. Email Draft (No Auto-Send)
        draft_res = await toolbox.execute_tool(
            "create_email_draft_record",
            {
                "recipient": "records@clinic.example.org",
                "subject": "Request for Urology Ultrasound Report",
                "body": "Please send my renal and bladder ultrasound report.",
                "category": "appointment",
            },
            alice_ctx,
        )
        assert draft_res["status"] == "draft_created"
        assert draft_res["auto_send"] is False
        assert draft_res["mailto_uri"].startswith("mailto:records%40clinic.example.org")

    async def test_agent_execution_node_expands_db_toolset(self) -> None:
        node = AgentExecutionNode()
        manifest = SimpleNamespace(
            id="urology-guide",
            domain="clinical",
            risk_class="clinical_assist",
            tools=["attach-read", "workspace-note", "skill-docs"],
        )
        resolved = node._resolve_tools(
            "urology-guide",
            manifest,
            {"db_toolset": "auto"},
        )
        resolved_names = {t["name"] for t in resolved if isinstance(t, dict)}
        assert "workspace-note" in resolved_names
        assert "upsert_clinical_note" in resolved_names
        assert "record_vital_reading" in resolved_names
        assert "create_appointment_record" in resolved_names
        assert "create_profile_reminder" in resolved_names
