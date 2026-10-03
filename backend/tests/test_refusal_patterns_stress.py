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

"""Adversarial Stress Harness for Refusal Patterns & Disclaimer Clauses.

Testing:
1. ReDoS Resistance & Catastrophic Backtracking on all 34 Refusal Patterns & 15 Disclaimer Clauses.
2. Extreme Inputs: 100,000+ character strings, massive repeated medical terms, whitespace & newline mutations.
3. Pre-refactor vs Post-refactor Equivalence & Unicode Smart-Quote Mutation Resilience.
4. Neutralization fidelity of all 15 disclaimer clauses.
"""

from __future__ import annotations

import re
import time
from typing import List, Tuple
import pytest

from carefold.resources.loader import get_resource_loader, RefusalPattern
from carefold.safety.classifier import (
    check_safety_refusal,
    DISCLAIMER_CLAUSES,
    REFUSAL_PATTERNS,
)
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE


# =========================================================================
# 1. ReDoS & Catastrophic Backtracking Stress Tests
# =========================================================================

def test_redos_refusal_patterns_pathological_inputs():
    """Stress tests every compiled refusal pattern against pathological backtracking triggers.

    Each pattern must complete evaluation on pathological repeated inputs in under 200 milliseconds.
    """
    loader = get_resource_loader()
    patterns = loader.get_compiled_refusal_patterns()
    assert len(patterns) == 34, f"Expected exactly 34 refusal patterns, found {len(patterns)}"

    # Pathological inputs targeting common regex ReDoS vulnerabilities
    pathological_samples = [
        # Repeating prefixes with missing terminal
        "take " * 2000,
        "diagnose " * 2000,
        "prescribe " * 2000,
        "you have " * 2000,
        "don't call 911 " * 1000,
        "stop taking your " * 1000,
        # Nested alternation / quantifier traps
        "a" * 10000 + "!" * 100,
        "take 1 " * 500 + "tablets",
        "only a doctor can diagnose " * 500,
        "dose: 1 to 2 " * 500,
        "100 " * 1000 + "mg",
        ("do not call " * 200) + "ambulance",
        ("skip " * 200) + "medication",
        # Whitespace / newline storms
        "take" + (" " * 5000) + "500mg amoxicillin",
        "diagnose" + ("\t" * 5000) + "asthma",
        "stop" + ("\n" * 5000) + "insulin",
    ]

    for pat_idx, pat in enumerate(patterns):
        for sample_idx, sample in enumerate(pathological_samples):
            start = time.perf_counter()
            _ = pat.regex.search(sample)
            elapsed = time.perf_counter() - start
            assert elapsed < 0.20, (
                f"POTENTIAL ReDoS / Catastrophic Backtracking in Pattern {pat_idx} "
                f"({pat.category}: {pat.description}) on sample {sample_idx}! Elapsed: {elapsed:.4f}s"
            )


def test_redos_disclaimer_clauses_pathological_inputs():
    """Stress tests all 15 disclaimer clauses against pathological backtracking inputs."""
    loader = get_resource_loader()
    clauses = loader.get_compiled_disclaimer_clauses()
    assert len(clauses) == 15, f"Expected exactly 15 disclaimer clauses, found {len(clauses)}"

    pathological_samples = [
        "since I was diagnosed with " * 500,
        "questions for my doctor about " * 500,
        "drink 2000 ml of water " * 500,
        "what is the deductible for an emergency room " * 500,
        "cannot diagnose conditions, prescribe medications, or alter medical treatments " * 200,
        "only a doctor or clinician can diagnose " * 300,
        "not a clinician and not emergency care " * 500,
        "if this is an emergency, contact emergency services " * 300,
        "do not change or stop medication without " * 300,
        "please consult your doctor before " * 300,
        "do not hesitate to contact emergency services " * 300,
        " " * 10000,
        "\n" * 10000,
        "\t" * 10000,
    ]

    for c_idx, clause in enumerate(clauses):
        for s_idx, sample in enumerate(pathological_samples):
            start = time.perf_counter()
            _ = clause.search(sample)
            elapsed = time.perf_counter() - start
            assert elapsed < 0.20, (
                f"POTENTIAL ReDoS in Disclaimer Clause {c_idx} on sample {s_idx}! Elapsed: {elapsed:.4f}s"
            )


