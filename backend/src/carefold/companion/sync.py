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

"""iOS HealthKit & Android Health Connect Companion Synchronization and PHI-Safe Reminders (AU-62, AU-75 / E10.4, E8.2, E4.5).

Implements:
- `ingest_companion_sync`:
  - Category permission checks (`"vitals"` for observations and wearable vitals, `"clinical_records"` for
    `HKClinicalRecord` and Android `Health Connect` `MedicalResource` payloads).
  - FHIR R4 `Observation` validation via `fhir.resources.R4B.observation.Observation` and idempotent upsert into
    `HealthResource(source_type="companion", source_ref=device.id)`.
  - Android `Health Connect` (`AU-75` / `E8.2`) normalization across `StepsRecord`, `HeartRateRecord`,
    `BloodPressureRecord`, `WeightRecord`, `BloodGlucoseRecord`, `OxygenSaturationRecord`, `SleepSessionRecord`,
    and `MedicalResource`, enforcing daily aggregation (`Titan S4`) for high-frequency `StepsRecord`,
    `HeartRateRecord`, and `SleepSessionRecord`.
  - Vitals safety red-flag evaluation (`evaluate_vitals_red_flags` / `check_vitals_red_flags`, `AU-32`) on
    blood pressure, SpO2, and blood glucose observations.
  - Platform-aware provenance (`"From Android Health Connect (<device_name>), <YYYY-MM-DD>"` or
    `"From iOS HealthKit/Health Records (<device_name>), <YYYY-MM-DD>"`) and `"trust": "untrusted"`.
- `list_companion_reminders`:
  - Category permission check (`"reminders"`).
  - Returns PHI-redacted local notification schedules (`E4.5`) for pending/snoozed reminders on the paired profile.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

from fhir.resources.R4B.allergyintolerance import AllergyIntolerance as FhirAllergyIntolerance
from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.medicationrequest import MedicationRequest as FhirMedicationRequest
from fhir.resources.R4B.medicationstatement import MedicationStatement as FhirMedicationStatement
from fhir.resources.R4B.observation import Observation as FhirObservation
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.clinical.vitals import LBS_TO_KG, MMOL_TO_MGDL, normalize_fhir_vitals
from carefold.companion.pairing import CompanionPairingError
from carefold.db.models import (
    AuditEventRecord,
    CompanionDevice,
    HealthResource,
    Reminder,
    utc_now,
)
from carefold.safety.vitals import VitalsEmergencyFlag, check_vitals_red_flags

_CLINICAL_RECORD_MODELS: Dict[str, Any] = {
    "Condition": FhirCondition,
    "MedicationRequest": FhirMedicationRequest,
    "MedicationStatement": FhirMedicationStatement,
    "AllergyIntolerance": FhirAllergyIntolerance,
    "Immunization": FhirImmunization,
    "Observation": FhirObservation,
}

SUPPORTED_CLINICAL_RECORD_TYPES = frozenset(_CLINICAL_RECORD_MODELS.keys())

SUPPORTED_HEALTH_CONNECT_RECORD_TYPES = frozenset({
    "StepsRecord",
    "HeartRateRecord",
    "BloodPressureRecord",
    "WeightRecord",
    "BloodGlucoseRecord",
    "OxygenSaturationRecord",
    "SleepSessionRecord",
    "MedicalResource",
})


def evaluate_vitals_red_flags(
    observation: Optional[Dict[str, Any]] = None,
    symptoms: Optional[List[str]] = None,
) -> VitalsEmergencyFlag:
    """Evaluates a FHIR R4 `Observation` or vitals dict against `AU-32` clinical red-flag thresholds."""
    return check_vitals_red_flags(observation=observation, symptoms=symptoms)


def _parse_iso_str_to_utc(raw_str: str) -> Optional[datetime]:
    """Parses an ISO-8601 timestamp or YYYY-MM-DD date string into a timezone-aware UTC datetime."""
    clean = raw_str.strip()
    if not clean:
        return None
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        if "T" not in clean and len(clean) == 10:
            dt = datetime.fromisoformat(f"{clean}T00:00:00+00:00")
        else:
            dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _parse_effective_datetime(raw_obj: Dict[str, Any]) -> Tuple[datetime, str]:
    """Extracts a timezone-aware UTC `effective_at` datetime and `YYYY-MM-DD` date string from a FHIR/vitals dict."""
    candidates = [
        raw_obj.get("effective_at"),
        raw_obj.get("effectiveDateTime"),
        (raw_obj.get("effectivePeriod") or {}).get("start")
        if isinstance(raw_obj.get("effectivePeriod"), dict)
        else None,
        raw_obj.get("time"),
        raw_obj.get("startTime"),
        raw_obj.get("endTime"),
        raw_obj.get("recordedDate"),
        raw_obj.get("onsetDateTime"),
        raw_obj.get("occurrenceDateTime"),
        raw_obj.get("authoredOn"),
        raw_obj.get("issued"),
        raw_obj.get("date"),
    ]
    for val in candidates:
        if isinstance(val, datetime):
            dt = val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
            dt_utc = dt.astimezone(timezone.utc)
            return dt_utc, dt_utc.strftime("%Y-%m-%d")
        if isinstance(val, str) and val.strip():
            parsed = _parse_iso_str_to_utc(val)
            if parsed is not None:
                return parsed, parsed.strftime("%Y-%m-%d")

    now = utc_now()
    return now, now.strftime("%Y-%m-%d")


def _normalize_companion_observation(
    raw_obs: Dict[str, Any],
    effective_dt: datetime,
) -> Dict[str, Any]:
    """Normalizes a raw vitals dict or FHIR `Observation` dict and validates it via `fhir.resources.R4B`."""
    if not isinstance(raw_obs, dict) or not raw_obs:
        raise ValueError("Each companion observation must be a non-empty dictionary.")

    flat_vital_keys = {
        "systolic",
        "diastolic",
        "heart_rate",
        "hr",
        "blood_glucose",
        "glucose",
        "spo2",
        "oxygen_saturation",
        "weight",
        "body_weight",
        "height",
        "body_height",
    }

    if raw_obs.get("resourceType") == "Observation" or "code" in raw_obs or "component" in raw_obs:
        candidate = copy.deepcopy(raw_obs)
        candidate.pop("effective_at", None)
        candidate.pop("source_id", None)
        candidate.pop("reported_symptoms", None)
        candidate.setdefault("resourceType", "Observation")
        candidate.setdefault("status", "final")
        candidate.setdefault("code", {"text": "Companion Observation"})
        candidate.setdefault("effectiveDateTime", effective_dt.isoformat())
    elif any(k in raw_obs for k in flat_vital_keys):
        candidate = normalize_fhir_vitals(raw_obs, effective_dt=effective_dt)
        if raw_obs.get("id"):
            candidate["id"] = str(raw_obs["id"])
    else:
        raise ValueError("Observation payload must be a FHIR R4 Observation or contain recognized vital sign keys.")

    validated = FhirObservation.model_validate(candidate)
    normalized = validated.model_dump(mode="json", exclude_none=True)
    return normalized


def _normalize_clinical_record(
    raw_record: Dict[str, Any],
    device_name: str,
    platform: str = "ios",
) -> Tuple[str, Dict[str, Any], datetime, str]:
    """Validates an `HKClinicalRecord` or Android `MedicalResource` FHIR R4 resource and attaches provenance."""
    if not isinstance(raw_record, dict) or not raw_record:
        raise ValueError("Each clinical record must be a non-empty dictionary.")

    inner = (
        raw_record.get("fhirResource")
        or raw_record.get("fhirData")
        or raw_record.get("resource")
        or raw_record
    )
    if isinstance(inner, str) and inner.strip().startswith("{"):
        try:
            inner = json.loads(inner)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid clinical record JSON string: {exc}") from exc

    if not isinstance(inner, dict):
        raise ValueError("Invalid clinical record resource payload.")

    # Unwrap nested data dict if Android MedicalResource uses {"fhirResource": {"data": {...}}}
    if "data" in inner and isinstance(inner["data"], dict) and "resourceType" in inner["data"]:
        inner = inner["data"]

    rtype = str(inner.get("resourceType") or "").strip()
    if rtype not in SUPPORTED_CLINICAL_RECORD_TYPES:
        raise ValueError(
            f"Unsupported clinical record resourceType '{rtype}'. "
            f"Supported: {sorted(SUPPORTED_CLINICAL_RECORD_TYPES)}"
        )

    model_cls = _CLINICAL_RECORD_MODELS[rtype]
    candidate = copy.deepcopy(inner)

    if rtype == "Observation":
        candidate.setdefault("status", "final")
        candidate.setdefault("code", {"text": "Clinical Observation"})
    elif rtype == "Condition":
        candidate.setdefault("subject", {"display": "Patient"})
    elif rtype == "MedicationRequest":
        candidate.setdefault("status", "active")
        candidate.setdefault("intent", "order")
        candidate.setdefault("subject", {"display": "Patient"})
        if "medicationCodeableConcept" not in candidate and "medicationReference" not in candidate:
            candidate["medicationCodeableConcept"] = {"text": "Medication"}
    elif rtype == "MedicationStatement":
        candidate.setdefault("status", "active")
        candidate.setdefault("subject", {"display": "Patient"})
        if "medicationCodeableConcept" not in candidate and "medicationReference" not in candidate:
            candidate["medicationCodeableConcept"] = {"text": "Medication"}
    elif rtype == "AllergyIntolerance":
        candidate.setdefault("patient", {"display": "Patient"})
    elif rtype == "Immunization":
        candidate.setdefault("status", "completed")
        candidate.setdefault("vaccineCode", {"text": "Immunization"})
        candidate.setdefault("patient", {"display": "Patient"})
        if "occurrenceDateTime" not in candidate and "occurrenceString" not in candidate:
            candidate["occurrenceDateTime"] = utc_now().strftime("%Y-%m-%d")

    validated = model_cls.model_validate(candidate)
    normalized = validated.model_dump(mode="json", exclude_none=True)

    effective_dt, date_str = _parse_effective_datetime(inner)
    clean_platform = (platform or "ios").strip().lower()
    if clean_platform == "android":
        origin_label = f"Android Health Connect ({device_name})"
    else:
        origin_label = f"iOS Health Records ({device_name})"
    source_display = f"From {origin_label}, {date_str}"

    normalized["source_display"] = source_display
    normalized["trust"] = "untrusted"
    normalized.setdefault("meta", {})
    if isinstance(normalized["meta"], dict):
        normalized["meta"]["source"] = source_display
        normalized["meta"]["trust"] = "untrusted"
    normalized["_carefold_provenance"] = {
        "source_name": origin_label,
        "source_display": source_display,
        "date": date_str,
        "trust": "untrusted",
    }

    raw_id = str(raw_record.get("id") or inner.get("id") or "").strip()
    if raw_id:
        source_id = f"{rtype}:{raw_id}"
    else:
        digest = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        source_id = f"{rtype}:{digest}"

    return rtype, normalized, effective_dt, source_id


def _extract_numeric_metric(val: Any, keys: Sequence[str] = ("value",)) -> float:
    """Extracts a float metric from a scalar or Android Health Connect unit wrapper dict."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str) and val.strip():
        return float(val.strip())
    if isinstance(val, dict):
        for k in keys:
            if k in val and val[k] is not None:
                return float(val[k])
    raise ValueError(f"Unable to extract numeric metric from {val!r}.")


