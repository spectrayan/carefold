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

"""Test Suite for Emergency Guardrails & Red Flags.

Stress-tests:
1. `check_emergency_red_flags`:
   - Negations (simple vs qualified vs complex negations)
   - Global negation masking vulnerability (negation of symptom A masking acute symptom B)
   - Historical context (benign historical vs acute event with past history)
   - Global historical masking vulnerability ("X years ago" masking acute emergency)
   - Stroke terminology coverage (e.g. "I am having a stroke")
   - Case, whitespace, and formatting permutations
   - Boundary values (empty, None, non-string, large payloads)
2. `InputGuardrailNode`:
   - Clinical consent gating (clinical domain + allow_clinical=False -> refusal)
   - Non-clinical bypass (administrative, wellness, etc.)
   - Precedence hierarchy (emergency > consent > clinical refusal)
   - Strict boolean gating for allow_clinical
   - Message structure extraction and edge cases
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from carefold.safety.emergency import check_emergency_red_flags, EmergencyFlag
from carefold.workflows.nodes.input_guardrail_node import InputGuardrailNode


# ============================================================================
# Section 1: check_emergency_red_flags - Case, Formatting & Boundary Robustness
# ============================================================================

class TestEmergencyRedFlagsFormattingAndBoundaries:
    """Stress tests case normalization, spacing, and edge inputs."""

    @pytest.mark.parametrize("prompt", [
        "CRUSHING CHEST PAIN RADIATING TO JAW",
        "crushing chest pain radiating to jaw",
        "Crushing Chest Pain Radiating To Left Arm",
        "cRuShInG cHeSt PaIn RaDiAtInG tO aRm",
        "FACIAL DROOP AND SLURRED SPEECH",
        "Facial Drooping And Arm Weakness",
        "THROAT IS CLOSING UP AND LIPS ARE SWOLLEN",
    ])
    def test_case_insensitivity(self, prompt: str):
        """Verifies detection is robust against any casing."""
        flag = check_emergency_red_flags(prompt)
        assert flag is not None
        assert flag.detected is True

    @pytest.mark.parametrize("prompt", [
        "crushing  chest   pain  radiating   to  jaw",
        "crushing\nchest\npain\nradiating to arm",
        "crushing\tchest\tpain radiating to arm",
    ])
    def test_whitespace_and_newlines(self, prompt: str):
        """Verifies detection handles irregular whitespace and line breaks."""
        flag = check_emergency_red_flags(prompt)
        assert flag is not None
        assert flag.detected is True

    @pytest.mark.parametrize("invalid_input", [
        None,
        "",
        "   ",
        "\n\t",
        12345,
        {"text": "chest pain"},
        ["chest pain"],
    ])
    def test_invalid_and_empty_inputs(self, invalid_input: any):
        """Verifies non-string or empty inputs return None without exception."""
        flag = check_emergency_red_flags(invalid_input)
        assert flag is None

    def test_large_input_payload(self):
        """Verifies behavior with large input payloads (stress test)."""
        benign_large = "I had a routine checkup. " * 5000
        flag = check_emergency_red_flags(benign_large)
        assert flag is None

        emergency_large = ("Routine note. " * 2000) + "crushing chest pain radiating to arm" + (" More notes. " * 2000)
        flag = check_emergency_red_flags(emergency_large)
        assert flag is not None
        assert flag.category == "acute_chest_pain"


# ============================================================================
# Section 2: check_emergency_red_flags - Negations & False Positives
# ============================================================================

class TestEmergencyRedFlagsNegations:
    """Tests negations to identify false positive triggers and negation patterns."""

    @pytest.mark.parametrize("prompt", [
        "The patient has no chest pain.",
        "Denies chest pain and denies shortness of breath.",
        "Negative for chest pain.",
        "Patient is without shortness of breath.",
        "I do not have chest pain.",
    ])
    def test_standard_negations_pass(self, prompt: str):
        """Verifies standard basic negation patterns return None."""
        flag = check_emergency_red_flags(prompt)
        assert flag is None

    @pytest.mark.parametrize("prompt", [
        "I do not have crushing chest pain.",
        "I don't have severe chest tightness.",
        "Patient denies crushing chest pain.",
        "Negative for severe chest pain.",
    ])
    def test_reproduce_qualified_negation_false_positive_defect(self, prompt: str):
        """When a user negates an emergency with a qualifying adjective (e.g. 'crushing', 'severe'),
        the current regex in NEGATION_PATTERNS fails to match due to rigid whitespace/phrase structure.
        The subsequent CHEST_PATTERNS then catches the adjective+noun and incorrectly generates
        a FALSE POSITIVE emergency red flag for an explicitly negated symptom.
        """
        flag = check_emergency_red_flags(prompt)
        # Document current limitation: flag is unexpectedly NOT None
        assert flag is not None, "Demonstrates current flaw: qualified negation fails to suppress red flag"
        assert flag.category == "acute_chest_pain"

    @pytest.mark.xfail(reason="Qualified negations currently cause false-positive emergency red flags")
    @pytest.mark.parametrize("prompt", [
        "I do not have crushing chest pain.",
        "I don't have severe chest tightness.",
        "Patient denies crushing chest pain.",
        "Negative for severe chest pain.",
    ])
    def test_ideal_qualified_negations_should_return_none(self, prompt: str):
        """Ideal contract: qualified negations should return None."""
        flag = check_emergency_red_flags(prompt)
        assert flag is None


# ============================================================================
# Section 3: check_emergency_red_flags - Global Negation & History Masking
# ============================================================================

class TestEmergencyRedFlagsMaskingVulnerabilities:
    """Stress tests interactions where benign phrases inadvertently suppress acute emergencies."""

    @pytest.mark.parametrize("prompt, expected_emergency_category", [
        (
            "Patient has no chest pain, but has slurred speech and facial droop.",
            "stroke_fast",
        ),
        (
            "No shortness of breath, but experiencing severe crushing chest pain radiating to jaw.",
            "acute_chest_pain",
        ),
        (
            "Negative for chest pain, but throat is closing up and lips are swollen.",
            "anaphylaxis",
        ),
        (
            "I had a stroke 10 years ago, but right now I have severe crushing chest pain radiating to my arm.",
            "acute_chest_pain",
        ),
        (
            "3 months ago I had knee surgery, but today my face is drooping and speech is slurred.",
            "stroke_fast",
        ),
        (
            "2 years ago my father died of a heart attack, and right now I have crushing chest pain radiating to my neck.",
            "acute_chest_pain",
        ),
    ])
    def test_reproduce_global_masking_false_negative_defect(self, prompt: str, expected_emergency_category: str):
        """`check_emergency_red_flags` evaluates NEGATION_PATTERNS globally across the entire string.
        If a negation pattern matches ANY symptom (e.g. 'no chest pain') or ANY temporal phrase
        ('years ago', 'months ago') anywhere in the prompt, Step 1 returns None immediately.
        This completely MASKS an acute, life-threatening emergency in the same prompt.
        """
        flag = check_emergency_red_flags(prompt)
        # Document current limitation: returns None despite active emergency
        assert flag is None, "Demonstrates current flaw: global negation suppresses acute emergency detection"

    @pytest.mark.xfail(reason="Global negation/temporal matching masks real co-occurring acute emergencies")
    @pytest.mark.parametrize("prompt, expected_emergency_category", [
        (
            "Patient has no chest pain, but has slurred speech and facial droop.",
            "stroke_fast",
        ),
        (
            "No shortness of breath, but experiencing severe crushing chest pain radiating to jaw.",
            "acute_chest_pain",
        ),
        (
            "Negative for chest pain, but throat is closing up and lips are swollen.",
            "anaphylaxis",
        ),
        (
            "I had a stroke 10 years ago, but right now I have severe crushing chest pain radiating to my arm.",
            "acute_chest_pain",
        ),
        (
            "3 months ago I had knee surgery, but today my face is drooping and speech is slurred.",
            "stroke_fast",
        ),
        (
            "2 years ago my father died of a heart attack, and right now I have crushing chest pain radiating to my neck.",
            "acute_chest_pain",
        ),
    ])
    def test_ideal_co_occurring_emergencies_should_be_detected(self, prompt: str, expected_emergency_category: str):
        """Ideal contract: active acute emergency symptoms must be detected even if other symptoms are negated."""
        flag = check_emergency_red_flags(prompt)
        assert flag is not None
        assert flag.category == expected_emergency_category


# ============================================================================
# Section 4: check_emergency_red_flags - Terminology Gaps (Stroke)
# ============================================================================

class TestEmergencyRedFlagsTerminologyGaps:
    """Tests direct emergency phrasing that is missing from regex lists."""

    @pytest.mark.parametrize("prompt", [
        "I am having a stroke",
        "Help, my husband is having a stroke",
        "Call an ambulance, acute stroke",
        "I think I'm having a stroke right now",
    ])
    def test_reproduce_direct_stroke_keyword_gap(self, prompt: str):
        """The keyword 'stroke' appears only in NEGATION_PATTERNS to suppress historical mentions.
        It is completely absent from STROKE_PATTERNS. Thus, a direct statement like
        'I am having a stroke' is not caught by `check_emergency_red_flags`.
        """
        flag = check_emergency_red_flags(prompt)
        # Document current limitation: returns None
        assert flag is None, "Demonstrates current flaw: affirmative 'stroke' keyword is not detected"

    @pytest.mark.xfail(reason="Direct affirmative 'stroke' keyword is omitted from STROKE_PATTERNS")
    @pytest.mark.parametrize("prompt", [
        "I am having a stroke",
        "Help, my husband is having a stroke",
        "Call an ambulance, acute stroke",
        "I think I'm having a stroke right now",
    ])
    def test_ideal_direct_stroke_keyword_should_trigger(self, prompt: str):
        """Ideal contract: direct acute stroke statements should trigger stroke_fast."""
        flag = check_emergency_red_flags(prompt)
        assert flag is not None
        assert flag.category == "stroke_fast"


# ============================================================================
# Section 5: InputGuardrailNode - Clinical Consent Gating & Routing
# ============================================================================

class TestInputGuardrailNodeConsentGating:
    """Verifies consent gating across domains, truthiness, and message types."""

    @pytest.mark.asyncio
    async def test_unconsented_clinical_request_refused(self):
        """Clinical request with allow_clinical=False must refuse with clinical_consent_required."""
        node = InputGuardrailNode()
        state = {
            "target_domain": "clinical",
            "allow_clinical": False,
            "messages": [{"role": "user", "content": "How should I treat hypertension?"}],
        }
        res = await node.execute(state)
        assert res["is_refusal"] is True
        assert res["refused"] is True
        assert res["refusal_reason"] == "clinical_consent_required"
        assert res["next_step"] == "refusal"
        assert res["tool_calls"] == []

    @pytest.mark.asyncio
    async def test_consented_clinical_request_proceeds(self):
        """Clinical request with allow_clinical=True must proceed to supervisor."""
        node = InputGuardrailNode()
        state = {
            "target_domain": "clinical",
            "allow_clinical": True,
            "messages": [{"role": "user", "content": "Help me prepare questions for my doctor."}],
        }
        res = await node.execute(state)
        assert res["is_refusal"] is False
        assert res["refused"] is False
        assert res["refusal_reason"] is None
        assert res["next_step"] == "supervisor"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("domain", [
        "administrative",
        "wellness",
        "navigation",
        "education",
        "general",
        None,
    ])
    async def test_non_clinical_domains_bypass_consent(self, domain: str | None):
        """Non-clinical queries proceed even if allow_clinical is False."""
        node = InputGuardrailNode()
        state = {
            "target_domain": domain,
            "allow_clinical": False,
            "messages": [{"role": "user", "content": "What is my insurance deductible?"}],
        }
        res = await node.execute(state)
        assert res["is_refusal"] is False
        assert res["refused"] is False
        assert res["next_step"] == "supervisor"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("falsy_val", [
        False,
        None,
        "",
        0,
        "false",
        "true",  # string "true" must NOT be accepted as boolean True
        1,       # integer 1 must NOT be accepted as boolean True
        [],
        {},
    ])
    async def test_strict_boolean_consent_requirement(self, falsy_val: any):
        """Ensures allow_clinical strictly requires boolean True."""
        node = InputGuardrailNode()
        state = {
            "target_domain": "clinical",
            "allow_clinical": falsy_val,
            "messages": [{"role": "user", "content": "Can you check my insulin schedule?"}],
        }
        res = await node.execute(state)
        assert res["is_refusal"] is True
        assert res["refusal_reason"] == "clinical_consent_required"

    @pytest.mark.asyncio
    async def test_domain_field_fallback(self):
        """Verifies state['domain'] is respected when state['target_domain'] is absent."""
        node = InputGuardrailNode()
        state = {
            "domain": "clinical",
            "allow_clinical": False,
            "messages": [{"role": "user", "content": "Can you evaluate my lab results?"}],
        }
        res = await node.execute(state)
        assert res["is_refusal"] is True
        assert res["refusal_reason"] == "clinical_consent_required"

    @pytest.mark.asyncio
    async def test_emergency_takes_precedence_over_unconsented_clinical(self):
        """Emergency red-flags must take priority over clinical consent gating."""
        node = InputGuardrailNode()
        state = {
            "target_domain": "clinical",
            "allow_clinical": False,
            "messages": [{"role": "user", "content": "Crushing chest pain radiating to arm"}],
        }
        res = await node.execute(state)
        assert res["is_refusal"] is True
        assert res["refusal_reason"] == "emergency_red_flag"
        assert res["emergency_red_flags"] is not None
        assert "911" in res["refusal_message"]

    @pytest.mark.asyncio
    async def test_message_extraction_types(self):
        """Verifies input guardrail extracts prompt from HumanMessage, dict, or state['prompt']."""
        node = InputGuardrailNode()

        # HumanMessage extraction
        res1 = await node.execute({
            "target_domain": "administrative",
            "messages": [HumanMessage(content="What are my copays?")],
        })
        assert res1["is_refusal"] is False

        # Fallback to state['prompt']
        res2 = await node.execute({
            "target_domain": "administrative",
            "prompt": "What are my copays?",
        })
        assert res2["is_refusal"] is False

        # Empty state handling
        res3 = await node.execute({})
        assert res3["is_refusal"] is False
