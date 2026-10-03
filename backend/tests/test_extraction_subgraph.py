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

"""Document Extraction Subgraph Unit and Integration Test Suite.

Tests:
1. Dossier models (InsuranceBenefitsDossier, ClinicalVisitDossier, GenericDocumentDossier, BaseDossier)
2. PII Sanitizer (sanitize_pii, mask_pii, PIISanitizer, adjacent tokens, clinical preservation)
3. GroundingValidator (numerical validation, currency, percentages, units, transpositions, hallucinations)
4. extract_document_dossier tool (dual invocation, args_schema, state population)
5. Extraction subgraph (create_extraction_subgraph, build_extraction_subgraph, end-to-end)
6. Supervisor integration with document-extractor specialist
7. Compatibility shim in carefold.tools.attachments
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest
from pydantic import ValidationError

from carefold.tools.attachments import (
    ALLOWED_ATTACHMENT_EXTENSIONS,
    ALLOWED_TEXT_EXTS,
    MAX_FILE_SIZE,
    attach_read_tool,
    execute_attach_read,
    extract_text_from_pdf_bytes,
)
from carefold.workflows.state import AgentState, create_initial_state
from carefold.workflows.subgraphs.extraction import (
    BaseDossier,
    ClinicalVisitDossier,
    DOSSIER_REGISTRY,
    DocumentDossier,
    ExtractDocumentDossierInput,
    ExtractDocumentDossierTool,
    GenericDocumentDossier,
    GroundingValidationResult,
    GroundingValidator,
    InsuranceBenefitsDossier,
    PIISanitizer,
    SanitizationResult,
    build_extraction_subgraph,
    create_extraction_node,
    create_extraction_subgraph,
    create_ingestion_node,
    extract_document_dossier,
    extract_numeric_tokens,
    get_dossier_cls,
    mask_pii,
    sanitize_pii,
    sanitize_pii_with_metadata,
)
from carefold.workflows.subgraphs.supervisor import (
    SPECIALIST_DOCUMENT_EXTRACTOR,
    build_supervisor_subgraph,
    create_supervisor_subgraph,
)
from tests.fixtures.fake_model import FakeListChatModel
from langchain_core.messages import HumanMessage


# ============================================================================
# 1. Dossier Models Tests
# ============================================================================

class TestExtractionDossiers:
    """Tests for structured extraction dossiers."""

    def test_insurance_benefits_dossier_instantiation_and_serialization(self):
        dossier = InsuranceBenefitsDossier(
            deductible="$1,500",
            copays={"primary_care": "$25", "specialist": "$50"},
            coinsurance="20%",
            out_of_pocket_maximum="$6,000",
            in_out_network_rules="20% in-network, 40% out-of-network",
            prior_authorization_flags=["MRI", "physical_therapy"],
        )
        assert dossier.deductible == "$1,500"
        assert dossier.copays["primary_care"] == "$25"
        assert dossier.coinsurance == "20%"
        assert dossier.out_of_pocket_maximum == "$6,000"
        assert "MRI" in dossier.prior_authorization_flags
        assert dossier.dossier_type == "insurance_benefits"

        # Serialization methods
        d_dict = dossier.to_dict(include_type=True)
        assert d_dict["dossier_type"] == "insurance_benefits"
        assert d_dict["deductible"] == "$1,500"

        d_json = dossier.to_json()
        assert '"deductible":"$1,500"' in d_json or '"deductible": "$1,500"' in d_json

    def test_clinical_visit_dossier_validation_and_methods(self):
        dossier = ClinicalVisitDossier(
            reason_for_visit="Annual wellness physical",
            physician_instructions=["Drink water", "Exercise 30 mins"],
            follow_up_timeline="4 weeks",
            questions_to_ask=["Discuss cholesterol"],
        )
        assert dossier.reason_for_visit == "Annual wellness physical"
        assert len(dossier.physician_instructions) == 2
        assert dossier.dossier_type == "clinical_visit"

        nums = dossier.extract_numerical_strings()
        assert any("4 weeks" in n or "4" in n for n in nums)

    def test_generic_document_dossier(self):
        dossier = GenericDocumentDossier(
            summary="Discharge instructions summary.",
            key_numerical_values={"stay": "24 hours", "bp": "120/80"},
            sections=["Medications", "Follow-up"],
        )
        assert dossier.summary == "Discharge instructions summary."
        assert dossier.dossier_type == "generic_document"
        nums = dossier.extract_numerical_strings()
        assert len(nums) >= 2

    def test_dossier_type_rejection(self):
        with pytest.raises(ValidationError):
            ClinicalVisitDossier(
                reason_for_visit=12345,  # int instead of str
                physician_instructions="Not a list",  # str instead of list
            )

    def test_dossier_registry_lookup(self):
        assert get_dossier_cls("insurance") is InsuranceBenefitsDossier
        assert get_dossier_cls("insurance_benefits") is InsuranceBenefitsDossier
        assert get_dossier_cls("clinical") is ClinicalVisitDossier
        assert get_dossier_cls("clinical_visit") is ClinicalVisitDossier
        assert get_dossier_cls("generic") is GenericDocumentDossier
        assert get_dossier_cls("unknown_type") is GenericDocumentDossier


# ============================================================================
# 2. PII Sanitizer Tests
# ============================================================================

class TestPiiSanitizerComprehensive:
    """Comprehensive tests for PII masking boundaries and clinical preservation."""

    def test_ssn_masking_hyphenated_and_unhyphenated(self):
        assert sanitize_pii("SSN: 123-45-6789.") == "SSN: [SSN]."
        assert sanitize_pii("Number is 123456789") == "Number is [SSN]"
        assert sanitize_pii("Patient SSN 123-45-6789", mask_type="redacted") == "Patient SSN [REDACTED]"

    def test_adjacent_tokens_boundary_safety(self):
        raw = "SSN: 123-45-6789MRN: MRN998877"
        sanitized = sanitize_pii(raw)
        assert "123-45-6789" not in sanitized
        assert "MRN998877" not in sanitized
        assert "[SSN]" in sanitized
        assert "[MRN]" in sanitized

    def test_phone_and_address_masking(self):
        raw = "Phone +1-555-432-1098, address: 123 Elm Street, Springfield, IL 62701."
        sanitized = sanitize_pii(raw)
        assert "+1-555-432-1098" not in sanitized
        assert "123 Elm Street" not in sanitized

    def test_clinical_terms_strictly_preserved(self):
        clinical_text = (
            "Blood pressure is 120/80 mmHg. Total length of stay: 24 hours. "
            "Administer Metformin 500 mg twice daily. Deductible is $1,500 with $25 copay."
        )
        sanitized = sanitize_pii(clinical_text)
        assert "120/80 mmHg" in sanitized
        assert "stay: 24 hours" in sanitized
        assert "500 mg" in sanitized
        assert "$1,500" in sanitized
        assert "$25" in sanitized

    def test_pii_sanitizer_metadata(self):
        text = "Contact 555-234-5678 or doc@example.com for MRN44921."
        res = sanitize_pii_with_metadata(text)
        assert isinstance(res, SanitizationResult)
        assert res.has_pii is True
        assert "phone" in res.redacted_counts
        assert "email" in res.redacted_counts
        assert "mrn" in res.redacted_counts

    def test_pii_sanitizer_class_interface(self):
        assert PIISanitizer.mask("Call (555) 234-5678") == "Call [PHONE]"
        assert PIISanitizer.sanitize("SSN: 123-45-6789", mask_type="redacted") == "SSN: [REDACTED]"


# ============================================================================
# 3. Grounding Validator Tests
# ============================================================================

class TestGroundingValidatorComprehensive:
    """Comprehensive tests for GroundingValidator."""

    def test_exact_and_formatted_numbers(self):
        res1 = GroundingValidator.validate_numerical_value("1500", "Deductible is $1500.")
        assert res1.is_grounded is True
        assert len(res1.matched_spans) > 0

        res2 = GroundingValidator.validate_numerical_value("$1,500", "Annual deductible is 1500 dollars")
        assert res2.is_grounded is True

    def test_percentages_and_units(self):
        res1 = GroundingValidator.validate_numerical_value("20%", "Coinsurance is 20 percent")
        assert res1.is_grounded is True

        res2 = GroundingValidator.validate_numerical_value("20.5%", "Special coinsurance is 20.5 percent.")
        assert res2.is_grounded is True

        res3 = GroundingValidator.validate_numerical_value("4 weeks", "Return in 4 weeks for follow-up.")
        assert res3.is_grounded is True

    def test_transposed_digits_and_hallucinations_rejected(self):
        res1 = GroundingValidator.validate_numerical_value("1050", "Out of pocket max is $1,500.")
        assert res1.is_grounded is False
        assert "1050" in res1.unmatched_values

        res2 = GroundingValidator.validate_numerical_value("$9,999", "Deductible is $1,500 and copay is $25")
        assert res2.is_grounded is False
        assert "$9,999" in res2.unmatched_values

    def test_cross_domain_unit_separation(self):
        # 20% coinsurance must not match $20 copay
        res = GroundingValidator.validate_numerical_value("20%", "Copay is $20.")
        assert res.is_grounded is False

    def test_full_dossier_grounding_validation(self):
        dossier = InsuranceBenefitsDossier(
            deductible="$1,500",
            copays={"primary_care": "$25", "specialist": "$50"},
            coinsurance="20%",
            out_of_pocket_maximum="$6,000",
            in_out_network_rules="20% in-network, 40% out-of-network",
            prior_authorization_flags=["MRI"],
        )
        raw_source = (
            "BENEFITS SUMMARY: Deductible is $1,500. Copays: primary care $25, specialist $50. "
            "Coinsurance: 20% in-network, 40% out-of-network. OOP max: $6,000."
        )
        res = GroundingValidator.validate(dossier, raw_source)
        assert res.is_grounded is True
        assert len(res.unmatched_values) == 0

        # Un-grounded figure in dossier
        hallucinated_dossier = InsuranceBenefitsDossier(
            deductible="$9,999",
            copays={"primary_care": "$25"},
        )
        bad_res = GroundingValidator.validate(hallucinated_dossier, raw_source)
        assert bad_res.is_grounded is False
        assert any("9,999" in u for u in bad_res.unmatched_values)


# ============================================================================
# 4. Extraction Tool Tests
# ============================================================================

class TestExtractDocumentDossierTool:
    """Tests for extract_document_dossier dual invocation tool."""

    def test_tool_contract_and_schema(self):
        assert isinstance(extract_document_dossier, ExtractDocumentDossierTool)
        assert extract_document_dossier.name == "extract_document_dossier"
        assert extract_document_dossier.args_schema == ExtractDocumentDossierInput

    def test_direct_invocation_with_document_text(self):
        raw_text = (
            "SCHEDULE OF BENEFITS\n"
            "Deductible: $1,500\n"
            "Primary Care Copay: $25\n"
            "Specialist Copay: $50\n"
            "Coinsurance: 20%\n"
            "Out-of-Pocket Max: $6,000\n"
        )
        state: dict = {}
        res = extract_document_dossier(
            document_text=raw_text,
            dossier_type="insurance",
            state=state,
        )
        assert res["status"] == "success"
        assert res["dossier_type"] == "insurance_benefits"
        assert res["is_grounded"] is True
        assert "document_dossiers" in state
        assert len(state["document_dossiers"]) == 1
        assert state["document_dossiers"][0]["data"]["deductible"] == "$1,500"

    @pytest.mark.asyncio
    async def test_async_invoke_tool(self):
        raw_text = (
            "CLINICAL VISIT NOTE\n"
            "Patient SSN: 123-45-6789, MRN: MRN44921\n"
            "Reason for visit: Persistent acute dry cough.\n"
            "Physician Instructions: Drink warm tea, rest.\n"
            "Follow-up: Return in 4 weeks.\n"
        )
        state: dict = {}
        res = await extract_document_dossier.ainvoke({
            "document_text": raw_text,
            "dossier_type": "clinical",
            "state": state,
        })
        assert res["status"] == "success"
        assert res["dossier_type"] == "clinical_visit"
        assert res["is_grounded"] is True
        assert len(state["document_dossiers"]) == 1


# ============================================================================
# 5. Extraction Subgraph Tests
# ============================================================================

class TestExtractionSubgraph:
    """Tests for create_extraction_subgraph and build_extraction_subgraph."""

    @pytest.mark.asyncio
    async def test_compiled_subgraph_execution(self):
        graph = build_extraction_subgraph()
        raw_text = (
            "SCHEDULE OF BENEFITS\n"
            "Deductible: $1,500\n"
            "Coinsurance: 20%\n"
        )
        state = create_initial_state(
            thread_id="t-m4-subgraph",
            user_id="u-test",
            messages=[HumanMessage(content="Extract insurance schedule")],
        )
        state["document_text"] = raw_text
        state["dossier_type"] = "insurance"

        result = await graph.ainvoke(state)
        assert "document_dossiers" in result
        assert len(result["document_dossiers"]) >= 1
        assert "Document extraction completed" in result["output"]

    @pytest.mark.asyncio
    async def test_supervisor_wiring_with_extraction(self):
        fake_model = FakeListChatModel(responses=["Unused"])
        app = build_supervisor_subgraph(model=fake_model)

        raw_text = (
            "CLINICAL VISIT NOTE\n"
            "Patient: Jane Doe, SSN: 123-45-6789\n"
            "Reason for visit: Follow-up visit.\n"
            "Follow-up: Return in 4 weeks.\n"
        )
        state = create_initial_state(
            thread_id="t-m4-sup",
            user_id="u-test",
            messages=[HumanMessage(content="Extract document details from attachment")],
        )
        state["document_text"] = raw_text
        state["dossier_type"] = "clinical"

        result = await app.ainvoke(state)
        assert result["current_agent"] == SPECIALIST_DOCUMENT_EXTRACTOR
        assert len(result["document_dossiers"]) >= 1
        assert "Document extraction completed" in result["output"]


# ============================================================================
# 6. Attachment Compatibility Shim Tests
# ============================================================================

class TestAttachmentShim:
    """Tests that carefold.tools.attachments compatibility shim works properly."""

    def test_shim_exports(self):
        assert callable(execute_attach_read)
        assert callable(attach_read_tool)
        assert callable(extract_text_from_pdf_bytes)
        assert MAX_FILE_SIZE == 10 * 1024 * 1024
        assert ".pdf" in ALLOWED_ATTACHMENT_EXTENSIONS
        assert ".txt" in ALLOWED_TEXT_EXTS


# ============================================================================
# 7. File Path Ingestion, Sandboxing, and Dynamic Extraction Tests
# ============================================================================

class TestExtractionToolFileResolutionAndSandboxing:
    """Verifies file_path ingestion, sandbox traversal defenses, and dynamic parsing."""

    def test_missing_file_raises_filenotfounderror(self):
        with pytest.raises(FileNotFoundError):
            extract_document_dossier.invoke({"file_path": "nonexistent_visit.txt"})

    def test_path_traversal_absolute_blocked(self):
        with pytest.raises((PermissionError, ValueError)):
            extract_document_dossier.invoke({"file_path": "/etc/hosts"})

    def test_path_traversal_relative_blocked(self):
        with pytest.raises((PermissionError, ValueError)):
            extract_document_dossier.invoke({"file_path": "../../etc/passwd"})

    def test_valid_sandboxed_file_read(self, tmp_path):
        # Create sandboxed attachment directory
        att_dir = tmp_path / "attachments"
        att_dir.mkdir(parents=True)
        note_file = att_dir / "encounter_note.txt"
        note_file.write_text(
            "Reason for visit: Routine checkup.\nFollow-up: 3 weeks.\nPhysician instructions: Walk daily.",
            encoding="utf-8",
        )

        res = extract_document_dossier.invoke({
            "file_path": "encounter_note.txt",
            "dossier_type": "clinical",
            "workspace_root": str(tmp_path),
        })
        assert res["status"] == "success"
        assert res["dossier"]["reason_for_visit"] == "Routine checkup"
        assert res["is_grounded"] is True

    @pytest.mark.asyncio
    async def test_dynamic_filename_extraction_in_subgraph(self, tmp_path):
        att_dir = tmp_path / "attachments"
        att_dir.mkdir(parents=True)
        custom_file = att_dir / "custom_discharge_summary.txt"
        custom_file.write_text(
            "Reason for visit: Follow-up after surgery.\nFollow-up: 2 weeks.\nPhysician instructions: Rest.",
            encoding="utf-8",
        )

        node = create_ingestion_node()
        state = create_initial_state(
            thread_id="t-dyn-file",
            user_id="u-test",
            messages=[HumanMessage(content="Please review attachment custom_discharge_summary.txt for my visit")],
        )
        res = await node(state)
        assert res["file_path"] == "custom_discharge_summary.txt"

    @pytest.mark.asyncio
    async def test_explicit_dossier_type_not_overwritten_by_prompt_keywords(self):
        node = create_extraction_node()
        state = create_initial_state(
            thread_id="t-dossier-preserve",
            user_id="u-test",
            messages=[HumanMessage(content="Here are my insurance benefits and copay details")],
        )
        state["document_text"] = "Summary: Custom general notes.\nLength of stay: 1 day."
        state["dossier_type"] = "generic"

        res = await node(state)
        assert res["document_dossiers"][0]["dossier_type"] in ("generic", "generic_document")
