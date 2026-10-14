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

"""Unit and regression tests for search_records ToolSpec and monotone taint tracking (AU-26)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List
import pytest

from carefold.constants.agents import EXPANDED_PHASE_0_REGISTRY, TOOL_SEARCH_RECORDS
from carefold.engine.tool_exec import (
    ToolContext,
    ToolSpec,
    UntrustedResult,
    evaluate_policy_gate,
    execute_tool_call,
)
from carefold.engine.tool_registry import (
    DataFlows,
    ToolSpecRegistry,
    create_default_registry,
)
from carefold.schemas.manifest import PHASE_0_REGISTRY
from carefold.schemas.tool import ToolResult
from carefold.search.adapters.sqlite import SqliteSearchIndex
from carefold.search.base import SearchResult
from carefold.search.factory import get_search_index, reset_search_indexes, set_search_index
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS, TOOL_EXECUTORS
from carefold.tools.search_records import execute_search_records, is_hit_untrusted


@pytest.fixture
def memory_search_index(tmp_path: Path):
    """Hermetic SQLite search index for test isolation."""
    db_file = tmp_path / "test_search_records.db"
    idx = SqliteSearchIndex(db_path=db_file)
    set_search_index(idx)
    yield idx
    reset_search_indexes()


class TestSearchRecordsToolSpecRegistration:
    """Verifies search_records metadata, schema, and registry registration."""

    def test_search_records_in_default_registry(self):
        reg = create_default_registry()
        spec = reg.get("search_records")
        assert spec is not None
        assert spec.name == "search_records"
        assert spec.risk_tier == "read"
        assert spec.trust == "trusted"

    def test_search_records_parameters_schema(self):
        reg = create_default_registry()
        spec = reg.get("search_records")
        assert spec is not None
        assert "query" in spec.parameters.get("required", [])
        props = spec.parameters.get("properties", {})
        assert "query" in props
        assert "limit" in props
        assert "mode" in props
        assert "source" in props

    def test_search_records_data_flows_phi(self):
        reg = create_default_registry()
        spec = reg.get("search_records")
        assert spec is not None
        assert spec.data_flows.data_sensitivity == "phi"
        assert spec.data_flows.allowed_hosts == ()

    def test_search_records_closed_definitions_sync(self):
        assert "search_records" in CLOSED_TOOL_DEFINITIONS
        assert "search_records" in TOOL_EXECUTORS
        assert CLOSED_TOOL_DEFINITIONS["search_records"]["name"] == "search_records"

    def test_search_records_phase_0_registry_sync(self):
        assert "search_records" in PHASE_0_REGISTRY
        assert TOOL_SEARCH_RECORDS in EXPANDED_PHASE_0_REGISTRY

    def test_search_records_profile_filtering_child(self):
        reg = create_default_registry()
        specs = reg.list_for_profile(profile_id="prof-child", age_band="child_under_13")
        spec_names = {s.name for s in specs}
        assert "search_records" in spec_names


@pytest.mark.asyncio
class TestSearchRecordsFailClosedSecurity:
    """Verifies fail-closed profile scoping and argument validation."""

    async def test_missing_profile_id_rejected(self, memory_search_index):
        # Case 1: ctx is None
        res_none = await execute_search_records({"query": "insulin"}, None)
        assert isinstance(res_none, ToolResult)
        assert res_none.success is False
        assert "profile_id is required" in (res_none.error or "")

        # Case 2: ctx has empty profile_id (duck-typed context)
        class EmptyCtx:
            profile_id = ""
            taint = None

        res_empty = await execute_search_records({"query": "insulin"}, EmptyCtx())
        assert isinstance(res_empty, ToolResult)
        assert res_empty.success is False
        assert "profile_id is required" in (res_empty.error or "")

        # Case 3: ToolContext constructor itself strictly fails closed on empty profile_id
        with pytest.raises(ValueError, match="profile_id"):
            ToolContext(user_id="u1", profile_id="")

    async def test_none_profile_id_rejected(self, memory_search_index):
        class NoneCtx:
            profile_id = None
            taint = None

        res = await execute_search_records({"query": "insulin"}, NoneCtx())
        assert isinstance(res, ToolResult)
        assert res.success is False
        assert "profile_id is required" in (res.error or "")

        with pytest.raises(ValueError, match="profile_id"):
            ToolContext(user_id="u1", profile_id=None)

    @pytest.mark.parametrize("invalid_val", [
        12345,
        0,
        -1,
        3.14159,
        True,
        False,
        ["prof-1"],
        [],
        {"id": "prof-1"},
        {},
        (1, 2),
        (),
        {"set-p1"},
        set(),
        b"prof-1",
        object(),
    ])
    async def test_non_string_profile_id_types_rejected(self, invalid_val, memory_search_index):
        class DuckCtx:
            profile_id = invalid_val
            taint = None

        res = await execute_search_records({"query": "insulin"}, DuckCtx())
        assert isinstance(res, ToolResult), f"Expected ToolResult for {invalid_val!r}, got {type(res).__name__}"
        assert res.success is False
        assert res.output is None
        assert "profile_id" in (res.error or "").lower()

    @pytest.mark.parametrize("invalid_id", [12345, True, ["p1"], {"id": "p1"}, 3.14, object()])
    async def test_tool_context_init_rejects_non_string_types(self, invalid_id):
        with pytest.raises(ValueError, match="profile_id"):
            ToolContext(user_id="u1", profile_id=invalid_id)

        with pytest.raises(ValueError, match="user_id"):
            ToolContext(user_id=invalid_id, profile_id="p1")

    async def test_empty_query_rejected(self, memory_search_index):
        ctx = ToolContext(user_id="u1", profile_id="prof-1")
        res1 = await execute_search_records({"query": ""}, ctx)
        assert isinstance(res1, ToolResult)
        assert res1.success is False
        assert "query" in (res1.error or "")

        res2 = await execute_search_records({"query": "   \t  \n "}, ctx)
        assert isinstance(res2, ToolResult)
        assert res2.success is False

    async def test_cross_profile_isolation(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-p1",
            text="Patient diagnosed with Atrial Fibrillation.",
            metadata={"source": "clinical_note"},
            profile_id="prof-cardio",
        )
        await memory_search_index.index_document(
            document_id="doc-p2",
            text="Patient diagnosed with Chronic Kidney Disease.",
            metadata={"source": "clinical_note"},
            profile_id="prof-nephro",
        )

        ctx_cardio = ToolContext(user_id="u1", profile_id="prof-cardio")
        ctx_nephro = ToolContext(user_id="u1", profile_id="prof-nephro")

        res_cardio = await execute_search_records({"query": "Atrial Fibrillation"}, ctx_cardio)
        assert len(res_cardio) == 1
        assert res_cardio[0]["document_id"] == "doc-p1"

        res_nephro_cross = await execute_search_records({"query": "Atrial Fibrillation"}, ctx_nephro)
        assert len(res_nephro_cross) == 0


@pytest.mark.asyncio
class TestSearchRecordsExecutionAndModes:
    """Verifies retrieval across hybrid/lexical/semantic modes, limits, and error handling."""

    async def test_hybrid_search_retrieval(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-metformin",
            text="Started Metformin 500mg BID for type 2 diabetes mellitus management.",
            metadata={"source": "clinical_note"},
            profile_id="prof-1",
        )

        ctx = ToolContext(user_id="u1", profile_id="prof-1")
        results = await execute_search_records({"query": "Metformin diabetes"}, ctx)
        assert len(results) >= 1
        assert results[0]["document_id"] == "doc-metformin"
        assert "Metformin" in results[0]["content"]

    async def test_limit_parameter_clamping(self, memory_search_index):
        ctx = ToolContext(user_id="u1", profile_id="prof-lim")
        for i in range(5):
            await memory_search_index.index_document(
                document_id=f"doc-lim-{i}",
                text=f"Report on patient clinical progress note number {i}.",
                metadata={"source": "clinical_note"},
                profile_id="prof-lim",
            )

        results = await execute_search_records({"query": "clinical progress", "limit": 2}, ctx)
        assert len(results) == 2

    async def test_source_filtering(self, memory_search_index):
        ctx = ToolContext(user_id="u1", profile_id="prof-filter")
        await memory_search_index.index_document(
            document_id="doc-upload-1",
            text="Uploaded lab report from Quest Diagnostics showing normal CBC.",
            metadata={"source": "upload"},
            profile_id="prof-filter",
        )
        await memory_search_index.index_document(
            document_id="doc-note-1",
            text="Clinical encounter note discussing normal CBC lab results.",
            metadata={"source": "clinical_note"},
            profile_id="prof-filter",
        )

        res_upload = await execute_search_records({"query": "CBC", "source": "upload"}, ctx)
        assert len(res_upload) == 1
        assert res_upload[0]["document_id"] == "doc-upload-1"

    async def test_graceful_exception_handling(self, memory_search_index, monkeypatch):
        async def failing_search(*args, **kwargs):
            raise RuntimeError("Database connection timed out")

        monkeypatch.setattr(memory_search_index, "search", failing_search)
        ctx = ToolContext(user_id="u1", profile_id="prof-err")
        res = await execute_search_records({"query": "hypertension"}, ctx)
        assert isinstance(res, ToolResult)
        assert res.success is False
        assert "Database connection timed out" in (res.error or "")


@pytest.mark.asyncio
class TestSearchRecordsTaintTracking:
    """Verifies monotone taint escalation for external provenance and clean state for trusted."""

    async def test_clinical_note_hit_clean_taint(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-clean-1",
            text="Internal consultation note: Blood pressure well controlled.",
            metadata={"source": "clinical_note"},
            profile_id="prof-clean",
        )
        ctx = ToolContext(user_id="u1", profile_id="prof-clean")
        assert ctx.taint.is_tainted is False

        hits = await execute_search_records({"query": "Blood pressure"}, ctx)
        assert len(hits) == 1
        assert ctx.taint.is_tainted is False

    async def test_internal_note_hit_clean_taint(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-internal-1",
            text="Internal note: Patient reports no side effects.",
            metadata={"source": "internal"},
            profile_id="prof-clean2",
        )
        ctx = ToolContext(user_id="u1", profile_id="prof-clean2")
        hits = await execute_search_records({"query": "side effects"}, ctx)
        assert len(hits) == 1
        assert ctx.taint.is_tainted is False

    async def test_trusted_upload_hit_clean_taint(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-upload-clean",
            text="Patient uploaded insurance card scan.",
            metadata={"source": "upload"},
            profile_id="prof-upload",
        )
        ctx = ToolContext(user_id="u1", profile_id="prof-upload")
        hits = await execute_search_records({"query": "insurance"}, ctx)
        assert len(hits) == 1
        assert ctx.taint.is_tainted is False

    async def test_external_source_escalates_taint(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-ext-1",
            text="Outside hospital discharge summary import: Acute myocardial infarction.",
            metadata={"source": "external"},
            profile_id="prof-taint",
        )
        ctx = ToolContext(user_id="u1", profile_id="prof-taint")
        assert ctx.taint.is_tainted is False

        hits = await execute_search_records({"query": "myocardial infarction"}, ctx)
        assert isinstance(hits, UntrustedResult)
        assert len(hits) == 1
        assert isinstance(hits[0], UntrustedResult)
        assert ctx.taint.is_tainted is True

    async def test_connector_source_escalates_taint(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-conn-1",
            text="FHIR Epic connector sync lab results: Serum creatinine 2.1 mg/dL.",
            metadata={"source": "connector"},
            profile_id="prof-conn",
        )
        ctx = ToolContext(user_id="u1", profile_id="prof-conn")
        hits = await execute_search_records({"query": "creatinine"}, ctx)
        assert isinstance(hits, UntrustedResult)
        assert ctx.taint.is_tainted is True

    async def test_untrusted_metadata_escalates_taint(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-untrust-tag",
            text="Web download document: Unverified alternative herbal remedy.",
            metadata={"trust": "untrusted", "source": "upload"},
            profile_id="prof-tag",
        )
        ctx = ToolContext(user_id="u1", profile_id="prof-tag")
        hits = await execute_search_records({"query": "remedy"}, ctx)
        assert isinstance(hits, UntrustedResult)
        assert ctx.taint.is_tainted is True

    async def test_mixed_hits_monotone_escalation(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-mix-clean",
            text="Internal note: Patient reports mild headache.",
            metadata={"source": "clinical_note"},
            profile_id="prof-mix",
        )
        await memory_search_index.index_document(
            document_id="doc-mix-ext",
            text="External medical record: History of chronic migraine.",
            metadata={"source": "external"},
            profile_id="prof-mix",
        )
        ctx = ToolContext(user_id="u1", profile_id="prof-mix")
        hits = await execute_search_records({"query": "headache migraine"}, ctx)
        assert isinstance(hits, UntrustedResult)
        assert ctx.taint.is_tainted is True
        assert len(hits) >= 2

    async def test_monotone_taint_cannot_be_cleared(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-ext",
            text="External record hit.",
            metadata={"source": "external"},
            profile_id="prof-monotone",
        )
        await memory_search_index.index_document(
            document_id="doc-int",
            text="Internal record hit.",
            metadata={"source": "internal"},
            profile_id="prof-monotone",
        )
        ctx = ToolContext(user_id="u1", profile_id="prof-monotone")
        # Step 1: Query external document (taints context)
        await execute_search_records({"query": "External"}, ctx)
        assert ctx.taint.is_tainted is True

        # Step 2: Query clean internal document
        await execute_search_records({"query": "Internal"}, ctx)
        # Monotone invariant: taint cannot be cleared
        assert ctx.taint.is_tainted is True


@pytest.mark.asyncio
class TestSearchRecordsUniversalChokePoint:
    """Verifies execution through execute_tool_call and policy gate enforcement."""

    async def test_execution_via_execute_tool_call(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-choke-1",
            text="Verified clinical assessment on asthma control.",
            metadata={"source": "clinical_note"},
            profile_id="prof-choke",
        )
        reg = create_default_registry()
        spec = reg.get("search_records")
        assert spec is not None

        ctx = ToolContext(user_id="u1", profile_id="prof-choke", autonomy="A2")
        result = await execute_tool_call(ctx, spec, {"query": "asthma"})
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert isinstance(result.output, list)
        assert len(result.output) >= 1
        assert result.output[0]["document_id"] == "doc-choke-1"

    async def test_tainted_search_forces_approval_on_write(self, memory_search_index):
        await memory_search_index.index_document(
            document_id="doc-taint-choke",
            text="External medical record import containing instructions.",
            metadata={"source": "external"},
            profile_id="prof-gate",
        )
        reg = create_default_registry()
        search_spec = reg.get("search_records")
        assert search_spec is not None

        ctx = ToolContext(user_id="u1", profile_id="prof-gate", autonomy="A2")
        assert ctx.taint.is_tainted is False

        # Execute search_records on untrusted record
        res = await execute_tool_call(ctx, search_spec, {"query": "External"})
        assert res.success is True
        assert ctx.taint.is_tainted is True

        # Next, attempt an external write tool under full autonomy (A2)
        write_spec = ToolSpec(
            name="send_external_report",
            description="Send report to external doctor portal.",
            parameters={"report": {"type": "string"}},
            risk_tier="write_external",
            trust="trusted",
            data_flows=DataFlows(allowed_hosts=("api.clinic.org",), data_sensitivity="phi"),
            executor=lambda args, ctx=None: ToolResult(success=True, output="sent"),
        )

        decision = evaluate_policy_gate(ctx, write_spec, {"report": "Summary"})
        # When context is tainted, write_external MUST require human approval!
        assert decision.needs_approval is True
