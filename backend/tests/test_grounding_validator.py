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

"""Grounding Validator and Numerical Extraction Test Suite.

Authoritative stress-testing and verification for:
1. GroundingValidator:
   - Extreme numerical formats: $0, $1,000,000 vs 1000000, 20.5% vs 20.5 percent, unformatted 3500 vs $3,500.
   - Rejection of transposed digits: 1050 vs $1,500, 250 vs 520, 1234 vs 1243.
   - Rejection of hallucinated figures: $9,999, nested ungrounded values in dossiers.
   - Semantic unit mismatches: 20% vs $20, 4 weeks vs 4 days, 120 bpm vs 120 mmHg.
2. Dual-Invocation Extraction:
   - Direct function call: extract_document_dossier(...)
   - Tool invoke: extract_document_dossier.invoke(...)
   - Async tool invoke: await extract_document_dossier.ainvoke(...)
   - State population: in-place modification of state["document_dossiers"].
3. Sandboxed File Reader & Filesystem Isolation:
   - Safe reading of plain text attachments in attachments/.
   - Safe rejection of path traversal (../../etc/passwd, ../../../etc/passwd).
   - Safe rejection of absolute paths (/etc/hosts, /etc/passwd).
   - Safe rejection of null-byte injections (file\\x00.pdf).
   - Safe rejection of URI schemes (file:///etc/passwd).
   - Safe rejection of escaping symlinks.
4. Extraction Subgraph Execution & State Population:
   - create_extraction_subgraph and build_extraction_subgraph compilation.
   - Subgraph execution populating AgentState["document_dossiers"].
   - Automatic dossier type inference (insurance vs clinical).
   - Supervisor routing to document-extractor specialist.
5. Concurrency & Stress Testing:
   - 50 concurrent grounding validations.
   - 50 concurrent tool invocations.
   - Multithreaded execution with ThreadPoolExecutor.
6. Empirical Defect Verification:
   - Defect 1: tool.py line 259 ATTACHMENTS_DIR / file_path raises TypeError because ATTACHMENTS_DIR is a str.
   - Defect 2: Insecure un-sandboxed fallback paths in tool.py candidate_paths (ws_root / file_path, Path(file_path)).
   - Defect 3: ExtractDocumentDossierInput args_schema omits workspace_root, stripping it during invoke.
   - Defect 4: Over-eager _CITY_STATE_ZIP regex in sanitizer.py consuming comma-separated compound clauses.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List
import pytest

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from carefold.config import settings
from carefold.constants.paths import ATTACHMENTS_DIR
from carefold.tools.attach_read import execute_attach_read
from carefold.workflows.state import AgentState, create_initial_state
from carefold.workflows.subgraphs.extraction import (
    ClinicalVisitDossier,
    GenericDocumentDossier,
    GroundingValidator,
    InsuranceBenefitsDossier,
    build_extraction_subgraph,
    create_extraction_subgraph,
    extract_document_dossier,
    extract_numeric_tokens,
    sanitize_pii,
)
from carefold.workflows.subgraphs.supervisor import (
    SPECIALIST_DOCUMENT_EXTRACTOR,
    build_supervisor_subgraph,
)
from tests.fixtures.fake_model import FakeListChatModel


# ============================================================================
# 1. GroundingValidator: Numerical Formats & Equivalence
# ============================================================================

class TestGroundingValidatorNumericalFormats:
    """Verifies format normalization and floating point tolerance across variations."""

    def test_zero_dollar_amount(self):
        """$0 matches 0 dollars and $0."""
        r1 = GroundingValidator.validate_numerical_value("$0", "Your preventive care copay is $0.")
        assert r1.is_grounded is True
        assert len(r1.unmatched_values) == 0

        r2 = GroundingValidator.validate_numerical_value("$0", "Your copay is 0 dollars.")
        assert r2.is_grounded is True

    def test_large_number_with_commas_vs_unformatted(self):
        """$1,000,000 matches 1000000 and vice versa."""
        r1 = GroundingValidator.validate_numerical_value("$1,000,000", "Lifetime limit is 1000000 dollars.")
        assert r1.is_grounded is True

        r2 = GroundingValidator.validate_numerical_value("1000000", "Lifetime limit is $1,000,000.")
        assert r2.is_grounded is True

    def test_decimal_percentages(self):
        """20.5% matches 20.5 percent and vice versa."""
        r1 = GroundingValidator.validate_numerical_value("20.5%", "Coinsurance rate is 20.5 percent.")
        assert r1.is_grounded is True

        r2 = GroundingValidator.validate_numerical_value("20.5 percent", "Coinsurance rate is 20.5%.")
        assert r2.is_grounded is True

    def test_unformatted_number_vs_currency_format(self):
        """unformatted 3500 matches $3,500 and vice versa."""
        r1 = GroundingValidator.validate_numerical_value("3500", "The annual deductible is $3,500.")
        assert r1.is_grounded is True

        r2 = GroundingValidator.validate_numerical_value("$3,500", "The annual deductible is 3500.")
        assert r2.is_grounded is True

    def test_negative_values(self):
        """Negative currency values match accurately."""
        r = GroundingValidator.validate_numerical_value("-$50", "Adjustment is -50 dollars.")
        assert r.is_grounded is True

    def test_extract_numeric_tokens_metadata(self):
        """Verifies tokenizer extracts correct val, currency flags, and percentage flags."""
        tokens = extract_numeric_tokens("Deductible $1,500, copay 20%, stay 24 hours")
        assert len(tokens) == 3
        assert tokens[0]["val"] == 1500.0
        assert tokens[0]["is_currency"] is True
        assert tokens[1]["val"] == 20.0
        assert tokens[1]["is_percentage"] is True
        assert tokens[2]["val"] == 24.0
        assert "hour" in tokens[2]["suffix"]


# ============================================================================
# 2. GroundingValidator: Rejection of Hallucinations & Transpositions
# ============================================================================

class TestGroundingValidatorRejections:
    """Verifies strict rejection of transposed digits, ungrounded figures, and unit mismatches."""

    def test_rejection_of_transposed_digits_1050_vs_1500(self):
        """Transposed digits 1050 vs $1,500 must fail grounding."""
        r = GroundingValidator.validate_numerical_value("1050", "The deductible is $1,500.")
        assert r.is_grounded is False
        assert "1050" in r.unmatched_values

        r_rev = GroundingValidator.validate_numerical_value("$1,500", "The deductible is $1,050.")
        assert r_rev.is_grounded is False

    def test_rejection_of_other_transpositions(self):
        """Transpositions 250 vs $520 and 1234 vs 1243 must fail grounding."""
        r1 = GroundingValidator.validate_numerical_value("250", "The specialist copay is $520.")
        assert r1.is_grounded is False

        r2 = GroundingValidator.validate_numerical_value("1234", "Authorization code 1243.")
        assert r2.is_grounded is False

    def test_rejection_of_hallucinated_figures_9999(self):
        """Hallucinated figure $9,999 must fail grounding."""
        r = GroundingValidator.validate_numerical_value("$9,999", "Deductible is $1,500 and copay is $25.")
        assert r.is_grounded is False
        assert any("9,999" in u for u in r.unmatched_values)

    def test_rejection_of_semantic_unit_mismatch_percent_vs_currency(self):
        """20% must not match $20 and vice versa."""
        r1 = GroundingValidator.validate_numerical_value("20%", "Your copay is $20.")
        assert r1.is_grounded is False

        r2 = GroundingValidator.validate_numerical_value("$20", "Your coinsurance is 20%.")
        assert r2.is_grounded is False

    def test_rejection_of_unit_quantity_mismatch(self):
        """4 weeks must not match 4 days."""
        r = GroundingValidator.validate_numerical_value("4 weeks", "Return in 4 days if symptoms persist.")
        assert r.is_grounded is False

    def test_rejection_of_clinical_vitals_unit_mismatch(self):
        """120 bpm must not match 120 mmHg."""
        r = GroundingValidator.validate_numerical_value("120 bpm", "Blood pressure recorded as 120 mmHg.")
        assert r.is_grounded is False

    def test_dossier_recursive_validation_passes_valid(self):
        """Valid dossier against matching source text passes validation."""
        text = "Deductible is $1,500. Copay is $25. Coinsurance is 20%. OOP Max is $6,000."
        dossier = InsuranceBenefitsDossier(
            deductible="$1,500",
            copays={"office_visit": "$25"},
            coinsurance="20%",
            out_of_pocket_maximum="$6,000",
        )
        res = GroundingValidator.validate(dossier, text)
        assert res.is_grounded is True
        assert len(res.unmatched_values) == 0

    def test_dossier_recursive_validation_flags_hallucinated_nested_field(self):
        """Hallucinated nested copay ($9,999) is detected and pinpointed with path."""
        text = "Deductible is $1,500. Copay is $25. Coinsurance is 20%."
        dossier = InsuranceBenefitsDossier(
            deductible="$1,500",
            copays={"primary_care": "$25", "specialist": "$9,999"},
            coinsurance="20%",
        )
        res = GroundingValidator.validate(dossier, text)
        assert res.is_grounded is False
        assert any("specialist" in u and "9,999" in u for u in res.unmatched_values)


# ============================================================================
# 3. Dual-Invocation Tool Contract
# ============================================================================

class TestDualInvocationExtraction:
    """Verifies extract_document_dossier works identically via direct call and .invoke()."""

    DOC_TEXT = (
        "SCHEDULE OF BENEFITS & COVERAGE\n"
        "Annual Deductible: $1,500\n"
        "Primary Care Visit Copay: $25\n"
        "Specialist Visit Copay: $50\n"
        "Coinsurance: 20%\n"
        "Out-of-Pocket Maximum: $6,000\n"
    )

    def test_direct_function_call(self):
        """Tool invoked as a normal Python function call."""
        res = extract_document_dossier(
            document_text=self.DOC_TEXT,
            dossier_type="insurance",
        )
        assert res["status"] == "success"
        assert res["is_grounded"] is True
        assert res["dossier"]["deductible"] == "$1,500"
        assert res["dossier"]["coinsurance"] == "20%"

    def test_langchain_tool_invoke(self):
        """Tool invoked via LangChain BaseTool.invoke()."""
        res = extract_document_dossier.invoke({
            "document_text": self.DOC_TEXT,
            "dossier_type": "insurance",
        })
        assert res["status"] == "success"
        assert res["is_grounded"] is True
        assert res["dossier"]["deductible"] == "$1,500"

    @pytest.mark.asyncio
    async def test_langchain_tool_ainvoke(self):
        """Tool invoked asynchronously via BaseTool.ainvoke()."""
        res = await extract_document_dossier.ainvoke({
            "document_text": self.DOC_TEXT,
            "dossier_type": "insurance",
        })
        assert res["status"] == "success"
        assert res["is_grounded"] is True
        assert res["dossier"]["deductible"] == "$1,500"

    def test_dual_invocation_output_parity(self):
        """Direct call and tool invoke yield identical outputs."""
        direct = extract_document_dossier(document_text=self.DOC_TEXT, dossier_type="insurance")
        invoked = extract_document_dossier.invoke({"document_text": self.DOC_TEXT, "dossier_type": "insurance"})
        assert direct == invoked

    def test_state_population_in_place(self):
        """Passing state dictionary appends extracted dossier to state['document_dossiers']."""
        state: Dict[str, Any] = {"document_dossiers": []}
        extract_document_dossier(
            document_text=self.DOC_TEXT,
            dossier_type="insurance",
            state=state,
        )
        assert len(state["document_dossiers"]) == 1
        dossier_entry = state["document_dossiers"][0]
        assert dossier_entry["dossier_type"] in ("insurance", "insurance_benefits")
        assert dossier_entry["data"]["deductible"] == "$1,500"
        assert dossier_entry["grounding"]["is_grounded"] is True


# ============================================================================
# 4. Sandboxed File Reader & Filesystem Isolation
# ============================================================================

class TestSandboxedFileReaderSecurity:
    """Verifies attach_read enforces directory boundary containment and blocks escape attempts."""

    @pytest.fixture
    def isolated_sandbox(self):
        """Creates temporary workspace containing attachments/ and notes/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            att_dir = ws / "attachments"
            att_dir.mkdir(parents=True)
            notes_dir = ws / "notes"
            notes_dir.mkdir(parents=True)

            # Legitimate file inside attachments/
            valid_doc = att_dir / "valid_record.txt"
            valid_doc.write_text("CLINICAL VISIT SUMMARY\nReason for visit: Annual checkup\nFollow-up: 2 weeks\n")

            # Sensitive file in notes/ (outside attachments/)
            secret_note = notes_dir / "secret.txt"
            secret_note.write_text("Confidential medical research data")

            # Symlink inside attachments/ pointing to notes/secret.txt
            symlink_escape = att_dir / "symlink_escape.txt"
            try:
                os.symlink(secret_note, symlink_escape)
            except OSError:
                pass

            ctx = type("MockCtx", (), {"workspace_root": ws})()
            yield ws, ctx

    @pytest.mark.asyncio
    async def test_safe_reading_legitimate_attachment(self, isolated_sandbox):
        """Legitimate file inside attachments/ is read successfully."""
        ws, ctx = isolated_sandbox
        res = await execute_attach_read({"path": "valid_record.txt"}, ctx)
        assert res.success is True
        assert "CLINICAL VISIT SUMMARY" in res.output["content"]

    @pytest.mark.asyncio
    async def test_rejection_of_relative_path_traversal(self, isolated_sandbox):
        """Rejects relative traversal ../notes/secret.txt and ../../etc/passwd."""
        ws, ctx = isolated_sandbox

        r1 = await execute_attach_read({"path": "../notes/secret.txt"}, ctx)
        assert r1.success is False
        assert "escapes allowed directory" in r1.error or "forbidden" in r1.error

        r2 = await execute_attach_read({"path": "../../etc/passwd"}, ctx)
        assert r2.success is False
        assert "escapes allowed directory" in r2.error or "forbidden" in r2.error

    @pytest.mark.asyncio
    async def test_rejection_of_absolute_path(self, isolated_sandbox):
        """Rejects root absolute paths /etc/hosts and /etc/passwd."""
        ws, ctx = isolated_sandbox
        res = await execute_attach_read({"path": "/etc/hosts"}, ctx)
        assert res.success is False
        assert "escapes allowed directory" in res.error or "forbidden" in res.error

    @pytest.mark.asyncio
    async def test_rejection_of_null_byte_injection(self, isolated_sandbox):
        """Rejects null-byte poisoning in path."""
        ws, ctx = isolated_sandbox
        res = await execute_attach_read({"path": "valid_record.txt\x00.pdf"}, ctx)
        assert res.success is False
        assert "Null byte detected" in res.error

    @pytest.mark.asyncio
    async def test_rejection_of_uri_schemes(self, isolated_sandbox):
        """Rejects URI schemes like file:///etc/passwd."""
        ws, ctx = isolated_sandbox
        res = await execute_attach_read({"path": "file:///etc/passwd"}, ctx)
        assert res.success is False
        assert "URI schemes are not permitted" in res.error

    @pytest.mark.asyncio
    async def test_rejection_of_symlink_escaping_sandbox(self, isolated_sandbox):
        """Rejects symlinks pointing outside attachments/ directory."""
        ws, ctx = isolated_sandbox
        res = await execute_attach_read({"path": "symlink_escape.txt"}, ctx)
        assert res.success is False
        assert "escapes sandbox" in res.error or "escapes allowed directory" in res.error