def _normalize_health_connect_batch(
    hc_records: Sequence[Dict[str, Any]],
) -> Tuple[List[Tuple[str, Dict[str, Any], datetime, Optional[List[str]]]], List[Dict[str, Any]]]:
    """Normalizes Android `Health Connect` records, aggregating high-frequency streams per day (`Titan S4`).

    Returns:
        Tuple of:
        - `normalized_observations`: list of `(source_id, fhir_obs_dict, effective_dt, reported_symptoms)`
        - `medical_resources`: list of raw clinical record dicts for `_normalize_clinical_record`.
    """
    steps_by_day: Dict[str, int] = {}
    hr_samples_by_day: Dict[str, List[float]] = {}
    sleep_hours_by_day: Dict[str, float] = {}

    point_observations: List[Tuple[str, Dict[str, Any], datetime, Optional[List[str]]]] = []
    medical_resources: List[Dict[str, Any]] = []

    for idx, rec in enumerate(hc_records):
        if not isinstance(rec, dict) or not rec:
            raise ValueError("Each Health Connect record must be a non-empty dictionary.")

        raw_type = str(rec.get("recordType") or rec.get("type") or "").strip()
        # Infer MedicalResource if a FHIR resource is passed directly
        if not raw_type and (
            "fhirResource" in rec
            or "fhirData" in rec
            or rec.get("resourceType") in SUPPORTED_CLINICAL_RECORD_TYPES
        ):
            raw_type = "MedicalResource"

        effective_dt, date_str = _parse_effective_datetime(rec)
        symptoms = rec.get("reported_symptoms") if isinstance(rec.get("reported_symptoms"), list) else None

        if raw_type in ("StepsRecord", "Steps"):
            count_val = int(round(_extract_numeric_metric(rec.get("count", 0), ("value", "count"))))
            if count_val < 0:
                raise ValueError("StepsRecord count cannot be negative.")
            steps_by_day[date_str] = steps_by_day.get(date_str, 0) + count_val

        elif raw_type in ("HeartRateRecord", "HeartRate"):
            samples = rec.get("samples")
            day_bpms = hr_samples_by_day.setdefault(date_str, [])
            if isinstance(samples, list) and samples:
                for sample in samples:
                    if isinstance(sample, dict):
                        _, sample_date = _parse_effective_datetime(sample)
                        target_date = sample_date if "time" in sample else date_str
                        bpm = _extract_numeric_metric(
                            sample.get("beatsPerMinute") or sample.get("bpm") or sample.get("value"),
                            ("beatsPerMinute", "bpm", "value"),
                        )
                        hr_samples_by_day.setdefault(target_date, []).append(bpm)
            else:
                bpm = _extract_numeric_metric(
                    rec.get("beatsPerMinute") or rec.get("bpm") or rec.get("heart_rate") or rec.get("value"),
                    ("beatsPerMinute", "bpm", "value"),
                )
                day_bpms.append(bpm)

        elif raw_type in ("SleepSessionRecord", "SleepSession"):
            if "durationHours" in rec or "hours" in rec:
                hours = float(rec.get("durationHours") or rec["hours"])
            elif "durationMinutes" in rec or "minutes" in rec:
                hours = float(rec.get("durationMinutes") or rec["minutes"]) / 60.0
            else:
                start_dt = _parse_iso_str_to_utc(str(rec.get("startTime") or ""))
                end_dt = _parse_iso_str_to_utc(str(rec.get("endTime") or ""))
                if start_dt and end_dt and end_dt > start_dt:
                    hours = (end_dt - start_dt).total_seconds() / 3600.0
                else:
                    hours = 0.0
            sleep_hours_by_day[date_str] = sleep_hours_by_day.get(date_str, 0.0) + max(0.0, hours)

        elif raw_type in ("BloodPressureRecord", "BloodPressure"):
            sys_val = _extract_numeric_metric(
                rec.get("systolic"),
                ("inMillimetersOfMercury", "mmHg", "value"),
            )
            dia_val = _extract_numeric_metric(
                rec.get("diastolic"),
                ("inMillimetersOfMercury", "mmHg", "value"),
            )
            obs_candidate = normalize_fhir_vitals(
                {"systolic": sys_val, "diastolic": dia_val},
                effective_dt=effective_dt,
            )
            raw_id = str(rec.get("id") or (rec.get("metadata") or {}).get("id") or f"hc-bp-{idx}-{date_str}")
            obs_candidate["id"] = raw_id
            validated = FhirObservation.model_validate(obs_candidate).model_dump(mode="json", exclude_none=True)
            point_observations.append((f"Observation:{raw_id}", validated, effective_dt, symptoms))

        elif raw_type in ("WeightRecord", "Weight"):
            w_raw = rec.get("weight") if "weight" in rec else rec.get("value")
            if isinstance(w_raw, dict) and "inPounds" in w_raw:
                weight_kg = float(w_raw["inPounds"]) / LBS_TO_KG
            else:
                weight_kg = _extract_numeric_metric(w_raw, ("inKilograms", "kg", "value"))
            obs_candidate = normalize_fhir_vitals(
                {"weight": round(weight_kg, 2), "unit": "kg"},
                effective_dt=effective_dt,
            )
            raw_id = str(rec.get("id") or (rec.get("metadata") or {}).get("id") or f"hc-wt-{idx}-{date_str}")
            obs_candidate["id"] = raw_id
            validated = FhirObservation.model_validate(obs_candidate).model_dump(mode="json", exclude_none=True)
            point_observations.append((f"Observation:{raw_id}", validated, effective_dt, symptoms))

        elif raw_type in ("BloodGlucoseRecord", "BloodGlucose"):
            bg_raw = rec.get("level") or rec.get("blood_glucose") or rec.get("glucose") or rec.get("value")
            if isinstance(bg_raw, dict) and "inMillimolesPerLiter" in bg_raw:
                bg_mgdl = float(bg_raw["inMillimolesPerLiter"]) * MMOL_TO_MGDL
            else:
                bg_mgdl = _extract_numeric_metric(
                    bg_raw,
                    ("inMilligramsPerDeciliter", "mg/dL", "value"),
                )
            obs_candidate = normalize_fhir_vitals(
                {"blood_glucose": round(bg_mgdl, 1), "unit": "mg/dL"},
                effective_dt=effective_dt,
            )
            raw_id = str(rec.get("id") or (rec.get("metadata") or {}).get("id") or f"hc-bg-{idx}-{date_str}")
            obs_candidate["id"] = raw_id
            validated = FhirObservation.model_validate(obs_candidate).model_dump(mode="json", exclude_none=True)
            point_observations.append((f"Observation:{raw_id}", validated, effective_dt, symptoms))

        elif raw_type in ("OxygenSaturationRecord", "OxygenSaturation"):
            spo2_raw = rec.get("percentage") or rec.get("spo2") or rec.get("oxygen_saturation") or rec.get("value")
            spo2_val = _extract_numeric_metric(spo2_raw, ("value", "percentage"))
            obs_candidate = normalize_fhir_vitals(
                {"spo2": round(spo2_val, 1)},
                effective_dt=effective_dt,
            )
            raw_id = str(rec.get("id") or (rec.get("metadata") or {}).get("id") or f"hc-spo2-{idx}-{date_str}")
            obs_candidate["id"] = raw_id
            validated = FhirObservation.model_validate(obs_candidate).model_dump(mode="json", exclude_none=True)
            point_observations.append((f"Observation:{raw_id}", validated, effective_dt, symptoms))

        elif raw_type == "MedicalResource":
            medical_resources.append(rec)

        else:
            raise ValueError(
                f"Unsupported Android Health Connect recordType '{raw_type}'. "
                f"Supported: {sorted(SUPPORTED_HEALTH_CONNECT_RECORD_TYPES)}"
            )

    aggregated_observations: List[Tuple[str, Dict[str, Any], datetime, Optional[List[str]]]] = []

    # 1. Daily aggregated StepsRecord (Titan S4)
    for date_str in sorted(steps_by_day.keys()):
        total_steps = steps_by_day[date_str]
        day_dt = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
        rec_id = f"hc-steps-{date_str}"
        steps_obs = FhirObservation.model_validate({
            "resourceType": "Observation",
            "id": rec_id,
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "activity",
                            "display": "Activity",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "41950-7",
                        "display": "Number of steps in 24 hour Measured",
                    }
                ],
                "text": "Daily Step Count",
            },
            "effectivePeriod": {
                "start": f"{date_str}T00:00:00+00:00",
                "end": f"{date_str}T23:59:59+00:00",
            },
            "valueQuantity": {
                "value": total_steps,
                "unit": "steps/day",
                "system": "http://unitsofmeasure.org",
                "code": "{steps}/d",
            },
        }).model_dump(mode="json", exclude_none=True)
        aggregated_observations.append((f"Observation:{rec_id}", steps_obs, day_dt, None))

    # 2. Daily aggregated HeartRateRecord (Titan S4)
    for date_str in sorted(hr_samples_by_day.keys()):
        bpms = hr_samples_by_day[date_str]
        if not bpms:
            continue
        avg_bpm = round(sum(bpms) / len(bpms), 1)
        min_bpm = round(min(bpms), 1)
        max_bpm = round(max(bpms), 1)
        day_dt = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
        rec_id = f"hc-hr-{date_str}"
        hr_obs = FhirObservation.model_validate({
            "resourceType": "Observation",
            "id": rec_id,
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
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "8867-4",
                        "display": "Heart rate",
                    }
                ],
                "text": "Daily Heart Rate Summary",
            },
            "effectivePeriod": {
                "start": f"{date_str}T00:00:00+00:00",
                "end": f"{date_str}T23:59:59+00:00",
            },
            "valueQuantity": {
                "value": avg_bpm,
                "unit": "bpm",
                "system": "http://unitsofmeasure.org",
                "code": "/min",
            },
            "component": [
                {
                    "code": {"text": "Minimum heart rate"},
                    "valueQuantity": {"value": min_bpm, "unit": "bpm", "system": "http://unitsofmeasure.org", "code": "/min"},
                },
                {
                    "code": {"text": "Maximum heart rate"},
                    "valueQuantity": {"value": max_bpm, "unit": "bpm", "system": "http://unitsofmeasure.org", "code": "/min"},
                },
            ],
        }).model_dump(mode="json", exclude_none=True)
        aggregated_observations.append((f"Observation:{rec_id}", hr_obs, day_dt, None))

    # 3. Daily aggregated SleepSessionRecord (Titan S4)
    for date_str in sorted(sleep_hours_by_day.keys()):
        total_hours = round(sleep_hours_by_day[date_str], 2)
        day_dt = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
        rec_id = f"hc-sleep-{date_str}"
        sleep_obs = FhirObservation.model_validate({
            "resourceType": "Observation",
            "id": rec_id,
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "93832-4",
                        "display": "Sleep duration",
                    }
                ],
                "text": "Daily Sleep Duration",
            },
            "effectivePeriod": {
                "start": f"{date_str}T00:00:00+00:00",
                "end": f"{date_str}T23:59:59+00:00",
            },
            "valueQuantity": {
                "value": total_hours,
                "unit": "h",
                "system": "http://unitsofmeasure.org",
                "code": "h",
            },
        }).model_dump(mode="json", exclude_none=True)
        aggregated_observations.append((f"Observation:{rec_id}", sleep_obs, day_dt, None))

    return aggregated_observations + point_observations, medical_resources


