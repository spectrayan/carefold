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

"""Governed AsyncSession handlers for Carefold agent clinical tools (#344).

All handlers registered here execute exclusively inside `McpDatabaseToolbox`
(`carefold_domain_read` / `carefold_domain_write`) via `execute_governed_db_operation`,
eliminating direct raw ORM session creation inside `carefold.tools.*`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.clinical.appointments import (
    InvalidStatusTransitionError,
    validate_status_transition,
)
from carefold.clinical.fhir_chart_queries import (
    query_fhir_observation_trends,
    query_fhir_patient_summary,
    query_fhir_search_resources,
)
from carefold.clinical.prep_pack import generate_and_persist_prep_pack
from carefold.clinical.preventive import evaluate_preventive_care, update_preventive_record
from carefold.clinical.school_forms import create_school_form, serialize_school_form
from carefold.clinical.school_ics import sync_school_ics_feed
from carefold.fhir.sql_pushdown import build_observation_coding_rows
from carefold.importers.service import commit_import_batch, stage_import
from carefold.models import Appointment, HealthResource, SchoolForm
from yarvelle_core.db.models import Job, Note


def _parse_iso_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


async def _op_tool_record_vitals(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    resource_id = str(payload["resource_id"])
    clean_profile_id = str(profile_id)
    fhir_obs = dict(payload["fhir_obs"])
    rec_dt = _parse_iso_dt(payload.get("effective_at"))
    recorded_dt = _parse_iso_dt(payload.get("recorded_at"))
    hr = HealthResource(
        id=resource_id,
        profile_id=clean_profile_id,
        resource_type="observation",
        source_type=str(payload.get("source_type") or "manual"),
        source_ref=payload.get("source_ref"),
        source_id=payload.get("source_id"),
        content_hash=str(payload["content_hash"]),
        data=fhir_obs,
        status="active",
        effective_at=rec_dt,
        recorded_at=recorded_dt,
    )
    session.add(hr)
    coding_rows = build_observation_coding_rows(
        resource_id=resource_id,
        profile_id=clean_profile_id,
        fhir_data=fhir_obs,
        resource_type="Observation",
    )
    if coding_rows:
        session.add_all(coding_rows)
    await session.flush()
    return {"resource_id": resource_id}


async def _op_tool_create_appointment(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    appt_id = str(payload["id"])
    now_utc = _parse_iso_dt(payload.get("now_utc"))
    start_dt = _parse_iso_dt(payload["start_time"]).astimezone(timezone.utc)
    end_dt = _parse_iso_dt(payload["end_time"]).astimezone(timezone.utc)
    appt = Appointment(
        id=appt_id,
        profile_id=str(profile_id),
        title=str(payload["title"]),
        provider_name=payload.get("provider_name"),
        specialty=payload.get("specialty"),
        location=payload.get("location"),
        clinic_phone=payload.get("clinic_phone"),
        start_time=start_dt,
        end_time=end_dt,
        timezone=str(payload.get("timezone") or "UTC"),
        status=str(payload.get("status") or "scheduled"),
        reason=payload.get("reason"),
        preparation_notes=payload.get("preparation_notes"),
        created_at=now_utc,
        updated_at=now_utc,
    )
    session.add(appt)
    await session.flush()
    return {"id": appt_id}


async def _op_tool_list_appointments(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    clean_profile_id = str(profile_id)
    status_filter = payload.get("status")
    start_after = payload.get("start_after")
    start_before = payload.get("start_before")
    limit = int(payload.get("limit", 20))
    offset = int(payload.get("offset", 0))

    query = select(Appointment).where(Appointment.profile_id == clean_profile_id)
    if status_filter:
        query = query.where(Appointment.status == str(status_filter).strip().lower())
    if start_after:
        try:
            dt_after = _parse_iso_dt(start_after)
            query = query.where(Appointment.start_time >= dt_after.astimezone(timezone.utc))
        except Exception:
            pass
    if start_before:
        try:
            dt_before = _parse_iso_dt(start_before)
            query = query.where(Appointment.start_time <= dt_before.astimezone(timezone.utc))
        except Exception:
            pass

    count_stmt = select(func.count()).select_from(query.subquery())
    total_count = (await session.execute(count_stmt)).scalar_one()

    query = query.order_by(Appointment.start_time.asc()).limit(limit).offset(offset)
    records = list((await session.execute(query)).scalars().all())
    appointments_list = [
        {
            "id": a.id,
            "profile_id": a.profile_id,
            "title": a.title,
            "provider_name": a.provider_name,
            "specialty": a.specialty,
            "location": a.location,
            "clinic_phone": a.clinic_phone,
            "start_time": a.start_time.isoformat() if a.start_time else None,
            "end_time": a.end_time.isoformat() if a.end_time else None,
            "timezone": a.timezone,
            "status": a.status,
            "reason": a.reason,
            "preparation_notes": a.preparation_notes,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }
        for a in records
    ]
    return {
        "appointments": appointments_list,
        "total": total_count,
        "limit": limit,
        "offset": offset,
    }


async def _op_tool_update_appointment_status(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    clean_profile_id = str(profile_id)
    appointment_id = str(payload["appointment_id"])
    target_status = str(payload["status"])
    now_utc = _parse_iso_dt(payload.get("now_utc"))

    stmt = select(Appointment).where(
        Appointment.id == appointment_id,
        Appointment.profile_id == clean_profile_id,
    )
    appt = (await session.execute(stmt)).scalar_one_or_none()
    if appt is None:
        return {
            "ok": False,
            "error_code": "CFD-500-002",
            "error": f"Appointment '{appointment_id}' not found for profile '{clean_profile_id}'.",
        }

    previous_status = appt.status
    try:
        validate_status_transition(previous_status, target_status)
    except (InvalidStatusTransitionError, ValueError) as err:
        return {
            "ok": False,
            "error_code": "CFD-100-003",
            "error": str(err),
        }

    appt.status = target_status
    appt.updated_at = now_utc
    await session.flush()
    return {
        "ok": True,
        "previous_status": previous_status,
        "status": target_status,
        "updated_at": now_utc.isoformat(),
    }


async def _op_tool_create_typed_note(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    clean_profile_id = str(profile_id)
    linked_appt_id = payload.get("linked_appointment_id")
    if linked_appt_id:
        appt_stmt = select(Appointment).where(
            Appointment.id == linked_appt_id,
            Appointment.profile_id == clean_profile_id,
        )
        if (await session.execute(appt_stmt)).scalar_one_or_none() is None:
            return {
                "ok": False,
                "error_code": "CFD-100-003",
                "error": "Security violation: Linked appointment does not exist or does not belong to profile.",
            }

    now = _parse_iso_dt(payload.get("now"))
    note_id = str(payload["note_id"])
    tags_list: List[str] = list(payload.get("tags_list") or [])
    new_note = Note(
        id=note_id,
        type=str(payload["note_type"]),
        user_id=user_id,
        profile_id=clean_profile_id,
        slug=str(payload["unique_slug"]),
        title=str(payload["title"]),
        content=str(payload["content"]),
        tags_json=json.dumps(tags_list),
        linked_appointment_id=linked_appt_id,
        created_at=now,
        updated_at=now,
    )
    session.add(new_note)

    content_hash = hashlib.sha256((new_note.content or "").encode("utf-8")).hexdigest()[:12]
    index_job = Job(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        kind="index_doc",
        payload=json.dumps({
            "document_id": new_note.id,
            "profile_id": clean_profile_id,
            "doc_type": "note",
        }),
        timezone="UTC",
        next_run_at=now,
        idempotency_key=f"index:note:{new_note.id}:{content_hash}",
        status="pending",
    )
    session.add(index_job)
    await session.flush()

    return {
        "ok": True,
        "output": {
            "id": new_note.id,
            "profile_id": clean_profile_id,
            "slug": new_note.slug,
            "title": new_note.title,
            "type": new_note.type,
            "content": new_note.content,
            "linked_appointment_id": new_note.linked_appointment_id,
            "tags": tags_list,
            "created_at": new_note.created_at.isoformat(),
            "updated_at": new_note.updated_at.isoformat(),
            "undo_reference": f"note:{new_note.id}",
        },
    }


async def _op_tool_check_preventive_care(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    return await evaluate_preventive_care(
        session,
        str(profile_id),
        schedule_source=payload.get("schedule_source"),
        sex=payload.get("sex"),
        category=payload.get("category"),
    )


async def _op_tool_update_preventive_status(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    record = await update_preventive_record(
        session,
        profile_id=str(profile_id),
        rule_id=str(payload["rule_id"]),
        status=str(payload["status"]),
        notes=payload.get("notes"),
        completed_at=payload.get("completed_at"),
        schedule_source=payload.get("schedule_source"),
        actor_user_id=str(payload.get("actor_user_id") or user_id or "user"),
    )
    ext_ref = f"preventive_record:{record.id}"
    return {
        "id": record.id,
        "record_id": record.id,
        "profile_id": record.profile_id,
        "rule_id": record.rule_id,
        "status": record.status,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "notes": record.notes,
        "schedule_source": record.schedule_source,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "external_ref": ext_ref,
        "undo_reference": ext_ref,
    }


async def _op_tool_create_school_form(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    form = await create_school_form(
        session,
        profile_id=str(profile_id),
        title=str(payload["title"]),
        school_or_camp_name=payload.get("school_or_camp_name"),
        form_type=str(payload.get("form_type") or "general"),
        attachment_id=payload.get("attachment_id"),
        expires_at=payload.get("expires_at"),
        status=str(payload.get("status") or "draft"),
        actor_user_id=str(payload.get("actor_user_id") or user_id or "user"),
    )
    return serialize_school_form(form)


async def _op_tool_list_school_forms(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    clean_profile_id = str(profile_id)
    status_filter = payload.get("status")
    form_type_filter = payload.get("form_type")
    stmt = select(SchoolForm).where(SchoolForm.profile_id == clean_profile_id)
    if status_filter and str(status_filter).strip():
        stmt = stmt.where(SchoolForm.status == str(status_filter).strip().lower())
    if form_type_filter and str(form_type_filter).strip():
        stmt = stmt.where(SchoolForm.form_type == str(form_type_filter).strip().lower())
    stmt = stmt.order_by(SchoolForm.created_at.desc())

    forms = [serialize_school_form(f) for f in (await session.execute(stmt)).scalars().all()]
    return {
        "profile_id": clean_profile_id,
        "forms": forms,
        "items": forms,
        "total": len(forms),
    }


async def _op_tool_generate_prep_pack(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    return await generate_and_persist_prep_pack(
        session=session,
        profile_id=str(profile_id),
        appointment_id=payload.get("appointment_id"),
        specialty=payload.get("specialty"),
        visit_reason=payload.get("visit_reason"),
        doctor_questions=payload.get("doctor_questions"),
        user_id=user_id,
    )


async def _op_tool_stage_clinical_import(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    batch = await stage_import(
        session=session,
        profile_id=str(profile_id),
        filename=str(payload.get("filename") or "clinical_import.dat"),
        content=payload["content"],
        source_name=payload.get("source_name"),
        fmt=payload.get("fmt"),
        user_id=user_id,
    )
    return {
        "id": batch.id,
        "batch_id": batch.id,
        "profile_id": batch.profile_id,
        "attachment_id": batch.attachment_id,
        "format": batch.format,
        "source_name": batch.source_name,
        "status": batch.status,
        "summary": json.loads(batch.summary_json or "{}"),
        "staged_records": json.loads(batch.staged_records_json or "[]"),
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "trust": "untrusted",
    }


async def _op_tool_commit_clinical_import(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    return await commit_import_batch(
        session=session,
        profile_id=str(profile_id),
        batch_id=str(payload["batch_id"]),
        selected_indices=payload.get("selected_indices"),
        actor_user_id=user_id,
    )


async def _op_tool_sync_school_ics(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    return await sync_school_ics_feed(
        session=session,
        profile_id=str(profile_id),
        feed_id=str(payload["feed_id"]),
        raw_ics_content=payload.get("raw_ics_content"),
    )


async def _op_tool_fhir_chart_search(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    return await query_fhir_search_resources(
        session,
        profile_id=str(profile_id),
        resource_type=str(payload.get("resource_type") or ""),
        code=payload.get("code"),
        category=payload.get("category"),
        date_from=payload.get("date_from"),
        limit=int(payload.get("limit", 25)),
    )


async def _op_tool_fhir_chart_summary(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    return await query_fhir_patient_summary(
        session,
        profile_id=str(profile_id),
        limit_per_section=int(payload.get("limit_per_section", 15)),
    )


async def _op_tool_fhir_chart_trends(
    session: AsyncSession,
    payload: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    ctx: Any,
) -> Dict[str, Any]:
    return await query_fhir_observation_trends(
        session,
        profile_id=str(profile_id),
        loinc_or_code=str(payload.get("loinc_or_code") or ""),
        limit=int(payload.get("limit", 12)),
    )


def register_clinical_tool_db_handlers(register_fn: Any) -> None:
    """Registers governed DB operation handlers for all Carefold clinical agent tools."""
    register_fn("tool.record_vitals", _op_tool_record_vitals, preserve_auto_stub=True)
    register_fn("tool.create_appointment", _op_tool_create_appointment, preserve_auto_stub=True)
    register_fn("tool.list_appointments", _op_tool_list_appointments, preserve_auto_stub=False)
    register_fn("tool.update_appointment_status", _op_tool_update_appointment_status, preserve_auto_stub=False)
    register_fn("tool.create_typed_note", _op_tool_create_typed_note, preserve_auto_stub=True)
    register_fn("tool.check_preventive_care", _op_tool_check_preventive_care, preserve_auto_stub=False)
    register_fn("tool.update_preventive_status", _op_tool_update_preventive_status, preserve_auto_stub=False)
    register_fn("tool.create_school_form", _op_tool_create_school_form, preserve_auto_stub=False)
    register_fn("tool.list_school_forms", _op_tool_list_school_forms, preserve_auto_stub=False)
    register_fn("tool.generate_prep_pack", _op_tool_generate_prep_pack, preserve_auto_stub=True)
    register_fn("tool.stage_clinical_import", _op_tool_stage_clinical_import, preserve_auto_stub=True)
    register_fn("tool.commit_clinical_import", _op_tool_commit_clinical_import, preserve_auto_stub=False)
    register_fn("tool.sync_school_ics", _op_tool_sync_school_ics, preserve_auto_stub=False)
    register_fn("tool.fhir_chart_search", _op_tool_fhir_chart_search, preserve_auto_stub=False)
    register_fn("tool.fhir_chart_summary", _op_tool_fhir_chart_summary, preserve_auto_stub=False)
    register_fn("tool.fhir_chart_trends", _op_tool_fhir_chart_trends, preserve_auto_stub=False)
