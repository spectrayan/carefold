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

"""Empirical Adversarial Test Suite for Response Synthesis & Output Guardrail Nodes.

Targets:
- ResponseSynthesizerNode (Phase 5 of Orchestrator-Driven Architecture)
- OutputGuardrailNode integration
- Zero-body structured audit logging
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List
import pytest

from carefold.config import settings
from carefold.workflows.nodes.output_guardrail_node import OutputGuardrailNode
from carefold.workflows.nodes.response_synthesizer_node import (
    CANONICAL_DISCLAIMER,
    ResponseSynthesizerNode,
)


class TestConflictingCardiorenalSynthesis:
    """Adversarially challenges ResponseSynthesizerNode with conflicting cardiorenal guidance."""

    def test_conflicting_cardiorenal_guidance_synthesis(self):
        """Cardiology fluid/sodium restriction vs Nephrology hydration/preservation tradeoff."""
        cardio_text = (
            "Cardiology Guidance:\n"
            "- Daily weights: report gain of > 2 lbs in 24 hours.\n"
            "- Strict fluid restriction to 1.5L per 24 hours.\n"
            "- Strict low sodium diet (< 1500 mg daily).\n"
            "- Watch for peripheral edema and orthopnea.\n\n"
            "DISCLAIMER: Carefold is educational only. Consult your physician."
        )
        nephro_text = (
            "Nephrology Guidance:\n"
            "- Baseline eGFR 35 mL/min (Stage 3b Chronic Kidney Disease).\n"
            "- Maintain hydration and liberal fluid intake to protect GFR and prevent acute kidney injury.\n"
            "- Avoid severe volume contraction which precipitates prerenal azotemia.\n"
            "- Serial monitoring of creatinine and potassium.\n\n"
            "NOTE: I am not a doctor or licensed physician. Consult your doctor."
        )

        state: Dict[str, Any] = {
            "specialist_outputs": {
                "cardiology-guide": cardio_text,
                "nephrology-guide": nephro_text,
            },
        }

        output = ResponseSynthesizerNode.synthesize_response(state)

        # 1. Master Agenda Structure
        assert "# Patient Consultation Master Agenda" in output
        assert "## Cardiology Guide Guidance" in output
        assert "## Nephrology Guide Guidance" in output

        # 2. Collaborative Doctor-Discussion Questions (Cardiorenal Coordination)
        assert "## Priority Doctor-Discussion Questions (Cardiorenal Coordination)" in output
        assert "fluid restriction and sodium intake be balanced to protect heart function while accommodating renal clearance" in output
        assert "What target weight range and lab monitoring intervals (electrolytes, BUN, creatinine) are recommended" in output

        # Extract the cardiorenal coordination section specifically
        cardiorenal_section_match = re.search(
            r"## Priority Doctor-Discussion Questions \(Cardiorenal Coordination\)(.*?)(?=##|\Z)",
            output,
            re.DOTALL,
        )
        assert cardiorenal_section_match is not None
        cardiorenal_text = cardiorenal_section_match.group(1).strip()

        # 3. Verify NO prescription directives in cardiorenal coordination framing
        rx_directives = re.findall(
            r"\b(prescribe|prescription|rx|start taking|administer|take medication)\b",
            cardiorenal_text,
            re.IGNORECASE,
        )
        assert rx_directives == [], f"Found prescription directives in cardiorenal framing: {rx_directives}"

        # 4. Verify NO drug dosages in cardiorenal coordination framing
        drug_dosages = re.findall(
            r"\b\d+\.?\d*\s*(?:mg|mcg|ml|g|units|tablets|capsules|pills)\b",
            cardiorenal_text,
            re.IGNORECASE,
        )
        assert drug_dosages == [], f"Found drug dosages in cardiorenal framing: {drug_dosages}"

        # 5. Verify NO diagnostic claims in cardiorenal coordination framing
        diagnostic_claims = re.findall(
            r"\b(we diagnose|you are diagnosed with|diagnosis is|patient suffers from)\b",
            cardiorenal_text,
            re.IGNORECASE,
        )
        assert diagnostic_claims == [], f"Found diagnostic claims in cardiorenal framing: {diagnostic_claims}"

        # 6. Verify framing is strictly inquisitive / collaborative consultation questions
        question_lines = [line.strip() for line in cardiorenal_text.splitlines() if line.strip().startswith("-")]
        assert len(question_lines) >= 2
        for q in question_lines:
            assert q.endswith("?"), f"Question line must end with a question mark: {q}"

    def test_constituent_disclaimers_stripped_and_replaced_by_one_canonical(self):
        """Constituent disclaimers from multiple specialists are completely stripped and replaced by exactly one canonical disclaimer."""
        outputs = {
            "cardiology-guide": (
                "Cardiology recommendations.\n\n"
                "DISCLAIMER: I am not a doctor. Consult your physician."
            ),
            "nephrology-guide": (
                "Nephrology recommendations.\n\n"
                "NOTE: I am not a licensed physician. Consult your doctor."
            ),
            "endocrinology-guide": (
                "Endocrinology recommendations.\n\n"
                "NOTE: I am not a clinician. See your physician."
            ),
            "pulmonology-guide": (
                "Pulmonology recommendations.\n\n"
                "Please consult your doctor before modifying any inhaler schedule."
            ),
            "gastro-guide": (
                "Gastroenterology recommendations.\n\n"
                "Please consult your physician before altering your diet."
            ),
        }

        state: Dict[str, Any] = {"specialist_outputs": outputs}
        output = ResponseSynthesizerNode.synthesize_response(state)

        # Canonical disclaimer must be present at the footer
        assert CANONICAL_DISCLAIMER in output

        # Exactly ONE occurrence of "DISCLAIMER:" in the entire text
        assert output.count("DISCLAIMER:") == 1

        # None of the constituent disclaimer bodies should remain
        assert "I am not a doctor" not in output
        assert "I am not a licensed physician" not in output
        assert "I am not a clinician" not in output
        assert "Please consult your doctor before modifying" not in output
        assert "Please consult your physician before altering" not in output


class TestZeroBodyAuditLogging:
    """Adversarially challenges Zero-Body structured audit logging in ResponseSynthesizerNode."""

    @pytest.mark.asyncio
    async def test_audit_logs_zero_body_retention_when_disabled(self):
        """Verify that audit logs do not leak raw response bodies or prompts when store_bodies=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "audit_test.jsonl"
            settings.audit_log_path = str(log_path)

            node = ResponseSynthesizerNode()

            sensitive_ssn = "SSN-999-00-1111"
            sensitive_clinical_fact = "PATIENT_CONFIDENTIAL_HIV_POSITIVE_HISTORY"
            sensitive_output_1 = "CARDIOLOGY_CONFIDENTIAL_CORONARY_ARTERY_DISEASE"
            sensitive_output_2 = "NEPHROLOGY_CONFIDENTIAL_STAGE_4_RENAL_FAILURE"

            state: Dict[str, Any] = {
                "thread_id": "thread-adversarial-123",
                "prompt": f"Patient query containing {sensitive_ssn} and {sensitive_clinical_fact}",
                "specialist_outputs": {
                    "cardiology-guide": f"{sensitive_output_1} with fluid management",
                    "nephrology-guide": f"{sensitive_output_2} with fluid coordination",
                },
                "store_bodies": False,
            }

            res = await node.execute(state)

            # Check output generated
            assert "output" in res
            assert "# Patient Consultation Master Agenda" in res["output"]

            # Verify file was written
            assert log_path.is_file()
            log_content = log_path.read_text(encoding="utf-8").strip()
            lines = log_content.splitlines()
            assert len(lines) == 1

            entry = json.loads(lines[0])

            # 1. Structural audit metadata is present
            assert entry.get("event") == "synthesis"
            assert entry.get("allowed") is True
            assert entry.get("thread_id") == "thread-adversarial-123"
            assert entry.get("target_agents") == ["cardiology-guide", "nephrology-guide"]
            assert "timestamp" in entry
            assert "ts" in entry

            # 2. NO raw prompt or completion bodies exist in the logged entry
            assert "prompt" not in entry
            assert "completion" not in entry
            assert "body" not in entry
            assert "response" not in entry

            # 3. None of the sensitive PII or clinical output strings leaked into the JSONL log
            assert sensitive_ssn not in log_content
            assert sensitive_clinical_fact not in log_content
            assert sensitive_output_1 not in log_content
            assert sensitive_output_2 not in log_content

            # 4. State audit_events also holds the zero-body redacted record
            state_events = res["audit_events"]
            assert len(state_events) >= 1
            last_event = state_events[-1]
            assert "prompt" not in last_event
            assert "completion" not in last_event

    @pytest.mark.asyncio
    async def test_audit_logs_preserve_bodies_when_explicitly_enabled(self):
        """When store_bodies=True is explicitly configured, audit logs record completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "audit_enabled_test.jsonl"
            settings.audit_log_path = str(log_path)

            node = ResponseSynthesizerNode()
            state: Dict[str, Any] = {
                "thread_id": "thread-enabled-456",
                "prompt": "Test query for audit retention",
                "specialist_outputs": {
                    "cardiology-guide": "Cardio advice with fluid balance",
                    "nephrology-guide": "Nephro advice with fluid balance",
                },
                "store_bodies": True,
            }

            res = await node.execute(state)

            log_content = log_path.read_text(encoding="utf-8").strip()
            entry = json.loads(log_content)

            assert "prompt" in entry
            assert "completion" in entry
            assert entry["prompt"] == "Test query for audit retention"
            assert "# Patient Consultation Master Agenda" in entry["completion"]


class TestPipelineSafetyIntercept:
    """Tests the interaction between ResponseSynthesizerNode and OutputGuardrailNode."""

    @pytest.mark.asyncio
    async def test_output_guardrail_intercepts_prescriptive_specialist_output(self):
        """If an upstream specialist tries to prescribe drugs or dosages, OutputGuardrailNode catches it downstream."""
        # Upstream specialist outputs prescriptive dosage
        adversarial_outputs = {
            "cardiology-guide": "Patient has CHF. Prescribe Furosemide 40 mg PO twice daily. fluid limit 1.5L.",
            "nephrology-guide": "Liberal fluid intake recommended for renal function.",
        }

        state: Dict[str, Any] = {
            "specialist_outputs": adversarial_outputs,
        }

        # Step 1: Synthesizer consolidates
        synth_node = ResponseSynthesizerNode()
        synth_result = await synth_node.execute(state)
        state.update(synth_result)

        assert state.get("next_step") == "output_guardrail"

        # Step 2: OutputGuardrailNode evaluates the synthesized output
        guard_node = OutputGuardrailNode()
        guard_result = await guard_node.execute(state)

        # OutputGuardrailNode MUST refuse the output due to prohibited dosing
        assert guard_result["is_refusal"] is True
        assert guard_result["refused"] is True
        assert "dose" in guard_result["refusal_reason"]
        assert guard_result["next_step"] == "reflection"


class TestEdgeCasesAndAdversarialVariations:
    """Stress tests and boundary condition mining for ResponseSynthesizerNode."""

    def test_single_agent_output_strips_disclaimer_and_appends_canonical(self):
        """Single agent output has constituent disclaimer stripped and canonical footer added."""
        state = {
            "specialist_outputs": {
                "cardiology-guide": "Monitor daily resting pulse.\n\nDISCLAIMER: Not a doctor.",
            },
        }
        output = ResponseSynthesizerNode.synthesize_response(state)
        assert output.count("DISCLAIMER:") == 1
        assert CANONICAL_DISCLAIMER in output
        assert "Monitor daily resting pulse." in output
        assert "# Patient Consultation Master Agenda" not in output

    def test_empty_specialist_outputs_handled_gracefully(self):
        """Empty specialist outputs gracefully returns fallback with canonical disclaimer."""
        state = {"specialist_outputs": {}}
        output = ResponseSynthesizerNode.synthesize_response(state)
        assert "No specialist outputs were generated." in output
        assert CANONICAL_DISCLAIMER in output

    def test_state_output_fallback_when_specialist_outputs_missing(self):
        """When specialist_outputs is absent, falls back to state['output'] with disclaimer stripping."""
        state = {
            "output": "Existing standalone summary.\n\nDISCLAIMER: Consult physician.",
        }
        output = ResponseSynthesizerNode.synthesize_response(state)
        assert output.count("DISCLAIMER:") == 1
        assert CANONICAL_DISCLAIMER in output
        assert "Existing standalone summary." in output

    def test_non_conflicting_multispecialist_synthesis(self):
        """Multi-agent output without cardiorenal fluid conflict omits priority doctor questions."""
        state = {
            "specialist_outputs": {
                "derma-guide": "Apply sunscreen SPF 30 daily.",
                "eye-guide": "Schedule annual dilated retinal exam.",
            },
        }
        output = ResponseSynthesizerNode.synthesize_response(state)
        assert "# Patient Consultation Master Agenda" in output
        assert "Priority Doctor-Discussion Questions" not in output
        assert "## Derma Guide Guidance" in output
        assert "## Eye Guide Guidance" in output
        assert CANONICAL_DISCLAIMER in output
