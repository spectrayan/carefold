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

"""Reminders & Recurrence Engine, RFC 5545 RRULE expansion, snooze lifecycle, and .ics export (AU-28)."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Dict, List, Optional
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.audit.logger import record_audit
from carefold.db.models import Reminder
from carefold.logging import get_logger

logger = get_logger("carefold.clinical.reminders")


# ============================================================================
# Section 1: RFC 5545 RRULE Recurrence Expansion
# ============================================================================

WEEKDAY_MAP = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}


def _parse_rrule(rrule_str: str) -> Dict[str, str]:
    """Parses an RFC 5545 RRULE string into key-value pairs."""
    clean = rrule_str.strip()
    if clean.upper().startswith("RRULE:"):
        clean = clean[6:].strip()
    parts = clean.split(";")
    result: Dict[str, str] = {}
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip().upper()] = v.strip().upper()
    return result


def _parse_until(until_str: str, tz: ZoneInfo) -> datetime:
    """Parses RFC 5545 UNTIL date/datetime string into timezone-aware UTC datetime."""
    until_clean = until_str.strip().upper()
    # Format: YYYYMMDDTHHMMSSZ
    if until_clean.endswith("Z"):
        until_clean = until_clean[:-1]
        if "T" in until_clean:
            dt = datetime.strptime(until_clean, "%Y%m%dT%H%M%S")
        else:
            dt = datetime.strptime(until_clean, "%Y%m%d")
        return dt.replace(tzinfo=timezone.utc)
    if "T" in until_clean:
        try:
            dt = datetime.strptime(until_clean, "%Y%m%dT%H%M%S")
            return dt.replace(tzinfo=tz).astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.strptime(until_clean, "%Y%m%d")
        return dt.replace(tzinfo=tz).astimezone(timezone.utc)
    except ValueError:
        # Fallback to ISO
        dt = datetime.fromisoformat(until_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz).astimezone(timezone.utc)
        return dt.astimezone(timezone.utc)


def advance_rrule_occurrence(
    current_due: datetime,
    rrule_str: str,
    tz_name: str = "UTC",
) -> Optional[datetime]:
    """Calculates the next due datetime based on RFC 5545 RRULE string.

    Evaluated in the target IANA timezone using standard library zoneinfo, datetime,
    and calendar (zero external dependencies). Preserves wall-clock stability across
    DST transitions and leap years.

    Args:
        current_due: The base/previous occurrence datetime.
        rrule_str: RFC 5545 recurrence rule string (e.g. 'FREQ=DAILY;INTERVAL=1').
        tz_name: Target profile IANA timezone (default: 'UTC').

    Returns:
        The next UTC datetime occurrence, or None if recurrence is exhausted (UNTIL/COUNT).
    """
    if not rrule_str or not rrule_str.strip():
        return None

    try:
        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
    except Exception:
        tz = ZoneInfo("UTC")

    if current_due.tzinfo is None:
        local_due = current_due.replace(tzinfo=tz)
    else:
        local_due = current_due.astimezone(tz)

    current_due_utc = local_due.astimezone(timezone.utc)
    rules = _parse_rrule(rrule_str)
    freq = rules.get("FREQ", "DAILY")
    interval = int(rules.get("INTERVAL", "1"))
    if interval < 1:
        interval = 1

    until_dt: Optional[datetime] = None
    if "UNTIL" in rules:
        try:
            until_dt = _parse_until(rules["UNTIL"], tz)
        except Exception as e:
            logger.warning("Failed to parse UNTIL token '%s': %s", rules["UNTIL"], e)

    candidate_local: datetime

    if freq == "DAILY":
        candidate_local = local_due + timedelta(days=interval)

    elif freq == "WEEKLY":
        byday_str = rules.get("BYDAY")
        if byday_str:
            target_days = sorted(
                WEEKDAY_MAP[d.strip()]
                for d in byday_str.split(",")
                if d.strip() in WEEKDAY_MAP
            )
            if not target_days:
                target_days = [local_due.weekday()]

            curr_wd = local_due.weekday()
            next_wd_in_week = [wd for wd in target_days if wd > curr_wd]
            if next_wd_in_week:
                days_ahead = next_wd_in_week[0] - curr_wd
                candidate_local = local_due + timedelta(days=days_ahead)
            else:
                days_ahead = (7 - curr_wd) + (interval - 1) * 7 + target_days[0]
                candidate_local = local_due + timedelta(days=days_ahead)
        else:
            candidate_local = local_due + timedelta(weeks=interval)

    elif freq == "MONTHLY":
        new_year = local_due.year + (local_due.month + interval - 1) // 12
        new_month = (local_due.month + interval - 1) % 12 + 1
        max_day = calendar.monthrange(new_year, new_month)[1]
        new_day = min(local_due.day, max_day)
        candidate_local = local_due.replace(year=new_year, month=new_month, day=new_day)

    elif freq == "YEARLY":
        target_year = local_due.year + interval
        if local_due.month == 2 and local_due.day == 29 and not calendar.isleap(target_year):
            candidate_local = local_due.replace(year=target_year, day=28)
        else:
            candidate_local = local_due.replace(year=target_year)

    elif freq == "HOURLY":
        candidate_local = local_due + timedelta(hours=interval)

    elif freq == "MINUTELY":
        candidate_local = local_due + timedelta(minutes=interval)

    else:
        # Default daily advancement
        candidate_local = local_due + timedelta(days=interval)

    candidate_utc = candidate_local.astimezone(timezone.utc)

    # Monotonicity check
    if candidate_utc <= current_due_utc:
        candidate_utc = current_due_utc + timedelta(days=1)

    if until_dt is not None and candidate_utc > until_dt:
        return None

    return candidate_utc


# ============================================================================
# Section 2: Snooze Engine
# ============================================================================

SNOOZE_DELTAS: Dict[str, timedelta] = {
    "+15m": timedelta(minutes=15),
    "15m": timedelta(minutes=15),
    "+1h": timedelta(hours=1),
    "1h": timedelta(hours=1),
    "+24h": timedelta(hours=24),
    "24h": timedelta(hours=24),
}


def apply_reminder_snooze(
    reminder: Dict[str, Any],
    snooze_interval: str,
    now_dt: datetime,
) -> Dict[str, Any]:
    """Applies +15m, +1h, or +24h snooze to a reminder dictionary.

    Args:
        reminder: Reminder state dictionary.
        snooze_interval: Interval string (+15m, +1h, +24h or aliases 15m, 1h, 24h).
        now_dt: Current evaluation datetime.

    Returns:
        Updated reminder dictionary with status 'snoozed' and ISO 'snooze_until'.

    Raises:
        ValueError: If interval is negative or unsupported, or reminder is in terminal state.
    """
    clean_interval = str(snooze_interval).strip().lower()
    if clean_interval not in SNOOZE_DELTAS:
        raise ValueError(
            f"Invalid snooze interval '{snooze_interval}'. Supported: +15m, +1h, +24h."
        )

    current_status = str(reminder.get("status", "pending")).lower()
    if current_status in ("completed", "cancelled"):
        raise ValueError(f"Cannot snooze reminder with status '{current_status}'.")

    delta = SNOOZE_DELTAS[clean_interval]
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    snooze_until = now_dt + delta
    updated = dict(reminder)
    updated["status"] = "snoozed"
    updated["snooze_until"] = snooze_until.isoformat()
    return updated


# ============================================================================
# Section 3: Sleep/Wake Overdue Coalescing (>24 Hours Overdue)
# ============================================================================


def coalesce_overdue_reminders(
    reminders: List[Dict[str, Any]],
    current_time: datetime,
) -> List[Dict[str, Any]]:
    """Transitions reminders overdue by > 24 hours to 'missed' status.

    Preserves completed and cancelled invariance. Snoozed reminders measure
    overdue duration from snooze_until, whereas pending reminders measure from next_due_at.

    Args:
        reminders: List of reminder state dicts.
        current_time: Evaluation anchor datetime.

    Returns:
        List of reminder dicts with eligible items transitioned to 'missed'.
    """
    if current_time.tzinfo is None:
        now_utc = current_time.replace(tzinfo=timezone.utc)
    else:
        now_utc = current_time.astimezone(timezone.utc)

    twenty_four_hours = timedelta(hours=24)
    coalesced: List[Dict[str, Any]] = []

    for r in reminders:
        r_copy = dict(r)
        status = str(r_copy.get("status", "pending")).lower()

        # Terminal statuses are invariant
        if status in ("completed", "cancelled"):
            coalesced.append(r_copy)
            continue

        if status in ("pending", "snoozed"):
            if status == "snoozed" and r_copy.get("snooze_until"):
                raw_due = r_copy.get("snooze_until")
            else:
                raw_due = r_copy.get("next_due_at")

            if raw_due:
                try:
                    if isinstance(raw_due, str):
                        due_dt = datetime.fromisoformat(raw_due)
                    elif isinstance(raw_due, datetime):
                        due_dt = raw_due
                    else:
                        due_dt = None

                    if due_dt is not None:
                        if due_dt.tzinfo is None:
                            due_dt = due_dt.replace(tzinfo=timezone.utc)
                        else:
                            due_dt = due_dt.astimezone(timezone.utc)

                        if now_utc - due_dt > twenty_four_hours:
                            r_copy["status"] = "missed"
                except Exception as e:
                    logger.warning("Failed to evaluate overdue date for reminder %s: %s", r_copy.get("id"), e)

        coalesced.append(r_copy)

    return coalesced


# ============================================================================
# Section 4: RFC 5545 .ics Calendar Generator
# ============================================================================


def _escape_ics_text(val: Optional[str]) -> str:
    """Escapes special characters in text per RFC 5545 §3.3.11."""
    if not val:
        return ""
    text = str(val)
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\\n").replace("\n", "\\n")
    return text


def generate_ics_calendar(
    reminders: List[Dict[str, Any]],
    sanitize_phi: bool = True,
) -> str:
    """Generates RFC 5545 .ics calendar content formatted with CRLF.

    Args:
        reminders: List of reminder state dicts or Reminder ORM instances.
        sanitize_phi: When True (default), masks medical specifics in title and description.
                      When False, exports verbatim title and description.

    Returns:
        Valid RFC 5545 iCalendar stream string.
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Carefold//Carefold Autonomy Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for r in reminders:
        if isinstance(r, dict):
            r_id = r.get("id") or str(uuid.uuid4())
            due_iso = r.get("next_due_at") or r.get("snooze_until") or r.get("created_at")
            category = r.get("category", "general")
            raw_title = r.get("title", "Carefold Reminder")
            raw_desc = r.get("description", "")
            rrule = r.get("rrule")
        else:
            r_id = getattr(r, "id", str(uuid.uuid4()))
            due_iso = getattr(r, "next_due_at", None) or getattr(r, "snooze_until", None)
            category = getattr(r, "category", "general")
            raw_title = getattr(r, "title", "Carefold Reminder")
            raw_desc = getattr(r, "description", "")
            rrule = getattr(r, "rrule", None)

        if due_iso:
            try:
                if isinstance(due_iso, str):
                    dt = datetime.fromisoformat(due_iso)
                elif isinstance(due_iso, datetime):
                    dt = due_iso
                else:
                    dt = datetime.now(timezone.utc)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                dt_stamp = dt.strftime("%Y%m%dT%H%M%SZ")
            except Exception:
                dt_stamp = now_stamp
        else:
            dt_stamp = now_stamp

        if sanitize_phi:
            cat_name = (category or "general").title()
            title = f"Carefold {cat_name} Reminder"
            desc = "Sanitized reminder event. Check Carefold app for private details."
        else:
            title = _escape_ics_text(raw_title)
            desc = _escape_ics_text(raw_desc)

        event_lines = [
            "BEGIN:VEVENT",
            f"UID:{r_id}@carefold.local",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART:{dt_stamp}",
            f"SUMMARY:{title}",
            f"DESCRIPTION:{desc}",
            "STATUS:CONFIRMED",
        ]
        if category:
            event_lines.append(f"CATEGORIES:{str(category).upper()}")
        if rrule:
            clean_rule = str(rrule).strip()
            if clean_rule.upper().startswith("RRULE:"):
                clean_rule = clean_rule[6:].strip()
            event_lines.append(f"RRULE:{clean_rule}")

        event_lines.append("END:VEVENT")
        lines.extend(event_lines)

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


