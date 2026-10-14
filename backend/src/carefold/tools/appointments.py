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

"""Closed tools for clinical appointments: create, list, and update status (AU-29)."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from carefold.audit.logger import record_audit
from carefold.clinical.appointments import (
    AppointmentStatus,
    InvalidStatusTransitionError,
    validate_status_transition,
)
from carefold.db.models import Appointment
from carefold.db.session import get_session_factory
from carefold.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.appointments")


async def execute_create_appointment(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Creates a new clinical appointment for a patient profile with fail-closed security."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("create_appointment rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed create_appointment.",
        )
    clean_profile_id = profile_id.strip()

    title = str(args.get("title", "")).strip() if isinstance(args, dict) else ""
    if not title:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'title' must be a non-empty string.",
        )

    start_raw = args.get("start_time") if isinstance(args, dict) else None
    end_raw = args.get("end_time") if isinstance(args, dict) else None
    if not start_raw or not end_raw:
        return ToolResult(
            success=False,
            output=None,
            error="Both 'start_time' and 'end_time' parameters are required.",
        )

    try:
        start_dt = datetime.fromisoformat(str(start_raw))
        end_dt = datetime.fromisoformat(str(end_raw))
    except Exception as exc:
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid ISO-8601 datetime format: {exc}",
        )

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    if end_dt <= start_dt:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'end_time' must be strictly after 'start_time'.",
        )

    tz_str = str(args.get("timezone", "UTC")).strip() or "UTC"
    try:
        ZoneInfo(tz_str)
    except Exception:
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid IANA timezone identifier: '{tz_str}'.",
        )

    status_str = str(args.get("status", "scheduled")).strip().lower()
    try:
        valid_status = AppointmentStatus(status_str).value
    except ValueError:
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid appointment status '{status_str}'. Permitted: requested, scheduled, confirmed.",
        )

    appt_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)

    factory = get_session_factory()
    async with factory() as session:
        appt = Appointment(
            id=appt_id,
            profile_id=clean_profile_id,
            title=title,
            provider_name=args.get("provider_name"),
            specialty=args.get("specialty"),
            location=args.get("location"),
            clinic_phone=args.get("clinic_phone"),
            start_time=start_dt.astimezone(timezone.utc),
            end_time=end_dt.astimezone(timezone.utc),
            timezone=tz_str,
            status=valid_status,
            reason=args.get("reason"),
            preparation_notes=args.get("preparation_notes"),
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(appt)
        await session.commit()

    actor_id = getattr(ctx, "user_id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": clean_profile_id,
                "action": "create",
                "tool": "create_appointment",
                "risk": "write_local",
                "external_ref": f"appointment:{appt_id}",
                "details": {
                    "title": title,
                    "status": valid_status,
                    "start_time": start_dt.isoformat(),
                    "end_time": end_dt.isoformat(),
                },
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for appointment %s: %s", appt_id, audit_err)

    return ToolResult(
        success=True,
        output={
            "id": appt_id,
            "profile_id": clean_profile_id,
            "title": title,
            "provider_name": args.get("provider_name"),
            "specialty": args.get("specialty"),
            "location": args.get("location"),
            "clinic_phone": args.get("clinic_phone"),
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "timezone": tz_str,
            "status": valid_status,
            "reason": args.get("reason"),
            "preparation_notes": args.get("preparation_notes"),
            "undo_reference": f"appointment:{appt_id}",
        },
    )


async def execute_list_appointments(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Queries scheduled and historical clinical appointments for a profile."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("list_appointments rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed list_appointments.",
        )
    clean_profile_id = profile_id.strip()

    status_filter = args.get("status") if isinstance(args, dict) else None
    start_after = args.get("start_after") if isinstance(args, dict) else None
    start_before = args.get("start_before") if isinstance(args, dict) else None
    limit = int(args.get("limit", 20)) if isinstance(args, dict) else 20
    offset = int(args.get("offset", 0)) if isinstance(args, dict) else 0

    limit = max(1, min(100, limit))
    offset = max(0, offset)

    factory = get_session_factory()
    async with factory() as session:
        query = select(Appointment).where(Appointment.profile_id == clean_profile_id)

        if status_filter:
            query = query.where(Appointment.status == str(status_filter).strip().lower())
        if start_after:
            try:
                dt_after = datetime.fromisoformat(str(start_after))
                if dt_after.tzinfo is None:
                    dt_after = dt_after.replace(tzinfo=timezone.utc)
                query = query.where(Appointment.start_time >= dt_after.astimezone(timezone.utc))
            except Exception:
                pass
        if start_before:
            try:
                dt_before = datetime.fromisoformat(str(start_before))
                if dt_before.tzinfo is None:
                    dt_before = dt_before.replace(tzinfo=timezone.utc)
                query = query.where(Appointment.start_time <= dt_before.astimezone(timezone.utc))
            except Exception:
                pass

        # Total count
        count_stmt = select(func.count()).select_from(query.subquery())
        count_res = await session.execute(count_stmt)
        total_count = count_res.scalar_one()

        query = query.order_by(Appointment.start_time.asc()).limit(limit).offset(offset)
        res = await session.execute(query)
        records = list(res.scalars().all())

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

    return ToolResult(
        success=True,
        output={
            "appointments": appointments_list,
            "total": total_count,
            "limit": limit,
            "offset": offset,
        },
    )


async def execute_update_appointment_status(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Updates the lifecycle status of an appointment with state machine transition checks."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("update_appointment_status rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed update_appointment_status.",
        )
    clean_profile_id = profile_id.strip()

    appointment_id = str(args.get("appointment_id", "")).strip() if isinstance(args, dict) else ""
    if not appointment_id:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'appointment_id' is required.",
        )

    target_status = str(args.get("status", "")).strip().lower() if isinstance(args, dict) else ""
    if not target_status:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'status' is required.",
        )

    now_utc = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.profile_id == clean_profile_id,
        )
        res = await session.execute(stmt)
        appt = res.scalar_one_or_none()

        if appt is None:
            return ToolResult(
                success=False,
                output=None,
                error=f"Appointment '{appointment_id}' not found for profile '{clean_profile_id}'.",
            )

        previous_status = appt.status
        try:
            validate_status_transition(previous_status, target_status)
        except InvalidStatusTransitionError as err:
            return ToolResult(
                success=False,
                output=None,
                error=str(err),
            )
        except ValueError as val_err:
            return ToolResult(
                success=False,
                output=None,
                error=str(val_err),
            )

        appt.status = target_status
        appt.updated_at = now_utc
        await session.commit()

    actor_id = getattr(ctx, "user_id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": clean_profile_id,
                "action": "update",
                "tool": "update_appointment_status",
                "risk": "write_local",
                "external_ref": f"appointment:{appointment_id}",
                "details": {
                    "previous_status": previous_status,
                    "new_status": target_status,
                    "cancellation_reason": args.get("cancellation_reason") if isinstance(args, dict) else None,
                },
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for update_appointment_status: %s", audit_err)

    return ToolResult(
        success=True,
        output={
            "id": appointment_id,
            "profile_id": clean_profile_id,
            "previous_status": previous_status,
            "status": target_status,
            "updated_at": now_utc.isoformat(),
            "undo_reference": f"appointment:{appointment_id}",
        },
    )


__all__ = [
    "execute_create_appointment",
    "execute_list_appointments",
    "execute_update_appointment_status",
]
