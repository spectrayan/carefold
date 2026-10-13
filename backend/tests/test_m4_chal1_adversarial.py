# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Adversarial challenge test suite for Milestone 4 (AU-26, AU-27).

Empirical challenger suite:
1. Fail-closed scoping stress (missing, empty, whitespace, and invalid profile_id types).
2. Parameter boundary attacks (limits, empty query, high-entropy binary, regex chars).
3. Taint escalation stress (untrusted sources, untrusted metadata markers, unrecognized sources).
4. Monotone taint invariant stress (clean queries never un-taint).
5. Downstream policy gate enforcement (tainted context forces approval on write_external under A0/A1/A2).
6. Sequence emulation on UntrustedResult (iteration, indexing, len, slicing, contains, equality).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from carefold.engine.tool_exec import (
    ToolContext,
    ToolSpec,
    UntrustedResult,
    evaluate_policy_gate,
    execute_tool_call,
)
from carefold.engine.tool_registry import DataFlows, create_default_registry
from carefold.schemas.tool import ToolResult
from carefold.search.adapters.sqlite import SqliteSearchIndex
from carefold.search.base import SearchIndex, SearchResult
from carefold.search.factory import reset_search_indexes, set_search_index
from carefold.tools.search_records import (
    TRUSTED_SOURCES,
    UNTRUSTED_SOURCES,
    execute_search_records,
    is_hit_untrusted,
)