# ============================================================================
# Section 5: JobRunner Handler Bridge (`kind="reminder"`)
# ============================================================================


async def handle_reminder_job(job: Any, session_factory: Optional[Any] = None) -> None:
    """Processes a due reminder job leased by JobRunner.

    Advances recurring reminders to their next occurrence via advance_rrule_occurrence,
    completes one-shot reminders, and checks >24h overdue coalescing.

    Args:
        job: DBJob ORM or in-memory job instance leased by JobRunner.
        session_factory: AsyncSession factory if running against a database.
    """
    # 1. Parse payload to extract reminder_id
    payload_data: Dict[str, Any] = {}
    if hasattr(job, "payload_dict") and isinstance(job.payload_dict, dict):
        payload_data = job.payload_dict
    elif hasattr(job, "payload") and job.payload:
        if isinstance(job.payload, str):
            try:
                payload_data = json.loads(job.payload)
            except Exception:
                pass
        elif isinstance(job.payload, dict):
            payload_data = job.payload

    reminder_id = payload_data.get("reminder_id")

    # In-memory execution fallback (when no DB session is provided)
    if session_factory is None:
        rrule = getattr(job, "rrule", None) or payload_data.get("rrule")
        tz_name = getattr(job, "timezone", "UTC") or payload_data.get("timezone", "UTC")
        next_run = getattr(job, "next_run_at", datetime.now(timezone.utc))

        if rrule:
            next_dt = advance_rrule_occurrence(next_run, rrule, tz_name)
            if next_dt is not None:
                setattr(job, "next_run_at", next_dt)
                setattr(job, "status", "pending")
                setattr(job, "attempts", 0)
                setattr(job, "lease_owner", None)
                setattr(job, "lease_until", None)
            else:
                setattr(job, "status", "completed")
                setattr(job, "lease_owner", None)
                setattr(job, "lease_until", None)
        else:
            setattr(job, "status", "completed")
            setattr(job, "lease_owner", None)
            setattr(job, "lease_until", None)
        return

    # Database execution
    if not reminder_id:
        setattr(job, "status", "completed")
        return

    now_utc = datetime.now(timezone.utc)

    async with session_factory() as session:
        stmt = select(Reminder).where(Reminder.id == str(reminder_id))
        res = await session.execute(stmt)
        reminder = res.scalar_one_or_none()

        if reminder is None:
            setattr(job, "status", "completed")
            return

        if reminder.status in ("completed", "cancelled"):
            setattr(job, "status", reminder.status)
            return

        # Check overdue coalescing (> 24 hours overdue)
        effective_due = reminder.snooze_until if (reminder.status == "snoozed" and reminder.snooze_until) else reminder.next_due_at
        if effective_due and (now_utc - effective_due.astimezone(timezone.utc)) > timedelta(hours=24):
            reminder.status = "missed"
            reminder.updated_at = now_utc
            setattr(job, "status", "missed")
            await session.commit()
            return

        # Trigger reminder
        reminder.last_triggered_at = now_utc
        reminder.updated_at = now_utc

        try:
            await record_audit(
                {
                    "profile_id": reminder.profile_id,
                    "action": "trigger",
                    "tool": "reminder",
                    "risk": "read",
                    "external_ref": f"reminder:{reminder.id}",
                    "details": {
                        "title": reminder.title,
                        "category": reminder.category,
                        "next_due_at": reminder.next_due_at.isoformat() if reminder.next_due_at else None,
                    },
                },
                actor_user_id="system:job_runner",
                risk="read",
            )
        except Exception as audit_err:
            logger.warning("Audit record failed for reminder trigger %s: %s", reminder.id, audit_err)

        if reminder.rrule:
            next_dt = advance_rrule_occurrence(reminder.next_due_at, reminder.rrule, reminder.timezone)
            if next_dt is not None:
                reminder.next_due_at = next_dt
                reminder.status = "pending"
                reminder.snooze_until = None
                setattr(job, "next_run_at", next_dt)
                setattr(job, "status", "pending")
                setattr(job, "attempts", 0)
                setattr(job, "lease_owner", None)
                setattr(job, "lease_until", None)
            else:
                reminder.status = "completed"
                setattr(job, "status", "completed")
        else:
            reminder.status = "completed"
            setattr(job, "status", "completed")

        await session.commit()


__all__ = [
    "SNOOZE_DELTAS",
    "advance_rrule_occurrence",
    "apply_reminder_snooze",
    "coalesce_overdue_reminders",
    "generate_ics_calendar",
    "handle_reminder_job",
]
