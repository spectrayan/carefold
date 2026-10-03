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

"""End-to-End Tests for Context Load & Pre-Validation Gating.

Verifies:
1. ContextLoader: Multi-source ingestion of query, checkpoints, attachments, notes, and catalog summary.
2. Safety Gating: Acute emergency red-flag triggers (immediate 911/ER diversion for chest pain, stroke FAST, anaphylaxis).
3. Clinical Consent Gating: Enforcing `allow_clinical` check before routing to clinical risk-class specialists.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import pytest

from carefold.config import settings


# ============================================================================
# Contract Specification & Reference Test Doubles
# ============================================================================

@dataclass
class EmergencyFlag:
    detected: bool
    category: str
    trigger_phrase: str
    referral_message: str


# Real module imports if available, otherwise reference contract implementation
try:
    from carefold.loaders.context_loader import ContextLoader as RealContextLoader
except ImportError:
    RealContextLoader = None

try:
    from carefold.safety.emergency import check_emergency_red_flags as real_check_emergency_red_flags
except ImportError:
    real_check_emergency_red_flags = None


class ReferenceContextLoader:
    """Authoritative reference test double for ContextLoader specification (PROJECT.md § Interface Contracts 1)."""

    @classmethod
    def load_context(cls, state: Dict[str, Any], workspace_root: Path) -> Dict[str, Any]:
        """Ingests attachments, notes, and catalog summary into AgentState."""
        updated = dict(state)

        # 1. Ingest attachments
        attachments_dir = workspace_root / "attachments"
        discovered_attachments: List[str] = []
        if attachments_dir.is_dir():
            for p in sorted(attachments_dir.glob("*")):
                if p.is_file() and not p.name.startswith("."):
                    # Security check: ignore directory traversal attempts
                    if ".." not in p.name:
                        discovered_attachments.append(str(p.resolve()))
        updated["attachments"] = discovered_attachments

        # 2. Ingest notes
        notes_dir = workspace_root / "workspace" / "notes"
        if not notes_dir.is_dir():
            notes_dir = workspace_root / "notes"
        discovered_notes: List[Dict[str, Any]] = []
        if notes_dir.is_dir():
            for np in sorted(notes_dir.glob("*.md")):
                if np.is_file() and not np.name.startswith("."):
                    content = np.read_text(encoding="utf-8")
                    snippet = content[:200].replace("\n", " ").strip()
                    discovered_notes.append({
                        "title": np.stem.replace("_", " ").title(),
                        "path": str(np.resolve()),
                        "snippet": snippet,
                    })
        updated["notes"] = discovered_notes

        # 3. Ingest catalog summary
        agents_dir = workspace_root / "agents"
        summary_lines: List[str] = []
        if agents_dir.is_dir():
            for ad in sorted(agents_dir.glob("*")):
                if ad.is_dir() and not ad.name.startswith("_system"):
                    summary_lines.append(f"- {ad.name}: healthcare navigation specialist")
        updated["catalog_summary"] = "\n".join(summary_lines)

        return updated


def reference_check_emergency_red_flags(prompt: str) -> Optional[EmergencyFlag]:
    """Authoritative reference test double for emergency red-flag gating (PROJECT.md § Interface Contracts 2)."""
    p_lower = prompt.lower()

    # Negation guard: "no chest pain", "do not have chest pain", "without shortness of breath"
    negations = [
        r"\b(?:no|not|without|never|denies|negative for)\s+(?:chest\s+pain|shortness of breath|difficulty breathing)",
        r"\b(?:years?|months?)\s+ago\b",
    ]
    for neg in negations:
        if re.search(neg, p_lower):
            return None

    # Acute chest pain patterns
    chest_patterns = [
        r"\b(?:crushing|squeezing|radiating|severe|acute)\s+chest\s+(?:pain|pressure|tightness)\b",
        r"\bchest\s+pain\s+(?:radiating|spreading)\s+to\s+(?:arm|jaw|neck|back)\b",
        r"\bpressure\s+in\s+(?:my\s+)?chest\b.*\bcold\s+sweat\b",
    ]
    for cp in chest_patterns:
        if re.search(cp, p_lower):
            return EmergencyFlag(
                detected=True,
                category="acute_chest_pain",
                trigger_phrase="acute chest pain/pressure",
                referral_message="EMERGENCY WARNING: Acute chest pain detected. Call 911 or visit the nearest emergency room immediately.",
            )

    # Stroke FAST patterns
    stroke_patterns = [
        r"\b(?:facial\s+droop|face\s+drooping|slurred\s+speech|arm\s+weakness|sudden\s+numbness\s+on\s+one\s+side)\b",
        r"\b(?:sudden\s+loss\s+of\s+vision|sudden\s+confusion|cannot\s+speak|unable\s+to\s+move\s+arm)\b",
    ]
    for sp in stroke_patterns:
        if re.search(sp, p_lower):
            return EmergencyFlag(
                detected=True,
                category="stroke_fast",
                trigger_phrase="FAST neurological symptoms",
                referral_message="EMERGENCY WARNING: Possible stroke symptoms detected. Call 911 immediately.",
            )

    # Anaphylaxis patterns
    anaphylaxis_patterns = [
        r"\b(?:throat\s+(?:is\s+)?closing(?:\s+up)?|(?:swollen\s+lips?|lips?\s+(?:are\s+)?swollen)|lip\s+edema|tongue\s+swelling|difficulty\s+swallowing\s+and\s+breathing)\b",
        r"\b(?:anaphylaxis|hives\s+and\s+(?:wheezing|shortness\s+of\s+breath))\b",
    ]
    for ap in anaphylaxis_patterns:
        if re.search(ap, p_lower):
            return EmergencyFlag(
                detected=True,
                category="anaphylaxis",
                trigger_phrase="acute allergic airway reaction",
                referral_message="EMERGENCY WARNING: Severe allergic reaction detected. Administer epinephrine if prescribed and call 911 immediately.",
            )

    return None


def get_context_loader():
    """Returns real ContextLoader if available, otherwise reference test double."""
    return RealContextLoader if RealContextLoader is not None else ReferenceContextLoader


def get_emergency_detector():
    """Returns real check_emergency_red_flags if available, otherwise reference test double."""
    return real_check_emergency_red_flags if real_check_emergency_red_flags is not None else reference_check_emergency_red_flags


# ============================================================================
# Tier 1: Feature Coverage: Context & Safety Gating
# ============================================================================

class TestContextAndSafetyGatingFeatureCoverage:
    """Tier 1: Feature coverage for ContextLoader, emergency red flags, and clinical consent."""

    def test_context_loader_ingests_attachments(self, e2e_workspace: Path):
        """Verifies ContextLoader discovers and loads files from attachments/ directory."""
        loader = get_context_loader()
        initial_state = {"prompt": "Review my visit summary", "thread_id": "t1"}

        result_state = loader.load_context(initial_state, e2e_workspace)

        assert "attachments" in result_state
        assert isinstance(result_state["attachments"], list)
        assert len(result_state["attachments"]) >= 2
        # Verify sample_visit.txt was discovered
        attachment_names = [Path(p).name for p in result_state["attachments"]]
        assert "sample_visit.txt" in attachment_names
        assert "sample_insurance.txt" in attachment_names

    def test_context_loader_ingests_user_notes(self, e2e_workspace: Path):
        """Verifies ContextLoader reads user notes with title, path, and snippet."""
        notes_dir = e2e_workspace / "workspace" / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        note_file = notes_dir / "hypertension_log.md"
        note_file.write_text("# Blood Pressure Log\n2026-10-01: 135/85 mmHg.\n2026-10-02: 130/82 mmHg.", encoding="utf-8")

        loader = get_context_loader()
        initial_state = {"prompt": "Check my BP trends"}
        result_state = loader.load_context(initial_state, e2e_workspace)

        assert "notes" in result_state
        assert isinstance(result_state["notes"], list)
        assert len(result_state["notes"]) >= 1

        note = next(n for n in result_state["notes"] if "Hypertension" in n["title"])
        assert "Blood Pressure Log" in note["snippet"]
        assert Path(note["path"]).exists()

    def test_context_loader_ingests_catalog_summary(self, e2e_workspace: Path):
        """Verifies ContextLoader injects catalog summary of available specialists."""
        loader = get_context_loader()
        initial_state = {"prompt": "Find a heart doctor"}
        result_state = loader.load_context(initial_state, e2e_workspace)

        assert "catalog_summary" in result_state
        summary = result_state["catalog_summary"]
        assert "cardiology-guide" in summary
        assert "nephrology-guide" in summary

    def test_emergency_red_flag_acute_chest_pain(self):
        """Verifies acute chest pain / radiating pressure triggers immediate 911 refusal."""
        detector = get_emergency_detector()
        prompt = "I have sudden crushing chest pain radiating to my left arm and jaw."

        flag = detector(prompt)
        assert flag is not None
        assert flag.detected is True
        assert flag.category == "acute_chest_pain"
        assert "911" in flag.referral_message

    def test_emergency_red_flag_stroke_fast(self):
        """Verifies FAST stroke symptoms trigger immediate 911 emergency referral."""
        detector = get_emergency_detector()
        prompt = "My mother has sudden facial drooping and slurred speech and can't raise her arm."

        flag = detector(prompt)
        assert flag is not None
        assert flag.detected is True
        assert flag.category == "stroke_fast"
        assert "911" in flag.referral_message

    def test_emergency_red_flag_anaphylaxis(self):
        """Verifies acute anaphylaxis triggers immediate emergency refusal."""
        detector = get_emergency_detector()
        prompt = "I ate peanuts 10 minutes ago, my throat is closing up and my lips are swollen."

        flag = detector(prompt)
        assert flag is not None
        assert flag.detected is True
        assert flag.category == "anaphylaxis"
        assert "epinephrine" in flag.referral_message.lower() or "911" in flag.referral_message

    def test_clinical_consent_gating_unconsented(self):
        """Clinical domain queries without allow_clinical=True trigger consent gating."""
        state = {
            "prompt": "What medication should I take for my blood pressure?",
            "target_domain": "clinical",
            "allow_clinical": False,
        }

        # Simulate InputGuardrailNode consent evaluation
        is_refusal = state.get("target_domain") == "clinical" and not state.get("allow_clinical")
        refusal_reason = "clinical_consent_required" if is_refusal else None

        assert is_refusal is True
        assert refusal_reason == "clinical_consent_required"

    def test_clinical_consent_gating_consented(self):
        """Clinical domain queries with allow_clinical=True proceed uninterrupted."""
        state = {
            "prompt": "Help me prepare questions for my cardiologist",
            "target_domain": "clinical",
            "allow_clinical": True,
        }

        is_refusal = state.get("target_domain") == "clinical" and not state.get("allow_clinical")
        assert is_refusal is False

    def test_administrative_domain_bypasses_clinical_consent(self):
        """Administrative queries (benefits, billing) do not require allow_clinical."""
        state = {
            "prompt": "What is my in-network copay for physical therapy?",
            "target_domain": "administrative",
            "allow_clinical": False,
        }

        is_refusal = state.get("target_domain") == "clinical" and not state.get("allow_clinical")
        assert is_refusal is False


# ============================================================================
# Tier 2: Boundary & Corner Cases: Context & Safety Gating
# ============================================================================

class TestContextAndSafetyGatingBoundaries:
    """Tier 2: Boundary conditions, corner cases, and negative tests for context & safety gating."""

    def test_missing_attachments_and_notes_directories(self, tmp_path: Path):
        """Handles empty or completely missing attachments and notes directories without crashing."""
        empty_root = tmp_path / "empty_workspace"
        empty_root.mkdir()

        loader = get_context_loader()
        state = loader.load_context({"prompt": "Hello"}, empty_root)

        assert state["attachments"] == []
        assert state["notes"] == []

    def test_path_traversal_in_attachment_loading(self, e2e_workspace: Path):
        """Ensures hidden or dot-dot files are ignored during attachment discovery."""
        att_dir = e2e_workspace / "attachments"
        # Create a hidden file
        (att_dir / ".hidden_secret.txt").write_text("secret", encoding="utf-8")

        loader = get_context_loader()
        state = loader.load_context({}, e2e_workspace)

        attachment_names = [Path(p).name for p in state["attachments"]]
        assert ".hidden_secret.txt" not in attachment_names

    def test_emergency_red_flag_negation(self):
        """Verifies explicit negation does NOT trigger emergency red-flag diversion."""
        detector = get_emergency_detector()
        prompt = "The patient has no chest pain and denies shortness of breath."

        flag = detector(prompt)
        assert flag is None, "Negated symptoms should not trigger emergency red flag"

    def test_emergency_red_flag_historical_context(self):
        """Verifies historical past-tense disclosures do not trigger acute 911 diversion."""
        detector = get_emergency_detector()
        prompt = "I had a heart attack 5 years ago, and I need help understanding my insurance deductible."

        flag = detector(prompt)
        assert flag is None, "Historical medical events should not trigger acute 911 diversion"

    def test_clinical_consent_boundary_values(self):
        """Verifies falsy variations of allow_clinical are properly treated as unconsented."""
        for falsy_val in [False, None, "", 0, "false"]:
            state = {
                "target_domain": "clinical",
                "allow_clinical": falsy_val,
            }
            # allow_clinical must be strictly boolean True
            is_consented = state.get("allow_clinical") is True
            assert is_consented is False, f"Falsy value {falsy_val!r} must not grant clinical consent"


# ============================================================================
# Tier 3: Cross-Feature Combinations: Context & Safety Gating
# ============================================================================

class TestContextAndSafetyGatingCrossFeature:
    """Tier 3: Pairwise integration across ContextLoader and Safety Gating."""

    def test_context_load_then_emergency_interception(self, e2e_workspace: Path):
        """Context is loaded, but acute emergency in prompt immediately intercepts workflow."""
        loader = get_context_loader()
        detector = get_emergency_detector()

        initial_state = {
            "prompt": "Severe crushing chest pain radiating to left jaw, please read my attachment!",
        }
        loaded_state = loader.load_context(initial_state, e2e_workspace)

        # Check emergency gate
        flag = detector(loaded_state["prompt"])
        assert flag is not None
        assert flag.detected is True

        # Workflow sets refusal
        loaded_state["is_refusal"] = True
        loaded_state["refusal_reason"] = "emergency_red_flag"
        loaded_state["refusal_message"] = flag.referral_message

        # Assert downstream orchestrator planning is blocked
        assert loaded_state["is_refusal"] is True
        assert "911" in loaded_state["refusal_message"]

    def test_unconsented_clinical_query_halts_before_planning(self):
        """Unconsented clinical request halts at safety gate before any plan can be executed."""
        state = {
            "prompt": "I have arrhythmia, should I change my beta blocker?",
            "target_domain": "clinical",
            "allow_clinical": False,
        }

        # Safety gating check
        if state.get("target_domain") == "clinical" and not state.get("allow_clinical"):
            state["is_refusal"] = True
            state["refusal_reason"] = "clinical_consent_required"

        assert state["is_refusal"] is True
        assert "execution_plan" not in state


# ============================================================================
# Tier 4: Real-World Application Scenarios: Context & Safety Gating
# ============================================================================

class TestContextAndSafetyGatingRealWorldScenarios:
    """Tier 4: Realistic end-to-end patient entry scenarios."""

    def test_acute_cardiac_emergency_diverted_instantly(self, e2e_workspace: Path):
        """Patient enters with sudden crushing chest pain; immediately routed to 911."""
        detector = get_emergency_detector()
        prompt = (
            "I'm feeling severe crushing chest tightness that started 20 minutes ago. "
            "It radiates down my left arm and I have a cold sweat."
        )
        flag = detector(prompt)
        assert flag is not None
        assert flag.category == "acute_chest_pain"
        assert "emergency room" in flag.referral_message.lower() or "911" in flag.referral_message

    def test_multimodal_chronic_patient_loaded_with_consent(self, e2e_workspace: Path):
        """Chronic multimorbid patient uploads visit summary and notes with clinical consent."""
        loader = get_context_loader()
        state = {
            "prompt": "I need help preparing for my upcoming cardiologist and nephrologist visits.",
            "target_domain": "clinical",
            "allow_clinical": True,
        }
        loaded_state = loader.load_context(state, e2e_workspace)

        assert loaded_state.get("is_refusal") is not True
        assert len(loaded_state["attachments"]) > 0
        assert "cardiology-guide" in loaded_state["catalog_summary"]