class SpySearchIndex(SearchIndex):
    """Spy search index tracking all search invocations and arguments."""

    def __init__(self):
        self.search_called: bool = False
        self.call_count: int = 0
        self.last_query: Optional[str] = None
        self.last_profile_id: Optional[str] = None
        self.last_limit: Optional[int] = None
        self.last_mode: Optional[str] = None
        self.last_filters: Optional[Dict[str, Any]] = None

    async def search(
        self,
        query: str,
        profile_id: str,
        limit: int = 10,
        mode: str = "hybrid",
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        self.search_called = True
        self.call_count += 1
        self.last_query = query
        self.last_profile_id = profile_id
        self.last_limit = limit
        self.last_mode = mode
        self.last_filters = filters
        return []

    async def index_document(self, document_id: str, text: str, metadata: dict, profile_id: str, user_id: str | None = None) -> None:
        pass

    async def delete_document(self, document_id: str, profile_id: str) -> bool:
        return True

    async def reindex_all(self, profile_id: str) -> int:
        return 0


class DuckContext:
    """Duck-typed execution context for adversarial testing."""

    def __init__(self, profile_id: Any, taint: Any = None):
        self.profile_id = profile_id
        self.taint = taint


@pytest.fixture
def spy_index():
    spy = SpySearchIndex()
    set_search_index(spy)
    yield spy
    reset_search_indexes()


@pytest.fixture
def sqlite_index(tmp_path: Path):
    db_file = tmp_path / "chal1_sqlite_test.db"
    idx = SqliteSearchIndex(db_path=db_file)
    set_search_index(idx)
    yield idx
    reset_search_indexes()


# ============================================================================
# Section 1: Fail-Closed Profile Scoping Stress
# ============================================================================

@pytest.mark.asyncio
class TestFailClosedProfileScopingStress:
    """Stress tests verifying that missing, empty, whitespace, or invalid-type profile_id fail closed."""

    async def test_ctx_none_rejected_without_querying_index(self, spy_index):
        res = await execute_search_records({"query": "warfarin"}, ctx=None)
        assert isinstance(res, ToolResult)
        assert res.success is False
        assert "profile_id is required" in (res.error or "")
        assert spy_index.search_called is False

    async def test_ctx_missing_profile_id_attr_rejected(self, spy_index):
        class MissingAttrCtx:
            taint = None

        res = await execute_search_records({"query": "warfarin"}, ctx=MissingAttrCtx())
        assert isinstance(res, ToolResult)
        assert res.success is False
        assert "profile_id is required" in (res.error or "")
        assert spy_index.search_called is False

    async def test_ctx_profile_id_none_rejected(self, spy_index):
        ctx = DuckContext(profile_id=None)
        res = await execute_search_records({"query": "warfarin"}, ctx=ctx)
        assert isinstance(res, ToolResult)
        assert res.success is False
        assert "profile_id is required" in (res.error or "")
        assert spy_index.search_called is False

    async def test_ctx_profile_id_empty_string_rejected(self, spy_index):
        ctx = DuckContext(profile_id="")
        res = await execute_search_records({"query": "warfarin"}, ctx=ctx)
        assert isinstance(res, ToolResult)
        assert res.success is False
        assert "profile_id is required" in (res.error or "")
        assert spy_index.search_called is False

    async def test_ctx_profile_id_whitespace_rejected(self, spy_index):
        for ws in [" ", "   ", "\t", "\n", " \t \n  "]:
            spy_index.search_called = False
            ctx = DuckContext(profile_id=ws)
            res = await execute_search_records({"query": "warfarin"}, ctx=ctx)
            assert isinstance(res, ToolResult)
            assert res.success is False
            assert "profile_id is required" in (res.error or "")
            assert spy_index.search_called is False

    async def test_ctx_profile_id_invalid_types_fail_closed(self, spy_index):
        """Adversarial stress: non-string profile_id types MUST return ToolResult(success=False)

        and must NEVER query the underlying search index.
        """
        invalid_types = [
            12345,
            0,
            -1,
            True,
            False,
            ["profile-1"],
            [],
            {"id": "profile-1"},
            {},
            (1, 2),
            (),
            3.14159,
            b"prof-1",
            object(),
        ]
        for invalid_val in invalid_types:
            spy_index.search_called = False
            spy_index.call_count = 0
            ctx = DuckContext(profile_id=invalid_val)
            res = await execute_search_records({"query": "warfarin"}, ctx=ctx)

            assert isinstance(res, ToolResult), (
                f"Expected ToolResult for invalid profile_id={invalid_val!r} (type {type(invalid_val).__name__}), "
                f"got {type(res).__name__}"
            )
            assert res.success is False, (
                f"Expected success=False for invalid profile_id={invalid_val!r}, got success={res.success}"
            )
            assert res.output is None, (
                f"Expected output=None for invalid profile_id={invalid_val!r}, got output={res.output!r}"
            )
            assert "profile_id" in (res.error or "").lower(), (
                f"Expected error message citing profile_id, got: {res.error}"
            )
            assert spy_index.search_called is False, (
                f"Security violation: Search index was queried with invalid profile_id={invalid_val!r}!"
            )
            assert spy_index.call_count == 0


# ============================================================================
# Section 2: Parameter Boundary Attacks
# ============================================================================

@pytest.mark.asyncio
class TestParameterBoundaryAttacks:
    """Stress tests on limit, query, and payload boundaries."""

    async def test_limit_boundaries(self, spy_index):
        ctx = DuckContext(profile_id="prof-bounds")

        # Negative limit clamped to 1
        await execute_search_records({"query": "aspirin", "limit": -10}, ctx=ctx)
        assert spy_index.last_limit == 1

        # Zero limit clamped to 1
        await execute_search_records({"query": "aspirin", "limit": 0}, ctx=ctx)
        assert spy_index.last_limit == 1

        # High limit clamped to 50
        await execute_search_records({"query": "aspirin", "limit": 10000}, ctx=ctx)
        assert spy_index.last_limit == 50

        # Non-integer / invalid limit falls back to default 5
        await execute_search_records({"query": "aspirin", "limit": "invalid"}, ctx=ctx)
        assert spy_index.last_limit == 5

        await execute_search_records({"query": "aspirin", "limit": None}, ctx=ctx)
        assert spy_index.last_limit == 5

    async def test_empty_and_whitespace_queries_rejected(self, spy_index):
        ctx = DuckContext(profile_id="prof-bounds")
        for q in ["", " ", "   ", "\t\t", "\n\r"]:
            spy_index.search_called = False
            res = await execute_search_records({"query": q}, ctx=ctx)
            assert isinstance(res, ToolResult)
            assert res.success is False
            assert "query" in (res.error or "").lower()
            assert spy_index.search_called is False

    async def test_high_entropy_binary_and_regex_queries(self, sqlite_index):
        ctx = DuckContext(profile_id="prof-bounds")
        adversarial_queries = [
            ".*+?^$()[]{}|\\",
            "\"\"\"",
            "AND OR NOT",
            "NEAR(foo, bar)",
            "*",
            "\x00\x01\xfe\xff",
            "A" * 10000,
            "DROP TABLE documents; -- ' OR 1=1",
        ]
        for q in adversarial_queries:
            # Must not crash or raise uncaught exception
            res = await execute_search_records({"query": q}, ctx=ctx)
            assert isinstance(res, (list, ToolResult, UntrustedResult))


# ============================================================================
# Section 3: Taint Escalation Stress
# ============================================================================

@pytest.mark.asyncio
class TestTaintEscalationStress:
    """Verifies that untrusted sources and metadata markers escalate taint monotonically."""

    async def test_all_untrusted_sources_escalate_taint(self, sqlite_index):
        sources = [
            "external",
            "import",
            "connector",
            "email",
            "web",
            "patient_portal",
            "untrusted",
            "external_ehr",
            "third_party",
            "unknown_vendor_feed",
        ]
        for src in sources:
            doc_id = f"doc-src-{src}"
            await sqlite_index.index_document(
                document_id=doc_id,
                text=f"Record containing target_keyword from source {src}",
                metadata={"source": src},
                profile_id="prof-taint-test",
            )
            ctx = ToolContext(user_id="u1", profile_id="prof-taint-test")
            assert ctx.taint.is_tainted is False

            res = await execute_search_records({"query": f"target_keyword {src}"}, ctx=ctx)
            assert isinstance(res, UntrustedResult), f"Source {src} failed to wrap in UntrustedResult"
            assert ctx.taint.is_tainted is True, f"Source {src} failed to set ctx.taint"

    async def test_all_untrusted_metadata_markers_escalate_taint(self, sqlite_index):
        metadata_cases = [
            {"trust": "untrusted"},
            {"trust": "UNTRUSTED"},
            {"untrusted": True},
            {"is_trusted": False},
            {"external": True},
            {"is_external": True},
            {"connector_id": "conn-epic-001"},
            {"connector_type": "fhir_r4"},
            {"origin": "external"},
        ]
        for i, meta in enumerate(metadata_cases):
            doc_id = f"doc-meta-{i}"
            full_meta = dict(meta)
            full_meta["source"] = "upload"  # Normally trusted source, overridden by metadata
            await sqlite_index.index_document(
                document_id=doc_id,
                text=f"Medical text for metadata case {i} target_meta",
                metadata=full_meta,
                profile_id="prof-meta-test",
            )
            ctx = ToolContext(user_id="u1", profile_id="prof-meta-test")
            res = await execute_search_records({"query": f"target_meta doc-meta-{i}"}, ctx=ctx)
            assert isinstance(res, UntrustedResult), f"Metadata {meta} failed to wrap in UntrustedResult"
            assert ctx.taint.is_tainted is True, f"Metadata {meta} failed to set ctx.taint"

    async def test_trusted_sources_remain_untainted(self, sqlite_index):
        trusted_sources = ["clinical_note", "note", "internal", "clinical", "upload"]
        for src in trusted_sources:
            doc_id = f"doc-trusted-{src}"
            await sqlite_index.index_document(
                document_id=doc_id,
                text=f"Trusted encounter text for {src} verified_clean",
                metadata={"source": src},
                profile_id="prof-clean-test",
            )
            ctx = ToolContext(user_id="u1", profile_id="prof-clean-test")
            res = await execute_search_records({"query": f"verified_clean {src}"}, ctx=ctx)
            assert not isinstance(res, UntrustedResult)
            assert ctx.taint.is_tainted is False


# ============================================================================
# Section 4: Monotone Invariant Stress
# ============================================================================

@pytest.mark.asyncio
class TestMonotoneTaintInvariantStress:
    """Verifies that once tainted, subsequent clean operations NEVER reset taint."""

    async def test_subsequent_clean_searches_never_untaint(self, sqlite_index):
        await sqlite_index.index_document(
            document_id="doc-ext-trigger",
            text="Adversarial external discharge summary",
            metadata={"source": "external"},
            profile_id="prof-mono-stress",
        )
        for i in range(10):
            await sqlite_index.index_document(
                document_id=f"doc-clean-{i}",
                text=f"Clean progress note number {i}",
                metadata={"source": "clinical_note"},
                profile_id="prof-mono-stress",
            )

        ctx = ToolContext(user_id="u1", profile_id="prof-mono-stress")
        assert ctx.taint.is_tainted is False

        # Step 1: Trigger taint via untrusted hit
        res_taint = await execute_search_records({"query": "Adversarial external"}, ctx=ctx)
        assert isinstance(res_taint, UntrustedResult)
        assert ctx.taint.is_tainted is True

        # Step 2: Perform 20 clean searches
        for i in range(20):
            res_clean = await execute_search_records({"query": "Clean progress note"}, ctx=ctx)
            assert not isinstance(res_clean, UntrustedResult)
            assert ctx.taint.is_tainted is True, f"Monotone violation: taint was cleared on iteration {i}!"


# ============================================================================
# Section 5: Downstream Policy Gate Enforcement Stress
# ============================================================================

class TestDownstreamPolicyGateStress:
    """Verifies that tainted context blocks write_external across autonomy levels."""

    def test_taint_blocks_write_external_all_autonomy_levels(self):
        spec = ToolSpec(
            name="send_external_telemetry",
            description="Send data to external host",
            risk_tier="write_external",
            trust="trusted",
            parameters={},
            data_flows=DataFlows(allowed_hosts=("api.hospital.org",), data_sensitivity="phi"),
            executor=lambda args, ctx=None: None,
        )

        for auto in ["A0", "A1", "A2"]:
            ctx = ToolContext(
                user_id="u1",
                profile_id="prof-gate-stress",
                autonomy=auto,
                extra={"consents": {"external_write_consent": True}},
            )
            ctx.taint.set()
            assert ctx.taint.is_tainted is True

            decision = evaluate_policy_gate(ctx, spec, {})
            assert decision.needs_approval is True
            assert "tainted" in decision.reason.lower()


# ============================================================================
# Section 6: Sequence Emulation on UntrustedResult
# ============================================================================

class TestUntrustedResultSequenceEmulation:
    """Verifies iteration, indexing, len, slicing, contains, and equality on UntrustedResult."""

    def test_iteration(self):
        # List data
        u = UntrustedResult(data=[10, 20, 30])
        assert [x for x in u] == [10, 20, 30]

        # Scalar data
        u_scalar = UntrustedResult(data="test_val")
        assert [x for x in u_scalar] == ["test_val"]

    def test_indexing(self):
        u = UntrustedResult(data=["first", "second", "third"])
        assert u[0] == "first"
        assert u[-1] == "third"

        u_dict = UntrustedResult(data={"a": 100, "b": 200})
        assert u_dict["a"] == 100

        u_scalar = UntrustedResult(data=42)
        with pytest.raises(TypeError):
            _ = u_scalar[0]

    def test_len(self):
        assert len(UntrustedResult(data=[1, 2, 3, 4])) == 4
        assert len(UntrustedResult(data=(1, 2))) == 2
        assert len(UntrustedResult(data={"k": "v"})) == 1
        assert len(UntrustedResult(data="scalar")) == 1

    def test_slicing(self):
        u = UntrustedResult(data=[0, 1, 2, 3, 4, 5])
        assert u[1:4] == [1, 2, 3]
        assert u[:2] == [0, 1]
        assert u[::2] == [0, 2, 4]
        assert u[::-1] == [5, 4, 3, 2, 1, 0]

    def test_contains(self):
        u = UntrustedResult(data=[10, 20, 30])
        assert 20 in u
        assert 99 not in u

        u_str = UntrustedResult(data="hello")
        assert "hello" in u_str

    def test_equality(self):
        u1 = UntrustedResult(data=[1, 2], taint=True, source="external")
        u2 = UntrustedResult(data=[1, 2], taint=True, source="external")
        u3 = UntrustedResult(data=[1, 2], taint=False, source="external")
        u4 = UntrustedResult(data=[1, 3], taint=True, source="external")

        assert u1 == u2
        assert u1 != u3
        assert u1 != u4
