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

"""Pediatric School Health Forms, Draft Prefill Compiler & Under-13 Safeguards (AU-39 / E11).

Implements:
- `compile_school_form_prefill`: Compiles draft prefill JSON from Profile and HealthResource records
  (immunisations, allergies, active medications, and latest height/weight/BP vitals) with explicit
  non-auto-submit disclaimer.
- `create_school_form`: Persists a SchoolForm record and automatically creates a 30-day advance
  renewal Reminder when `expires_at` is provided.
- `check_under_13_safeguards`: Enforces E11.6 under-13 child profile invariants
  (`guardian_only=True`, `allow_child_login=False`, `allow_external_writes=False`, `telemetry_enabled=False`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Literal, Optional, Sequence, Set, Union
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import (
    AuditEventRecord,
    HealthResource,
    Job,
    Profile,
    Reminder,
    SchoolForm,
    User,
)

logger = logging.getLogger("carefold.clinical.school_forms")


async def _resolve_actor_user_id(
    session: AsyncSession,
    profile_id: str,
    actor_user_id: Optional[str],
) -> Optional[str]:
    """Resolves a valid User.id for FK columns (AuditEventRecord.actor_user_id)."""
    if actor_user_id and str(actor_user_id).strip():
        candidate = str(actor_user_id).strip()
        user_res = await session.execute(select(User.id).where(User.id == candidate))
        if user_res.scalar_one_or_none() is not None:
            return candidate
    prof_res = await session.execute(select(Profile.user_id).where(Profile.id == profile_id))
    return prof_res.scalar_one_or_none()

SchoolFormTypeLiteral = Literal[
    "physical",
    "immunization",
    "medication_authorization",
    "sports_clearance",
    "general",
]
SchoolFormStatusLiteral = Literal["draft", "active", "expired", "archived"]

VALID_SCHOOL_FORM_TYPES: Set[str] = {
    "physical",
    "immunization",
    "medication_authorization",
    "sports_clearance",
    "general",
}
VALID_SCHOOL_FORM_STATUSES: Set[str] = {
    "draft",
    "active",
    "expired",
    "archived",
}

SCHOOL_FORM_DISCLAIMER: str = (
    "Draft prefill generated from your saved records for parent and clinician review. Never auto-submitted."
)

UNDER_13_CUTOFF_MONTHS: int = 156  # 13 years = 156 months


def _parse_data_dict(raw_data: Any) -> Dict[str, Any]:
    """Safely normalizes a HealthResource.data field into a dictionary."""
    if isinstance(raw_data, dict):
        return raw_data
    if isinstance(raw_data, str):
        try:
            parsed = json.loads(raw_data)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _extract_display_name(data: Dict[str, Any], fallback_keys: Sequence[str] = ()) -> str:
    """Extracts a human-readable display string from FHIR CodeableConcept or simple dict keys."""
    for k in fallback_keys:
        val = data.get(k)
        if isinstance(val, str) and val.strip():
            return val.strip()

    for concept_key in ("vaccineCode", "medicationCodeableConcept", "code", "substance"):
        concept = data.get(concept_key)
        if isinstance(concept, str) and concept.strip():
            return concept.strip()
        if isinstance(concept, dict):
            text_val = concept.get("text") or concept.get("display")
            if isinstance(text_val, str) and text_val.strip():
                return text_val.strip()
            coding = concept.get("coding")
            if isinstance(coding, list):
                for c in coding:
                    if isinstance(c, dict):
                        disp = c.get("display") or c.get("text") or c.get("code")
                        if isinstance(disp, str) and disp.strip():
                            return disp.strip()

    for generic_key in ("title", "name", "display", "description"):
        val = data.get(generic_key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    return "Recorded Entry"


def _extract_code_string(data: Dict[str, Any]) -> Optional[str]:
    """Extracts primary code identifier from a FHIR resource dictionary."""
    for key in ("cvx_code", "loinc_code", "cpt_code", "rxnorm_code", "code_value"):
        if data.get(key) is not None and str(data[key]).strip():
            return str(data[key]).strip()

    for concept_key in ("vaccineCode", "medicationCodeableConcept", "code"):
        concept = data.get(concept_key)
        if isinstance(concept, dict):
            if concept.get("code") is not None:
                return str(concept["code"]).strip()
            coding = concept.get("coding")
            if isinstance(coding, list) and coding:
                first = coding[0]
                if isinstance(first, dict) and first.get("code") is not None:
                    return str(first["code"]).strip()
    return None


def _extract_vital_from_observation(
    data: Dict[str, Any],
    effective_iso: str,
) -> Dict[str, Any]:
    """Extracts height, weight, or blood_pressure from an Observation resource dictionary."""
    extracted: Dict[str, Any] = {}

    # 1. Direct keys on data
    if data.get("height") is not None or data.get("body_height") is not None:
        val = data.get("height") if data.get("height") is not None else data.get("body_height")
        unit = data.get("height_unit") or data.get("unit") or "cm"
        extracted["height"] = {"value": val, "unit": unit, "effective_at": effective_iso}

    if data.get("weight") is not None or data.get("body_weight") is not None:
        val = data.get("weight") if data.get("weight") is not None else data.get("body_weight")
        unit = data.get("weight_unit") or data.get("unit") or "kg"
        extracted["weight"] = {"value": val, "unit": unit, "effective_at": effective_iso}

    if data.get("systolic") is not None and data.get("diastolic") is not None:
        extracted["blood_pressure"] = {
            "systolic": data["systolic"],
            "diastolic": data["diastolic"],
            "unit": "mmHg",
            "display": f"{data['systolic']}/{data['diastolic']} mmHg",
            "effective_at": effective_iso,
        }
    elif isinstance(data.get("blood_pressure"), (str, dict)):
        extracted["blood_pressure"] = data["blood_pressure"]

    # 2. FHIR R4 Observation code & valueQuantity
    code_obj = data.get("code")
    codings = code_obj.get("coding", []) if isinstance(code_obj, dict) else []
    vq = data.get("valueQuantity") if isinstance(data.get("valueQuantity"), dict) else {}

    for c in codings:
        if not isinstance(c, dict):
            continue
        c_code = str(c.get("code") or "").strip()
        c_disp = str(c.get("display") or "").lower()
        if (c_code == "8302-2" or "height" in c_disp) and vq.get("value") is not None:
            extracted.setdefault(
                "height",
                {
                    "value": vq["value"],
                    "unit": vq.get("unit", "cm"),
                    "effective_at": effective_iso,
                },
            )
        elif (c_code == "29463-7" or "weight" in c_disp) and vq.get("value") is not None:
            extracted.setdefault(
                "weight",
                {
                    "value": vq["value"],
                    "unit": vq.get("unit", "kg"),
                    "effective_at": effective_iso,
                },
            )

    # 3. FHIR R4 Observation components (e.g. blood pressure 85354-9 panel)
    components = data.get("component")
    if isinstance(components, list):
        sys_val = None
        dia_val = None
        for comp in components:
            if not isinstance(comp, dict):
                continue
            comp_codings = comp.get("code", {}).get("coding", []) if isinstance(comp.get("code"), dict) else []
            comp_vq = comp.get("valueQuantity") if isinstance(comp.get("valueQuantity"), dict) else {}
            comp_val = comp_vq.get("value")
            for cc in comp_codings:
                if not isinstance(cc, dict):
                    continue
                code_str = str(cc.get("code") or "")
                if code_str == "8480-6" and comp_val is not None:
                    sys_val = comp_val
                elif code_str == "8462-4" and comp_val is not None:
                    dia_val = comp_val
                elif code_str == "8302-2" and comp_val is not None:
                    extracted.setdefault(
                        "height",
                        {"value": comp_val, "unit": comp_vq.get("unit", "cm"), "effective_at": effective_iso},
                    )
                elif code_str == "29463-7" and comp_val is not None:
                    extracted.setdefault(
                        "weight",
                        {"value": comp_val, "unit": comp_vq.get("unit", "kg"), "effective_at": effective_iso},
                    )
        if sys_val is not None and dia_val is not None:
            extracted.setdefault(
                "blood_pressure",
                {
                    "systolic": sys_val,
                    "diastolic": dia_val,
                    "unit": "mmHg",
                    "display": f"{sys_val}/{dia_val} mmHg",
                    "effective_at": effective_iso,
                },
            )

    return extracted


async def compile_school_form_prefill(
    session: AsyncSession,
    profile_id: str,
) -> Dict[str, Any]:
    """Compiles a structured draft prefill dictionary from saved Profile & HealthResource rows (E11.3).

    Never auto-submits; includes explicit parent/clinician review disclaimer.
    """
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required.")

    prof_stmt = select(Profile).where(Profile.id == clean_profile_id)
    prof_res = await session.execute(prof_stmt)
    profile = prof_res.scalar_one_or_none()
    if profile is None:
        raise ValueError(f"Profile '{clean_profile_id}' not found.")

    hr_stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == clean_profile_id,
            HealthResource.status == "active",
        )
        .order_by(HealthResource.effective_at.desc(), HealthResource.recorded_at.desc())
    )
    hr_res = await session.execute(hr_stmt)
    resources = list(hr_res.scalars().all())

    immunisations: List[Dict[str, Any]] = []
    allergies: List[Dict[str, Any]] = []
    medications: List[Dict[str, Any]] = []
    latest_height: Optional[Dict[str, Any]] = None
    latest_weight: Optional[Dict[str, Any]] = None
    latest_bp: Optional[Dict[str, Any]] = None

    for hr in resources:
        rtype = (hr.resource_type or "").strip().lower()
        data = _parse_data_dict(hr.data)
        eff_iso = hr.effective_at.isoformat() if hr.effective_at else None
        eff_date = hr.effective_at.date().isoformat() if hr.effective_at else None

        if rtype in ("immunization", "immunisation"):
            vaccine_name = _extract_display_name(data, fallback_keys=("vaccine", "vaccine_name", "title", "name"))
            occ_date = data.get("occurrenceDateTime") or data.get("date") or eff_date
            immunisations.append({
                "id": hr.id,
                "vaccine": vaccine_name,
                "name": vaccine_name,
                "code": _extract_code_string(data),
                "date": str(occ_date) if occ_date else eff_date,
                "status": str(data.get("status") or "completed"),
            })
        elif rtype in ("allergy_intolerance", "allergyintolerance", "allergy"):
            substance = _extract_display_name(data, fallback_keys=("allergen", "substance", "title", "name"))
            reaction = data.get("reaction")
            if isinstance(reaction, list) and reaction:
                first_rx = reaction[0]
                if isinstance(first_rx, dict):
                    manif = first_rx.get("manifestation")
                    if isinstance(manif, list) and manif and isinstance(manif[0], dict):
                        reaction_str = manif[0].get("text") or manif[0].get("display")
                    else:
                        reaction_str = first_rx.get("description")
                else:
                    reaction_str = str(first_rx)
            elif isinstance(reaction, str):
                reaction_str = reaction
            else:
                reaction_str = None

            allergies.append({
                "id": hr.id,
                "substance": substance,
                "allergen": substance,
                "criticality": data.get("criticality") or data.get("severity") or "unknown",
                "reaction": reaction_str,
                "recorded_date": eff_date,
            })
        elif rtype in ("medication_statement", "medicationstatement", "medication_request", "medicationrequest", "medication"):
            med_name = _extract_display_name(data, fallback_keys=("medication", "medication_name", "title", "name"))
            dosage_val = data.get("dosage")
            if isinstance(dosage_val, list) and dosage_val:
                first_d = dosage_val[0]
                dosage_str = first_d.get("text") if isinstance(first_d, dict) else str(first_d)
            elif isinstance(dosage_val, str):
                dosage_str = dosage_val
            else:
                dosage_str = data.get("dose")

            medications.append({
                "id": hr.id,
                "medication": med_name,
                "name": med_name,
                "dosage": dosage_str,
                "status": str(data.get("status") or "active"),
            })
        elif rtype == "observation":
            vitals_found = _extract_vital_from_observation(data, eff_iso or "")
            if latest_height is None and "height" in vitals_found:
                latest_height = vitals_found["height"]
            if latest_weight is None and "weight" in vitals_found:
                latest_weight = vitals_found["weight"]
            if latest_bp is None and "blood_pressure" in vitals_found:
                latest_bp = vitals_found["blood_pressure"]

    return {
        "profile_id": profile.id,
        "student_name": profile.name,
        "date_of_birth": profile.date_of_birth,
        "relationship": profile.relationship,
        "immunisations": immunisations,
        "allergies": allergies,
        "medications": medications,
        "latest_vitals": {
            "height": latest_height,
            "weight": latest_weight,
            "blood_pressure": latest_bp,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "auto_submitted": False,
        "disclaimer": SCHOOL_FORM_DISCLAIMER,
    }


def _parse_optional_datetime(val: Optional[Union[datetime, str]]) -> Optional[datetime]:
    """Parses an optional datetime or ISO-8601 string into a UTC-aware datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc) if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str) and val.strip():
        clean = val.strip()
        if len(clean) == 10 and clean.count("-") == 2:
            dt = datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt
        parsed = datetime.fromisoformat(clean)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


