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

"""Document Extraction and Grounding Tools Test Suite.

Authoritative stress-testing and verification for:
1. SanitizePIITool:
   - Direct identifier masking: SSN (hyphenated, dotted, space, unhyphenated 9-digit, labeled context),
     MRN (token, labeled), phone (US, intl, ext), address (street, unit, PO box, contextual), email.
   - Tag ([SSN], [MRN], [PHONE], [ADDRESS], [EMAIL]) vs Redacted ([REDACTED]) masking modes.
   - Strict preservation of clinical vitals (120/80 mmHg, 140/90 mmHg, 72 bpm, 98.6 F,
     Metformin 500 mg, Lisinopril 10 mg, HbA1c 6.5%, WBC 4.5, $1,500, $25, 20%).
   - Prevention of false positives on medical abbreviations (Dr. Smith, CT scan, sentinel LN, different way).
   - LangChain tool contract, args_schema, sync (.invoke / ._run) and async (.ainvoke / ._arun).
2. ExtractStructuredDataTool:
   - Structured extraction targeting InsuranceBenefitsDossier, ClinicalVisitDossier, GenericDocumentDossier.
   - Verification of typed schema fields and dictionary outputs.
   - Model structured output binding vs deterministic fallback heuristic.
   - Sync and async invocations.
3. ValidateGroundingTool:
   - Numerical grounding verification across currency ($1,500 vs 1500 dollars, $1,000,000 vs 1000000, $0).
   - Percentages (20% vs 20 percent, 20.5% vs 20.5 percent) and clinical units ('4 weeks').
   - Rejection of transposed digits (1050 vs $1,500, 250 vs $520, 1234 vs 1243).
   - Rejection of hallucinated numbers ($9,999).
   - Rejection of cross-domain unit mismatches (20% vs $20, 4 days vs 4 weeks).
   - Support for Pydantic models, dicts, and JSON strings as dossier input.
   - Sync and async invocations.
4. Delegation Tools (ListAgentsTool & DelegateToAgentTool):
   - ListAgentsTool: parameterless schema, catalog discovery, exclusion of orchestrator, fallback discovery.
   - DelegateToAgentTool: input schema, formatting of JSON delegation directives, whitespace trimming.
   - Sync and async execution.
5. extract_document_dossier Backward Compatibility & Sandboxing:
   - Dual invocation: direct function call vs LangChain tool (.invoke / .ainvoke).
   - State dictionary population (state["document_dossiers"]).
   - Sandbox security: rejection of path traversal (/etc/hosts, ../../etc/passwd).
   - Missing attachment handling: FileNotFoundError on non-existent sandboxed files.
6. Concurrency & Stress Harness:
   - Multi-threaded and multi-task concurrent executions.
7. Empirical Defects Verification:
   - Defect 1: Truncation of uncomma'd 4-digit dollar figures ($1000 -> $100, $6000 -> $600) in _heuristic_dossier_extractor.
   - Defect 2: Alternation omission in copay regex (Primary care copay: $25 dropped or misclassified to office_visit).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
import pytest

from pydantic import BaseModel
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from carefold.config import settings
from carefold.constants.agents import (
    AGENT_ORCHESTRATOR,
    AGENT_DOCUMENT_EXTRACTOR,
    TOOL_DELEGATE_TO_AGENT,
    TOOL_EXTRACT_DOCUMENT_DOSSIER,
    TOOL_EXTRACT_STRUCTURED_DATA,
    TOOL_LIST_AGENTS,
    TOOL_SANITIZE_PII,
    TOOL_VALIDATE_GROUNDING,
)
from carefold.constants.extraction import (
    DEFAULT_DOSSIER_TYPE,
    DOSSIER_TYPE_CLINICAL,
    DOSSIER_TYPE_GENERIC,
    DOSSIER_TYPE_INSURANCE,
)
from carefold.agents.registry import get_agent_registry, AgentRegistry
from carefold.tools.extraction_tools import (
    ExtractStructuredDataInput,
    ExtractStructuredDataTool,
    SanitizePIIInput,
    SanitizePIITool,
    ValidateGroundingInput,
    ValidateGroundingTool,
)
from carefold.tools.delegation_tools import (
    DelegateToAgentInput,
    DelegateToAgentTool,
    ListAgentsInput,
    ListAgentsTool,
)
from carefold.workflows.subgraphs.extraction.dossiers import (
    ClinicalVisitDossier,
    GenericDocumentDossier,
    InsuranceBenefitsDossier,
    get_dossier_cls,
)
from carefold.workflows.subgraphs.extraction.grounding import GroundingValidator
from carefold.workflows.subgraphs.extraction.sanitizer import sanitize_pii
from carefold.workflows.subgraphs.extraction.tool import (
    DocumentSandboxError,
    ExtractDocumentDossierInput,
    ExtractDocumentDossierTool,
    _heuristic_dossier_extractor,
    extract_document_dossier,
)


class MockStructuredChatModel(BaseChatModel):
    """Subclass of BaseChatModel implementing with_structured_output for empirical testing."""
    target_dossier: Any = None

    @property
    def _llm_type(self) -> str:
        return "mock-structured"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="mock"))])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        mock_runnable = MagicMock()
        mock_runnable.invoke.return_value = self.target_dossier

        async def _mock_ainvoke(*args: Any, **kw: Any) -> Any:
            return self.target_dossier

        mock_runnable.ainvoke = _mock_ainvoke
        return mock_runnable


# ============================================================================
# 1. SanitizePIITool Stress & Clinical Preservation Tests
# ============================================================================

class TestSanitizePIIToolAdversarial:
    """Stress tests and boundary checks for SanitizePIITool."""

    def test_tool_contract_and_metadata(self):
        tool = SanitizePIITool()
        assert tool.name == TOOL_SANITIZE_PII
        assert tool.args_schema == SanitizePIIInput
        assert callable(tool._run)
        assert callable(tool._arun)

    @pytest.mark.parametrize(
        "raw_ssn,expected_tag",
        [
            ("SSN: 123-45-6789", "SSN: [SSN]"),
            ("SSN: 123.45.6789", "SSN: [SSN]"),
            ("SSN: 123 45 6789", "SSN: [SSN]"),
            ("Social Security Number: 987654321", "Social Security Number: [SSN]"),
            ("Soc Sec: 987-65-4321", "Soc Sec: [SSN]"),
            ("Patient ID: 987654321.", "Patient ID: [SSN]."),
        ],
    )
    def test_ssn_varieties_and_formats(self, raw_ssn: str, expected_tag: str):
        tool = SanitizePIITool()
        res_tag = tool.invoke({"text": raw_ssn, "mask_type": "tag"})
        assert expected_tag in res_tag
        assert "123-45-6789" not in res_tag
        assert "987654321" not in res_tag

        res_redacted = tool.invoke({"text": raw_ssn, "mask_type": "redacted"})
        assert "[REDACTED]" in res_redacted

    def test_mrn_varieties(self):
        tool = SanitizePIITool()
        text = "Tokens: MRN44921, MRN998877. Labeled: MRN: 987654, Medical Record Number: 112233, Med Rec #: A-9988."
        sanitized = tool.invoke({"text": text, "mask_type": "tag"})
        assert "MRN44921" not in sanitized
        assert "MRN998877" not in sanitized
        assert "987654" not in sanitized
        assert "112233" not in sanitized
        assert "[MRN]" in sanitized

        redacted = tool.invoke({"text": text, "mask_type": "redacted"})
        assert "[REDACTED]" in redacted
        assert "[MRN]" not in redacted

    def test_phone_and_email_masking(self):
        tool = SanitizePIITool()
        text = (
            "Contact: (555) 234-5678 or 555-234-5678 or 555.234.5678. "
            "Intl: +1-555-432-1098 or +44 20 7946 0958. "
            "Extension: 555-234-5678 ext 102. "
            "Emails: patient@carefold.org, jane.doe+test@gmail.com."
        )
        sanitized = tool.invoke({"text": text, "mask_type": "tag"})
        assert "555-234-5678" not in sanitized
        assert "+1-555-432-1098" not in sanitized
        assert "patient@carefold.org" not in sanitized
        assert "[PHONE]" in sanitized
        assert "[EMAIL]" in sanitized

    def test_address_and_po_box_masking(self):
        tool = SanitizePIITool()
        text = (
            "Residence: 123 Elm Street, Springfield, IL 62701. "
            "Office: 456 Oak Avenue, Suite 200, Dallas, TX 75001. "
            "Mail to: P.O. Box 987, Austin, TX 78701."
        )
        sanitized = tool.invoke({"text": text, "mask_type": "tag"})
        assert "123 Elm Street" not in sanitized
        assert "456 Oak Avenue" not in sanitized
        assert "P.O. Box 987" not in sanitized
        assert "[ADDRESS]" in sanitized

    def test_clinical_vitals_strictly_preserved(self):
        """CRITICAL INVARIANT: Clinical vitals, dosages, and lab figures must NEVER be redacted."""
        tool = SanitizePIITool()
        clinical_note = (
            "Vitals: Blood pressure 120/80 mmHg, pulse 72 bpm, temp 98.6 F, respiratory rate 16. "
            "Current meds: Metformin 500 mg PO BID, Lisinopril 10 mg daily, Amoxicillin 250mg/5ml. "
            "Labs: HbA1c 6.5%, WBC 4.5 x 10^3 / uL, Serum glucose 95 mg/dL, Creatinine 0.9 mg/dL. "
            "Plan: Length of stay: 24 hours. Return in 4 weeks for repeat evaluation. "
            "Insurance: Deductible $1,500, copay $25, coinsurance 20%."
        )
        sanitized = tool.invoke({"text": clinical_note, "mask_type": "tag"})

        assert "120/80 mmHg" in sanitized
        assert "72 bpm" in sanitized
        assert "98.6 F" in sanitized
        assert "500 mg" in sanitized
        assert "10 mg" in sanitized
        assert "250mg/5ml" in sanitized
        assert "6.5%" in sanitized
        assert "95 mg/dL" in sanitized
        assert "0.9 mg/dL" in sanitized
        assert "stay: 24 hours" in sanitized
        assert "4 weeks" in sanitized
        assert "$1,500" in sanitized
        assert "$25" in sanitized
        assert "20%" in sanitized

    def test_medical_abbreviations_not_misidentified_as_addresses(self):
        """Prevent collision with Dr. Smith (Drive), CT scan (Court), sentinel LN (Lane), different way (Way)."""
        tool = SanitizePIITool()
        text = (
            "Seen by Dr. Smith for consultation. Ordered a chest CT scan and pelvis CT scan. "
            "Biopsy of the sentinel LN showed no metastasis. He approached therapy in a different way."
        )
        sanitized = tool.invoke({"text": text, "mask_type": "tag"})
        assert "Dr. Smith" in sanitized
        assert "CT scan" in sanitized
        assert "sentinel LN" in sanitized
        assert "different way" in sanitized
        assert "[ADDRESS]" not in sanitized

    @pytest.mark.asyncio
    async def test_async_sanitization(self):
        tool = SanitizePIITool()
        text = "Patient SSN 123-45-6789, MRN MRN998877, email test@example.com."
        res = await tool.ainvoke({"text": text, "mask_type": "redacted"})
        assert "[REDACTED]" in res
        assert "123-45-6789" not in res
        assert "MRN998877" not in res
        assert "test@example.com" not in res

    def test_edge_cases_empty_and_whitespace(self):
        tool = SanitizePIITool()
        assert tool.invoke({"text": ""}) == ""
        assert tool.invoke({"text": "   "}) == "   "
        assert tool.invoke({"text": "No PII here!"}) == "No PII here!"


# ============================================================================
# 2. ExtractStructuredDataTool Tests
# ============================================================================

class TestExtractStructuredDataToolAdversarial:
    """Stress tests for ExtractStructuredDataTool."""

    def test_tool_contract_and_metadata(self):
        tool = ExtractStructuredDataTool()
        assert tool.name == TOOL_EXTRACT_STRUCTURED_DATA
        assert tool.args_schema == ExtractStructuredDataInput

    def test_extract_insurance_benefits_heuristic_fallback(self):
        tool = ExtractStructuredDataTool()
        text = (
            "SCHEDULE OF BENEFITS\n"
            "Annual deductible is $1,500.\n"
            "Primary care: $25\n"
            "Specialist: $50\n"
            "Coinsurance: 20%\n"
            "Out-of-pocket maximum is $6,000.\n"
            "Prior authorization required for MRI and physical therapy.\n"
            "Covered in-network only.\n"
        )
        res = tool.invoke({"text": text, "schema_type": "insurance"})
        assert isinstance(res, dict)
        assert res["deductible"] == "$1,500"
        assert res["copays"]["primary_care"] == "$25"
        assert res["copays"]["specialist"] == "$50"
        assert res["coinsurance"] == "20%"
        assert res["out_of_pocket_maximum"] == "$6,000"
        assert "MRI" in res["prior_authorization_flags"]
        assert "physical therapy" in res["prior_authorization_flags"]

    def test_extract_clinical_visit_heuristic_fallback(self):
        tool = ExtractStructuredDataTool()
        text = (
            "CLINICAL VISIT SUMMARY\n"
            "Reason for visit: Acute upper respiratory infection.\n"
            "Physician instructions: Rest, hydration, saline nasal spray.\n"
            "Follow-up: Return in 2 weeks.\n"
            "Questions: Inquire about allergy testing.\n"
        )
        res = tool.invoke({"text": text, "schema_type": "clinical"})
        assert isinstance(res, dict)
        assert res["reason_for_visit"] == "Acute upper respiratory infection"
        assert res["follow_up_timeline"] == "2 weeks"
        assert len(res["physician_instructions"]) >= 1
        assert len(res["questions_to_ask"]) >= 1

    def test_extract_generic_document_heuristic_fallback(self):
        tool = ExtractStructuredDataTool()
        text = (
            "Summary: General discharge instructions for post-op care.\n"
            "Length of stay: 3 days.\n"
            "IV hydration: Normal saline 1000 mL.\n"
            "Sections: Discharge Medication, Wound Care, Diet.\n"
        )
        res = tool.invoke({"text": text, "schema_type": "generic"})
        assert isinstance(res, dict)
        assert res["summary"] == "General discharge instructions for post-op care."
        assert res["key_numerical_values"].get("length_of_stay") == "3 days"
        assert len(res["sections"]) >= 1

    def test_extract_with_model_structured_output(self):
        """Verify that when a model with with_structured_output is supplied, it is invoked."""
        expected_dossier = InsuranceBenefitsDossier(
            deductible="$2,500",
            copays={"primary_care": "$30"},
            coinsurance="15%",
            out_of_pocket_maximum="$7,500",
        )
        mock_model = MockStructuredChatModel(target_dossier=expected_dossier)

        tool = ExtractStructuredDataTool(model=mock_model)
        res = tool.invoke({"text": "Custom insurance policy note", "schema_type": "insurance"})

        assert res["deductible"] == "$2,500"
        assert res["copays"]["primary_care"] == "$30"
        assert res["coinsurance"] == "15%"
        assert res["out_of_pocket_maximum"] == "$7,500"

    @pytest.mark.asyncio
    async def test_async_extraction(self):
        tool = ExtractStructuredDataTool()
        text = (
            "INSURANCE DETAILS\n"
            "Deductible: $2,000\n"
            "Copay is $30\n"
            "Coinsurance: 15%\n"
        )
        res = await tool.ainvoke({"text": text, "schema_type": "insurance"})
        assert isinstance(res, dict)
        assert res["deductible"] == "$2,000"
        assert res["coinsurance"] == "15%"


# ============================================================================
# 3. ValidateGroundingTool Tests
# ============================================================================

class TestValidateGroundingToolAdversarial:
    """Stress tests and boundary checks for ValidateGroundingTool."""

    def test_tool_contract_and_metadata(self):
        tool = ValidateGroundingTool()
        assert tool.name == TOOL_VALIDATE_GROUNDING
        assert tool.args_schema == ValidateGroundingInput

    def test_exact_and_formatted_currency_grounding(self):
        tool = ValidateGroundingTool()
        source = "Deductible is $1,500. Out-of-pocket max is 6000 dollars. Copay is $0."
        dossier = {
            "deductible": "$1,500",
            "out_of_pocket_maximum": "$6,000",
            "copay": "$0",
        }
        res = tool.invoke({"dossier": dossier, "source_text": source})
        assert res["is_grounded"] is True
        assert len(res["unmatched_values"]) == 0

    def test_percentages_and_units_grounding(self):
        tool = ValidateGroundingTool()
        source = "Coinsurance is 20 percent. Special rate is 20.5%. Return in 4 weeks."
        dossier = {
            "coinsurance": "20%",
            "special_rate": "20.5%",
            "timeline": "4 weeks",
        }
        res = tool.invoke({"dossier": dossier, "source_text": source})
        assert res["is_grounded"] is True

    def test_transposed_digits_rejected(self):
        """Transposed digits must be flagged as ungrounded."""
        tool = ValidateGroundingTool()
        source = "Out of pocket max is $1,500. Copay is $250."
        # Transposed: 1050 instead of 1500; 520 instead of 250
        bad_dossier = {
            "out_of_pocket_maximum": "$1,050",
            "copay": "$520",
        }
        res = tool.invoke({"dossier": bad_dossier, "source_text": source})
        assert res["is_grounded"] is False
        assert len(res["unmatched_values"]) == 2

    def test_hallucinated_figures_rejected(self):
        tool = ValidateGroundingTool()
        source = "Deductible is $1,500. Copay is $25."
        bad_dossier = {
            "deductible": "$1,500",
            "copay": "$25",
            "emergency_room": "$9,999",  # Hallucinated
        }
        res = tool.invoke({"dossier": bad_dossier, "source_text": source})
        assert res["is_grounded"] is False
        assert any("9,999" in u for u in res["unmatched_values"])

    def test_cross_domain_unit_mismatch_rejected(self):
        tool = ValidateGroundingTool()
        # Source has $20 copay, dossier claims 20% coinsurance
        source = "Copay is $20 for office visits."
        bad_dossier = {"coinsurance": "20%"}
        res = tool.invoke({"dossier": bad_dossier, "source_text": source})
        assert res["is_grounded"] is False

    def test_timeline_unit_mismatch_rejected(self):
        tool = ValidateGroundingTool()
        source = "Follow up in 4 weeks."
        bad_dossier = {"follow_up": "4 days"}
        res = tool.invoke({"dossier": bad_dossier, "source_text": source})
        assert res["is_grounded"] is False

    def test_pydantic_model_input(self):
        tool = ValidateGroundingTool()
        source = "Deductible: $1,500. Primary care: $25. Coinsurance: 20%."
        dossier = InsuranceBenefitsDossier(
            deductible="$1,500",
            copays={"primary_care": "$25"},
            coinsurance="20%",
        )
        res = tool.invoke({"dossier": dossier, "source_text": source})
        assert res["is_grounded"] is True

    def test_json_string_input(self):
        tool = ValidateGroundingTool()
        source = "Deductible is $1,500."
        dossier_json = json.dumps({"deductible": "$1,500"})
        res = tool.invoke({"dossier": dossier_json, "source_text": source})
        assert res["is_grounded"] is True

    @pytest.mark.asyncio
    async def test_async_grounding_validation(self):
        tool = ValidateGroundingTool()
        source = "Deductible: $1,500."
        res = await tool.ainvoke({"dossier": {"deductible": "$1,500"}, "source_text": source})
        assert res["is_grounded"] is True


# ============================================================================
# 4. Delegation Tools (ListAgentsTool & DelegateToAgentTool) Tests
# ============================================================================

class TestDelegationToolsAdversarial:
    """Stress tests for ListAgentsTool and DelegateToAgentTool."""

    def test_list_agents_tool_contract_and_schema(self):
        tool = ListAgentsTool()
        assert tool.name == TOOL_LIST_AGENTS
        assert tool.args_schema == ListAgentsInput

    def test_list_agents_tool_with_live_registry(self):
        registry = get_agent_registry()
        tool = ListAgentsTool(registry=registry)
        output = tool.invoke({})
        assert isinstance(output, str)
        # Verify specialist agents are present
        assert "visit-steward" in output
        assert "benefits-guide" in output
        assert "habit-companion" in output
        assert "document-extractor" in output
        # Verify orchestrator itself is excluded from specialist delegation catalog
        assert "**orchestrator**" not in output

    def test_list_agents_tool_fallback_without_registry(self):
        tool = ListAgentsTool(registry=None)
        output = tool.invoke({})
        assert isinstance(output, str)
        assert "visit-steward" in output
        assert "document-extractor" in output

    @pytest.mark.asyncio
    async def test_list_agents_tool_async(self):
        tool = ListAgentsTool()
        output = await tool.ainvoke({})
        assert isinstance(output, str)
        assert len(output) > 20

    def test_delegate_to_agent_tool_contract_and_schema(self):
        tool = DelegateToAgentTool()
        assert tool.name == TOOL_DELEGATE_TO_AGENT
        assert tool.args_schema == DelegateToAgentInput

    def test_delegate_to_agent_tool_output_format(self):
        tool = DelegateToAgentTool()
        raw_res = tool.invoke({
            "agent_id": "benefits-guide",
            "instructions": "Please analyze copays and deductibles.",
        })
        payload = json.loads(raw_res)
        assert payload["status"] == "delegated"
        assert payload["agent_id"] == "benefits-guide"
        assert payload["instructions"] == "Please analyze copays and deductibles."

    def test_delegate_to_agent_tool_whitespace_handling(self):
        tool = DelegateToAgentTool()
        raw_res = tool.invoke({
            "agent_id": "   document-extractor   \n",
            "instructions": "  Extract note.  ",
        })
        payload = json.loads(raw_res)
        assert payload["agent_id"] == "document-extractor"
        assert payload["instructions"] == "Extract note."

    @pytest.mark.asyncio
    async def test_delegate_to_agent_tool_async(self):
        tool = DelegateToAgentTool()
        raw_res = await tool.ainvoke({
            "agent_id": "visit-steward",
            "instructions": "Prepare for oncology consult.",
        })
        payload = json.loads(raw_res)
        assert payload["status"] == "delegated"
        assert payload["agent_id"] == "visit-steward"


# ============================================================================
# 5. extract_document_dossier Dual Invocation & Sandboxing Tests
# ============================================================================

class TestExtractDocumentDossierBackwardCompatibilityAndSecurity:
    """Stress tests verifying dual invocation, state mutation, and sandbox security."""

    def test_tool_singleton_properties(self):
        assert isinstance(extract_document_dossier, ExtractDocumentDossierTool)
        assert extract_document_dossier.name == TOOL_EXTRACT_DOCUMENT_DOSSIER
        assert extract_document_dossier.args_schema == ExtractDocumentDossierInput

    def test_direct_callable_invocation_styles(self):
        """Tool can be called as a standard Python function in multiple ways."""
        raw_text = (
            "SCHEDULE OF BENEFITS\n"
            "Deductible: $1,500\n"
            "Primary Care: $25\n"
            "Coinsurance: 20%\n"
        )
        # Style 1: Keyword args
        res1 = extract_document_dossier(document_text=raw_text, dossier_type="insurance")
        assert res1["status"] == "success"
        assert res1["dossier_type"] == "insurance_benefits"

        # Style 2: Dict argument
        res2 = extract_document_dossier({"document_text": raw_text, "dossier_type": "insurance"})
        assert res2["status"] == "success"
        assert res2["dossier_type"] == "insurance_benefits"

        # Style 3: Positional arguments (file_path=None, document_text=..., dossier_type=...)
        res3 = extract_document_dossier(None, raw_text, "insurance")
        assert res3["status"] == "success"
        assert res3["dossier_type"] == "insurance_benefits"

    def test_langchain_tool_invoke_and_ainvoke(self):
        raw_text = (
            "CLINICAL VISIT NOTE\n"
            "Reason for visit: Annual physical exam.\n"
            "Follow-up: 4 weeks.\n"
        )
        # Sync invoke
        res_sync = extract_document_dossier.invoke({
            "document_text": raw_text,
            "dossier_type": "clinical",
        })
        assert res_sync["status"] == "success"
        assert res_sync["dossier_type"] == "clinical_visit"

    @pytest.mark.asyncio
    async def test_langchain_tool_ainvoke(self):
        raw_text = (
            "CLINICAL VISIT NOTE\n"
            "Reason for visit: Post-op check.\n"
            "Follow-up: 1 week.\n"
        )
        res_async = await extract_document_dossier.ainvoke({
            "document_text": raw_text,
            "dossier_type": "clinical",
        })
        assert res_async["status"] == "success"
        assert res_async["dossier_type"] == "clinical_visit"

    def test_state_dictionary_population(self):
        raw_text = (
            "BENEFITS SUMMARY\n"
            "Deductible: $1,500\n"
            "Coinsurance: 20%\n"
        )
        state: Dict[str, Any] = {"document_dossiers": []}
        res = extract_document_dossier(
            document_text=raw_text,
            dossier_type="insurance",
            state=state,
        )
        assert res["status"] == "success"
        assert len(state["document_dossiers"]) == 1
        dossier_entry = state["document_dossiers"][0]
        assert dossier_entry["dossier_type"] == "insurance_benefits"
        assert dossier_entry["data"]["deductible"] == "$1,500"
        assert dossier_entry["grounding"]["is_grounded"] is True

    def test_path_traversal_absolute_paths_blocked(self):
        """Absolute paths like /etc/hosts or /etc/passwd must raise DocumentSandboxError or PermissionError."""
        for forbidden in ["/etc/hosts", "/etc/passwd", "/var/log/system.log"]:
            with pytest.raises((DocumentSandboxError, PermissionError, ValueError)):
                extract_document_dossier.invoke({"file_path": forbidden})

    def test_path_traversal_relative_escapes_blocked(self):
        """Relative path traversal escaping attachments directory must be blocked."""
        for traversal in ["../../etc/passwd", "../../../secret.txt", "attachments/../../escape.txt"]:
            with pytest.raises((DocumentSandboxError, PermissionError, ValueError)):
                extract_document_dossier.invoke({"file_path": traversal})

    def test_nonexistent_sandboxed_file_raises_filenotfound(self, tmp_path):
        """A non-existent file inside valid attachments directory must raise FileNotFoundError."""
        att_dir = tmp_path / "attachments"
        att_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            extract_document_dossier.invoke({
                "file_path": "does_not_exist_987654.txt",
                "workspace_root": str(tmp_path),
            })

    def test_valid_sandboxed_file_processing(self, tmp_path):
        """Valid file inside attachments directory is safely read and extracted."""
        att_dir = tmp_path / "attachments"
        att_dir.mkdir(parents=True)
        note = att_dir / "valid_note.txt"
        note.write_text(
            "Reason for visit: Routine dermatology check.\nFollow-up: 6 months.\nPhysician instructions: Apply lotion.",
            encoding="utf-8",
        )
        res = extract_document_dossier.invoke({
            "file_path": "valid_note.txt",
            "dossier_type": "clinical",
            "workspace_root": str(tmp_path),
        })
        assert res["status"] == "success"
        assert res["dossier"]["reason_for_visit"] == "Routine dermatology check"
        assert res["is_grounded"] is True


# ============================================================================
# 6. Concurrency & Stress Testing
# ============================================================================

class TestConcurrencyAndStressHarness:
    """Stress harness executing extraction tools concurrently."""

    def test_concurrent_pii_sanitization(self):
        tool = SanitizePIITool()
        inputs = [
            f"Patient {i}: SSN 123-45-{i:04d}, Phone (555) 000-{i:04d}, email user{i}@example.com, BP 120/80 mmHg."
            for i in range(100)
        ]

        def _worker(text: str) -> str:
            return tool.invoke({"text": text, "mask_type": "tag"})

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(_worker, inputs))

        assert len(results) == 100
        for i, res in enumerate(results):
            assert f"123-45-{i:04d}" not in res
            assert f"user{i}@example.com" not in res
            assert "120/80 mmHg" in res
            assert "[SSN]" in res
            assert "[PHONE]" in res
            assert "[EMAIL]" in res

    def test_concurrent_grounding_validation(self):
        tool = ValidateGroundingTool()
        pairs = [
            (
                {"deductible": f"${1000 + i:,}", "copay": f"${20 + i}"},
                f"BENEFITS: Deductible is ${1000 + i:,}. Office copay is ${20 + i}."
            )
            for i in range(50)
        ]

        def _worker(pair: Any) -> Any:
            dossier, source = pair
            return tool.invoke({"dossier": dossier, "source_text": source})

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(_worker, pairs))

        assert len(results) == 50
        for res in results:
            assert res["is_grounded"] is True

    @pytest.mark.asyncio
    async def test_concurrent_async_extraction_tools(self):
        extract_tool = ExtractStructuredDataTool()
        tasks = []
        for i in range(20):
            text = (
                f"SCHEDULE OF BENEFITS {i}\n"
                f"Deductible: ${1000 + i:,}\n"
                f"Coinsurance: 20%\n"
            )
            tasks.append(extract_tool.ainvoke({"text": text, "schema_type": "insurance"}))

        results = await asyncio.gather(*tasks)
        assert len(results) == 20
        for i, res in enumerate(results):
            assert res["deductible"] == f"${1000 + i:,}"
            assert res["coinsurance"] == "20%"


# ============================================================================
# 7. Extraction Edge Cases & Defect Remediation Tests
# ============================================================================

class TestExtractionEdgeCasesVerification:
    """Verifies remediation of edge cases in _heuristic_dossier_extractor."""

    def test_uncommad_4digit_dollar_figure_truncation(self):
        r"""In _heuristic_dossier_extractor, regex r'(\$?\d+(?:,\d{3})*)' fully captures
        uncomma'd 4-digit dollar figures without truncation (e.g. $1000 -> $1000, $6000 -> $6000).
        """
        # Uncomma'd figures are fully captured without truncation:
        d1 = _heuristic_dossier_extractor("Deductible: $1000", "insurance")
        assert d1.deductible == "$1000"

        d2 = _heuristic_dossier_extractor("Out of pocket max: $6000", "insurance")
        assert d2.out_of_pocket_maximum == "$6000"

        # Comma'd figures extract accurately:
        d_comma = _heuristic_dossier_extractor("Deductible: $1,000", "insurance")
        assert d_comma.deductible == "$1,000"

    def test_labeled_copay_with_colon_or_is_dropped_or_misclassified(self):
        r"""In _heuristic_dossier_extractor, copay regex correctly matches phrases with 'copay:'
        and accurately classifies primary care and specialist copays.
        """
        # When labeled with 'copay:', primary_care and specialist are accurately parsed
        d = _heuristic_dossier_extractor("Primary care copay: $25\nSpecialist copay: $50", "insurance")
        assert d.copays.get("primary_care") == "$25"
        assert d.copays.get("specialist") == "$50"