async def _upsert_companion_health_resource(
    session: AsyncSession,
    profile_id: str,
    device_id: str,
    resource_type: str,
    source_id: str,
    data: Dict[str, Any],
    effective_at: datetime,
) -> HealthResource:
    """Idempotently upserts a companion-sourced `HealthResource` row."""
    content_hash = hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    now = utc_now()

    stmt = select(HealthResource).where(
        HealthResource.profile_id == profile_id,
        HealthResource.source_type == "companion",
        HealthResource.source_ref == device_id,
        HealthResource.source_id == source_id,
    )
    res = await session.execute(stmt)
    existing = res.scalar_one_or_none()

    if existing is not None:
        existing.resource_type = resource_type.lower()
        existing.content_hash = content_hash
        existing.data = data
        existing.status = "active"
        existing.effective_at = effective_at
        existing.updated_at = now
        return existing

    record = HealthResource(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        resource_type=resource_type.lower(),
        source_type="companion",
        source_ref=device_id,
        source_id=source_id,
        content_hash=content_hash,
        data=data,
        status="active",
        effective_at=effective_at,
        recorded_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    return record


async def ingest_companion_sync(
    session: AsyncSession,
    device: CompanionDevice,
    observations: Optional[Sequence[Dict[str, Any]]] = None,
    clinical_records: Optional[Sequence[Dict[str, Any]]] = None,
    health_connect_records: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Ingests iOS HealthKit or Android Health Connect observations and clinical records (`AU-62`, `AU-75`)."""
    if device is None or device.status != "active":
        raise CompanionPairingError("Companion device must be active to synchronize records.")

    allowed_cats = set(device.allowed_categories)
    obs_list = list(observations or [])
    clin_list = list(clinical_records or [])
    hc_list = list(health_connect_records or [])

    hc_observations, hc_medical_resources = _normalize_health_connect_batch(hc_list) if hc_list else ([], [])

    if (obs_list or hc_observations) and "vitals" not in allowed_cats:
        raise CompanionPairingError(
            f"Companion device '{device.id}' is not authorized to sync 'vitals' (allowed: {sorted(allowed_cats)})."
        )

    if (clin_list or hc_medical_resources) and "clinical_records" not in allowed_cats:
        raise CompanionPairingError(
            f"Companion device '{device.id}' is not authorized to sync 'clinical_records' "
            f"(allowed: {sorted(allowed_cats)})."
        )

    is_android = (device.platform or "ios").strip().lower() == "android"
    upserted_observations = 0
    upserted_clinical_records = 0
    observation_ids: List[str] = []
    clinical_record_ids: List[str] = []
    red_flags: List[Dict[str, Any]] = []

    # 1. Process direct observations
    for idx, raw_obs in enumerate(obs_list):
        effective_dt, date_str = _parse_effective_datetime(raw_obs)
        normalized_obs = _normalize_companion_observation(raw_obs, effective_dt=effective_dt)

        if is_android:
            source_display = f"From Android Health Connect ({device.device_name}), {date_str}"
        else:
            source_display = f"From iOS HealthKit ({device.device_name}), {date_str}"
        normalized_obs["source_display"] = source_display

        raw_id = str(raw_obs.get("id") or raw_obs.get("source_id") or normalized_obs.get("id") or "").strip()
        if raw_id:
            source_id = f"Observation:{raw_id}" if not raw_id.startswith("Observation:") else raw_id
        else:
            digest = hashlib.sha256(
                json.dumps(normalized_obs, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:16]
            source_id = f"Observation:{idx}:{digest}"

        hr = await _upsert_companion_health_resource(
            session=session,
            profile_id=device.profile_id,
            device_id=device.id,
            resource_type="observation",
            source_id=source_id,
            data=normalized_obs,
            effective_at=effective_dt,
        )
        upserted_observations += 1
        observation_ids.append(hr.id)

        symptoms = raw_obs.get("reported_symptoms") if isinstance(raw_obs, dict) else None
        flag = evaluate_vitals_red_flags(normalized_obs, symptoms=symptoms)
        if flag.triggered:
            flag_dict = flag.to_dict()
            flag_dict["resource_id"] = hr.id
            flag_dict["source_id"] = source_id
            red_flags.append(flag_dict)

    # 2. Process normalized Android Health Connect observations (including daily-aggregated steps/HR/sleep)
    for source_id, hc_obs, effective_dt, symptoms in hc_observations:
        date_str = effective_dt.strftime("%Y-%m-%d")
        source_display = f"From Android Health Connect ({device.device_name}), {date_str}"
        hc_obs["source_display"] = source_display
        hc_obs["trust"] = "untrusted"
        hc_obs["_carefold_provenance"] = {
            "source_name": f"Android Health Connect ({device.device_name})",
            "source_display": source_display,
            "date": date_str,
            "trust": "untrusted",
        }

        hr = await _upsert_companion_health_resource(
            session=session,
            profile_id=device.profile_id,
            device_id=device.id,
            resource_type="observation",
            source_id=source_id,
            data=hc_obs,
            effective_at=effective_dt,
        )
        upserted_observations += 1
        observation_ids.append(hr.id)

        flag = evaluate_vitals_red_flags(hc_obs, symptoms=symptoms)
        if flag.triggered:
            flag_dict = flag.to_dict()
            flag_dict["resource_id"] = hr.id
            flag_dict["source_id"] = source_id
            red_flags.append(flag_dict)

    # 3. Process clinical records (HKClinicalRecord + Android Health Connect MedicalResource)
    combined_clinical = [
        (raw_clin, device.platform or "ios") for raw_clin in clin_list
    ] + [
        (raw_med, "android") for raw_med in hc_medical_resources
    ]
    for raw_clin, rec_platform in combined_clinical:
        rtype, normalized_clin, effective_dt, source_id = _normalize_clinical_record(
            raw_clin,
            device_name=device.device_name,
            platform=rec_platform,
        )
        hr = await _upsert_companion_health_resource(
            session=session,
            profile_id=device.profile_id,
            device_id=device.id,
            resource_type=rtype.lower(),
            source_id=source_id,
            data=normalized_clin,
            effective_at=effective_dt,
        )
        upserted_clinical_records += 1
        clinical_record_ids.append(hr.id)

        if rtype == "Observation":
            flag = evaluate_vitals_red_flags(normalized_clin)
            if flag.triggered:
                flag_dict = flag.to_dict()
                flag_dict["resource_id"] = hr.id
                flag_dict["source_id"] = source_id
                red_flags.append(flag_dict)

    now = utc_now()
    device.last_seen_at = now
    device.updated_at = now

    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "device_id": device.id,
                "profile_id": device.profile_id,
                "platform": device.platform,
                "upserted_observations": upserted_observations,
                "upserted_clinical_records": upserted_clinical_records,
                "red_flags_count": len(red_flags),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit_record = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=device.profile_id,
        actor_user_id=device.user_id,
        principal="connector",
        event="companion_sync",
        tool="ingest_companion_sync",
        risk="write_local",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"companion_device:{device.id}",
        detail_redacted=json.dumps({
            "device_id": device.id,
            "platform": device.platform,
            "upserted_observations": upserted_observations,
            "upserted_clinical_records": upserted_clinical_records,
            "red_flags_count": len(red_flags),
        }),
    )
    session.add(audit_record)
    await session.commit()

    return {
        "device_id": device.id,
        "profile_id": device.profile_id,
        "platform": device.platform,
        "upserted_observations": upserted_observations,
        "upserted_clinical_records": upserted_clinical_records,
        "observation_ids": observation_ids,
        "clinical_record_ids": clinical_record_ids,
        "red_flags": red_flags,
    }


async def list_companion_reminders(
    session: AsyncSession,
    device: CompanionDevice,
) -> List[Dict[str, Any]]:
    """Returns PHI-redacted local notification payloads (`E4.5`) for pending/snoozed reminders on `device.profile_id`."""
    if device is None or device.status != "active":
        raise CompanionPairingError("Companion device must be active to fetch reminders.")

    allowed_cats = set(device.allowed_categories)
    if "reminders" not in allowed_cats:
        raise CompanionPairingError(
            f"Companion device '{device.id}' is not authorized to read 'reminders' "
            f"(allowed: {sorted(allowed_cats)})."
        )

    stmt = (
        select(Reminder)
        .where(
            Reminder.profile_id == device.profile_id,
            Reminder.status.in_(("pending", "snoozed")),
        )
        .order_by(Reminder.next_due_at.asc())
    )
    res = await session.execute(stmt)
    reminders = list(res.scalars().all())

    now = utc_now()
    device.last_seen_at = now
    device.updated_at = now
    await session.commit()

    payloads: List[Dict[str, Any]] = []
    for r in reminders:
        cat_label = (r.category or "general").strip().title()
        sanitized_title = f"Carefold {cat_label} Reminder"
        sanitized_body = "Open Carefold to view your scheduled health reminder."
        payloads.append({
            "id": r.id,
            "reminder_id": r.id,
            "profile_id": r.profile_id,
            "category": r.category,
            "title": sanitized_title,
            "body": sanitized_body,
            "description": sanitized_body,
            "phi_redacted": True,
            "next_due_at": r.next_due_at.isoformat() if r.next_due_at else None,
            "snooze_until": r.snooze_until.isoformat() if r.snooze_until else None,
            "timezone": r.timezone,
            "rrule": r.rrule,
            "status": r.status,
        })

    return payloads


__all__ = [
    "SUPPORTED_CLINICAL_RECORD_TYPES",
    "SUPPORTED_HEALTH_CONNECT_RECORD_TYPES",
    "evaluate_vitals_red_flags",
    "ingest_companion_sync",
    "list_companion_reminders",
]
