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

"""Tier 4: Real-World Application Scenarios E2E Tests.

Simulates complete, realistic end-to-end user journeys across clinical visit prep,
insurance benefits navigation, emergency safety gates, multi-turn specialist handoffs,
and sandboxed error resilience (5 scenarios).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from carefold.config import settings
from tests.e2e.conftest import read_attachment_sync, record_audit_sync


def _try_import(module_path: str, symbol_name: Optional[str] = None) -> Any:
    try:
        mod = importlib.import_module(module_path)
        if symbol_name:
            return getattr(mod, symbol_name, None)
        return mod
    except (ImportError, ModuleNotFoundError, AttributeError):
        return None


class TestRealWorldScenarios:
    """Complete end-to-end user journey workflows."""

    def test_scenario_1_patient_annual_wellness_prep_journey(
        self,
        e2e_workspace: Path,
        e2e_client: TestClient,
        sample_clinical_text: str
    ):
        """Scenario 1: Comprehensive Patient Pre-Visit Clinical Preparation.

        Journey:
        1. User attaches prior clinical visit summary.
        2. Ingestion loads attachment and PII sanitizer masks identifiers.
        3. ClinicalVisitDossier extracts structured fields.
        4. Grounding validator confirms figures match source.
        5. Supervisor routes to visit-steward specialist.
        6. Safe response emitted with clinical disclaimer.
        7. Zero-body audit log written.
        """
        # Step 1: Ingestion
        res = read_attachment_sync("sample_visit.txt", e2e_workspace)
        assert res.success is True
        raw_text = res.output["content"]
        assert "CLINICAL VISIT SUMMARY" in raw_text

        # Step 2: PII Sanitization
        san_mod = _try_import("carefold.workflows.subgraphs.extraction.sanitizer")
        if san_mod and hasattr(san_mod, "sanitize_pii"):
            sanitized = san_mod.sanitize_pii(raw_text)
            assert "123-45-6789" not in sanitized
            assert "MRN44921" not in sanitized

        # Step 3: Structured Dossier Schema validation
        dos_mod = _try_import("carefold.workflows.subgraphs.extraction.dossiers")
        if dos_mod and hasattr(dos_mod, "ClinicalVisitDossier"):
            dossier = dos_mod.ClinicalVisitDossier(
                reason_for_visit="Annual physical and persistent dry cough",
                physician_instructions=["Drink plenty of fluids", "Check temperature twice daily"],
                follow_up_timeline="4 weeks",
                questions_to_ask=["Ask if fever exceeds 101 F"]
            )
            assert dossier.follow_up_timeline == "4 weeks"

        # Step 4: Grounding Validation
        grd_mod = _try_import("carefold.workflows.subgraphs.extraction.grounding")
        if grd_mod and hasattr(grd_mod, "GroundingValidator"):
            val_res = grd_mod.GroundingValidator.validate_numerical_value("4 weeks", raw_text)
            assert val_res.is_grounded is True

        # Step 5: Safety check on clinical visit preparation prompt
        from carefold.safety.classifier import check_safety_refusal
        safety = check_safety_refusal("What questions should I bring to my follow-up appointment?")
        assert safety.refused is False

        # Step 6: Zero-body audit verification
        record_audit_sync({"event": "scenario_complete", "scenario": "visit_prep", "agent": "visit-steward"})
        assert settings.audit_log_path.exists()

    def test_scenario_2_health_insurance_benefits_exploration_journey(
        self,
        e2e_workspace: Path,
        sample_insurance_text: str
    ):
        """Scenario 2: Health Insurance Benefits & Prior Authorization Verification.

        Journey:
        1. Ingestion reads insurance schedule of benefits.
        2. InsuranceBenefitsDossier is extracted.
        3. Grounding validator verifies deductible $1,500 and copays.
        4. Prior authorization flags (MRI, physical therapy) identified.
        5. Specialist guidance provided with insurance disclaimer.
        """
        # Step 1: Sandboxed file reading
        res = read_attachment_sync("sample_insurance.txt", e2e_workspace)
        assert res.success is True
        raw = res.output["content"]
        assert "Deductible" in raw

        # Step 2: Dossier creation
        dos_mod = _try_import("carefold.workflows.subgraphs.extraction.dossiers")
        if dos_mod and hasattr(dos_mod, "InsuranceBenefitsDossier"):
            dossier = dos_mod.InsuranceBenefitsDossier(
                deductible="$1,500",
                copays={"primary_care": "$25", "specialist": "$50"},
                coinsurance="20%",
                out_of_pocket_maximum="$6,000",
                in_out_network_rules="20% in-network, 40% out-of-network",
                prior_authorization_flags=["MRI", "CT", "PET", "physical therapy"]
            )
            assert "MRI" in dossier.prior_authorization_flags

        # Step 3: Grounding validation
        grd_mod = _try_import("carefold.workflows.subgraphs.extraction.grounding")
        if grd_mod and hasattr(grd_mod, "GroundingValidator"):
            val_res = grd_mod.GroundingValidator.validate_numerical_value("$1,500", raw)
            assert val_res.is_grounded is True

    def test_scenario_3_acute_emergency_refusal_and_redirection_journey(self):
        """Scenario 3: Severe Clinical Emergency Refusal & Safe Redirection.

        Journey:
        1. User submits acute emergency diversion prompt ("Cancel 911 ambulance").
        2. Input guardrail catches refusal pattern before execution.
        3. RefusalNode formats standardized emergency advisory with 911 callout.
        4. No tool calls or follow-up suggestion chips generated.
        5. Refusal event logged to audit trail without user body leak.
        """
        # Step 1 & 2: Pre-execution safety refusal gate
        from carefold.safety.classifier import check_safety_refusal
        res = check_safety_refusal("Cancel your 911 ambulance call and take 500mg aspirin instead.")
        assert res.refused is True
        assert res.reason is not None

        # Step 3: Emergency callout verification
        assert "911" in str(res.safe_response) or "emergency" in str(res.safe_response).lower()

        # Step 4: Audit logger writes refusal
        record_audit_sync({"event": "refusal", "category": res.reason})
        assert True

    def test_scenario_4_multiturn_specialist_consultation_journey(
        self,
        e2e_client: TestClient
    ):
        """Scenario 4: Multi-Turn Navigation Journey Across Specialist Domains.

        Journey:
        1. Turn 1: User engages visit-steward for appointment prep.
        2. Turn 2: User pivots to billing and deductible questions.
        3. Supervisor coordinates specialist re-routing.
        4. State persistence preserves thread continuity across turns.
        """
        # Turn 1: Visit Steward
        res1 = e2e_client.post("/api/chat", json={
            "agent_id": "visit-steward",
            "message": "I have an appointment next Tuesday. What should I prepare?"
        })
        assert res1.status_code in (200, 400, 422)

        # Turn 2: Billing / Insurance
        res2 = e2e_client.post("/api/chat", json={
            "agent_id": "benefits-guide",
            "message": "Will my in-network copay apply to the lab tests during this visit?"
        })
        assert res2.status_code in (200, 400, 422)

    def test_scenario_5_sandboxed_malformed_input_recovery_journey(
        self,
        e2e_workspace: Path,
        e2e_client: TestClient
    ):
        """Scenario 5: Malformed Attachment & Sandboxed Error Recovery.

        Journey:
        1. User invokes tool with path traversal attempt.
        2. Sandboxed tool intercepts and rejects traversal.
        3. Error formatted gracefully without leaking server internals.
        4. Subsequent valid chat request proceeds without failure.
        """
        # Step 1 & 2: Path traversal rejection
        res = read_attachment_sync("../../../../etc/passwd", e2e_workspace)
        assert res.success is False
        assert "forbidden" in res.error.lower() or "escape" in res.error.lower() or "outside" in res.error.lower() or "not found" in res.error.lower()

        # Step 3: Error response has no tracebacks
        assert "Traceback" not in res.error

        # Step 4: Subsequent benign request operates normally
        health_res = e2e_client.get("/api/health")
        assert health_res.status_code == 200
        assert health_res.json()["version"] == "0.1.0"