# ============================================================================
# 5. Extraction Subgraph Execution & State Population
# ============================================================================

class TestExtractionSubgraphExecution:
    """Verifies extraction subgraph assembly, channel updates, and supervisor integration."""

    def test_subgraph_compilation(self):
        """Tests that create_extraction_subgraph and build_extraction_subgraph compile cleanly."""
        sg = create_extraction_subgraph(compile=False)
        assert isinstance(sg, StateGraph)
        assert "ingestion_node" in sg.nodes
        assert "extraction_node" in sg.nodes

        compiled = build_extraction_subgraph()
        assert isinstance(compiled, CompiledStateGraph)

    @pytest.mark.asyncio
    async def test_subgraph_execution_populates_document_dossiers(self):
        """Subgraph ainvoke extracts dossier and populates document_dossiers list."""
        app = build_extraction_subgraph()
        state = create_initial_state(
            thread_id="t-ext-1",
            user_id="u-1",
            messages=[HumanMessage(content="Extract my insurance benefits")],
        )
        state["document_text"] = (
            "SCHEDULE OF BENEFITS\n"
            "Annual Deductible: $1,500\n"
            "Primary Care Copay: $25\n"
            "Coinsurance: 20%\n"
            "Out-of-Pocket Maximum: $6,000\n"
        )
        state["dossier_type"] = "insurance"

        result = await app.ainvoke(state)
        assert "document_dossiers" in result
        assert len(result["document_dossiers"]) == 1
        dossier_payload = result["document_dossiers"][0]
        assert dossier_payload["dossier_type"] in ("insurance", "insurance_benefits")
        assert dossier_payload["data"]["deductible"] == "$1,500"
        assert dossier_payload["grounding"]["is_grounded"] is True

    @pytest.mark.asyncio
    async def test_subgraph_auto_infers_dossier_type_from_query(self):
        """Auto-selects clinical dossier when prompt mentions visit/doctor."""
        app = build_extraction_subgraph()
        state = create_initial_state(
            thread_id="t-ext-2",
            user_id="u-1",
            messages=[HumanMessage(content="Extract details from my recent doctor visit summary")],
        )
        state["document_text"] = (
            "CLINICAL VISIT SUMMARY\n"
            "Reason for visit: Persistent cough\n"
            "Physician Instructions: Rest, hydration\n"
            "Follow-up: 4 weeks\n"
        )

        result = await app.ainvoke(state)
        assert len(result["document_dossiers"]) == 1
        assert result["document_dossiers"][0]["dossier_type"] in ("clinical", "clinical_visit")
        assert result["document_dossiers"][0]["data"]["follow_up_timeline"] == "4 weeks"

    @pytest.mark.asyncio
    async def test_supervisor_subgraph_wires_document_extractor_and_populates_dossiers(self):
        """Specialist supervisor dispatches to document-extractor and preserves document_dossiers."""
        fake = FakeListChatModel(responses=[""])
        app = build_supervisor_subgraph(model=fake)

        state = create_initial_state(
            thread_id="t-sup-doc",
            user_id="u-1",
            messages=[HumanMessage(content="Extract structured data from this document")],
        )
        state["document_text"] = (
            "SCHEDULE OF BENEFITS\n"
            "Annual Deductible: $1,500\n"
            "Copay: $25\n"
            "Coinsurance: 20%\n"
        )
        state["routed_subgraph"] = SPECIALIST_DOCUMENT_EXTRACTOR

        result = await app.ainvoke(state)
        assert result["current_agent"] == SPECIALIST_DOCUMENT_EXTRACTOR
        assert len(result.get("document_dossiers", [])) == 1
        assert result["document_dossiers"][0]["data"]["deductible"] == "$1,500"


