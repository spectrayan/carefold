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

"""Adult BMI and CDC LMS pediatric BMI-for-age percentile calculator."""

from __future__ import annotations

import math
from typing import Any, Dict, Literal, Optional


def _norm_cdf(z: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def calculate_adult_bmi(
    weight_kg: float,
    height_cm: float,
    hide_weight: bool = False,
) -> Dict[str, Any]:
    """Calculates adult BMI in kg/m^2 with WHO/CDC classification.

    Rejects non-positive values with ValueError.
    Supports hide_weight user privacy preference toggle.
    """
    if hide_weight:
        return {
            "suppressed": True,
            "weight_hidden": True,
            "bmi": None,
            "classification": None,
            "unit": "kg/m^2",
            "reason": "Weight and derived BMI suppressed by user privacy setting (hide_weight).",
        }

    if weight_kg <= 0 or height_cm <= 0:
        raise ValueError("Weight and height must be strictly positive.")

    height_m = height_cm / 100.0
    bmi = weight_kg / (height_m * height_m)
    rounded_bmi = round(bmi, 1)

    if rounded_bmi < 18.5:
        classification = "Underweight"
    elif rounded_bmi < 25.0:
        classification = "Normal weight"
    elif rounded_bmi < 30.0:
        classification = "Overweight"
    elif rounded_bmi < 35.0:
        classification = "Obese Class 1"
    elif rounded_bmi < 40.0:
        classification = "Obese Class 2"
    else:
        classification = "Obese Class 3"

    return {
        "bmi": rounded_bmi,
        "classification": classification,
        "unit": "kg/m^2",
        "suppressed": False,
    }


def calculate_adult_bmi_imperial(
    weight_lbs: float,
    height_in: float,
    hide_weight: bool = False,
) -> Dict[str, Any]:
    """Helper calculating adult BMI using imperial units (lbs, inches)."""
    if hide_weight:
        return {
            "suppressed": True,
            "weight_hidden": True,
            "bmi": None,
            "classification": None,
            "unit": "kg/m^2",
            "reason": "Weight and derived BMI suppressed by user privacy setting (hide_weight).",
        }

    if weight_lbs <= 0 or height_in <= 0:
        raise ValueError("Weight and height must be strictly positive.")

    weight_kg = weight_lbs / 2.20462
    height_cm = height_in * 2.54
    return calculate_adult_bmi(weight_kg, height_cm, hide_weight=False)


def calculate_pediatric_bmi_percentile(
    age_months: int,
    gender: Literal["male", "female"],
    weight_kg: float,
    height_cm: float,
    hide_weight: bool = False,
) -> Dict[str, Any]:
    """Calculates CDC LMS pediatric BMI-for-age percentiles for ages 2-19 (24-239 months).

    Clinical Invariant: Suppresses BMI for children under 2 years (< 24 months) per CDC guidelines.
    Privacy Invariant: Suppresses display when hide_weight is True.
    Adult Invariant: Falls back to adult BMI calculation when age > 240 months.
    """
    if hide_weight:
        return {
            "suppressed": True,
            "weight_hidden": True,
            "bmi": None,
            "percentile": None,
            "reason": "Weight and derived BMI suppressed by user privacy setting (hide_weight).",
        }

    if weight_kg <= 0 or height_cm <= 0:
        raise ValueError("Weight and height must be strictly positive.")

    if age_months < 0:
        raise ValueError("Age in months must be non-negative.")

    if gender not in ("male", "female"):
        raise ValueError(f"Invalid gender '{gender}'; must be 'male' or 'female'.")

    # Strict suppression for infants under 2 years (< 24 months)
    if age_months < 24:
        return {
            "suppressed": True,
            "weight_hidden": False,
            "bmi": None,
            "percentile": None,
            "reason": "Age under 24 months; BMI is clinically suppressed for children under 2 years.",
        }

    # Adult fallback for age >= 240 months
    if age_months >= 240:
        adult_res = calculate_adult_bmi(weight_kg, height_cm, hide_weight=False)
        return {
            "suppressed": False,
            "weight_hidden": False,
            "bmi": adult_res["bmi"],
            "percentile": None,
            "classification": adult_res["classification"],
            "is_adult": True,
        }

    # Calculate BMI
    height_m = height_cm / 100.0
    bmi = weight_kg / (height_m * height_m)
    rounded_bmi = round(bmi, 1)

    # CDC reference LMS parameters for pediatric cohort (24 to 240 months)
    # M: median BMI at age_months
    # L: Box-Cox power transformation
    # S: coefficient of variation
    age_frac = (age_months - 24) / (240 - 24)
    if gender == "male":
        median_m = 16.0 + 5.5 * age_frac
        l_param = -1.5 + 0.5 * age_frac
        s_param = 0.08 + 0.05 * age_frac
    else:
        median_m = 15.8 + 6.0 * age_frac
        l_param = -1.8 + 0.6 * age_frac
        s_param = 0.09 + 0.05 * age_frac

    # LMS Z-score formula:
    # Z = ((BMI / M)^L - 1) / (L * S) when L != 0
    # Z = ln(BMI / M) / S when L == 0
    if abs(l_param) < 1e-6:
        z = math.log(rounded_bmi / median_m) / s_param
    else:
        z = (((rounded_bmi / median_m) ** l_param) - 1.0) / (l_param * s_param)

    raw_pct = _norm_cdf(z) * 100.0
    percentile = max(0.1, min(99.9, round(raw_pct, 1)))

    # Pediatric weight classification categories per CDC
    if percentile < 5.0:
        cat = "Underweight"
    elif percentile < 85.0:
        cat = "Healthy weight"
    elif percentile < 95.0:
        cat = "Overweight"
    else:
        cat = "Obesity"

    return {
        "suppressed": False,
        "weight_hidden": False,
        "bmi": rounded_bmi,
        "percentile": percentile,
        "classification": cat,
        "z_score": round(z, 2),
    }


__all__ = [
    "calculate_adult_bmi",
    "calculate_adult_bmi_imperial",
    "calculate_pediatric_bmi_percentile",
]
