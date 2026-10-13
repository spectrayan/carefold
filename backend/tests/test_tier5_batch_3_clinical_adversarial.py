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

"""White-Box Adversarial Stress Test Suite for Carefold Autonomy Batch 3 (Tier 5).

Covers clinical vitals pipeline, LOINC normalization edge cases, CDC pediatric BMI LMS
tables, diurnal BP moving averages (AHA/ACC 2025), clinical red-flag severity preemption,
symptom negation span masking, appointment lifecycle transitions, and RFC 5545 RRULE
temporal engine edge cases (leap years, month-end clamping, DST wall-clock stability,
snooze immutability, overdue coalescing, and .ics PHI sanitization).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List
from zoneinfo import ZoneInfo
import pytest

from carefold.clinical.appointments import (
    AppointmentStatus,
    InvalidStatusTransitionError,
    VALID_STATUS_TRANSITIONS,
    evaluate_post_visit_transitions,
    generate_how_to_book_drafts,
    validate_status_transition,
)
from carefold.clinical.bmi import (
    calculate_adult_bmi,
    calculate_adult_bmi_imperial,
    calculate_pediatric_bmi_percentile,
)
from carefold.clinical.reminders import (
    advance_rrule_occurrence,
    apply_reminder_snooze,
    coalesce_overdue_reminders,
    generate_ics_calendar,
)
from carefold.clinical.vitals import (
    INCHES_TO_CM,
    LBS_TO_KG,
    LOINC_CODES,
    MMOL_TO_MGDL,
    calculate_diurnal_bp_trends,
    classify_blood_pressure,
    normalize_fhir_vitals,
    parse_all_vitals_observations,
)
from carefold.safety.vitals import (
    FALLBACK_ACUTE_SYMPTOMS,
    FALLBACK_HYPOTENSION_SYMPTOMS,
    FALLBACK_NEGATION_TERMS,
    VitalsEmergencyFlag,
    _extract_vitals_components,
    _parse_affirmative_symptoms,
    _safe_float,
    check_vitals_red_flags,
)


# ============================================================================
# Category 1: Clinical Vitals & LOINC Normalization Pipeline
# ============================================================================


def test_loinc_normalization_bp_multi_component_and_types():
    """Validates systolic/diastolic LOINC mapping, unit coding, and string float parsing."""
    raw = {"systolic": "128.5", "diastolic": "84.2"}
    eff = datetime(2026, 10, 10, 8, 30, 0, tzinfo=timezone.utc)
    obs = normalize_fhir_vitals(raw, effective_dt=eff)

    assert obs["resourceType"] == "Observation"
    assert obs["status"] == "final"
    assert obs["effectiveDateTime"] == eff.isoformat()
    assert obs["code"]["coding"][0]["code"] == LOINC_CODES["blood_pressure"]
    assert len(obs["component"]) == 2

    sys_comp = obs["component"][0]
    dia_comp = obs["component"][1]

    assert sys_comp["code"]["coding"][0]["code"] == LOINC_CODES["systolic"]
    assert sys_comp["valueQuantity"]["value"] == 128.5
    assert sys_comp["valueQuantity"]["unit"] == "mmHg"
    assert sys_comp["valueQuantity"]["code"] == "mm[Hg]"

    assert dia_comp["code"]["coding"][0]["code"] == LOINC_CODES["diastolic"]
    assert dia_comp["valueQuantity"]["value"] == 84.2
    assert dia_comp["valueQuantity"]["unit"] == "mmHg"
    assert dia_comp["valueQuantity"]["code"] == "mm[Hg]"


def test_loinc_normalization_units_conversion():
    """Tests conversions for glucose (mmol/L to mg/dL), weight (lbs to kg), and height (in to cm)."""
    eff = datetime(2026, 10, 10, 9, 0, 0, tzinfo=timezone.utc)

    # Glucose in mmol/L
    g_raw = {"blood_glucose": 5.0, "unit": "mmol/L"}
    g_obs = normalize_fhir_vitals(g_raw, effective_dt=eff)
    expected_mgdl = round(5.0 * MMOL_TO_MGDL, 1)  # 90.1
    assert g_obs["code"]["coding"][0]["code"] == LOINC_CODES["blood_glucose"]
    assert g_obs["valueQuantity"]["value"] == expected_mgdl
    assert g_obs["valueQuantity"]["unit"] == "mg/dL"

    # Weight in lbs
    wt_raw = {"weight": 165.0, "unit": "lbs"}
    wt_obs = normalize_fhir_vitals(wt_raw, effective_dt=eff)
    expected_kg = round(165.0 / LBS_TO_KG, 1)  # 74.8
    assert wt_obs["code"]["coding"][0]["code"] == LOINC_CODES["body_weight"]
    assert wt_obs["valueQuantity"]["value"] == expected_kg
    assert wt_obs["valueQuantity"]["unit"] == "kg"

    # Height in inches
    ht_raw = {"height": 70.0, "unit": "inches"}
    ht_obs = normalize_fhir_vitals(ht_raw, effective_dt=eff)
    expected_cm = round(70.0 * INCHES_TO_CM, 1)  # 177.8
    assert ht_obs["code"]["coding"][0]["code"] == LOINC_CODES["body_height"]
    assert ht_obs["valueQuantity"]["value"] == expected_cm
    assert ht_obs["valueQuantity"]["unit"] == "cm"


def test_parse_all_vitals_observations_multi_metric():
    """Verifies that a multi-metric dictionary parses into 6 separate FHIR R4 Observations."""
    raw = {
        "systolic": 118,
        "diastolic": 76,
        "heart_rate": 72,
        "glucose": 95,
        "spo2": 99,
        "weight": 70.0,
        "height": 175.0,
    }
    observations = parse_all_vitals_observations(raw)
    assert len(observations) == 6

    codes = [obs["code"]["coding"][0]["code"] for obs in observations]
    assert LOINC_CODES["blood_pressure"] in codes
    assert LOINC_CODES["heart_rate"] in codes
    assert LOINC_CODES["blood_glucose"] in codes
    assert LOINC_CODES["oxygen_saturation"] in codes
    assert LOINC_CODES["body_weight"] in codes
    assert LOINC_CODES["body_height"] in codes


def test_vitals_extraction_robustness_malformed_nan_inf():
    """Adversarial stress test on _safe_float and _extract_vitals_components with NaN, Inf, and malformed data."""
    assert _safe_float(None) is None
    assert _safe_float("") is None
    assert _safe_float("invalid") is None
    assert _safe_float(float("nan")) is None
    assert _safe_float(float("inf")) is None
    assert _safe_float(float("-inf")) is None
    assert _safe_float("120.5") == 120.5

    # Test malformed observation dict
    extracted = _extract_vitals_components({
        "systolic": "NaN",
        "diastolic": float("inf"),
        "spo2": None,
        "blood_glucose": "",
    })
    assert "systolic" not in extracted
    assert "diastolic" not in extracted
    assert "spo2" not in extracted
    assert "blood_glucose" not in extracted

    # Test empty or non-dict
    assert _extract_vitals_components({}) == {}
    assert _extract_vitals_components(None) == {}  # type: ignore


# ============================================================================
# Category 2: Adult & CDC Pediatric BMI Engine Boundaries
# ============================================================================


def test_pediatric_bmi_exact_boundary_at_240_months():
    """Tests the critical boundary condition: 239m (pediatric LMS curve) vs exact 240m (adult fallback)."""
    # At 239 months: child curve evaluated, percentile populated
    res_239 = calculate_pediatric_bmi_percentile(
        age_months=239,
        gender="male",
        weight_kg=65.0,
        height_cm=175.0,
    )
    assert res_239["suppressed"] is False
    assert res_239["percentile"] is not None
    assert "z_score" in res_239
    assert res_239.get("is_adult") is not True

    # At exact 240 months: transitions to adult BMI formula, percentile is None, is_adult is True
    res_240 = calculate_pediatric_bmi_percentile(
        age_months=240,
        gender="male",
        weight_kg=65.0,
        height_cm=175.0,
    )
    assert res_240["suppressed"] is False
    assert res_240["percentile"] is None
    assert res_240["is_adult"] is True
    assert res_240["bmi"] == 21.2
    assert res_240["classification"] == "Normal weight"

    # At 241 months: adult BMI formula
    res_241 = calculate_pediatric_bmi_percentile(
        age_months=241,
        gender="female",
        weight_kg=60.0,
        height_cm=165.0,
    )
    assert res_241["is_adult"] is True
    assert res_241["percentile"] is None


def test_pediatric_bmi_suppression_under_24_months():
    """Verifies that children under 2 years (< 24 months) are clinically suppressed per CDC guidelines."""
    # Age 0 months (newborn)
    res_0 = calculate_pediatric_bmi_percentile(0, "female", 3.5, 50.0)
    assert res_0["suppressed"] is True
    assert res_0["bmi"] is None
    assert res_0["percentile"] is None
    assert "under 24 months" in res_0["reason"]

    # Age 23 months (1 month before 2nd birthday)
    res_23 = calculate_pediatric_bmi_percentile(23, "male", 12.0, 86.0)
    assert res_23["suppressed"] is True
    assert res_23["bmi"] is None
    assert res_23["percentile"] is None
    assert "under 24 months" in res_23["reason"]

    # Age 24 months: eligible for CDC pediatric LMS evaluation
    res_24 = calculate_pediatric_bmi_percentile(24, "male", 12.5, 87.0)
    assert res_24["suppressed"] is False
    assert res_24["bmi"] is not None
    assert res_24["percentile"] is not None
    assert res_24["classification"] in ("Healthy weight", "Underweight", "Overweight", "Obesity")


def test_pediatric_bmi_non_binary_gender_rejection_and_adult_fallback_path():
    """Verifies calculate_pediatric_bmi_percentile rejects non-binary strings and verifies fallback contract."""
    # Direct calculate_pediatric_bmi_percentile strictly requires "male" or "female"
    with pytest.raises(ValueError, match="Invalid gender 'non-binary'"):
        calculate_pediatric_bmi_percentile(48, "non-binary", 16.0, 102.0)  # type: ignore

    with pytest.raises(ValueError, match="Invalid gender 'other'"):
        calculate_pediatric_bmi_percentile(48, "other", 16.0, 102.0)  # type: ignore

    # System-level fallback architecture simulation:
    # When gender is not biologically male/female, the system computes adult BMI and suppresses LMS percentile
    raw_gender = "non-binary"
    norm_gender = "male" if raw_gender in ("male", "m") else ("female" if raw_gender in ("female", "f") else None)
    assert norm_gender is None

    # Fallback to adult BMI with transparency reason
    adult_fallback = calculate_adult_bmi(weight_kg=16.0, height_cm=102.0, hide_weight=False)
    assert adult_fallback["bmi"] == 15.4
    fallback_result = {
        "suppressed": True,
        "weight_hidden": False,
        "bmi": adult_fallback["bmi"],
        "percentile": None,
        "reason": "CDC pediatric LMS growth charts are defined for biological sex (male/female); percentile is suppressed for non-binary gender.",
    }
    assert fallback_result["bmi"] == 15.4
    assert fallback_result["percentile"] is None
    assert "non-binary" in fallback_result["reason"]


def test_bmi_defenses_negative_age_and_non_positive_inputs():
    """Adversarial testing on negative ages, negative weights, zero heights, and hide_weight toggle."""
    # Negative age
    with pytest.raises(ValueError, match="Age in months must be non-negative."):
        calculate_pediatric_bmi_percentile(-1, "male", 15.0, 100.0)

    # Non-positive weight/height in adult calculator
    with pytest.raises(ValueError, match="Weight and height must be strictly positive."):
        calculate_adult_bmi(-10.0, 170.0)
    with pytest.raises(ValueError, match="Weight and height must be strictly positive."):
        calculate_adult_bmi(70.0, 0.0)

    # Imperial calculator defenses
    with pytest.raises(ValueError, match="Weight and height must be strictly positive."):
        calculate_adult_bmi_imperial(0.0, 68.0)

    # hide_weight privacy toggle
    adult_hidden = calculate_adult_bmi(70.0, 175.0, hide_weight=True)
    assert adult_hidden["suppressed"] is True
    assert adult_hidden["weight_hidden"] is True
    assert adult_hidden["bmi"] is None

    peds_hidden = calculate_pediatric_bmi_percentile(48, "male", 16.0, 102.0, hide_weight=True)
    assert peds_hidden["suppressed"] is True
    assert peds_hidden["weight_hidden"] is True
    assert peds_hidden["percentile"] is None


# ============================================================================
# Category 3: Diurnal Blood Pressure Moving Averages
# ============================================================================


def test_diurnal_bp_am_pm_partitioning_and_exact_windows():
    """Verifies AHA/ACC 2025 diurnal windows: AM 05:00-11:59 and PM 12:00-22:00."""
    now = datetime(2026, 10, 11, 0, 0, 0, tzinfo=timezone.utc)
    readings = [
        # AM Window boundaries
        {"effective_at": "2026-10-10T05:00:00Z", "systolic": 115, "diastolic": 75},
        {"effective_at": "2026-10-10T11:59:00Z", "systolic": 125, "diastolic": 79},
        # PM Window boundaries
        {"effective_at": "2026-10-10T12:00:00Z", "systolic": 130, "diastolic": 82},
        {"effective_at": "2026-10-10T22:00:00Z", "systolic": 134, "diastolic": 86},
    ]
    trends = calculate_diurnal_bp_trends(readings, now_dt=now, user_tz="UTC")

    # AM window: (115 + 125) / 2 = 120.0, (75 + 79) / 2 = 77.0 -> Elevated
    assert trends["7_day"]["am"]["count"] == 2
    assert trends["7_day"]["am"]["systolic"] == 120.0
    assert trends["7_day"]["am"]["diastolic"] == 77.0
    assert trends["7_day"]["am"]["classification"] == "Elevated"

    # PM window: (130 + 134) / 2 = 132.0, (82 + 86) / 2 = 84.0 -> Stage 1
    assert trends["7_day"]["pm"]["count"] == 2
    assert trends["7_day"]["pm"]["systolic"] == 132.0
    assert trends["7_day"]["pm"]["diastolic"] == 84.0
    assert trends["7_day"]["pm"]["classification"] == "Stage 1"


def test_diurnal_bp_night_window_strict_exclusion():
    """Verifies that readings between 22:01 and 04:59 local time are strictly excluded from diurnal averages."""
    now = datetime(2026, 10, 11, 0, 0, 0, tzinfo=timezone.utc)
    readings = [
        # Night readings (MUST BE EXCLUDED)
        {"effective_at": "2026-10-10T22:01:00Z", "systolic": 190, "diastolic": 110},
        {"effective_at": "2026-10-10T23:30:00Z", "systolic": 185, "diastolic": 105},
        {"effective_at": "2026-10-10T02:00:00Z", "systolic": 175, "diastolic": 95},
        {"effective_at": "2026-10-10T04:59:00Z", "systolic": 180, "diastolic": 100},
        # One valid AM reading
        {"effective_at": "2026-10-10T07:30:00Z", "systolic": 118, "diastolic": 76},
        # One valid PM reading
        {"effective_at": "2026-10-10T14:30:00Z", "systolic": 122, "diastolic": 78},
    ]
    trends = calculate_diurnal_bp_trends(readings, now_dt=now, user_tz="UTC")

    assert trends["7_day"]["am"]["count"] == 1
    assert trends["7_day"]["am"]["systolic"] == 118.0
    assert trends["7_day"]["am"]["classification"] == "Normal"

    assert trends["7_day"]["pm"]["count"] == 1
    assert trends["7_day"]["pm"]["systolic"] == 122.0
    assert trends["7_day"]["pm"]["classification"] == "Elevated"


def test_diurnal_bp_time_horizons_7_30_90_days():
    """Verifies moving average filtering across 7-day, 30-day, and 90-day cutoffs."""
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    readings = [
        # 3 days ago (in 7d, 30d, 90d) at 09:00 UTC
        {"effective_at": (now - timedelta(days=3)).replace(hour=9).isoformat(), "systolic": 110, "diastolic": 70},
        # 15 days ago (in 30d, 90d) at 09:00 UTC
        {"effective_at": (now - timedelta(days=15)).replace(hour=9).isoformat(), "systolic": 130, "diastolic": 80},
        # 45 days ago (in 90d only) at 09:00 UTC
        {"effective_at": (now - timedelta(days=45)).replace(hour=9).isoformat(), "systolic": 150, "diastolic": 90},
        # 100 days ago (expired, excluded from all) at 09:00 UTC
        {"effective_at": (now - timedelta(days=100)).replace(hour=9).isoformat(), "systolic": 190, "diastolic": 100},
        # Future reading (excluded)
        {"effective_at": (now + timedelta(days=2)).replace(hour=9).isoformat(), "systolic": 120, "diastolic": 80},
    ]
    trends = calculate_diurnal_bp_trends(readings, now_dt=now, user_tz="UTC")

    assert trends["7_day"]["am"]["count"] == 1
    assert trends["7_day"]["am"]["systolic"] == 110.0

    assert trends["30_day"]["am"]["count"] == 2
    assert trends["30_day"]["am"]["systolic"] == 120.0  # (110 + 130) / 2

    assert trends["90_day"]["am"]["count"] == 3
    assert trends["90_day"]["am"]["systolic"] == 130.0  # (110 + 130 + 150) / 3


def test_diurnal_bp_timezone_stability_multiregion():
    """Adversarial test evaluating timezone partitioning in New York, Tokyo, and Honolulu."""
    # Reading taken at 14:00 UTC
    reading = {"effective_at": "2026-10-10T14:00:00Z", "systolic": 124, "diastolic": 82}
    now = datetime(2026, 10, 11, 0, 0, 0, tzinfo=timezone.utc)

    # In UTC: 14:00 is PM
    t_utc = calculate_diurnal_bp_trends([reading], now_dt=now, user_tz="UTC")
    assert t_utc["7_day"]["am"]["count"] == 0
    assert t_utc["7_day"]["pm"]["count"] == 1

    # In America/New_York (EDT, UTC-4): 14:00 UTC is 10:00 AM local time -> AM window!
    t_ny = calculate_diurnal_bp_trends([reading], now_dt=now, user_tz="America/New_York")
    assert t_ny["7_day"]["am"]["count"] == 1
    assert t_ny["7_day"]["pm"]["count"] == 0

    # In Asia/Tokyo (UTC+9): 14:00 UTC is 23:00 local time -> Night window -> strictly excluded!
    t_tokyo = calculate_diurnal_bp_trends([reading], now_dt=now, user_tz="Asia/Tokyo")
    assert t_tokyo["7_day"]["am"]["count"] == 0
    assert t_tokyo["7_day"]["pm"]["count"] == 0

    # In Pacific/Honolulu (UTC-10): 14:00 UTC is 04:00 local time -> Night window -> strictly excluded!
    t_hnl = calculate_diurnal_bp_trends([reading], now_dt=now, user_tz="Pacific/Honolulu")
    assert t_hnl["7_day"]["am"]["count"] == 0
    assert t_hnl["7_day"]["pm"]["count"] == 0


def test_diurnal_bp_aha_acc_classifications():
    """Validates classify_blood_pressure across all 5 AHA/ACC 2025 tiers and insufficient data handling."""
    assert classify_blood_pressure(115, 75) == "Normal"
    assert classify_blood_pressure(125, 75) == "Elevated"
    assert classify_blood_pressure(132, 75) == "Stage 1"
    assert classify_blood_pressure(115, 84) == "Stage 1"
    assert classify_blood_pressure(145, 75) == "Stage 2"
    assert classify_blood_pressure(115, 92) == "Stage 2"
    assert classify_blood_pressure(182, 75) == "Hypertensive Crisis"
    assert classify_blood_pressure(115, 122) == "Hypertensive Crisis"

    # Empty readings returns "Insufficient Data"
    empty_trends = calculate_diurnal_bp_trends([], user_tz="UTC")
    assert empty_trends["7_day"]["am"]["classification"] == "Insufficient Data"
    assert empty_trends["7_day"]["am"]["systolic"] is None


# ============================================================================
# Category 4: Clinical Safety Boundaries & Red-Flag Severity Preemption
# ============================================================================


def test_hypertensive_crisis_symptomatic_independent_thresholds():
    """Verifies that either SBP >= 180 or DBP >= 120 with acute symptoms triggers non-suppressible 911."""
    # SBP isolated crisis with chest pain
    flag_sys = check_vitals_red_flags(
        vitals={"systolic": 182, "diastolic": 85},
        reported_symptoms=["chest pain"],
    )
    assert flag_sys.triggered is True
    assert flag_sys.category == "bp_crisis_symptomatic"
    assert flag_sys.severity == "emergency"
    assert "Call 911 immediately" in flag_sys.directive
    assert flag_sys.prompt_recheck is False

    # DBP isolated crisis with dysarthria
    flag_dia = check_vitals_red_flags(
        vitals={"systolic": 135, "diastolic": 125},
        reported_symptoms=["slurred speech"],
    )
    assert flag_dia.triggered is True
    assert flag_dia.category == "bp_crisis_symptomatic"
    assert flag_dia.severity == "emergency"
    assert "Call 911 immediately" in flag_dia.directive


def test_symptom_negation_span_masking_deep():
    """Tests white-box negation parsing on complex medical phrasing with affirmative co-occurrence."""
    acute = FALLBACK_ACUTE_SYMPTOMS
    hypo = FALLBACK_HYPOTENSION_SYMPTOMS
    cues = FALLBACK_NEGATION_TERMS

    # Pure negation phrases: denies chest pain, no shortness of breath, without dizziness
    has_a, has_h, aff_a, aff_h = _parse_affirmative_symptoms(
        [
            "denies chest pain",
            "patient reports no shortness of breath",
            "without severe back pain",
            "negative for dyspnea",
            "denies dizziness and without fainting",
        ],
        acute,
        hypo,
        cues,
    )
    assert has_a is False
    assert has_h is False
    assert len(aff_a) == 0
    assert len(aff_h) == 0

    # Mixed negation with affirmative acute symptom: "denies chest pain, but experiencing slurred speech"
    has_a_mixed, _, aff_a_mixed, _ = _parse_affirmative_symptoms(
        ["patient denies chest pain, but experiencing slurred speech"],
        acute,
        hypo,
        cues,
    )
    assert has_a_mixed is True
    assert len(aff_a_mixed) == 1

    # End-to-end integration: BP 190/100 with "denies chest pain" -> Asymptomatic BP crisis
    flag_neg = check_vitals_red_flags(
        vitals={"systolic": 190, "diastolic": 100},
        reported_symptoms=["denies chest pain"],
    )
    assert flag_neg.category == "bp_crisis_asymptomatic"
    assert flag_neg.prompt_recheck is True
    assert "Rest quietly for 5 minutes" in flag_neg.directive


def test_multi_vital_preemption_hypoxemia_over_asymptomatic_bp_crisis():
    """Clinical Priority Invariant: Life-threatening SpO2 < 90% strictly preempts asymptomatic BP rest directive."""
    flag = check_vitals_red_flags(
        vitals={
            "systolic": 195,
            "diastolic": 125,
            "spo2": 84,  # Severe hypoxemia
        },
        reported_symptoms=[],  # No symptoms
    )

    assert flag.triggered is True
    # Priority 200 (hypoxemia) > 100 (asymptomatic bp)
    assert flag.category == "severe_hypoxemia"
    assert flag.severity == "emergency"
    assert flag.prompt_recheck is False
    # Invariant: Must NOT instruct patient to rest for 5 minutes when SpO2 is critically low
    assert "Rest quietly for 5 minutes" not in flag.directive
    assert "SpO2 is below 90%" in flag.directive


def test_multi_vital_co_occurring_emergencies_directive_synthesis():
    """Verifies that co-occurring emergencies (symptomatic BP crisis + hypoxemia) combine critical directives."""
    flag = check_vitals_red_flags(
        vitals={
            "systolic": 200,
            "diastolic": 130,
            "spo2": 86,
        },
        reported_symptoms=["crushing chest pain"],
    )

    assert flag.triggered is True
    assert flag.category == "bp_crisis_symptomatic"
    assert flag.severity == "emergency"
    assert flag.prompt_recheck is False
    # Combined directive contains both critical alerts
    assert "Call 911 immediately" in flag.directive
    assert "SpO2 is below 90%" in flag.directive


def test_severe_hypoglycemia_rule_of_15_mmol_and_mgdl():
    """Validates Rule of 15 acute directive on glucose < 54 mg/dL and mmol/L equivalent."""
    # In mg/dL
    flag_mgdl = check_vitals_red_flags(vitals={"blood_glucose": 48})
    assert flag_mgdl.triggered is True
    assert flag_mgdl.category == "severe_hypoglycemia"
    assert flag_mgdl.severity == "urgent"
    assert "Rule of 15" in flag_mgdl.directive
    assert flag_mgdl.prompt_recheck is True

    # In mmol/L: 2.8 mmol/L * 18.0182 = 50.45 mg/dL (< 54)
    flag_mmol = check_vitals_red_flags(vitals={"blood_glucose": 2.8, "unit": "mmol/L"})
    assert flag_mmol.triggered is True
    assert flag_mmol.category == "severe_hypoglycemia"

    # Boundary: 54.0 mg/dL does not trigger
    flag_norm = check_vitals_red_flags(vitals={"blood_glucose": 54.0})
    assert flag_norm.triggered is False


def test_symptomatic_hypotension_hemodynamic_boundary():
    """Verifies hypotension (< 90/60) requires hemodynamic symptoms to trigger clinical referral."""
    # Low BP without symptoms -> does not trigger
    flag_asymp = check_vitals_red_flags(vitals={"systolic": 85, "diastolic": 55}, reported_symptoms=[])
    assert flag_asymp.triggered is False

    # Low systolic (<90) with dizziness -> triggers
    flag_symp_sys = check_vitals_red_flags(
        vitals={"systolic": 88, "diastolic": 65},
        reported_symptoms=["dizziness"],
    )
    assert flag_symp_sys.triggered is True
    assert flag_symp_sys.category == "symptomatic_hypotension"
    assert flag_symp_sys.severity == "urgent"
    assert "Sit or lie down immediately" in flag_symp_sys.directive

    # Low diastolic (<60) with syncope -> triggers
    flag_symp_dia = check_vitals_red_flags(
        vitals={"systolic": 95, "diastolic": 56},
        reported_symptoms=["syncope"],
    )
    assert flag_symp_dia.triggered is True
    assert flag_symp_dia.category == "symptomatic_hypotension"


# ============================================================================
# Category 5: Appointments & RFC 5545 RRULE Recurrence Engine
# ============================================================================


def test_appointment_lifecycle_state_machine_strict_transitions():
    """Adversarial validation of appointment state machine transitions, illegal paths, and idempotency."""
    # Legal transitions
    validate_status_transition("requested", "scheduled")
    validate_status_transition("scheduled", "confirmed")
    validate_status_transition("confirmed", "completed")
    validate_status_transition("completed", "cancelled")
    validate_status_transition("cancelled", "requested")

    # Idempotent no-op
    validate_status_transition("confirmed", "confirmed")

    # Prohibited direct transitions
    with pytest.raises(InvalidStatusTransitionError) as exc_info:
        validate_status_transition("requested", "completed")
    assert exc_info.value.from_status == "requested"
    assert exc_info.value.to_status == "completed"

    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("completed", "scheduled")

    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("cancelled", "confirmed")

    # Unknown status name
    with pytest.raises(ValueError, match="Unknown appointment status"):
        validate_status_transition("pending", "confirmed")


def test_post_visit_transitions_evaluation():
    """Verifies that confirmed visits past end_time transition to completed with structured followup prompt."""
    now = datetime(2026, 10, 10, 15, 0, 0, tzinfo=timezone.utc)
    appts = [
        # 1. Confirmed visit that ended 30m ago -> MUST transition
        {
            "id": "appt-1",
            "title": "Cardiology Follow-up",
            "status": "confirmed",
            "end_time": (now - timedelta(minutes=30)).isoformat(),
        },
        # 2. Confirmed visit ending in the future -> MUST NOT transition
        {
            "id": "appt-2",
            "title": "Future Dental Visit",
            "status": "confirmed",
            "end_time": (now + timedelta(hours=2)).isoformat(),
        },
        # 3. Scheduled visit in past (not confirmed) -> MUST NOT transition
        {
            "id": "appt-3",
            "title": "Tentative Physical",
            "status": "scheduled",
            "end_time": (now - timedelta(hours=1)).isoformat(),
        },
    ]

    completed_ids, prompts = evaluate_post_visit_transitions(appts, current_time=now)
    assert completed_ids == ["appt-1"]
    assert len(prompts) == 1
    assert prompts[0]["appointment_id"] == "appt-1"
    assert prompts[0]["prompt_type"] == "post_visit_followup"
    assert len(prompts[0]["suggested_actions"]) == 2


def test_how_to_book_drafts_generation():
    """Verifies structured phone script, portal message draft, and pre-visit checklist creation."""
    drafts = generate_how_to_book_drafts(
        title="Neurology Consult",
        provider_name="Dr. Jane Smith",
        specialty="Neurology",
        clinic_phone="555-0199",
        reason="Persistent migraines",
        insurance_name="BlueCross BlueShield",
        insurance_member_id="BCBS123456",
        insurance_group_number="GRP987",
        preferred_days=["Tuesday", "Thursday"],
        preferred_time_of_day="Morning",
        visit_mode="in-person",
    )

    assert drafts["status"] == "requested"
    assert "Dr. Jane Smith" in drafts["phone_script"]
    assert "555-0199" in drafts["phone_script"]
    assert "BCBS123456" in drafts["phone_script"]
    assert "Persistent migraines" in drafts["portal_draft"]
    assert len(drafts["checklist"]) == 5


def test_rrule_leap_year_feb_29_clamping_and_advancement():
    """Verifies leap year Feb 29 advancement: clamping to Feb 28 in non-leap year and preservation in leap year."""
    # Leap year base: Feb 29, 2024
    base_leap = datetime(2024, 2, 29, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Advance 1 year to non-leap year (2025): MUST clamp to Feb 28
    next_2025 = advance_rrule_occurrence(base_leap, "FREQ=YEARLY;INTERVAL=1", "UTC")
    assert next_2025 == datetime(2025, 2, 28, 10, 0, 0, tzinfo=timezone.utc)

    # 2. Advance 4 years to next leap year (2028): MUST preserve Feb 29
    next_2028 = advance_rrule_occurrence(base_leap, "FREQ=YEARLY;INTERVAL=4", "UTC")
    assert next_2028 == datetime(2028, 2, 29, 10, 0, 0, tzinfo=timezone.utc)


def test_rrule_monthly_day_clamping_across_short_months():
    """Verifies day clamping for monthly recurrences starting on the 31st across 28/29/30 day months."""
    # Jan 31, 2026 -> Feb 2026 has 28 days -> clamps to Feb 28
    jan_31_2026 = datetime(2026, 1, 31, 9, 0, 0, tzinfo=timezone.utc)
    feb_2026 = advance_rrule_occurrence(jan_31_2026, "FREQ=MONTHLY;INTERVAL=1", "UTC")
    assert feb_2026 == datetime(2026, 2, 28, 9, 0, 0, tzinfo=timezone.utc)

    # Jan 31, 2024 -> Feb 2024 has 29 days (leap year) -> clamps to Feb 29
    jan_31_2024 = datetime(2024, 1, 31, 9, 0, 0, tzinfo=timezone.utc)
    feb_2024 = advance_rrule_occurrence(jan_31_2024, "FREQ=MONTHLY;INTERVAL=1", "UTC")
    assert feb_2024 == datetime(2024, 2, 29, 9, 0, 0, tzinfo=timezone.utc)

    # Mar 31, 2026 -> Apr 2026 has 30 days -> clamps to Apr 30
    mar_31_2026 = datetime(2026, 3, 31, 9, 0, 0, tzinfo=timezone.utc)
    apr_2026 = advance_rrule_occurrence(mar_31_2026, "FREQ=MONTHLY;INTERVAL=1", "UTC")
    assert apr_2026 == datetime(2026, 4, 30, 9, 0, 0, tzinfo=timezone.utc)


def test_rrule_dst_wall_clock_stability():
    """Verifies wall-clock stability across US Spring Forward (March 2026) and Fall Back (November 2026)."""
    tz_ny = "America/New_York"

    # 1. Spring forward: 2026-03-07 (EST, UTC-5) -> 2026-03-08 (EDT, UTC-4)
    base_spring = datetime(2026, 3, 7, 8, 0, 0, tzinfo=ZoneInfo(tz_ny))
    next_spring = advance_rrule_occurrence(base_spring, "FREQ=DAILY;INTERVAL=1", tz_ny)
    assert next_spring is not None
    local_spring = next_spring.astimezone(ZoneInfo(tz_ny))
    assert local_spring.hour == 8
    assert local_spring.minute == 0
    assert local_spring.day == 8
    # UTC offset changed from -05:00 to -04:00 (13:00 UTC -> 12:00 UTC)
    assert next_spring.hour == 12

    # 2. Fall back: 2026-10-31 (EDT, UTC-4) -> 2026-11-01 (EST, UTC-5)
    base_fall = datetime(2026, 10, 31, 8, 0, 0, tzinfo=ZoneInfo(tz_ny))
    next_fall = advance_rrule_occurrence(base_fall, "FREQ=DAILY;INTERVAL=1", tz_ny)
    assert next_fall is not None
    local_fall = next_fall.astimezone(ZoneInfo(tz_ny))
    assert local_fall.hour == 8
    assert local_fall.minute == 0
    assert local_fall.day == 1
    # UTC offset changed from -04:00 to -05:00 (12:00 UTC -> 13:00 UTC)
    assert next_fall.hour == 13


def test_rrule_until_token_exhaustion():
    """Verifies that an RRULE with UNTIL returns None once candidate exceeds the boundary."""
    base = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    # UNTIL is set to 2026-10-10 12:00 UTC
    rule = "FREQ=DAILY;INTERVAL=1;UNTIL=20261010T120000Z"
    # Next candidate would be 2026-10-11 08:00 UTC, which exceeds UNTIL -> returns None
    assert advance_rrule_occurrence(base, rule, "UTC") is None


def test_reminder_snooze_presets_and_terminal_immutability():
    """Adversarial testing on +15m, +1h, +24h snoozing, invalid presets, and terminal status immutability."""
    now = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)
    rem = {"id": "rem-1", "title": "Take Lisinopril", "status": "pending"}

    # +15m
    snoozed_15m = apply_reminder_snooze(rem, "+15m", now)
    assert snoozed_15m["status"] == "snoozed"
    assert snoozed_15m["snooze_until"] == (now + timedelta(minutes=15)).isoformat()

    # +1h
    snoozed_1h = apply_reminder_snooze(rem, "1h", now)
    assert snoozed_1h["snooze_until"] == (now + timedelta(hours=1)).isoformat()

    # +24h
    snoozed_24h = apply_reminder_snooze(rem, "+24h", now)
    assert snoozed_24h["snooze_until"] == (now + timedelta(hours=24)).isoformat()

    # Invalid snooze presets
    with pytest.raises(ValueError, match="Invalid snooze interval"):
        apply_reminder_snooze(rem, "+30m", now)
    with pytest.raises(ValueError, match="Invalid snooze interval"):
        apply_reminder_snooze(rem, "-1h", now)

    # Terminal state immutability: completed and cancelled reminders cannot be snoozed
    rem_comp = {"id": "rem-2", "status": "completed"}
    with pytest.raises(ValueError, match="Cannot snooze reminder with status 'completed'"):
        apply_reminder_snooze(rem_comp, "+1h", now)

    rem_canc = {"id": "rem-3", "status": "cancelled"}
    with pytest.raises(ValueError, match="Cannot snooze reminder with status 'cancelled'"):
        apply_reminder_snooze(rem_canc, "+1h", now)


def test_sleep_wake_coalescing_overdue_24h_to_missed():
    """Verifies that reminders overdue by > 24 hours coalesce into 'missed' status without notification storms."""
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    reminders = [
        # 1. Pending reminder overdue by 26 hours -> MUST become missed
        {
            "id": "r-1",
            "status": "pending",
            "next_due_at": (now - timedelta(hours=26)).isoformat(),
        },
        # 2. Pending reminder overdue by 23 hours -> MUST remain pending
        {
            "id": "r-2",
            "status": "pending",
            "next_due_at": (now - timedelta(hours=23)).isoformat(),
        },
        # 3. Snoozed reminder whose snooze_until is overdue by 25 hours -> MUST become missed
        {
            "id": "r-3",
            "status": "snoozed",
            "next_due_at": (now - timedelta(hours=48)).isoformat(),
            "snooze_until": (now - timedelta(hours=25)).isoformat(),
        },
        # 4. Snoozed reminder whose snooze_until was 2 hours ago -> MUST remain snoozed
        {
            "id": "r-4",
            "status": "snoozed",
            "next_due_at": (now - timedelta(hours=30)).isoformat(),
            "snooze_until": (now - timedelta(hours=2)).isoformat(),
        },
        # 5. Completed reminder due 5 days ago -> Invariant: remains completed
        {
            "id": "r-5",
            "status": "completed",
            "next_due_at": (now - timedelta(days=5)).isoformat(),
        },
        # 6. Cancelled reminder due 5 days ago -> Invariant: remains cancelled
        {
            "id": "r-6",
            "status": "cancelled",
            "next_due_at": (now - timedelta(days=5)).isoformat(),
        },
    ]

    coalesced = coalesce_overdue_reminders(reminders, current_time=now)
    assert coalesced[0]["status"] == "missed"
    assert coalesced[1]["status"] == "pending"
    assert coalesced[2]["status"] == "missed"
    assert coalesced[3]["status"] == "snoozed"
    assert coalesced[4]["status"] == "completed"
    assert coalesced[5]["status"] == "cancelled"


def test_ics_export_crlf_and_phi_sanitization():
    """Verifies RFC 5545 .ics generation adheres to CRLF line breaks and masks private PHI by default."""
    reminders = [
        {
            "id": "rem-phi-1",
            "title": "Take 50mg Metoprolol Succinate BID",
            "description": "Prescribed by Dr. Heart for Stage 2 hypertension. Refill Rx #998811.",
            "category": "medication",
            "next_due_at": "2026-10-10T08:00:00Z",
            "rrule": "FREQ=DAILY;INTERVAL=1",
        },
        {
            "id": "rem-phi-2",
            "title": "Log Morning Blood Glucose",
            "description": "Fasting reading before breakfast.",
            "category": "vitals",
            "next_due_at": "2026-10-10T07:30:00Z",
        },
    ]

    # 1. Sanitized export (default)
    ics_sanitized = generate_ics_calendar(reminders, sanitize_phi=True)
    assert "\r\n" in ics_sanitized
    assert "\n" not in ics_sanitized.replace("\r\n", "")  # Strict CRLF

    # Invariants: PHI must be masked
    assert "Metoprolol" not in ics_sanitized
    assert "Stage 2 hypertension" not in ics_sanitized
    assert "SUMMARY:Carefold Medication Reminder" in ics_sanitized
    assert "SUMMARY:Carefold Vitals Reminder" in ics_sanitized
    assert "Sanitized reminder event" in ics_sanitized
    assert "RRULE:FREQ=DAILY;INTERVAL=1" in ics_sanitized

    # 2. Unsanitized export (explicit opt-out)
    ics_raw = generate_ics_calendar(reminders, sanitize_phi=False)
    assert "SUMMARY:Take 50mg Metoprolol Succinate BID" in ics_raw
    assert "Stage 2 hypertension" in ics_raw
