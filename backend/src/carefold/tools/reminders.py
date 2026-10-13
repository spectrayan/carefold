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

"""Closed tools for clinical reminders: create (with Job scheduling) and list (AU-28)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from carefold.audit.logger import record_audit
from carefold.db.models import Job, Reminder
from carefold.db.session import get_session_factory
from carefold.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.reminders")

VALID_REMINDER_CATEGORIES = frozenset({"medication", "vitals", "appointment", "prep", "general"})


async def execute_create_reminder(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Creates a new clinical reminder and enqueues matching wall-clock Job with fail-closed security."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("create_reminder rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed create_reminder.",
        )
    clean_profile_id = profile_id.strip()

    title = str(args.get("title", "")).strip() if isinstance(args, dict) else ""
    if not title:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'title' must be a non-empty string.",
        )

    due_raw = args.get("next_due_at") if isinstance(args, dict) else None
    if not due_raw:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'next_due_at' must be a valid ISO-8601 timestamp.",
        )

    try:
        due_dt = datetime.fromisoformat(str(due_raw))
    except Exception as exc:
        return ToolResult(
            success=False,
            output=None,
            error=f"Parameter 'next_due_at' must be a valid ISO-8601 timestamp: {exc}",
        )

    if due_dt.tzinfo is None:
        due_dt = due_dt.replace(tzinfo=timezone.utc)

    category = str(args.get("category", "general")).strip().lower() if isinstance(args, dict) else "general"
    if category not in VALID_REMINDER_CATEGORIES:
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid reminder category '{category}'. Allowed categories: medication, vitals, appointment, prep, general.",
        )

    tz_str = str(args.get("timezone", "UTC")).strip() if isinstance(args, dict) else "UTC"
    tz_str = tz_str or "UTC"
    try:
        ZoneInfo(tz_str)
    except Exception:
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid IANA timezone identifier: '{tz_str}'.",
        )

    rrule_raw = args.get("rrule") if isinstance(args, dict) else None
    clean_rrule: Optional[str] = None
    if rrule_raw:
        clean_rrule = str(rrule_raw).strip()
        if "FREQ=" not in clean_rrule.upper():
            return ToolResult(
                success=False,
                output=None,
                error="Invalid RFC 5545 RRULE syntax. Must include FREQ token (e.g. 'FREQ=DAILY;INTERVAL=1').",
            )

    rem_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    due_utc = due_dt.astimezone(timezone.utc)

    factory = get_session_factory()
    async with factory() as session:
        reminder = Reminder(
            id=rem_id,
            profile_id=clean_profile_id,
            title=title,
            description=args.get("description") if isinstance(args, dict) else None,
            category=category,
            rrule=clean_rrule,
            timezone=tz_str,
            next_due_at=due_utc,
            status="pending",
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(reminder)

        # Enqueue corresponding wall-clock Job in jobs table
        job = Job(
            id=job_id,
            profile_id=clean_profile_id,
            kind="reminder",
            payload=json.dumps({"reminder_id": rem_id}),
            timezone=tz_str,
            rrule=clean_rrule,
            next_run_at=due_utc,
            status="pending",
            idempotency_key=f"reminder:{rem_id}",
            attempts=0,
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(job)
        await session.commit()

    actor_id = getattr(ctx, "user_id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": clean_profile_id,
                "action": "create",
                "tool": "create_reminder",
                "risk": "write_local",
                "external_ref": f"reminder:{rem_id}",
                "details": {
                    "title": title,
                    "category": category,
                    "next_due_at": due_utc.isoformat(),
                    "rrule": clean_rrule,
                },
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for reminder %s: %s", rem_id, audit_err)

    return ToolResult(
        success=True,
        output={
            "id": rem_id,
            "job_id": job_id,
            "profile_id": clean_profile_id,
            "title": title,
            "description": args.get("description") if isinstance(args, dict) else None,
            "category": category,
            "rrule": clean_rrule,
            "timezone": tz_str,
            "next_due_at": due_utc.isoformat(),
            "status": "pending",
            "undo_reference": f"reminder:{rem_id}",
        },
    )


async def execute_list_reminders(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Queries clinical reminders for a patient profile."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("list_reminders rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed list_reminders.",
        )
    clean_profile_id = profile_id.strip()

    status_filter = args.get("status") if isinstance(args, dict) else None
    category_filter = args.get("category") if isinstance(args, dict) else None
    due_before = args.get("due_before") if isinstance(args, dict) else None
    limit = int(args.get("limit", 50)) if isinstance(args, dict) else 50
    offset = int(args.get("offset", 0)) if isinstance(args, dict) else 0

    limit = max(1, min(100, limit))
    offset = max(0, offset)

    factory = get_session_factory()
    async with factory() as session:
        query = select(Reminder).where(Reminder.profile_id == clean_profile_id)

        if status_filter:
            query = query.where(Reminder.status == str(status_filter).strip().lower())
        if category_filter:
            query = query.where(Reminder.category == str(category_filter).strip().lower())
        if due_before:
            try:
                dt_before = datetime.fromisoformat(str(due_before))
                if dt_before.tzinfo is None:
                    dt_before = dt_before.replace(tzinfo=timezone.utc)
                query = query.where(Reminder.next_due_at <= dt_before.astimezone(timezone.utc))
            except Exception:
                pass

        count_stmt = select(func.count()).select_from(query.subquery())
        count_res = await session.execute(count_stmt)
        total_count = count_res.scalar_one()

        query = query.order_by(Reminder.next_due_at.asc()).limit(limit).offset(offset)
        res = await session.execute(query)
        records = list(res.scalars().all())

    reminders_list = [
        {
            "id": r.id,
            "profile_id": r.profile_id,
            "title": r.title,
            "description": r.description,
            "category": r.category,
            "rrule": r.rrule,
            "timezone": r.timezone,
            "next_due_at": r.next_due_at.isoformat() if r.next_due_at else None,
            "status": r.status,
            "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
            "snooze_until": r.snooze_until.isoformat() if r.snooze_until else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in records
    ]

    return ToolResult(
        success=True,
        output={
            "reminders": reminders_list,
            "total": total_count,
            "limit": limit,
            "offset": offset,
        },
    )


__all__ = [
    "VALID_REMINDER_CATEGORIES",
    "execute_create_reminder",
    "execute_list_reminders",
]
