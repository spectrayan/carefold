# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Golden Test Suite for Vitals Red Flags Safety Engine.

Verifies:
1. 100% recall on symptomatic hypertensive crises -> 'Call 911 immediately'.
2. 100% recall on asymptomatic hypertensive crises -> 5-min recheck & clinician directive.
3. 100% recall on severe hypoxemia (SpO2 < 90%) -> urgent evaluation directive.
4. 100% recall on severe hypoglycemia (< 54 mg/dL or mmol/L equiv) -> Rule of 15 directive.
5. 100% recall on symptomatic hypotension (< 90/60 with symptoms) -> clinical referral.
6. Zero false negatives across 44+ synthetic scenarios.
7. Zero false positives on benign controls and boundary thresholds.
8. Compatibility with FHIR R4 observations and EmergencyRedFlag dataclass unpacking.
"""

from typing import Any, Dict, List, Optional
import pytest

from carefold.safety.vitals import VitalsEmergencyFlag, check_vitals_red_flags
from tests.e2e.contracts_clinical_domain import EmergencyRedFlag


# ============================================================================
# Section 1: Hypertensive Crisis — Symptomatic (Non-Suppressible Call 911)
# ============================================================================

@pytest.mark.parametrize(
    "vitals, symptoms, expected_symptom",
    [
        ({"systolic": 180, "diastolic": 120}, ["chest pain"], "chest pain"),
        ({"systolic": 181, "diastolic": 121}, ["shortness of breath"], "shortness of breath"),
        ({"systolic": 220, "diastolic": 130}, ["crushing chest pressure"], "crushing chest pressure"),
        ({"systolic": 200, "diastolic": 110}, ["severe back pain"], "severe back pain"),
        ({"systolic": 190, "diastolic": 125}, ["unilateral numbness"], "unilateral numbness"),
        ({"systolic": 195, "diastolic": 115}, ["arm weakness"], "arm weakness"),
        ({"systolic": 185, "diastolic": 122}, ["acute vision loss"], "acute vision loss"),
        ({"systolic": 210, "diastolic": 140}, ["dysarthria"], "dysarthria"),
        ({"systolic": 185, "diastolic": 85}, ["chest tightness"], "chest tightness"),
        ({"systolic": 140, "diastolic": 125}, ["difficulty speaking"], "difficulty speaking"),
    ],
)
def test_hypertensive_crisis_symptomatic_triggers_911(
    vitals: Dict[str, Any], symptoms: List[str], expected_symptom: str
):
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is True
    assert flag.detected is True
    assert flag.category == "bp_crisis_symptomatic"
    assert flag.severity == "emergency"
    assert "Call 911" in flag.directive
    assert flag.prompt_recheck is False
    assert flag["category"] == "bp_crisis_symptomatic"

    # Dataclass unpacking parity
    unpacked = EmergencyRedFlag(**flag)
    assert unpacked.triggered is True
    assert unpacked.category == "bp_crisis_symptomatic"


# ============================================================================
# Section 2: Hypertensive Crisis — Asymptomatic (Prompt Clinician Directive)
# ============================================================================

@pytest.mark.parametrize(
    "vitals, symptoms",
    [
        ({"systolic": 180, "diastolic": 120}, []),
        ({"systolic": 180, "diastolic": 80}, []),
        ({"systolic": 130, "diastolic": 120}, []),
        ({"systolic": 185, "diastolic": 115}, []),
        ({"systolic": 200, "diastolic": 105}, None),
        ({"systolic": 210, "diastolic": 125}, []),
        ({"systolic": 190, "diastolic": 120}, ["mild headache"]),
        ({"systolic": 182, "diastolic": 122}, ["fatigue"]),
    ],
)
def test_hypertensive_crisis_asymptomatic_triggers_prompt_recheck(
    vitals: Dict[str, Any], symptoms: Optional[List[str]]
):
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is True
    assert flag.category == "bp_crisis_asymptomatic"
    assert flag.severity == "urgent"
    assert flag.prompt_recheck is True
    assert "recheck" in flag.directive
    assert "contact your clinician promptly today" in flag.directive.lower()

    unpacked = EmergencyRedFlag(**flag)
    assert unpacked.triggered is True
    assert unpacked.category == "bp_crisis_asymptomatic"


# ============================================================================
# Section 3: Severe Hypoxemia (SpO2 < 90%)
# ============================================================================

@pytest.mark.parametrize(
    "spo2_val",
    [89.9, 89.0, 87.0, 85.0, 70.0, 55.0],
)
def test_severe_hypoxemia_under_90_triggers_emergency(spo2_val: float):
    flag = check_vitals_red_flags({"spo2": spo2_val})
    assert flag.triggered is True
    assert flag.category == "severe_hypoxemia"
    assert flag.severity == "emergency"
    assert "SpO2 is below 90%" in flag.directive
    assert flag.prompt_recheck is False

    unpacked = EmergencyRedFlag(**flag)
    assert unpacked.triggered is True
    assert unpacked.category == "severe_hypoxemia"


# ============================================================================
# Section 4: Severe Hypoglycemia (Glucose < 54 mg/dL)
# ============================================================================

@pytest.mark.parametrize(
    "vitals_input",
    [
        {"blood_glucose": 53.9},
        {"blood_glucose": 50.0},
        {"blood_glucose": 48.0},
        {"blood_glucose": 25.0},
        {"blood_glucose": 2.9, "unit": "mmol/L"},
        {"blood_glucose": 2.5, "unit": "mmol/L"},
    ],
)
def test_severe_hypoglycemia_triggers_rule_of_15(vitals_input: Dict[str, Any]):
    flag = check_vitals_red_flags(vitals_input)
    assert flag.triggered is True
    assert flag.category == "severe_hypoglycemia"
    assert flag.severity == "urgent"
    assert "Rule of 15" in flag.directive
    assert flag.prompt_recheck is True

    unpacked = EmergencyRedFlag(**flag)
    assert unpacked.triggered is True
    assert unpacked.category == "severe_hypoglycemia"


# ============================================================================
# Section 5: Symptomatic Hypotension (< 90/60 with symptoms)
# ============================================================================

@pytest.mark.parametrize(
    "vitals, symptoms",
    [
        ({"systolic": 89, "diastolic": 59}, ["dizziness"]),
        ({"systolic": 84, "diastolic": 56}, ["syncope"]),
        ({"systolic": 75, "diastolic": 45}, ["fainting"]),
        ({"systolic": 88, "diastolic": 65}, ["lightheadedness"]),
        ({"systolic": 100, "diastolic": 58}, ["presyncope"]),
        ({"systolic": 70, "diastolic": 40}, ["feeling faint"]),
    ],
)
def test_symptomatic_hypotension_triggers_referral(vitals: Dict[str, Any], symptoms: List[str]):
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is True
    assert flag.category == "symptomatic_hypotension"
    assert flag.severity == "urgent"
    assert "dizziness or syncope" in flag.directive
    assert flag.prompt_recheck is False

    unpacked = EmergencyRedFlag(**flag)
    assert unpacked.triggered is True
    assert unpacked.category == "symptomatic_hypotension"


# ============================================================================
# Section 6: Negative Controls & Exact Boundary Non-Triggers
# ============================================================================

@pytest.mark.parametrize(
    "vitals, symptoms",
    [
        ({"systolic": 179, "diastolic": 119}, []),
        ({"systolic": 90, "diastolic": 60}, ["dizziness"]),
        ({"systolic": 85, "diastolic": 55}, []),  # asymptomatic hypotension
        ({"spo2": 90.0}, []),
        ({"spo2": 91.0}, []),
        ({"spo2": 98.0}, []),
        ({"blood_glucose": 54.0}, []),
        ({"blood_glucose": 3.1, "unit": "mmol/L"}, []),
        ({"systolic": 118, "diastolic": 76, "spo2": 98.0, "blood_glucose": 95.0}, []),
    ],
)
def test_negative_controls_produce_zero_false_positives(
    vitals: Dict[str, Any], symptoms: List[str]
):
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is False
    assert flag.detected is False
    assert flag.severity == "normal"
    assert flag.category is None
    assert bool(flag) is False

    unpacked = EmergencyRedFlag(**flag)
    assert unpacked.triggered is False


# ============================================================================
# Section 7: FHIR R4 Observation Resource Integration
# ============================================================================

def test_fhir_r4_blood_pressure_observation_parsing():
    """Verifies that nested FHIR R4 LOINC 85354-9 components are parsed correctly."""
    fhir_bp = {
        "resourceType": "Observation",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}]},
        "component": [
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                "valueQuantity": {"value": 195, "unit": "mmHg"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                "valueQuantity": {"value": 125, "unit": "mmHg"},
            },
        ],
    }
    flag = check_vitals_red_flags(fhir_bp, reported_symptoms=["chest pain"])
    assert flag.triggered is True
    assert flag.category == "bp_crisis_symptomatic"
    assert flag.severity == "emergency"


# ============================================================================
# Section 8: Single-Component Blood Pressure Evaluation (AU-32 / Verification)
# ============================================================================

@pytest.mark.parametrize(
    "vitals, symptoms, expected_category, expected_severity, expected_recheck, expected_directive_snippet",
    [
        # Isolated Systolic Crisis (>= 180)
        ({"systolic": 210}, ["chest pain"], "bp_crisis_symptomatic", "emergency", False, "Call 911"),
        ({"systolic": 195}, [], "bp_crisis_asymptomatic", "urgent", True, "Rest quietly for 5 minutes"),
        ({"systolic": 180}, None, "bp_crisis_asymptomatic", "urgent", True, "recheck"),
        # Isolated Diastolic Crisis (>= 120)
        ({"diastolic": 130}, ["shortness of breath"], "bp_crisis_symptomatic", "emergency", False, "Call 911"),
        ({"diastolic": 125}, [], "bp_crisis_asymptomatic", "urgent", True, "Rest quietly for 5 minutes"),
        ({"diastolic": 120}, None, "bp_crisis_asymptomatic", "urgent", True, "recheck"),
        # Isolated Hypotension (< 90 systolic or < 60 diastolic) with symptoms
        ({"systolic": 75}, ["syncope"], "symptomatic_hypotension", "urgent", False, "dizziness or syncope"),
        ({"diastolic": 45}, ["dizziness"], "symptomatic_hypotension", "urgent", False, "dizziness or syncope"),
        ({"systolic": 85}, ["feeling faint"], "symptomatic_hypotension", "urgent", False, "dizziness or syncope"),
    ],
)
def test_single_component_bp_red_flags(
    vitals: Dict[str, Any],
    symptoms: Optional[List[str]],
    expected_category: str,
    expected_severity: str,
    expected_recheck: bool,
    expected_directive_snippet: str,
):
    """Verifies 100% recall on single-component blood pressure readings without paired values."""
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is True
    assert flag.category == expected_category
    assert flag.severity == expected_severity
    assert flag.prompt_recheck is expected_recheck
    assert expected_directive_snippet.lower() in flag.directive.lower()

    unpacked = EmergencyRedFlag(**flag)
    assert unpacked.triggered is True
    assert unpacked.category == expected_category


@pytest.mark.parametrize(
    "vitals, symptoms",
    [
        ({"systolic": 120}, []),
        ({"systolic": 135}, ["headache"]),
        ({"diastolic": 75}, []),
        ({"diastolic": 85}, None),
        ({"systolic": 85}, []),  # Asymptomatic isolated systolic hypotension
        ({"diastolic": 55}, []),  # Asymptomatic isolated diastolic hypotension
    ],
)
def test_single_component_bp_negative_controls(vitals: Dict[str, Any], symptoms: Optional[List[str]]):
    """Verifies that non-crisis single-component readings do not trigger false alarms."""
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is False
    assert flag.severity == "normal"
    assert flag.category is None


# ============================================================================
# Section 9: Symptom Negation Filtering (AU-32 / Verification)
# ============================================================================

@pytest.mark.parametrize(
    "vitals, symptoms, expected_category, expected_severity, expected_recheck",
    [
        # Hypertensive crisis with explicitly denied symptoms -> Must remain ASYMPTOMATIC (urgent), NOT 911
        ({"systolic": 180, "diastolic": 110}, ["patient denies chest pain"], "bp_crisis_asymptomatic", "urgent", True),
        ({"systolic": 180, "diastolic": 110}, ["no shortness of breath"], "bp_crisis_asymptomatic", "urgent", True),
        ({"systolic": 180, "diastolic": 110}, ["denies headache"], "bp_crisis_asymptomatic", "urgent", True),
        ({"systolic": 190, "diastolic": 115}, ["negative for chest pain"], "bp_crisis_asymptomatic", "urgent", True),
        ({"systolic": 195, "diastolic": 120}, ["without difficulty breathing"], "bp_crisis_asymptomatic", "urgent", True),
        ({"systolic": 200, "diastolic": 115}, ["never had chest pressure"], "bp_crisis_asymptomatic", "urgent", True),
    ],
)
def test_hypertensive_crisis_symptom_negation_prevents_false_911(
    vitals: Dict[str, Any],
    symptoms: List[str],
    expected_category: str,
    expected_severity: str,
    expected_recheck: bool,
):
    """Verifies that negated symptoms prevent unwarranted 911 escalations."""
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is True
    assert flag.category == expected_category
    assert flag.severity == expected_severity
    assert flag.prompt_recheck is expected_recheck
    assert "Call 911" not in flag.directive
    assert "rest quietly for 5 minutes" in flag.directive.lower()


@pytest.mark.parametrize(
    "vitals, symptoms",
    [
        # Hypotension with negated dizziness/syncope -> Must NOT trigger symptomatic_hypotension
        ({"systolic": 89, "diastolic": 59}, ["no dizziness"]),
        ({"systolic": 89, "diastolic": 59}, ["patient denies dizziness"]),
        ({"systolic": 89, "diastolic": 59}, ["without syncope"]),
        ({"systolic": 85, "diastolic": 55}, ["negative for lightheadedness"]),
        ({"systolic": 80, "diastolic": 50}, ["denies feeling faint"]),
    ],
)
def test_hypotension_negation_prevents_false_symptomatic_flag(
    vitals: Dict[str, Any], symptoms: List[str]
):
    """Verifies that negated symptoms in low BP patients do not trigger clinical referral."""
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is False
    assert flag.severity == "normal"
    assert flag.category is None


def test_mixed_negation_with_affirmative_acute_symptom():
    """Verifies that if one symptom is denied but another is affirmed, emergency triggers."""
    vitals = {"systolic": 195, "diastolic": 125}
    symptoms = ["patient denies chest pain, but reports acute shortness of breath"]
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is True
    assert flag.category == "bp_crisis_symptomatic"
    assert flag.severity == "emergency"
    assert "Call 911" in flag.directive


# ============================================================================
# Section 10: Multi-Vital Priority Ranking & Severity Preemption (AU-32)
# ============================================================================

@pytest.mark.parametrize(
    "vitals, symptoms, expected_category, expected_severity, prohibited_snippet",
    [
        # Asymptomatic BP Crisis (urgent) + Severe Hypoxemia SpO2 70% (emergency) -> Hypoxemia must win
        (
            {"systolic": 185, "diastolic": 115, "spo2": 70.0},
            [],
            "severe_hypoxemia",
            "emergency",
            "Rest quietly for 5 minutes",
        ),
        # Symptomatic Hypotension (urgent) + Severe Hypoxemia SpO2 75% (emergency) -> Hypoxemia must win
        (
            {"systolic": 84, "diastolic": 56, "spo2": 75.0},
            ["dizziness"],
            "severe_hypoxemia",
            "emergency",
            "Sit or lie down",
        ),
        # Asymptomatic BP Crisis (urgent) + Severe Hypoglycemia (urgent) -> Hypoglycemia takes priority
        (
            {"systolic": 190, "diastolic": 120, "blood_glucose": 45.0},
            [],
            "severe_hypoglycemia",
            "urgent",
            "Rest quietly for 5 minutes",
        ),
        # Severe Hypoxemia SpO2 85% (emergency) + Severe Hypoglycemia (urgent) -> Hypoxemia must win
        (
            {"systolic": 118, "diastolic": 76, "spo2": 88.0, "blood_glucose": 48.0},
            [],
            "severe_hypoxemia",
            "emergency",
            "Rule of 15",
        ),
    ],
)
def test_multi_vital_priority_ranking(
    vitals: Dict[str, Any],
    symptoms: List[str],
    expected_category: str,
    expected_severity: str,
    prohibited_snippet: str,
):
    """Verifies that life-threatening emergencies preempt lower severity directives."""
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is True
    assert flag.category == expected_category
    assert flag.severity == expected_severity
    assert prohibited_snippet.lower() not in flag.directive.lower()


def test_multi_vital_priority_dual_emergency_combines_directives():
    """Verifies that co-occurring emergency conditions combine critical instructions."""
    flag = check_vitals_red_flags(
        {"systolic": 200, "diastolic": 130, "spo2": 75.0},
        reported_symptoms=["chest pain"],
    )
    assert flag.triggered is True
    assert flag.category == "bp_crisis_symptomatic"
    assert flag.severity == "emergency"
    assert "Call 911" in flag.directive
    assert "SpO2 is below 90%" in flag.directive


# ============================================================================
# Section 11: Malformed and Non-Numeric Input Resilience (AU-32 / Verification)
# ============================================================================

@pytest.mark.parametrize(
    "vitals, expected_triggered, expected_category, expected_severity",
    [
        # Non-numeric string inputs that cannot be parsed
        ({"systolic": "high", "diastolic": 80}, False, None, "normal"),
        ({"systolic": "high", "diastolic": 130}, True, "bp_crisis_asymptomatic", "urgent"),
        ({"spo2": "null"}, False, None, "normal"),
        ({"blood_glucose": "invalid"}, False, None, "normal"),
        ({"blood_glucose": "fifty"}, False, None, "normal"),
        # Valid numeric strings that should cleanly parse
        ({"systolic": "210", "diastolic": "130"}, True, "bp_crisis_asymptomatic", "urgent"),
        ({"spo2": "85.0"}, True, "severe_hypoxemia", "emergency"),
        # Nulls, empty strings, and complex invalid types
        ({"systolic": None, "diastolic": 125}, True, "bp_crisis_asymptomatic", "urgent"),
        ({"systolic": "", "diastolic": ""}, False, None, "normal"),
        ({"systolic": [180], "spo2": {"val": 70}}, False, None, "normal"),
        ({}, False, None, "normal"),
    ],
)
def test_malformed_input_graceful_handling(
    vitals: Dict[str, Any],
    expected_triggered: bool,
    expected_category: Optional[str],
    expected_severity: str,
):
    """Verifies that non-numeric, None, or malformed inputs do not raise unhandled exceptions."""
    flag = check_vitals_red_flags(vitals)
    assert flag.triggered is expected_triggered
    assert flag.category == expected_category
    assert flag.severity == expected_severity


# ============================================================================
# Section 12: Verification Boundary Control Verification (T01 – T15)
# ============================================================================

@pytest.mark.parametrize(
    "test_id, vitals, symptoms, expected_triggered, expected_category, expected_severity",
    [
        ("T01", {"systolic": 179, "diastolic": 119}, [], False, None, "normal"),
        ("T02", {"systolic": 180, "diastolic": 119}, [], True, "bp_crisis_asymptomatic", "urgent"),
        ("T03", {"systolic": 179, "diastolic": 120}, [], True, "bp_crisis_asymptomatic", "urgent"),
        ("T04", {"systolic": 220, "diastolic": 140}, [], True, "bp_crisis_asymptomatic", "urgent"),
        ("T05", {"systolic": 220, "diastolic": 140}, ["chest pain"], True, "bp_crisis_symptomatic", "emergency"),
        ("T06", {"spo2": 90.0}, [], False, None, "normal"),
        ("T07", {"spo2": 89.0}, [], True, "severe_hypoxemia", "emergency"),
        ("T08", {"spo2": 75.0}, [], True, "severe_hypoxemia", "emergency"),
        ("T09", {"blood_glucose": 55.0}, [], False, None, "normal"),
        ("T10", {"blood_glucose": 54.0}, [], False, None, "normal"),
        ("T11", {"blood_glucose": 53.0}, [], True, "severe_hypoglycemia", "urgent"),
        ("T12", {"blood_glucose": 35.0}, [], True, "severe_hypoglycemia", "urgent"),
        ("T13", {"systolic": 89, "diastolic": 59}, ["dizziness"], True, "symptomatic_hypotension", "urgent"),
        ("T14", {"systolic": 89, "diastolic": 59}, [], False, None, "normal"),
        ("T15", {"systolic": 91, "diastolic": 61}, ["dizziness"], False, None, "normal"),
    ],
)
def test_vitals_t01_t15_boundary_controls(
    test_id: str,
    vitals: Dict[str, Any],
    symptoms: List[str],
    expected_triggered: bool,
    expected_category: Optional[str],
    expected_severity: str,
):
    """Verifies all 15 clinical boundary controls T01 through T15."""
    flag = check_vitals_red_flags(vitals, reported_symptoms=symptoms)
    assert flag.triggered is expected_triggered, f"{test_id} triggered mismatch"
    assert flag.category == expected_category, f"{test_id} category mismatch"
    assert flag.severity == expected_severity, f"{test_id} severity mismatch"
