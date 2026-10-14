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

"""iOS Companion HealthKit Observation & HKClinicalRecord Synchronization and PHI-Safe Reminders (AU-62 / E10.4, E4.5).

Implements:
- `ingest_companion_sync`:
  - Category permission checks (`"vitals"` for observations, `"clinical_records"` for `HKClinicalRecord` payloads).
  - FHIR R4 `Observation` validation via `fhir.resources.R4B.observation.Observation` and idempotent upsert into
    `HealthResource(source_type="companion", source_ref=device.id)`.
  - Vitals safety red-flag evaluation (`evaluate_vitals_red_flags` / `check_vitals_red_flags`, `AU-32`) on
    blood pressure, SpO2, and blood glucose observations.
  - `HKClinicalRecord` (`E10.4`) validation across `Condition`, `MedicationRequest`, `MedicationStatement`,
    `AllergyIntolerance`, `Immunization`, and `Observation` with provenance
    `"From iOS Health Records (<device_name>), <YYYY-MM-DD>"` and `"trust": "untrusted"`.
- `list_companion_reminders`:
  - Category permission check (`"reminders"`).
  - Returns PHI-redacted local notification schedules (`E4.5`) for pending/snoozed reminders on the paired profile.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple
import uuid

from fhir.resources.R4B.allergyintolerance import AllergyIntolerance as FhirAllergyIntolerance
from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.medicationrequest import MedicationRequest as FhirMedicationRequest
from fhir.resources.R4B.medicationstatement import MedicationStatement as FhirMedicationStatement
from fhir.resources.R4B.observation import Observation as FhirObservation
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.clinical.vitals import normalize_fhir_vitals
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


def evaluate_vitals_red_flags(
    observation: Optional[Dict[str, Any]] = None,
    symptoms: Optional[List[str]] = None,
) -> VitalsEmergencyFlag:
    """Evaluates a FHIR R4 `Observation` or vitals dict against `AU-32` clinical red-flag thresholds."""
    return check_vitals_red_flags(observation=observation, symptoms=symptoms)


def _parse_effective_datetime(raw_obj: Dict[str, Any]) -> Tuple[datetime, str]:
    """Extracts a timezone-aware UTC `effective_at` datetime and `YYYY-MM-DD` date string from a FHIR/vitals dict."""
    candidates = [
        raw_obj.get("effective_at"),
        raw_obj.get("effectiveDateTime"),
        (raw_obj.get("effectivePeriod") or {}).get("start")
        if isinstance(raw_obj.get("effectivePeriod"), dict)
        else None,
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
            clean = val.strip()
            if clean.endswith("Z"):
                clean = clean[:-1] + "+00:00"
            try:
                if "T" not in clean and len(clean) == 10:
                    dt = datetime.fromisoformat(f"{clean}T00:00:00+00:00")
                else:
                    dt = datetime.fromisoformat(clean)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt_utc = dt.astimezone(timezone.utc)
                return dt_utc, dt_utc.strftime("%Y-%m-%d")
            except ValueError:
                continue

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
        candidate.setdefault("code", {"text": "HealthKit Observation"})
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
) -> Tuple[str, Dict[str, Any], datetime, str]:
    """Validates an `HKClinicalRecord` FHIR R4 resource (`E10.4`) and attaches provenance and untrusted metadata."""
    if not isinstance(raw_record, dict) or not raw_record:
        raise ValueError("Each clinical record must be a non-empty dictionary.")

    # Support either a direct FHIR R4 resource dict or an HKClinicalRecord wrapper containing 'fhirResource'/'resource'
    inner = raw_record.get("fhirResource") or raw_record.get("resource") or raw_record
    if not isinstance(inner, dict):
        raise ValueError("Invalid HKClinicalRecord resource payload.")

    rtype = str(inner.get("resourceType") or "").strip()
    if rtype not in SUPPORTED_CLINICAL_RECORD_TYPES:
        raise ValueError(
            f"Unsupported HKClinicalRecord resourceType '{rtype}'. "
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
    source_display = f"From iOS Health Records ({device_name}), {date_str}"

    normalized["source_display"] = source_display
    normalized["trust"] = "untrusted"
    normalized.setdefault("meta", {})
    if isinstance(normalized["meta"], dict):
        normalized["meta"]["source"] = source_display
        normalized["meta"]["trust"] = "untrusted"
    normalized["_carefold_provenance"] = {
        "source_name": f"iOS Health Records ({device_name})",
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
    observations: Optional[List[Dict[str, Any]]] = None,
    clinical_records: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Ingests aggregated HealthKit `Observation` readings and `HKClinicalRecord` FHIR R4 resources (`AU-62`)."""
    if device is None or device.status != "active":
        raise CompanionPairingError("Companion device must be active to synchronize records.")

    allowed_cats = set(device.allowed_categories)
    obs_list = list(observations or [])
    clin_list = list(clinical_records or [])

    if obs_list and "vitals" not in allowed_cats:
        raise CompanionPairingError(
            f"Companion device '{device.id}' is not authorized to sync 'vitals' (allowed: {sorted(allowed_cats)})."
        )

    if clin_list and "clinical_records" not in allowed_cats:
        raise CompanionPairingError(
            f"Companion device '{device.id}' is not authorized to sync 'clinical_records' "
            f"(allowed: {sorted(allowed_cats)})."
        )

    upserted_observations = 0
    upserted_clinical_records = 0
    observation_ids: List[str] = []
    clinical_record_ids: List[str] = []
    red_flags: List[Dict[str, Any]] = []

    for idx, raw_obs in enumerate(obs_list):
        effective_dt, date_str = _parse_effective_datetime(raw_obs)
        normalized_obs = _normalize_companion_observation(raw_obs, effective_dt=effective_dt)

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

    for raw_clin in clin_list:
        rtype, normalized_clin, effective_dt, source_id = _normalize_clinical_record(
            raw_clin,
            device_name=device.device_name,
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
    "evaluate_vitals_red_flags",
    "ingest_companion_sync",
    "list_companion_reminders",
]