async def create_school_form(
    session: AsyncSession,
    profile_id: str,
    title: str,
    *,
    school_or_camp_name: Optional[str] = None,
    form_type: str = "general",
    attachment_id: Optional[str] = None,
    expires_at: Optional[Union[datetime, str]] = None,
    status: str = "draft",
    actor_user_id: Optional[str] = None,
) -> SchoolForm:
    """Creates a SchoolForm with compiled draft prefill and optional 30-day advance renewal Reminder."""
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required.")

    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("Parameter 'title' must be a non-empty string.")

    clean_type = (form_type or "general").strip().lower()
    if clean_type not in VALID_SCHOOL_FORM_TYPES:
        raise ValueError(
            f"Invalid form_type '{form_type}'. Permitted: {sorted(VALID_SCHOOL_FORM_TYPES)}."
        )

    clean_status = (status or "draft").strip().lower()
    if clean_status not in VALID_SCHOOL_FORM_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Permitted: {sorted(VALID_SCHOOL_FORM_STATUSES)}."
        )

    expires_dt = _parse_optional_datetime(expires_at)
    prefill_dict = await compile_school_form_prefill(session, clean_profile_id)
    now_utc = datetime.now(timezone.utc)

    reminder_id: Optional[str] = None
    if expires_dt is not None:
        rem_id = str(uuid.uuid4())
        candidate_due = expires_dt - timedelta(days=30)
        next_due_dt = candidate_due if candidate_due > now_utc else expires_dt

        reminder = Reminder(
            id=rem_id,
            profile_id=clean_profile_id,
            title=f"Renew school form: {clean_title}",
            description=(
                f"Annual school/camp health form '{clean_title}' "
                f"({school_or_camp_name or 'institution'}) expires on {expires_dt.date().isoformat()}."
            ),
            category="prep",
            timezone="UTC",
            next_due_at=next_due_dt,
            status="pending",
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(reminder)

        job = Job(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            kind="reminder",
            payload=json.dumps({"reminder_id": rem_id, "school_form_title": clean_title}),
            timezone="UTC",
            next_run_at=next_due_dt,
            status="pending",
            idempotency_key=f"reminder:{rem_id}",
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(job)
        await session.flush()
        reminder_id = rem_id

    form_id = str(uuid.uuid4())
    school_form = SchoolForm(
        id=form_id,
        profile_id=clean_profile_id,
        attachment_id=attachment_id,
        title=clean_title,
        school_or_camp_name=school_or_camp_name.strip() if school_or_camp_name else None,
        form_type=clean_type,
        expires_at=expires_dt,
        reminder_id=reminder_id,
        prefill_draft_json=json.dumps(prefill_dict),
        status=clean_status,
        created_at=now_utc,
        updated_at=now_utc,
    )
    session.add(school_form)

    resolved_actor_id = await _resolve_actor_user_id(session, clean_profile_id, actor_user_id)
    audit_rec = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now_utc,
        profile_id=clean_profile_id,
        actor_user_id=resolved_actor_id,
        principal="user",
        event="tool",
        tool="create_school_form",
        risk="write_local",
        decision="allow",
        external_ref=f"school_form:{form_id}",
        detail_redacted=json.dumps({
            "title": clean_title,
            "form_type": clean_type,
            "status": clean_status,
            "reminder_id": reminder_id,
        }),
    )
    session.add(audit_rec)
    await session.commit()
    await session.refresh(school_form)

    return school_form


async def regenerate_school_form_prefill(
    session: AsyncSession,
    profile_id: str,
    form_id: str,
    *,
    actor_user_id: Optional[str] = None,
) -> SchoolForm:
    """Regenerates the draft prefill JSON on an existing SchoolForm from latest HealthResources."""
    clean_profile_id = profile_id.strip()
    stmt = select(SchoolForm).where(
        SchoolForm.id == form_id.strip(),
        SchoolForm.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    school_form = res.scalar_one_or_none()
    if school_form is None:
        raise ValueError(f"SchoolForm '{form_id}' not found for profile '{profile_id}'.")

    prefill_dict = await compile_school_form_prefill(session, clean_profile_id)
    now_utc = datetime.now(timezone.utc)
    school_form.prefill_draft_json = json.dumps(prefill_dict)
    school_form.updated_at = now_utc

    resolved_actor_id = await _resolve_actor_user_id(session, clean_profile_id, actor_user_id)
    audit_rec = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now_utc,
        profile_id=clean_profile_id,
        actor_user_id=resolved_actor_id,
        principal="user",
        event="tool",
        tool="regenerate_school_form_prefill",
        risk="write_local",
        decision="allow",
        external_ref=f"school_form:{school_form.id}",
        detail_redacted=json.dumps({"form_id": school_form.id, "action": "prefill"}),
    )
    session.add(audit_rec)
    await session.commit()
    await session.refresh(school_form)
    return school_form


def serialize_school_form(form: SchoolForm) -> Dict[str, Any]:
    """Serializes a SchoolForm ORM model into a dictionary with parsed prefill_draft."""
    try:
        prefill_data = json.loads(form.prefill_draft_json) if form.prefill_draft_json else {}
    except Exception:
        prefill_data = {}

    return {
        "id": form.id,
        "profile_id": form.profile_id,
        "attachment_id": form.attachment_id,
        "title": form.title,
        "school_or_camp_name": form.school_or_camp_name,
        "form_type": form.form_type,
        "expires_at": form.expires_at.isoformat() if form.expires_at else None,
        "reminder_id": form.reminder_id,
        "prefill_draft": prefill_data,
        "status": form.status,
        "created_at": form.created_at.isoformat() if form.created_at else None,
        "updated_at": form.updated_at.isoformat() if form.updated_at else None,
    }


def check_under_13_safeguards(
    profile: Any,
    action: str = "view",
    *,
    reference_date: Optional[Union[datetime, date]] = None,
) -> Dict[str, Any]:
    """Evaluates whether a Profile is under 13 and enforces E11.6 child privacy invariants.

    Invariants for under-13 profiles:
    - `guardian_only = True`
    - `allow_child_login = False`
    - `allow_external_writes = False`
    - `telemetry_enabled = False`
    """
    dob_str = getattr(profile, "date_of_birth", None) if profile is not None else None
    rel_str = str(getattr(profile, "relationship", "") or "").strip().lower()

    if reference_date is None:
        ref_date = datetime.now(timezone.utc).date()
    elif isinstance(reference_date, datetime):
        ref_date = reference_date.date()
    else:
        ref_date = reference_date

    age_months: Optional[int] = None
    if dob_str and isinstance(dob_str, str) and dob_str.strip():
        try:
            clean_dob = dob_str.strip()
            dob_date = (
                datetime.fromisoformat(clean_dob).date()
                if "T" in clean_dob
                else datetime.strptime(clean_dob[:10], "%Y-%m-%d").date()
            )
            months = (ref_date.year - dob_date.year) * 12 + (ref_date.month - dob_date.month)
            if ref_date.day < dob_date.day:
                months -= 1
            age_months = max(0, months)
        except Exception:
            age_months = None

    if age_months is not None:
        is_under_13 = age_months < UNDER_13_CUTOFF_MONTHS
    else:
        # Fail-closed for child profiles without a parseable date_of_birth
        is_under_13 = rel_str == "child"

    clean_action = (action or "view").strip().lower()
    prohibited_under_13_actions = {
        "child_login",
        "direct_login",
        "external_write",
        "write_external",
        "enable_telemetry",
        "telemetry",
        "auto_submit",
    }

    if is_under_13:
        is_allowed = clean_action not in prohibited_under_13_actions
        reason = (
            f"Action '{clean_action}' is strictly prohibited for under-13 pediatric profiles (E11.6)."
            if not is_allowed
            else "Guardian-managed pediatric profile safeguards active (E11.6)."
        )
        return {
            "profile_id": getattr(profile, "id", None),
            "age_months": age_months,
            "is_under_13": True,
            "age_band": "child_under_13",
            "guardian_only": True,
            "allow_child_login": False,
            "allow_external_writes": False,
            "telemetry_enabled": False,
            "action": clean_action,
            "allowed": is_allowed,
            "reason": reason,
        }

    age_band = "teen" if (age_months is not None and age_months < 216) else "adult"
    return {
        "profile_id": getattr(profile, "id", None),
        "age_months": age_months,
        "is_under_13": False,
        "age_band": age_band,
        "guardian_only": False,
        "allow_child_login": True,
        "allow_external_writes": True,
        "telemetry_enabled": False,
        "action": clean_action,
        "allowed": True,
        "reason": "Standard profile safeguards active.",
    }


__all__ = [
    "SCHOOL_FORM_DISCLAIMER",
    "UNDER_13_CUTOFF_MONTHS",
    "VALID_SCHOOL_FORM_STATUSES",
    "VALID_SCHOOL_FORM_TYPES",
    "check_under_13_safeguards",
    "compile_school_form_prefill",
    "create_school_form",
    "regenerate_school_form_prefill",
    "serialize_school_form",
]