# ============================================================================
# 6. Concurrency & Stress Testing
# ============================================================================

class TestExtractionConcurrencyAndStress:
    """Stress tests high concurrency and thread safety."""

    @pytest.mark.asyncio
    async def test_50_concurrent_grounding_validations(self):
        """Executes 50 concurrent grounding checks without state contamination."""
        cases = [
            ("$1,500", "Deductible is $1,500", True),
            ("1050", "Deductible is $1,500", False),
            ("20.5%", "Coinsurance is 20.5 percent", True),
            ("$9,999", "Deductible is $1,500", False),
            ("$0", "Copay is $0", True),
        ]

        async def worker(idx: int) -> bool:
            val, text, exp = cases[idx % len(cases)]
            res = GroundingValidator.validate_numerical_value(val, text)
            return res.is_grounded == exp

        tasks = [worker(i) for i in range(50)]
        results = await asyncio.gather(*tasks)
        assert all(results)

    @pytest.mark.asyncio
    async def test_50_concurrent_tool_invocations(self):
        """Executes 50 concurrent tool ainvokes across various text inputs."""
        texts = [
            "Deductible is $1,500. Copay: $25. Coinsurance: 20%.",
            "Reason for visit: Cough. Follow-up: 2 weeks. Physician instructions: Rest.",
            "Summary: Administrative admission. Length of stay: 24 hours.",
        ]
        types = ["insurance", "clinical", "generic"]

        async def run_tool(idx: int) -> bool:
            t = texts[idx % len(texts)]
            dt = types[idx % len(types)]
            res = await extract_document_dossier.ainvoke({
                "document_text": t,
                "dossier_type": dt,
            })
            return res["status"] == "success" and res["is_grounded"] is True

        tasks = [run_tool(i) for i in range(50)]
        results = await asyncio.gather(*tasks)
        assert all(results)

    def test_multithreaded_grounding_stress(self):
        """Stress-tests grounding validation across 10 OS threads via ThreadPoolExecutor."""
        def worker(thread_idx: int) -> bool:
            r1 = GroundingValidator.validate_numerical_value("$1,000,000", "Limit is 1000000 dollars.")
            r2 = GroundingValidator.validate_numerical_value("1050", "Deductible is $1,500.")
            return r1.is_grounded is True and r2.is_grounded is False

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(20)]
            results = [f.result(timeout=5) for f in futures]

        assert all(results)


