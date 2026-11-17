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

"""Observation parser, FHIR R4 LOINC mappings, and diurnal BP trend engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# Standard LOINC codes for vital signs
LOINC_CODES: Dict[str, str] = {
    "blood_pressure": "85354-9",
    "systolic": "8480-6",
    "diastolic": "8462-4",
    "heart_rate": "8867-4",
    "blood_glucose": "2339-0",
    "oxygen_saturation": "2708-6",
    "body_weight": "29463-7",
    "body_height": "8302-2",
    "temperature": "8310-5",
    "body_temperature": "8310-5",
    "respiratory_rate": "9279-1",
}

# Unit conversion constants
MMOL_TO_MGDL: float = 18.0182
LBS_TO_KG: float = 2.20462
INCHES_TO_CM: float = 2.54


def normalize_fhir_vitals(
    raw_vitals: Dict[str, Any],
    effective_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Normalizes raw vitals dictionary into a compliant FHIR R4 Observation resource.

    Supports Blood Pressure panel (systolic/diastolic), Heart Rate, Blood Glucose
    (with mmol/L to mg/dL conversion), Oxygen Saturation, Body Weight (with lbs to kg
    conversion), and Body Height (with inches to cm conversion).
    """
    now_iso = (effective_dt or datetime.now(timezone.utc)).isoformat()
    components: List[Dict[str, Any]] = []

    # 1. Blood Pressure panel (systolic & diastolic)
    if "systolic" in raw_vitals and "diastolic" in raw_vitals:
        components.append({
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": LOINC_CODES["systolic"],
                        "display": "Systolic blood pressure",
                    }
                ]
            },
            "valueQuantity": {
                "value": float(raw_vitals["systolic"]),
                "unit": "mmHg",
                "system": "http://unitsofmeasure.org",
                "code": "mm[Hg]",
            },
        })
        components.append({
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": LOINC_CODES["diastolic"],
                        "display": "Diastolic blood pressure",
                    }
                ]
            },
            "valueQuantity": {
                "value": float(raw_vitals["diastolic"]),
                "unit": "mmHg",
                "system": "http://unitsofmeasure.org",
                "code": "mm[Hg]",
            },
        })

    resource: Dict[str, Any] = {
        "resourceType": "Observation",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                        "display": "Vital Signs",
                    }
                ]
            }
        ],
        "effectiveDateTime": now_iso,
    }

    if components:
        resource["code"] = {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": LOINC_CODES["blood_pressure"],
                    "display": "Blood pressure panel",
                }
            ]
        }
        resource["component"] = components
    elif any(k in raw_vitals and raw_vitals[k] is not None for k in ("heart_rate", "hr")):
        raw_val = next((raw_vitals[k] for k in ("heart_rate", "hr") if k in raw_vitals and raw_vitals[k] is not None), None)
        val = float(raw_val) if raw_val is not None else 0.0
        resource["code"] = {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": LOINC_CODES["heart_rate"],
                    "display": "Heart rate",
                }
            ]
        }
        resource["valueQuantity"] = {
            "value": val,
            "unit": "bpm",
            "system": "http://unitsofmeasure.org",
            "code": "/min",
        }
    elif any(k in raw_vitals and raw_vitals[k] is not None for k in ("blood_glucose", "glucose")):
        raw_val = next((raw_vitals[k] for k in ("blood_glucose", "glucose") if k in raw_vitals and raw_vitals[k] is not None), None)
        val = float(raw_val) if raw_val is not None else 0.0
        unit = str(raw_vitals.get("glucose_unit") or raw_vitals.get("unit") or "mg/dL").strip()
        val_mgdl = val * MMOL_TO_MGDL if unit in ("mmol/L", "mmol") else val
        resource["code"] = {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": LOINC_CODES["blood_glucose"],
                    "display": "Glucose [Mass/volume] in Blood",
                }
            ]
        }
        resource["valueQuantity"] = {
            "value": round(val_mgdl, 1),
            "unit": "mg/dL",
            "system": "http://unitsofmeasure.org",
            "code": "mg/dL",
        }
    elif any(k in raw_vitals and raw_vitals[k] is not None for k in ("spo2", "oxygen_saturation")):
        raw_val = next((raw_vitals[k] for k in ("spo2", "oxygen_saturation") if k in raw_vitals and raw_vitals[k] is not None), None)
        val = float(raw_val) if raw_val is not None else 0.0
        resource["code"] = {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": LOINC_CODES["oxygen_saturation"],
                    "display": "Oxygen saturation in Arterial blood",
                }
            ]
        }
        resource["valueQuantity"] = {
            "value": val,
            "unit": "%",
            "system": "http://unitsofmeasure.org",
            "code": "%",
        }
    elif any(k in raw_vitals and raw_vitals[k] is not None for k in ("weight", "body_weight")):
        raw_val = next((raw_vitals[k] for k in ("weight", "body_weight") if k in raw_vitals and raw_vitals[k] is not None), None)
        val = float(raw_val) if raw_val is not None else 0.0
        unit = str(raw_vitals.get("weight_unit") or raw_vitals.get("unit") or "kg").strip().lower()
        val_kg = val / LBS_TO_KG if unit in ("lbs", "lb", "pound", "pounds") else val
        resource["code"] = {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": LOINC_CODES["body_weight"],
                    "display": "Body weight",
                }
            ]
        }
        resource["valueQuantity"] = {
            "value": round(val_kg, 1),
            "unit": "kg",
            "system": "http://unitsofmeasure.org",
            "code": "kg",
        }
    elif any(k in raw_vitals and raw_vitals[k] is not None for k in ("height", "body_height")):
        raw_val = next((raw_vitals[k] for k in ("height", "body_height") if k in raw_vitals and raw_vitals[k] is not None), None)
        val = float(raw_val) if raw_val is not None else 0.0
        unit = str(raw_vitals.get("height_unit") or raw_vitals.get("unit") or "cm").strip().lower()
        val_cm = val * INCHES_TO_CM if unit in ("in", "inches", "inch") else val
        resource["code"] = {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": LOINC_CODES["body_height"],
                    "display": "Body height",
                }
            ]
        }
        resource["valueQuantity"] = {
            "value": round(val_cm, 1),
            "unit": "cm",
            "system": "http://unitsofmeasure.org",
            "code": "cm",
        }
    elif any(k in raw_vitals and raw_vitals[k] is not None for k in ("temperature", "body_temperature", "temp")):
        raw_val = next((raw_vitals[k] for k in ("temperature", "body_temperature", "temp") if k in raw_vitals and raw_vitals[k] is not None), None)
        val = float(raw_val) if raw_val is not None else 0.0
        u = raw_vitals.get("temp_unit") or raw_vitals.get("unit")
        if not u or u == "mg/dL":
            u = "degF"
        u_str = str(u).strip()
        if u_str.lower() in ("c", "celsius", "degc", "°c", "cel"):
            unit = "Cel"
            unit_code = "Cel"
        else:
            unit = "degF"
            unit_code = "[degF]"
        resource["code"] = {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": LOINC_CODES["temperature"],
                    "display": "Body temperature",
                }
            ]
        }
        resource["valueQuantity"] = {
            "value": round(val, 1),
            "unit": unit,
            "system": "http://unitsofmeasure.org",
            "code": unit_code,
        }
    elif any(k in raw_vitals and raw_vitals[k] is not None for k in ("respiratory_rate", "resp_rate", "rr")):
        raw_val = next((raw_vitals[k] for k in ("respiratory_rate", "resp_rate", "rr") if k in raw_vitals and raw_vitals[k] is not None), None)
        val = float(raw_val) if raw_val is not None else 0.0
        resource["code"] = {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": LOINC_CODES["respiratory_rate"],
                    "display": "Respiratory rate",
                }
            ]
        }
        resource["valueQuantity"] = {
            "value": round(val, 1),
            "unit": "breaths/min",
            "system": "http://unitsofmeasure.org",
            "code": "/min",
        }

    return resource


