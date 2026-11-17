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

"""Unit tests for Carefold vitals clinical normalization and multi-metric parsing."""

from __future__ import annotations

import pytest

from carefold.clinical.vitals import (
    LOINC_CODES,
    normalize_fhir_vitals,
    parse_all_vitals_observations,
)


class TestVitalsClinicalNormalization:
    """Verifies temperature, respiratory rate, and zero-value clinical normalization."""

    def test_temperature_default_degf(self):
        obs = normalize_fhir_vitals({"temperature": 98.6})
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["temperature"]
        assert obs["valueQuantity"]["value"] == 98.6
        assert obs["valueQuantity"]["unit"] == "degF"
        assert obs["valueQuantity"]["code"] == "[degF]"
        assert obs["valueQuantity"]["unit"] != "mg/dL"

    def test_temperature_with_celsius(self):
        obs = normalize_fhir_vitals({"temperature": 37.0, "temp_unit": "C"})
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["temperature"]
        assert obs["valueQuantity"]["value"] == 37.0
        assert obs["valueQuantity"]["unit"] == "Cel"
        assert obs["valueQuantity"]["code"] == "Cel"
        assert obs["valueQuantity"]["unit"] != "mg/dL"

    def test_temperature_with_cel_code(self):
        obs = normalize_fhir_vitals({"temperature": 37.0, "temp_unit": "Cel"})
        assert obs["valueQuantity"]["unit"] == "Cel"
        assert obs["valueQuantity"]["code"] == "Cel"

    def test_temperature_zero_value(self):
        obs = normalize_fhir_vitals({"temperature": 0.0})
        assert obs["valueQuantity"]["value"] == 0.0
        assert obs["valueQuantity"]["unit"] == "degF"
        assert obs["valueQuantity"]["code"] == "[degF]"

    def test_respiratory_rate_zero_value(self):
        obs = normalize_fhir_vitals({"respiratory_rate": 0.0})
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["respiratory_rate"]
        assert obs["valueQuantity"]["value"] == 0.0
        assert obs["valueQuantity"]["unit"] == "breaths/min"
        assert obs["valueQuantity"]["code"] == "/min"

    def test_other_vitals_zero_value_no_crash(self):
        for metric, expected_unit in [
            ("heart_rate", "bpm"),
            ("blood_glucose", "mg/dL"),
            ("spo2", "%"),
            ("weight", "kg"),
            ("height", "cm"),
        ]:
            obs = normalize_fhir_vitals({metric: 0.0})
            assert obs["valueQuantity"]["value"] == 0.0
            assert obs["valueQuantity"]["unit"] == expected_unit

    def test_parse_all_vitals_temperature_unit_not_corrupted_by_mg_dl(self):
        # Raw vitals with unit="mg/dL" (e.g. from Pydantic default or glucose) must not corrupt temperature
        raw = {"temperature": 98.6, "unit": "mg/dL"}
        observations = parse_all_vitals_observations(raw)
        assert len(observations) == 1
        obs = observations[0]
        assert obs["code"]["coding"][0]["code"] == LOINC_CODES["temperature"]
        assert obs["valueQuantity"]["unit"] == "degF"
        assert obs["valueQuantity"]["code"] == "[degF]"
        assert obs["valueQuantity"]["unit"] != "mg/dL"

    def test_parse_all_vitals_temperature_celsius(self):
        raw = {"temperature": 37.0, "temp_unit": "C"}
        observations = parse_all_vitals_observations(raw)
        assert len(observations) == 1
        obs = observations[0]
        assert obs["valueQuantity"]["unit"] == "Cel"
        assert obs["valueQuantity"]["code"] == "Cel"

    def test_parse_all_vitals_zero_values(self):
        raw = {"temperature": 0.0, "respiratory_rate": 0.0, "heart_rate": 0.0}
        observations = parse_all_vitals_observations(raw)
        assert len(observations) == 3
        codes = [obs["code"]["coding"][0]["code"] for obs in observations]
        assert LOINC_CODES["temperature"] in codes
        assert LOINC_CODES["respiratory_rate"] in codes
        assert LOINC_CODES["heart_rate"] in codes
        for obs in observations:
            assert obs["valueQuantity"]["value"] == 0.0
