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

"""Closed tools for clinical appointments routed via McpDatabaseToolbox (AU-29, #344)."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict
import uuid
from zoneinfo import ZoneInfo

from carefold.clinical.appointments import AppointmentStatus
from carefold.clinical.db_hooks import execute_governed_db_operation
from yarvelle_core.audit.logger import record_audit
from yarvelle_core.db.session import get_session_factory  # noqa: F401
from yarvelle_core.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.appointments")


async def execute_create_appointment(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Creates a new clinical appointment for a patient profile via McpDatabaseToolbox."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("create_appointment rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed create_appointment.",
            error_code="YRV-300-014",
            retryable=False,
        )
    clean_profile_id = profile_id.strip()

    title = str(args.get("title", "")).strip() if isinstance(args, dict) else ""
    if not title:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'title' must be a non-empty string.",
            error_code="CFD-100-003",
            retryable=False,
        )

    start_raw = args.get("start_time") if isinstance(args, dict) else None
    end_raw = args.get("end_time") if isinstance(args, dict) else None
    if not start_raw or not end_raw:
        return ToolResult(
            success=False,
            output=None,
            error="Both 'start_time' and 'end_time' parameters are required.",
            error_code="CFD-100-003",
            retryable=False,
        )

    try:
        start_dt = datetime.fromisoformat(str(start_raw))
        end_dt = datetime.fromisoformat(str(end_raw))
    except Exception as exc:
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid ISO-8601 datetime format: {exc}",
            error_code="CFD-100-003",
            retryable=False,
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
            error_code="CFD-100-003",
            retryable=False,
        )

    tz_str = str(args.get("timezone", "UTC")).strip() or "UTC"
    try:
        ZoneInfo(tz_str)
    except Exception:
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid IANA timezone identifier: '{tz_str}'.",
            error_code="CFD-100-003",
            retryable=False,
        )

    status_str = str(args.get("status", "scheduled")).strip().lower()
    try:
        valid_status = AppointmentStatus(status_str).value
    except ValueError:
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid appointment status '{status_str}'. Permitted: requested, scheduled, confirmed.",
            error_code="CFD-100-003",
            retryable=False,
        )

    appt_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)

    await execute_governed_db_operation(
        "tool.create_appointment",
        {
            "id": appt_id,
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
            "now_utc": now_utc.isoformat(),
        },
        ctx=ctx,
        profile_id=clean_profile_id,
        risk_tier="write_local",
        caller_module_name=__name__,
    )

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
    """Queries scheduled and historical clinical appointments via McpDatabaseToolbox."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("list_appointments rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed list_appointments.",
            error_code="YRV-300-014",
            retryable=False,
        )
    clean_profile_id = profile_id.strip()

    status_filter = args.get("status") if isinstance(args, dict) else None
    start_after = args.get("start_after") if isinstance(args, dict) else None
    start_before = args.get("start_before") if isinstance(args, dict) else None
    limit = int(args.get("limit", 20)) if isinstance(args, dict) else 20
    offset = int(args.get("offset", 0)) if isinstance(args, dict) else 0

    limit = max(1, min(100, limit))
    offset = max(0, offset)

    out = await execute_governed_db_operation(
        "tool.list_appointments",
        {
            "status": status_filter,
            "start_after": start_after,
            "start_before": start_before,
            "limit": limit,
            "offset": offset,
        },
        ctx=ctx,
        profile_id=clean_profile_id,
        risk_tier="read",
        caller_module_name=__name__,
    )
    return ToolResult(success=True, output=out)


async def execute_update_appointment_status(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Updates the lifecycle status of an appointment via McpDatabaseToolbox."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("update_appointment_status rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed update_appointment_status.",
            error_code="YRV-300-014",
            retryable=False,
        )
    clean_profile_id = profile_id.strip()

    appointment_id = str(args.get("appointment_id", "")).strip() if isinstance(args, dict) else ""
    if not appointment_id:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'appointment_id' is required.",
            error_code="CFD-100-003",
            retryable=False,
        )

    target_status = str(args.get("status", "")).strip().lower() if isinstance(args, dict) else ""
    if not target_status:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'status' is required.",
            error_code="CFD-100-003",
            retryable=False,
        )

    now_utc = datetime.now(timezone.utc)
    res = await execute_governed_db_operation(
        "tool.update_appointment_status",
        {
            "appointment_id": appointment_id,
            "status": target_status,
            "now_utc": now_utc.isoformat(),
        },
        ctx=ctx,
        profile_id=clean_profile_id,
        risk_tier="write_local",
        caller_module_name=__name__,
    )
    if not res.get("ok"):
        return ToolResult(
            success=False,
            output=None,
            error=res["error"],
            error_code=res["error_code"],
            retryable=False,
        )

    previous_status = res["previous_status"]
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
            "updated_at": res["updated_at"],
            "undo_reference": f"appointment:{appointment_id}",
        },
    )


__all__ = [
    "SPEC_CREATE",
    "SPEC_LIST",
    "SPEC_UPDATE_STATUS",
    "execute_create_appointment",
    "execute_list_appointments",
    "execute_update_appointment_status",
]

_SPEC_ATTRS = {
    "SPEC_CREATE": "create_appointment",
    "SPEC_LIST": "list_appointments",
    "SPEC_UPDATE_STATUS": "update_appointment_status",
}


def __getattr__(name: str) -> Any:
    if name in _SPEC_ATTRS:
        from carefold.tools import get_health_tool_spec

        return get_health_tool_spec(_SPEC_ATTRS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