def parse_all_vitals_observations(
    raw_vitals: Dict[str, Any],
    effective_dt: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Parses a multi-metric raw vitals dictionary into separate FHIR R4 Observations."""
    observations: List[Dict[str, Any]] = []

    # Blood pressure
    if raw_vitals.get("systolic") is not None and raw_vitals.get("diastolic") is not None:
        observations.append(normalize_fhir_vitals(
            {"systolic": raw_vitals["systolic"], "diastolic": raw_vitals["diastolic"]},
            effective_dt=effective_dt,
        ))

    # Heart rate
    hr_val = next((raw_vitals[k] for k in ("heart_rate", "hr") if k in raw_vitals and raw_vitals[k] is not None), None)
    if hr_val is not None:
        observations.append(normalize_fhir_vitals(
            {"heart_rate": hr_val},
            effective_dt=effective_dt,
        ))

    # Blood glucose
    glucose_val = next((raw_vitals[k] for k in ("blood_glucose", "glucose") if k in raw_vitals and raw_vitals[k] is not None), None)
    if glucose_val is not None:
        glucose_unit = raw_vitals.get("glucose_unit") or raw_vitals.get("unit") or "mg/dL"
        observations.append(normalize_fhir_vitals(
            {"blood_glucose": glucose_val, "unit": glucose_unit},
            effective_dt=effective_dt,
        ))

    # Oxygen saturation
    spo2_val = next((raw_vitals[k] for k in ("spo2", "oxygen_saturation") if k in raw_vitals and raw_vitals[k] is not None), None)
    if spo2_val is not None:
        observations.append(normalize_fhir_vitals(
            {"spo2": spo2_val},
            effective_dt=effective_dt,
        ))

    # Weight
    wt_val = next((raw_vitals[k] for k in ("weight", "body_weight") if k in raw_vitals and raw_vitals[k] is not None), None)
    if wt_val is not None:
        wt_unit = raw_vitals.get("weight_unit") or raw_vitals.get("unit") or "kg"
        observations.append(normalize_fhir_vitals(
            {"weight": wt_val, "unit": wt_unit},
            effective_dt=effective_dt,
        ))

    # Height
    ht_val = next((raw_vitals[k] for k in ("height", "body_height") if k in raw_vitals and raw_vitals[k] is not None), None)
    if ht_val is not None:
        ht_unit = raw_vitals.get("height_unit") or raw_vitals.get("unit") or "cm"
        observations.append(normalize_fhir_vitals(
            {"height": ht_val, "unit": ht_unit},
            effective_dt=effective_dt,
        ))

    # Temperature
    temp_val = next((raw_vitals[k] for k in ("temperature", "body_temperature", "temp") if k in raw_vitals and raw_vitals[k] is not None), None)
    if temp_val is not None:
        temp_unit = raw_vitals.get("temp_unit")
        if not temp_unit or temp_unit == "mg/dL":
            raw_u = raw_vitals.get("unit")
            if raw_u in ("degF", "F", "Cel", "C", "°F", "°C", "fahrenheit", "celsius"):
                temp_unit = raw_u
            else:
                temp_unit = "degF"
        observations.append(normalize_fhir_vitals(
            {"temperature": temp_val, "unit": temp_unit, "temp_unit": temp_unit},
            effective_dt=effective_dt,
        ))

    # Respiratory rate
    resp_val = next((raw_vitals[k] for k in ("respiratory_rate", "resp_rate", "rr") if k in raw_vitals and raw_vitals[k] is not None), None)
    if resp_val is not None:
        observations.append(normalize_fhir_vitals(
            {"respiratory_rate": resp_val},
            effective_dt=effective_dt,
        ))

    return observations


def classify_blood_pressure(systolic: float, diastolic: float) -> str:
    """Classifies blood pressure reading per AHA/ACC 2025 guidelines.

    Tiers:
    - Hypertensive Crisis: SBP >= 180 or DBP >= 120
    - Stage 2: SBP >= 140 or DBP >= 90
    - Stage 1: SBP 130-139 or DBP 80-89
    - Elevated: SBP 120-129 and DBP < 80
    - Normal: SBP < 120 and DBP < 80
    """
    if systolic >= 180 or diastolic >= 120:
        return "Hypertensive Crisis"
    if systolic >= 140 or diastolic >= 90:
        return "Stage 2"
    if (130 <= systolic <= 139) or (80 <= diastolic <= 89):
        return "Stage 1"
    if (120 <= systolic <= 129) and diastolic < 80:
        return "Elevated"
    if systolic < 120 and diastolic < 80:
        return "Normal"
    return "Normal"


def _extract_bp_values(reading: Dict[str, Any]) -> Optional[tuple[float, float]]:
    """Extracts systolic and diastolic floats from a reading record or FHIR Observation."""
    if "systolic" in reading and "diastolic" in reading:
        try:
            return float(reading["systolic"]), float(reading["diastolic"])
        except (ValueError, TypeError):
            pass

    # Check reading.get("data") which may be a dict or json string
    data = reading.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = None

    if isinstance(data, dict):
        components = data.get("component") or []
        sys_val = None
        dia_val = None
        for comp in components:
            codes = [c.get("code") for c in comp.get("code", {}).get("coding", [])]
            val = comp.get("valueQuantity", {}).get("value")
            if "8480-6" in codes and val is not None:
                sys_val = float(val)
            elif "8462-4" in codes and val is not None:
                dia_val = float(val)
        if sys_val is not None and dia_val is not None:
            return sys_val, dia_val

    return None


def calculate_diurnal_bp_trends(
    readings: List[Dict[str, Any]],
    now_dt: Optional[datetime] = None,
    user_tz: str = "UTC",
) -> Dict[str, Any]:
    """Calculates 7-day, 30-day, and 90-day moving averages partitioned into AM and PM windows.

    - AM Window: 05:00 - 11:59 local time (5 <= hour <= 11)
    - PM Window: 12:00 - 22:00 local time (12 <= hour < 22 or (hour == 22 and minute == 0))
    - Readings outside AM/PM windows (night hours) are excluded from daytime diurnal averages.
    - Classifies averages per AHA/ACC 2025 guideline.
    """
    try:
        tz = ZoneInfo(user_tz)
    except Exception:
        tz = ZoneInfo("UTC")

    now = (now_dt or datetime.now(timezone.utc)).astimezone(tz)
    windows: Dict[str, int] = {"7_day": 7, "30_day": 30, "90_day": 90}
    trends: Dict[str, Any] = {}

    for win_name, days in windows.items():
        cutoff = now - timedelta(days=days)
        am_sys: List[float] = []
        am_dia: List[float] = []
        pm_sys: List[float] = []
        pm_dia: List[float] = []

        for r in readings:
            eff_at = r.get("effective_at")
            if not eff_at:
                continue

            try:
                if isinstance(eff_at, datetime):
                    if eff_at.tzinfo is None:
                        eff_at = eff_at.replace(tzinfo=timezone.utc)
                    r_dt = eff_at.astimezone(tz)
                else:
                    # Clean potential trailing Z or offsets
                    eff_str = str(eff_at)
                    parsed_dt = datetime.fromisoformat(eff_str)
                    if parsed_dt.tzinfo is None:
                        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                    r_dt = parsed_dt.astimezone(tz)
            except Exception:
                continue

            if r_dt < cutoff or r_dt > now:
                continue

            bp_pair = _extract_bp_values(r)
            if not bp_pair:
                continue
            sys_val, dia_val = bp_pair

            r_hour = r_dt.hour
            r_minute = r_dt.minute

            # AM: 05:00 - 11:59
            if 5 <= r_hour <= 11:
                am_sys.append(sys_val)
                am_dia.append(dia_val)
            # PM: 12:00 - 22:00
            elif (12 <= r_hour < 22) or (r_hour == 22 and r_minute == 0):
                pm_sys.append(sys_val)
                pm_dia.append(dia_val)

        avg_am_sys = round(sum(am_sys) / len(am_sys), 1) if am_sys else None
        avg_am_dia = round(sum(am_dia) / len(am_dia), 1) if am_dia else None
        avg_pm_sys = round(sum(pm_sys) / len(pm_sys), 1) if pm_sys else None
        avg_pm_dia = round(sum(pm_dia) / len(pm_dia), 1) if pm_dia else None

        trends[win_name] = {
            "am": {
                "count": len(am_sys),
                "systolic": avg_am_sys,
                "diastolic": avg_am_dia,
                "classification": (
                    classify_blood_pressure(avg_am_sys, avg_am_dia)
                    if avg_am_sys is not None and avg_am_dia is not None
                    else "Insufficient Data"
                ),
            },
            "pm": {
                "count": len(pm_sys),
                "systolic": avg_pm_sys,
                "diastolic": avg_pm_dia,
                "classification": (
                    classify_blood_pressure(avg_pm_sys, avg_pm_dia)
                    if avg_pm_sys is not None and avg_pm_dia is not None
                    else "Insufficient Data"
                ),
            },
        }

    return trends


__all__ = [
    "LOINC_CODES",
    "MMOL_TO_MGDL",
    "LBS_TO_KG",
    "INCHES_TO_CM",
    "normalize_fhir_vitals",
    "parse_all_vitals_observations",
    "classify_blood_pressure",
    "calculate_diurnal_bp_trends",
]
