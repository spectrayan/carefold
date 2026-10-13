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

"""Unit tests for Carefold Autonomy Batch 3 vitals pipeline.

Verifies:
1. FHIR R4 Observation normalization for all supported vitals (BP, HR, Glucose, SpO2, Weight, Height).
2. Unit conversions (mmol/L -> mg/dL, lbs -> kg, inches -> cm).
3. Adult BMI calculation (metric and imperial) and classification.
4. Pediatric BMI-for-age percentile calculation and infant (<24 months) suppression.
5. Diurnal blood pressure trend calculations (7/30/90-day AM vs PM moving averages).
6. Blood pressure classification according to AHA/ACC guidelines.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from carefold.clinical.bmi import (
    calculate_adult_bmi,
    calculate_adult_bmi_imperial,
    calculate_pediatric_bmi_percentile,
)
from carefold.clinical.vitals import (
    LOINC_CODES,
    calculate_diurnal_bp_trends,
    classify_blood_pressure,
    normalize_fhir_vitals,
)


class TestFhirVitalsNormalization:
    """Verifies LOINC observation mapping and FHIR R4 schema compliance."""

    def test_normalize_blood_pressure_panel(self):
        raw = {"systolic": 120, "diastolic": 80}
        obs = normalize_fhir_vitals(raw)
        assert obs["resourceType"] == "Observation"
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["blood_pressure"]
        components = {c["code"]["coding"][0]["code"]: c["valueQuantity"]["value"] for c in obs["component"]}
        assert components[LOINC_CODES["systolic"]] == 120.0
        assert components[LOINC_CODES["diastolic"]] == 80.0

    def test_normalize_heart_rate(self):
        obs = normalize_fhir_vitals({"heart_rate": 72})
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["heart_rate"]
        assert obs["valueQuantity"]["value"] == 72.0
        assert obs["valueQuantity"]["unit"] == "bpm"

    def test_normalize_blood_glucose_mg_dl(self):
        obs = normalize_fhir_vitals({"blood_glucose": 95.0, "unit": "mg/dL"})
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["blood_glucose"]
        assert obs["valueQuantity"]["value"] == 95.0
        assert obs["valueQuantity"]["unit"] == "mg/dL"

    def test_normalize_blood_glucose_mmol_conversion(self):
        obs = normalize_fhir_vitals({"blood_glucose": 5.5, "unit": "mmol/L"})
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["blood_glucose"]
        assert pytest.approx(obs["valueQuantity"]["value"], rel=1e-2) == 99.1
        assert obs["valueQuantity"]["unit"] == "mg/dL"

    def test_normalize_oxygen_saturation(self):
        obs = normalize_fhir_vitals({"spo2": 98.0})
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["oxygen_saturation"]
        assert obs["valueQuantity"]["value"] == 98.0
        assert obs["valueQuantity"]["unit"] == "%"

    def test_normalize_body_weight_kg_and_lbs(self):
        obs_kg = normalize_fhir_vitals({"weight": 70.0, "unit": "kg"})
        assert obs_kg["code"]["coding"][0]["code"] == LOINC_CODES["body_weight"]
        assert obs_kg["valueQuantity"]["value"] == 70.0
        assert obs_kg["valueQuantity"]["unit"] == "kg"

        obs_lbs = normalize_fhir_vitals({"weight": 154.32, "unit": "lbs"})
        assert pytest.approx(obs_lbs["valueQuantity"]["value"], rel=1e-2) == 70.0
        assert obs_lbs["valueQuantity"]["unit"] == "kg"

    def test_normalize_body_height_cm_and_inches(self):
        obs_cm = normalize_fhir_vitals({"height": 175.0, "unit": "cm"})
        assert obs_cm["code"]["coding"][0]["code"] == LOINC_CODES["body_height"]
        assert obs_cm["valueQuantity"]["value"] == 175.0
        assert obs_cm["valueQuantity"]["unit"] == "cm"

        obs_in = normalize_fhir_vitals({"height": 68.9, "unit": "in"})
        assert pytest.approx(obs_in["valueQuantity"]["value"], rel=1e-2) == 175.0
        assert obs_in["valueQuantity"]["unit"] == "cm"


class TestBmiCalculator:
    """Verifies adult BMI formulas, pediatric percentiles, and suppression rules."""

    def test_calculate_adult_bmi_standard(self):
        res = calculate_adult_bmi(weight_kg=70.0, height_cm=175.0)
        assert res["bmi"] == 22.9
        assert res["classification"] == "Normal weight"
        assert res["suppressed"] is False

    def test_calculate_adult_bmi_imperial(self):
        res = calculate_adult_bmi_imperial(weight_lbs=154.32, height_in=68.9)
        assert res["bmi"] == 22.9
        assert res["classification"] == "Normal weight"

    def test_calculate_adult_bmi_hide_weight(self):
        res = calculate_adult_bmi(weight_kg=70.0, height_cm=175.0, hide_weight=True)
        assert res["suppressed"] is True
        assert res["bmi"] is None
        assert res["classification"] is None

    def test_calculate_adult_bmi_invalid_input(self):
        with pytest.raises(ValueError):
            calculate_adult_bmi(weight_kg=0, height_cm=175.0)
        with pytest.raises(ValueError):
            calculate_adult_bmi(weight_kg=70.0, height_cm=-10.0)

    def test_calculate_pediatric_bmi_percentile_child(self):
        # 10-year-old (120 months) male
        res = calculate_pediatric_bmi_percentile(
            weight_kg=32.0,
            height_cm=138.0,
            age_months=120,
            gender="male",
        )
        assert res["suppressed"] is False
        assert 1.0 <= res["percentile"] <= 99.0
        assert res["classification"] in ("Healthy weight", "Underweight", "Overweight", "Obesity")

    def test_calculate_pediatric_bmi_infant_suppression(self):
        res = calculate_pediatric_bmi_percentile(
            weight_kg=9.5,
            height_cm=75.0,
            age_months=18,
            gender="female",
        )
        assert res["suppressed"] is True
        assert res["percentile"] is None
        assert "suppressed for children under 2" in res["reason"]


class TestDiurnalBpTrendsAndClassification:
    """Verifies diurnal AM/PM blood pressure trend aggregation and classification."""

    def test_classify_blood_pressure_categories(self):
        assert classify_blood_pressure(115, 75) == "Normal"
        assert classify_blood_pressure(125, 75) == "Elevated"
        assert classify_blood_pressure(135, 85) == "Stage 1"
        assert classify_blood_pressure(145, 95) == "Stage 2"
        assert classify_blood_pressure(185, 125) == "Hypertensive Crisis"

    def test_calculate_diurnal_bp_trends_partitioning(self):
        tz = "America/New_York"
        # Reading at 08:00 EDT (AM)
        dt_am = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)  # 08:00 EDT
        # Reading at 16:00 EDT (PM)
        dt_pm = datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)  # 16:00 EDT

        readings = [
            {
                "effective_at": dt_am.isoformat(),
                "data": {
                    "resourceType": "Observation",
                    "component": [
                        {"code": {"coding": [{"code": LOINC_CODES["systolic"]}]}, "valueQuantity": {"value": 120}},
                        {"code": {"coding": [{"code": LOINC_CODES["diastolic"]}]}, "valueQuantity": {"value": 80}},
                    ],
                },
            },
            {
                "effective_at": dt_pm.isoformat(),
                "data": {
                    "resourceType": "Observation",
                    "component": [
                        {"code": {"coding": [{"code": LOINC_CODES["systolic"]}]}, "valueQuantity": {"value": 130}},
                        {"code": {"coding": [{"code": LOINC_CODES["diastolic"]}]}, "valueQuantity": {"value": 85}},
                    ],
                },
            },
        ]

        trends = calculate_diurnal_bp_trends(
            readings=readings,
            now_dt=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            user_tz=tz,
        )

        assert "7_day" in trends
        assert trends["7_day"]["am"]["count"] == 1
        assert trends["7_day"]["am"]["systolic"] == 120.0
        assert trends["7_day"]["pm"]["count"] == 1
        assert trends["7_day"]["pm"]["systolic"] == 130.0
