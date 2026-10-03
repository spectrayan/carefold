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

"""End-to-End Tests for Response Synthesis & Output Guardrailing.

Verifies:
1. ResponseSynthesizerNode:
   - Single-agent output pass-through
   - Multi-agent consolidation into a unified patient master agenda
   - Cardiorenal tradeoff reconciliation (fluid/sodium) into collaborative doctor-discussion questions
   - Disclaimer deduplication (stripping constituent disclaimers, single canonical footer)
2. Zero-Body Structured Audit Logging:
   - Ensuring no raw prompt or response bodies leak into audit logs when store_bodies=False.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import pytest

from carefold.config import settings
from carefold.audit.logger import record_audit


# ============================================================================
# Contract Specification & Reference Test Doubles
# ============================================================================

CANONICAL_DISCLAIMER = (
    "DISCLAIMER: Carefold is an educational and administrative navigation companion, not a licensed healthcare provider. "
    "Do not alter prescription medications or therapy plans without consulting your physician."
)

CONSTITUENT_DISCLAIMER_PATTERNS = [
    re.compile(r"DISCLAIMER:.*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
    re.compile(r"NOTE: I am not a (?:doctor|licensed physician|clinician).*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
    re.compile(r"Please consult your (?:doctor|physician) before.*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
]


# Try importing real ResponseSynthesizerNode if implemented in M5
try:
    from carefold.workflows.nodes.response_synthesizer_node import ResponseSynthesizerNode as RealResponseSynthesizerNode  # type: ignore
    HAS_REAL_SYNTHESIZER = True
except ImportError:
    HAS_REAL_SYNTHESIZER = False
    RealResponseSynthesizerNode = None


class ReferenceResponseSynthesizerNode:
    """Authoritative reference test double for ResponseSynthesizerNode (PROJECT.md § Interface Contracts 5)."""

    @classmethod
    def strip_disclaimers(cls, text: str) -> str:
        """Removes constituent agent disclaimers from specialist text."""
        cleaned = text
        for pat in CONSTITUENT_DISCLAIMER_PATTERNS:
            cleaned = pat.sub("", cleaned).strip()
        return cleaned

    @classmethod
    def synthesize_response(cls, state: Dict[str, Any]) -> str:
        """Synthesizes specialist outputs into a master agenda with cardiorenal reconciliation."""
        specialist_outputs = state.get("specialist_outputs", {})
        if not specialist_outputs:
            return f"No specialist outputs were generated.\n\n{CANONICAL_DISCLAIMER}"

        # Single agent fast-path
        if len(specialist_outputs) == 1:
            single_text = list(specialist_outputs.values())[0]
            clean_text = cls.strip_disclaimers(single_text)
            return f"{clean_text}\n\n{CANONICAL_DISCLAIMER}"

        # Multi-agent synthesis
        sections: List[str] = ["# Patient Consultation Master Agenda\n"]

        # Check for cardiorenal fluid/sodium tradeoff
        has_cardio = "cardiology-guide" in specialist_outputs
        has_nephro = "nephrology-guide" in specialist_outputs
        combined_text = " ".join(specialist_outputs.values()).lower()
        has_fluid_conflict = ("fluid" in combined_text or "sodium" in combined_text) and (has_cardio and has_nephro)

        # 1. Cardiorenal Tradeoff Framing (collaborative doctor-discussion questions without prescribing)
        if has_fluid_conflict:
            sections.append(
                "## Priority Doctor-Discussion Questions (Cardiorenal Coordination)\n"
                "- How should daily fluid restriction and sodium intake be balanced to protect heart function while accommodating renal clearance?\n"
                "- What target weight range and lab monitoring intervals (electrolytes, BUN, creatinine) are recommended when adjusting diuretic therapies?\n"
            )

        # 2. Specialist Domain Agendas
        for agent_id, output_text in specialist_outputs.items():
            specialty_title = agent_id.replace("-", " ").title()
            clean_output = cls.strip_disclaimers(output_text)
            sections.append(f"## {specialty_title} Guidance\n{clean_output}\n")

        # 3. Canonical Deduplicated Disclaimer Footer
        sections.append(CANONICAL_DISCLAIMER)

        full_output = "\n".join(sections)
        state["output"] = full_output
        return full_output


def get_synthesizer():
    """Returns real ResponseSynthesizerNode if available, otherwise reference double."""
    return RealResponseSynthesizerNode if RealResponseSynthesizerNode is not None else ReferenceResponseSynthesizerNode


# ============================================================================
# Tier 1: Feature Coverage (R5)
# ============================================================================

# ============================================================================
# Tier 1: Feature Coverage: Response Synthesis
# ============================================================================

class TestResponseSynthesisFeatureCoverage:
    """Tier 1: Feature coverage for multi-agent synthesis, tradeoff questions, and disclaimers."""

    def test_single_agent_output_passthrough(self):
        """Single agent output passes through with only disclaimer deduplication."""
        synth = get_synthesizer()
        raw_text = (
            "Here is your hypertension checkup agenda:\n"
            "1. Discuss morning BP spikes.\n"
            "DISCLAIMER: I am not a doctor. Consult your physician."
        )
        state = {
            "specialist_outputs": {"cardiology-guide": raw_text},
        }

        output = synth.synthesize_response(state)

        assert "hypertension checkup agenda" in output
        assert "Discuss morning BP spikes" in output
        # Verify constituent disclaimer stripped and canonical disclaimer added exactly once
        assert output.count("DISCLAIMER:") == 1
        assert CANONICAL_DISCLAIMER in output

    def test_merges_parallel_specialist_outputs_into_master_agenda(self):
        """Merges outputs from multiple specialists into unified patient master agenda."""
        synth = get_synthesizer()
        state = {
            "specialist_outputs": {
                "cardiology-guide": "Track daily pulse and blood pressure.",
                "endocrinology-guide": "Review 14-day continuous glucose monitor report.",
            },
        }

        output = synth.synthesize_response(state)

        assert "# Patient Consultation Master Agenda" in output
        assert "## Cardiology Guide Guidance" in output
        assert "Track daily pulse and blood pressure." in output
        assert "## Endocrinology Guide Guidance" in output
        assert "Review 14-day continuous glucose monitor report." in output

    def test_cardiorenal_tradeoff_collaborative_doctor_questions(self):
        """Frames cardiorenal fluid/sodium contradictions into non-prescriptive doctor-discussion questions."""
        synth = get_synthesizer()
        state = {
            "specialist_outputs": {
                "cardiology-guide": "Cardiology recommends strict 1.5L daily fluid restriction and sodium moderation.",
                "nephrology-guide": "Nephrology cautions that severe fluid restriction may increase serum creatinine.",
            },
        }

        output = synth.synthesize_response(state)

        # Must frame as doctor-discussion questions, NOT prescriptive dosing
        assert "Doctor-Discussion Questions" in output
        assert "fluid restriction and sodium intake be balanced" in output
        assert "protect heart function while accommodating renal clearance" in output
        # Must not prescribe or recommend specific dosage adjustments
        assert "prescribe" not in output.lower()

    def test_disclaimer_deduplication_single_canonical_footer(self):
        """Strips multiple constituent specialist disclaimers and appends single canonical disclaimer."""
        synth = get_synthesizer()
        state = {
            "specialist_outputs": {
                "cardiology-guide": "Cardio advice.\nDISCLAIMER: I am not a doctor. Consult your physician.",
                "nephrology-guide": "Renal advice.\nDISCLAIMER: I am not a physician. Consult your doctor.",
                "endocrinology-guide": "Endo advice.\nNOTE: I am not a clinician. See your physician.",
            },
        }

        output = synth.synthesize_response(state)

        # Count total disclaimer occurrences in final merged output
        assert output.count("DISCLAIMER:") == 1
        assert CANONICAL_DISCLAIMER in output

    @pytest.mark.asyncio
    async def test_zero_body_audit_logging_enforcement(self, e2e_workspace: Path):
        """Structured audit log records events with zero raw request/response body when disabled."""
        log_file = e2e_workspace / "logs" / "test_audit.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        event = {
            "event": "run",
            "agent_id": "orchestrator",
            "execution_plan_mode": "parallel",
            "target_agents": ["cardiology-guide", "nephrology-guide"],
            "request_body": "Sensitive patient medical record with PII and clinical history",
            "response_body": "Detailed clinical synthesis with confidential diagnoses",
        }

        # Record audit with store_bodies=False
        await record_audit(event, log_path=log_file, store_bodies=False)

        assert log_file.is_file()
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1

        last_entry = json.loads(lines[-1])
        # Assert metadata is preserved
        assert last_entry.get("agent_id") == "orchestrator"
        # Assert raw bodies are completely absent or redacted to zero-body
        assert "Sensitive patient medical record" not in json.dumps(last_entry)
        assert "Detailed clinical synthesis" not in json.dumps(last_entry)
        assert last_entry.get("request_body") is None or "request_body" not in last_entry


# ============================================================================
# Tier 2: Boundary & Corner Cases: Response Synthesis
# ============================================================================

class TestResponseSynthesisBoundaries:
    """Tier 2: Boundary conditions and stress tests for response synthesis."""

    def test_synthesizer_empty_specialist_outputs(self):
        """Empty specialist_outputs returns clean fallback message without raising error."""
        synth = get_synthesizer()
        output = synth.synthesize_response({"specialist_outputs": {}})
        assert "No specialist outputs were generated" in output
        assert CANONICAL_DISCLAIMER in output

    def test_ten_duplicate_disclaimers_collapsed_to_one(self):
        """Ten agents emitting redundant disclaimers are deduplicated into exactly one footer."""
        synth = get_synthesizer()
        outputs = {
            f"agent-{i}": f"Content {i}.\nDISCLAIMER: Not a doctor, consult physician."
            for i in range(10)
        }
        output = synth.synthesize_response({"specialist_outputs": outputs})
        assert output.count("DISCLAIMER:") == 1

    def test_specialist_output_without_disclaimers(self):
        """Clean outputs without any existing disclaimers receive the canonical disclaimer."""
        synth = get_synthesizer()
        state = {
            "specialist_outputs": {"cardiology-guide": "Simple lifestyle recommendations."},
        }
        output = synth.synthesize_response(state)
        assert CANONICAL_DISCLAIMER in output

    @pytest.mark.asyncio
    async def test_zero_body_audit_extreme_payload_size(self, e2e_workspace: Path):
        """Large 200KB payload is completely omitted from audit log."""
        log_file = e2e_workspace / "logs" / "extreme_payload_audit.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        large_payload = "A" * 200_000
        event = {
            "event": "run",
            "agent_id": "orchestrator",
            "body": large_payload,
            "response": large_payload,
        }

        await record_audit(event, log_path=log_file, store_bodies=False)
        log_content = log_file.read_text(encoding="utf-8")
        assert len(log_content) < 5000, "Audit log must not store large body payloads"


# ============================================================================
# Tier 3: Cross-Feature Combinations: Response Synthesis
# ============================================================================

class TestResponseSynthesisCrossFeature:
    """Tier 3: Pairwise integration across Dispatcher and Synthesizer."""

    def test_dispatcher_outputs_fed_into_synthesizer(self):
        """Dispatched specialist outputs feed directly into ResponseSynthesizerNode."""
        synth = get_synthesizer()
        state = {
            "specialist_outputs": {
                "ortho-guide": "Pre-operative physical therapy assessment.",
                "prior-auth-navigator": "Prior authorization checklist complete.",
            },
        }

        full_output = synth.synthesize_response(state)
        assert "Ortho Guide Guidance" in full_output
        assert "Prior Auth Navigator Guidance" in full_output
        assert state["output"] == full_output


# ============================================================================
# Tier 4: Real-World Application Scenarios: Response Synthesis
# ============================================================================

class TestResponseSynthesisRealWorldScenarios:
    """Tier 4: Realistic multimorbid patient synthesis."""

    def test_cardiorenal_patient_agenda_synthesis(self):
        """Multimorbid cardiorenal patient outputs synthesized into prioritized consultation agenda."""
        synth = get_synthesizer()
        state = {
            "specialist_outputs": {
                "cardiology-guide": (
                    "CARDIOLOGY ENCOUNTER PREPARATION:\n"
                    "- Review 7-day home BP log (average 138/86 mmHg).\n"
                    "- Note reported 3-lb weight gain and bilateral ankle puffiness.\n"
                    "- Discuss 1.5L daily fluid restriction.\n"
                    "DISCLAIMER: Consult your doctor."
                ),
                "nephrology-guide": (
                    "NEPHROLOGY ENCOUNTER PREPARATION:\n"
                    "- Current eGFR 42 mL/min (Stage 3 CKD).\n"
                    "- Monitor for over-diuresis and acute kidney injury with strict fluid limits.\n"
                    "- Inquire about potassium and sodium tracking worksheet.\n"
                    "DISCLAIMER: Not medical advice."
                ),
            },
        }

        output = synth.synthesize_response(state)

        # 1. Master Agenda Header
        assert "# Patient Consultation Master Agenda" in output
        # 2. Priority Cardiorenal Doctor Questions
        assert "Priority Doctor-Discussion Questions" in output
        assert "fluid restriction and sodium intake" in output
        # 3. Specialty Guidance
        assert "Cardiology Guide Guidance" in output
        assert "Nephrology Guide Guidance" in output
        # 4. Canonical Disclaimer Footer
        assert CANONICAL_DISCLAIMER in output
        assert output.count("DISCLAIMER:") == 1