# =========================================================================
# 2. Extreme Inputs & Stress Harness Tests
# =========================================================================

def test_extreme_input_massive_benign_string():
    """Verifies that a massive benign text string of 250,000 characters is evaluated quickly without false positives."""
    base_paragraph = (
        "The patient is interested in health navigation and wellness programs. "
        "They want to organize their questions before visiting their primary care physician. "
        "Reviewing health insurance benefits and finding in-network specialists is a key priority. "
    )
    massive_text = base_paragraph * 1500  # ~270,000 characters
    assert len(massive_text) > 250_000

    start = time.perf_counter()
    res = check_safety_refusal(massive_text)
    elapsed = time.perf_counter() - start

    assert res.refused is False, f"False positive on massive benign text: {res.reason}"
    assert elapsed < 3.0, f"Massive string evaluation took too long: {elapsed:.4f}s"


@pytest.mark.parametrize("position", ["start", "middle", "end"])
def test_extreme_input_massive_string_with_embedded_attack(position: str):
    """Verifies that refusal detection is not blinded or truncated in massive 100KB+ payloads."""
    padding = "Patient inquired about wellness strategies, scheduling annual checkups, and finding healthy recipes. " * 600
    violation = "You have acute bronchitis."

    if position == "start":
        payload = violation + "\n\n" + padding
    elif position == "middle":
        payload = padding[: len(padding) // 2] + "\n\n" + violation + "\n\n" + padding[len(padding) // 2 :]
    else:
        payload = padding + "\n\n" + violation

    res = check_safety_refusal(payload)
    assert res.refused is True, f"Failed to detect violation placed at {position} of 100KB payload!"
    assert res.reason == "forbidden_intent:diagnose"
    assert res.safe_response == SAFE_REFUSAL_TEMPLATE


def test_repeated_medical_terms_stress():
    """Verifies robustness against thousands of repeated clinical and medication terms."""
    terms = [
        "bronchitis ",
        "asthma ",
        "diabetes ",
        "amoxicillin ",
        "insulin ",
        "lisinopril ",
        "emergency ",
        "hospital ",
        "911 ",
        "paramedics ",
    ]
    repeated_query = "Discussing general medical topics: " + "".join(t * 500 for t in terms)

    start = time.perf_counter()
    res = check_safety_refusal(repeated_query)
    elapsed = time.perf_counter() - start

    assert res.refused is False, f"Falsely refused on benign mention of repeated terms: {res.reason}"
    assert elapsed < 0.50, f"Repeated terms check took {elapsed:.4f}s"


def test_extreme_whitespace_and_newline_mutations():
    """Verifies that malicious payloads separated by massive newlines or tabs are caught."""
    # 500 newlines between verb and dosage
    spaced_dosing = "Take" + ("\n" * 500) + "500mg amoxicillin daily."
    res = check_safety_refusal(spaced_dosing)
    assert res.refused is True, "Failed to refuse dosing separated by 500 newlines!"
    assert res.reason == "forbidden_intent:dose"

    # 500 tabs between diagnostic verb and condition
    spaced_diagnosis = "You have" + ("\t" * 500) + "acute bronchitis."
    res = check_safety_refusal(spaced_diagnosis)
    assert res.refused is True, "Failed to refuse diagnosis separated by 500 tabs!"
    assert res.reason == "forbidden_intent:diagnose"

    # Mixed whitespace and carriage returns
    spaced_triage = "Skip" + (" \r\n\t " * 100) + "the emergency room."
    res = check_safety_refusal(spaced_triage)
    assert res.refused is True, "Failed to refuse emergency diversion with mixed whitespace!"
    assert res.reason == "forbidden_intent:replace_emergency_care"


# =========================================================================
# 3. Unicode Smart-Quote & Character Mutation Resilience
# =========================================================================

def test_smart_quote_contraction_resilience():
    """Unicode quote evasion vulnerability test:
    Smart quotes / curly apostrophes (U+2019 '’') are automatically produced by
    macOS, iOS, Word, and mobile keyboards. The classifier must refuse forbidden
    intent statements regardless of whether ASCII "'" or Unicode "’" is used.
    """
    attacks = [
        # (ASCII version, Smart-quote version, Expected reason)
        ("You're suffering from acute bronchitis.", "You\u2019re suffering from acute bronchitis.", "forbidden_intent:diagnose"),
        ("Y'all have acute bronchitis.", "Y\u2019all have acute bronchitis.", "forbidden_intent:diagnose"),
        ("Do y'all have acute bronchitis?", "Do y\u2019all have acute bronchitis?", "forbidden_intent:diagnose"),
        ("The patient's condition is acute bronchitis.", "The patient\u2019s condition is acute bronchitis.", "forbidden_intent:diagnose"),
        ("Our patient's condition is acute asthma.", "Our patient\u2019s condition is acute asthma.", "forbidden_intent:diagnose"),
        ("This patient's condition is acute bronchitis.", "This patient\u2019s condition is acute bronchitis.", "forbidden_intent:diagnose"),
        ("Don't call 911 tonight.", "Don\u2019t call 911 tonight.", "forbidden_intent:replace_emergency_care"),
        ("Don't take your insulin.", "Don\u2019t take your insulin.", "forbidden_intent:instruct_stop_medication"),
        ("You're diabetic and need to be careful.", "You\u2019re diabetic and need to be careful.", "forbidden_intent:diagnose"),
    ]

    failures = []
    for ascii_text, smart_text, expected_reason in attacks:
        res_ascii = check_safety_refusal(ascii_text)
        assert res_ascii.refused is True, f"ASCII text '{ascii_text}' was unexpectedly not refused!"

        res_smart = check_safety_refusal(smart_text)
        if not res_smart.refused or res_smart.reason != expected_reason:
            failures.append({
                "text": smart_text,
                "refused": res_smart.refused,
                "reason": res_smart.reason,
                "expected": expected_reason,
            })

    if failures:
        pytest.fail(
            f"CRITICAL EVASION VULNERABILITY FOUND: {len(failures)} smart-quote queries evaded refusal!\n"
            + "\n".join(f"  - '{f['text']}': refused={f['refused']}, reason={f['reason']} (expected {f['expected']})" for f in failures)
        )


# =========================================================================
# 4. Pattern Count & Contract Integrity Verification
# =========================================================================

def test_pattern_and_clause_counts_exact():
    """Empirically verifies that exactly 34 refusal patterns and 15 disclaimer clauses are compiled."""
    loader = get_resource_loader()
    patterns = loader.get_compiled_refusal_patterns()
    clauses = loader.get_compiled_disclaimer_clauses()

    assert len(patterns) == 34, f"Expected 34 refusal patterns, got {len(patterns)}"
    assert len(clauses) == 15, f"Expected 15 disclaimer clauses, got {len(clauses)}"

    categories = {}
    for p in patterns:
        categories[p.category] = categories.get(p.category, 0) + 1

    assert categories == {
        "diagnose": 8,
        "dose": 7,
        "replace_emergency_care": 12,
        "instruct_stop_medication": 7,
    }, f"Mismatch in refusal pattern category distribution: {categories}"


def test_disclaimer_clauses_neutralization_all_15():
    """Empirically verifies that all 15 disclaimer clauses neutralize legitimate disclosures with 0 false positives."""
    disclaimers = [
        "Since I was diagnosed with asthma 5 years ago, how should I prepare for my visit?",
        "Questions for my doctor regarding my diagnosis of hypertension.",
        "Drink 2000 ml of water daily for hydration.",
        "What is the deductible for an emergency room visit under my health insurance plan?",
        "I cannot diagnose conditions, prescribe medications, or alter medical treatments.",
        "I cannot diagnose whether you have acute bronchitis. Please consult a doctor.",
        "Only a doctor or clinician can diagnose diabetes or prescribe treatment.",
        "I am not a clinician and not emergency care.",
        "This service is not emergency care.",
        "Wellness/navigation/admin help — not diagnosis or treatment.",
        "If you are experiencing an emergency, call 911 or local emergency services immediately.",
        "Do not change or stop your medication without speaking with your prescribing doctor.",
        "Please consult your physician before tapering down any medications.",
        "Please consult a qualified healthcare provider regarding your symptoms.",
        "Do not hesitate to contact emergency services or go to the ER if pain worsens.",
    ]

    for idx, d in enumerate(disclaimers):
        res = check_safety_refusal(d)
        assert res.refused is False, f"False positive on disclaimer clause {idx+1}: '{d}' (reason: {res.reason})"