# ============================================================================
# 7. Grounding Defects Remediation Tests
# ============================================================================

class TestGroundingDefectsRemediation:
    """Verifies that defects in grounding validation have been cleanly remediated."""

    def test_attachments_dir_type_in_fallback(self):
        """Non-existent files cleanly raise FileNotFoundError (not TypeError)."""
        assert isinstance(ATTACHMENTS_DIR, str), "ATTACHMENTS_DIR is a string constant"

        # Calling extract_document_dossier with a non-existent file raises FileNotFoundError
        with pytest.raises(FileNotFoundError):
            extract_document_dossier(file_path="non_existent_file.txt")

    def test_path_traversal_blocked_in_tool(self):
        """Path traversal attempts like /etc/hosts or escaping paths raise PermissionError / SandboxSecurityError,
        strictly preventing arbitrary file reads outside the sandbox.
        """
        ctx = type("MockCtx", (), {"workspace_root": Path("/tmp")})()
        res = asyncio.run(execute_attach_read({"path": "../notes/secret.txt"}, ctx))
        assert res.success is False

        # Path traversal attempts must be strictly blocked and raise PermissionError / SandboxSecurityError
        with pytest.raises((PermissionError, ValueError)):
            extract_document_dossier(file_path="../notes/secret.txt")

        with pytest.raises((PermissionError, ValueError)):
            extract_document_dossier(file_path="/etc/hosts")

    def test_args_schema_includes_workspace_root(self):
        """ExtractDocumentDossierInput args_schema includes workspace_root so callers
        can specify custom workspace root paths.
        """
        from carefold.workflows.subgraphs.extraction.tool import ExtractDocumentDossierInput
        assert "workspace_root" in ExtractDocumentDossierInput.model_fields

    def test_defect_4_greedy_address_regex_eats_compound_sentences(self):
        """DEFECT 4 REMEDIATION:
        Non-address compound clauses and medical contexts are preserved without
        over-eager address masking.
        """
        text = "Lives at 123 Elm Street, hospital stay was brief"
        sanitized = sanitize_pii(text)
        assert "hospital stay was brief" in sanitized
        assert sanitized.strip() == "Lives at [ADDRESS], hospital stay was brief"
