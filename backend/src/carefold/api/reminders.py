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

"""REST API endpoints for Clinical Reminders, Snooze Lifecycle, and .ics Export (AU-28)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import secrets
from typing import Any, Dict, List, Literal, Optional
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db
from carefold.api.profiles import get_user_profile_access
from carefold.audit.logger import record_audit
from carefold.auth.ports import UserProfile
from carefold.clinical.reminders import (
    SNOOZE_DELTAS,
    advance_rrule_occurrence,
    apply_reminder_snooze,
    generate_ics_calendar,
)
from carefold.db.models import Job, Profile, Reminder

logger = logging.getLogger("carefold.api.reminders")

router = APIRouter(tags=["reminders"])

ReminderCategoryLiteral = Literal["medication", "vitals", "appointment", "prep", "general"]
ReminderStatusLiteral = Literal["pending", "completed", "snoozed", "missed", "cancelled"]


# ============================================================================
# Section 1: Access Control Dependency
# ============================================================================


def require_profile_access(required_access: str):
    """Enforces profile-scoped role-based access control for reminders."""
    async def _dependency(
        profile_id: str,
        user: UserProfile = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> Profile:
        clean_id = (profile_id or "").strip()
        if not clean_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="profile_id path parameter is required.",
            )

        stmt = select(Profile).where(Profile.id == clean_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile '{clean_id}' not found.",
            )

        access = await get_user_profile_access(profile, user, db)
        if access is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not have permission for this profile.",
            )

        if required_access == "manage" and access != "manage":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: management permissions required to modify reminders for this profile.",
            )

        if required_access == "view_clinical" and access not in ("manage", "view_clinical"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required to inspect reminders.",
            )

        return profile

    return _dependency


_profile_reminder_preferences: Dict[str, Dict[str, Any]] = {}


def set_profile_reminder_preference(profile_id: str, key: str, value: Any) -> None:
    """Sets a runtime preference for a profile (e.g. calendar_feed_token)."""
    _profile_reminder_preferences.setdefault(profile_id, {})[key] = value


def get_profile_reminder_preference(profile_id: str, key: str, default: Any = None) -> Any:
    """Gets a runtime preference for a profile."""
    return _profile_reminder_preferences.get(profile_id, {}).get(key, default)


# ============================================================================
# Section 2: Pydantic Request & Response Schemas
# ============================================================================


class ReminderCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Reminder prompt or directive title")
    next_due_at: datetime = Field(..., description="Scheduled next execution timestamp (ISO-8601)")
    description: Optional[str] = Field(None, description="Detailed context or instructions")
    category: ReminderCategoryLiteral = Field("general", description="Reminder category")
    rrule: Optional[str] = Field(None, max_length=255, description="RFC 5545 recurrence rule specification string")
    timezone: str = Field("UTC", max_length=64, description="Local profile IANA timezone identifier")

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, v: str) -> str:
        tz_str = v.strip() or "UTC"
        try:
            ZoneInfo(tz_str)
        except Exception as exc:
            raise ValueError(f"Invalid IANA timezone identifier: '{tz_str}'.") from exc
        return tz_str

    @field_validator("rrule")
    @classmethod
    def validate_rrule_syntax(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        clean = v.strip()
        if "FREQ=" not in clean.upper():
            raise ValueError("Invalid RFC 5545 RRULE syntax. Must include FREQ token (e.g. 'FREQ=DAILY;INTERVAL=1').")
        return clean


class ReminderUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    category: Optional[ReminderCategoryLiteral] = None
    rrule: Optional[str] = None
    timezone: Optional[str] = None
    next_due_at: Optional[datetime] = None
    status: Optional[ReminderStatusLiteral] = None

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        tz_str = v.strip() or "UTC"
        try:
            ZoneInfo(tz_str)
        except Exception as exc:
            raise ValueError(f"Invalid IANA timezone identifier: '{tz_str}'.") from exc
        return tz_str

    @field_validator("rrule")
    @classmethod
    def validate_rrule_syntax(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        clean = v.strip()
        if "FREQ=" not in clean.upper():
            raise ValueError("Invalid RFC 5545 RRULE syntax. Must include FREQ token (e.g. 'FREQ=DAILY;INTERVAL=1').")
        return clean


class ReminderSnoozeRequest(BaseModel):
    interval: str = Field(..., description="Snooze increment preset (+15m, +1h, +24h)")


class ReminderResponse(BaseModel):
    id: str
    profile_id: str
    title: str
    description: Optional[str] = None
    category: str
    rrule: Optional[str] = None
    timezone: str
    next_due_at: datetime
    status: str
    last_triggered_at: Optional[datetime] = None
    snooze_until: Optional[datetime] = None
    job_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ReminderListResponse(BaseModel):
    reminders: List[ReminderResponse]
    total: int


# ============================================================================
# Section 3: REST API Endpoints
# ============================================================================


@router.post(
    "/profiles/{profile_id}/reminders",
    response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new clinical reminder and schedule Job",
)
async def create_reminder(
    profile_id: str,
    payload: ReminderCreateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> ReminderResponse:
    """Creates a new reminder and enqueues matching wall-clock Job in the jobs table."""
    due_dt = payload.next_due_at
    if due_dt.tzinfo is None:
        due_utc = due_dt.replace(tzinfo=timezone.utc)
    else:
        due_utc = due_dt.astimezone(timezone.utc)

    now_utc = datetime.now(timezone.utc)
    rem_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    reminder = Reminder(
        id=rem_id,
        profile_id=profile.id,
        title=payload.title.strip(),
        description=payload.description,
        category=payload.category,
        rrule=payload.rrule,
        timezone=payload.timezone,
        next_due_at=due_utc,
        status="pending",
        created_at=now_utc,
        updated_at=now_utc,
    )
    db.add(reminder)

    job = Job(
        id=job_id,
        profile_id=profile.id,
        kind="reminder",
        payload=json.dumps({"reminder_id": rem_id}),
        timezone=payload.timezone,
        rrule=payload.rrule,
        next_run_at=due_utc,
        status="pending",
        idempotency_key=f"reminder:{rem_id}",
        attempts=0,
        created_at=now_utc,
        updated_at=now_utc,
    )
    db.add(job)
    await db.commit()
    await db.refresh(reminder)

    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "create",
                "tool": "create_reminder",
                "risk": "write_local",
                "external_ref": f"reminder:{rem_id}",
                "details": {
                    "title": reminder.title,
                    "category": reminder.category,
                    "next_due_at": due_utc.isoformat(),
                    "rrule": reminder.rrule,
                },
            },
            actor_user_id=user.id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for create_reminder %s: %s", rem_id, audit_err)

    return ReminderResponse(
        id=reminder.id,
        profile_id=reminder.profile_id,
        title=reminder.title,
        description=reminder.description,
        category=reminder.category,
        rrule=reminder.rrule,
        timezone=reminder.timezone,
        next_due_at=reminder.next_due_at,
        status=reminder.status,
        last_triggered_at=reminder.last_triggered_at,
        snooze_until=reminder.snooze_until,
        job_id=job_id,
        created_at=reminder.created_at,
        updated_at=reminder.updated_at,
    )


@router.get(
    "/profiles/{profile_id}/reminders",
    response_model=ReminderListResponse,
    summary="List clinical reminders for a profile",
)
async def list_reminders(
    profile_id: str,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    category: Optional[str] = Query(None, description="Filter by category"),
    due_before: Optional[str] = Query(None, description="Filter reminders due on or before ISO-8601 timestamp"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> ReminderListResponse:
    """Lists reminders, automatically sweeps overdue items past 24 hours to missed."""
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = now_utc - timedelta(hours=24)

    # 1. Sweep overdue reminders > 24 hours
    overdue_stmt = select(Reminder).where(
        Reminder.profile_id == profile.id,
        Reminder.status.in_(["pending", "snoozed"]),
    )
    overdue_res = await db.execute(overdue_stmt)
    pending_items = list(overdue_res.scalars().all())

    sweep_needed = False
    for r in pending_items:
        eff_due = r.snooze_until if (r.status == "snoozed" and r.snooze_until) else r.next_due_at
        if eff_due:
            eff_due_utc = eff_due.astimezone(timezone.utc) if eff_due.tzinfo else eff_due.replace(tzinfo=timezone.utc)
            if now_utc - eff_due_utc > timedelta(hours=24):
                r.status = "missed"
                r.updated_at = now_utc
                sweep_needed = True

                # Also mark job missed
                job_stmt = select(Job).where(
                    Job.kind == "reminder",
                    Job.idempotency_key == f"reminder:{r.id}",
                    Job.status == "pending",
                )
                j_res = await db.execute(job_stmt)
                m_job = j_res.scalar_one_or_none()
                if m_job:
                    m_job.status = "missed"
                    m_job.updated_at = now_utc

    if sweep_needed:
        await db.commit()

    # 2. Query filtered reminders
    query = select(Reminder).where(Reminder.profile_id == profile.id)

    if status_filter:
        query = query.where(Reminder.status == status_filter.strip().lower())
    if category:
        query = query.where(Reminder.category == category.strip().lower())
    if due_before:
        try:
            dt_b = datetime.fromisoformat(due_before)
            if dt_b.tzinfo is None:
                dt_b = dt_b.replace(tzinfo=timezone.utc)
            query = query.where(Reminder.next_due_at <= dt_b.astimezone(timezone.utc))
        except Exception:
            pass

    count_stmt = select(func.count()).select_from(query.subquery())
    count_res = await db.execute(count_stmt)
    total = count_res.scalar_one()

    query = query.order_by(Reminder.next_due_at.asc()).limit(limit).offset(offset)
    res = await db.execute(query)
    records = list(res.scalars().all())

    return ReminderListResponse(
        reminders=[
            ReminderResponse(
                id=r.id,
                profile_id=r.profile_id,
                title=r.title,
                description=r.description,
                category=r.category,
                rrule=r.rrule,
                timezone=r.timezone,
                next_due_at=r.next_due_at,
                status=r.status,
                last_triggered_at=r.last_triggered_at,
                snooze_until=r.snooze_until,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in records
        ],
        total=total,
    )


@router.get(
    "/profiles/{profile_id}/reminders/export.ics",
    summary="Export reminders as RFC 5545 .ics calendar stream",
)
async def export_ics_calendar(
    profile_id: str,
    sanitize_phi: bool = Query(True, description="Default-on PHI masking for external calendars"),
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Exports active reminders in standards-compliant RFC 5545 iCalendar stream."""
    stmt = select(Reminder).where(
        Reminder.profile_id == profile.id,
        Reminder.status != "cancelled",
    ).order_by(Reminder.next_due_at.asc())
    res = await db.execute(stmt)
    records = list(res.scalars().all())

    ics_content = generate_ics_calendar(records, sanitize_phi=sanitize_phi)
    return Response(
        content=ics_content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="carefold_reminders.ics"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.get(
    "/profiles/{profile_id}/reminders/feed.ics",
    summary="Live authenticated RFC 5545 calendar subscription feed",
)
async def calendar_subscription_feed(
    profile_id: str,
    token: Optional[str] = Query(None, description="Calendar feed subscription token"),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Provides an authenticated live calendar feed for OS/mobile calendar apps."""
    clean_id = (profile_id or "").strip()
    if not clean_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing profile_id.")

    stmt = select(Profile).where(Profile.id == clean_id)
    res = await db.execute(stmt)
    profile = res.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    # Validate feed token against profile preferences
    auth_token = token
    if not auth_token and authorization and authorization.startswith("Bearer "):
        auth_token = authorization[7:].strip()

    expected_token = get_profile_reminder_preference(profile.id, "calendar_feed_token")
    if not expected_token and hasattr(profile, "preferences") and isinstance(profile.preferences, dict):
        expected_token = profile.preferences.get("calendar_feed_token")
    if not expected_token and hasattr(profile, "preferences_json") and profile.preferences_json:
        try:
            prefs = json.loads(profile.preferences_json)
            if isinstance(prefs, dict):
                expected_token = prefs.get("calendar_feed_token")
        except Exception:
            pass

    # If no feed token configured, or provided token does not match
    if not auth_token or not expected_token or not secrets.compare_digest(auth_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid calendar feed token.",
        )

    rem_stmt = select(Reminder).where(
        Reminder.profile_id == profile.id,
        Reminder.status != "cancelled",
    ).order_by(Reminder.next_due_at.asc())
    rem_res = await db.execute(rem_stmt)
    records = list(rem_res.scalars().all())

    ics_content = generate_ics_calendar(records, sanitize_phi=True)
    return Response(
        content=ics_content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="carefold_reminders.ics"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.get(
    "/profiles/{profile_id}/reminders/{reminder_id}",
    response_model=ReminderResponse,
    summary="Get single reminder details",
)
async def get_reminder(
    profile_id: str,
    reminder_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> ReminderResponse:
    """Fetches single reminder record by ID."""
    stmt = select(Reminder).where(
        Reminder.id == reminder_id,
        Reminder.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    rem = res.scalar_one_or_none()
    if rem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder '{reminder_id}' not found.",
        )

    return ReminderResponse(
        id=rem.id,
        profile_id=rem.profile_id,
        title=rem.title,
        description=rem.description,
        category=rem.category,
        rrule=rem.rrule,
        timezone=rem.timezone,
        next_due_at=rem.next_due_at,
        status=rem.status,
        last_triggered_at=rem.last_triggered_at,
        snooze_until=rem.snooze_until,
        created_at=rem.created_at,
        updated_at=rem.updated_at,
    )


@router.patch(
    "/profiles/{profile_id}/reminders/{reminder_id}",
    response_model=ReminderResponse,
    summary="Update reminder fields or mark completed",
)
async def update_reminder(
    profile_id: str,
    reminder_id: str,
    payload: ReminderUpdateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> ReminderResponse:
    """Updates reminder fields and advances recurrence if completed."""
    stmt = select(Reminder).where(
        Reminder.id == reminder_id,
        Reminder.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    rem = res.scalar_one_or_none()
    if rem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder '{reminder_id}' not found.",
        )

    now_utc = datetime.now(timezone.utc)
    previous_status = rem.status

    if payload.title is not None:
        rem.title = payload.title.strip()
    if payload.description is not None:
        rem.description = payload.description
    if payload.category is not None:
        rem.category = payload.category
    if payload.timezone is not None:
        rem.timezone = payload.timezone
    if payload.rrule is not None:
        rem.rrule = payload.rrule

    # If updating next_due_at directly
    if payload.next_due_at is not None:
        due_utc = payload.next_due_at.astimezone(timezone.utc) if payload.next_due_at.tzinfo else payload.next_due_at.replace(tzinfo=timezone.utc)
        rem.next_due_at = due_utc

    # Check status transitions
    if payload.status is not None:
        if payload.status == "completed":
            # If recurring, advance occurrence
            if rem.rrule:
                next_dt = advance_rrule_occurrence(rem.next_due_at, rem.rrule, rem.timezone)
                if next_dt is not None:
                    rem.next_due_at = next_dt
                    rem.status = "pending"
                    rem.snooze_until = None
                    rem.last_triggered_at = now_utc
                else:
                    rem.status = "completed"
                    rem.last_triggered_at = now_utc
            else:
                rem.status = "completed"
                rem.last_triggered_at = now_utc
        else:
            rem.status = payload.status

    rem.updated_at = now_utc

    # Sync corresponding Job
    job_stmt = select(Job).where(
        Job.kind == "reminder",
        Job.idempotency_key == f"reminder:{rem.id}",
    )
    j_res = await db.execute(job_stmt)
    matching_job = j_res.scalar_one_or_none()

    if matching_job:
        matching_job.next_run_at = rem.next_due_at
        matching_job.rrule = rem.rrule
        matching_job.timezone = rem.timezone
        matching_job.status = "pending" if rem.status in ("pending", "snoozed") else rem.status
        matching_job.lease_owner = None
        matching_job.lease_until = None
        matching_job.updated_at = now_utc

    await db.commit()
    await db.refresh(rem)

    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "update",
                "tool": "update_reminder",
                "risk": "write_local",
                "external_ref": f"reminder:{rem.id}",
                "details": {
                    "previous_status": previous_status,
                    "new_status": rem.status,
                    "next_due_at": rem.next_due_at.isoformat(),
                },
            },
            actor_user_id=user.id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for update_reminder: %s", audit_err)

    return ReminderResponse(
        id=rem.id,
        profile_id=rem.profile_id,
        title=rem.title,
        description=rem.description,
        category=rem.category,
        rrule=rem.rrule,
        timezone=rem.timezone,
        next_due_at=rem.next_due_at,
        status=rem.status,
        last_triggered_at=rem.last_triggered_at,
        snooze_until=rem.snooze_until,
        created_at=rem.created_at,
        updated_at=rem.updated_at,
    )


@router.delete(
    "/profiles/{profile_id}/reminders/{reminder_id}",
    summary="Delete or cancel a reminder",
)
async def delete_reminder(
    profile_id: str,
    reminder_id: str,
    hard_delete: bool = Query(False, description="Set True to permanently delete record"),
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cancels (soft) or permanently deletes (hard) a reminder and associated Job."""
    stmt = select(Reminder).where(
        Reminder.id == reminder_id,
        Reminder.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    rem = res.scalar_one_or_none()
    if rem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder '{reminder_id}' not found.",
        )

    job_stmt = select(Job).where(
        Job.kind == "reminder",
        Job.idempotency_key == f"reminder:{rem.id}",
    )
    j_res = await db.execute(job_stmt)
    matching_job = j_res.scalar_one_or_none()

    now_utc = datetime.now(timezone.utc)
    if hard_delete:
        await db.delete(rem)
        if matching_job:
            await db.delete(matching_job)
        await db.commit()
        status_result = "deleted"
    else:
        rem.status = "cancelled"
        rem.updated_at = now_utc
        if matching_job:
            matching_job.status = "cancelled"
            matching_job.updated_at = now_utc
        await db.commit()
        status_result = "cancelled"

    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "delete" if hard_delete else "cancel",
                "tool": "delete_reminder",
                "risk": "write_local",
                "external_ref": f"reminder:{reminder_id}",
                "details": {"hard_delete": hard_delete, "status": status_result},
            },
            actor_user_id=user.id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for delete_reminder: %s", audit_err)

    return {"status": status_result, "reminder_id": reminder_id}


@router.post(
    "/profiles/{profile_id}/reminders/{reminder_id}/snooze",
    response_model=ReminderResponse,
    summary="Snooze reminder by +15m, +1h, or +24h",
)
async def snooze_reminder(
    profile_id: str,
    reminder_id: str,
    payload: ReminderSnoozeRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> ReminderResponse:
    """Applies preset snooze (+15m, +1h, +24h) to reminder and reschedules wall-clock Job."""
    stmt = select(Reminder).where(
        Reminder.id == reminder_id,
        Reminder.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    rem = res.scalar_one_or_none()
    if rem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder '{reminder_id}' not found.",
        )

    now_utc = datetime.now(timezone.utc)
    rem_dict = {
        "id": rem.id,
        "status": rem.status,
        "next_due_at": rem.next_due_at.isoformat(),
        "snooze_until": rem.snooze_until.isoformat() if rem.snooze_until else None,
    }

    try:
        snoozed_data = apply_reminder_snooze(rem_dict, payload.interval, now_utc)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )

    snooze_dt = datetime.fromisoformat(snoozed_data["snooze_until"])
    rem.status = "snoozed"
    rem.snooze_until = snooze_dt
    rem.updated_at = now_utc

    # Update matching job
    job_stmt = select(Job).where(
        Job.kind == "reminder",
        Job.idempotency_key == f"reminder:{rem.id}",
    )
    j_res = await db.execute(job_stmt)
    matching_job = j_res.scalar_one_or_none()
    if matching_job:
        matching_job.next_run_at = snooze_dt
        matching_job.status = "pending"
        matching_job.lease_owner = None
        matching_job.lease_until = None
        matching_job.updated_at = now_utc

    await db.commit()
    await db.refresh(rem)

    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "snooze",
                "tool": "snooze_reminder",
                "risk": "write_local",
                "external_ref": f"reminder:{rem.id}",
                "details": {
                    "interval": payload.interval,
                    "snooze_until": snooze_dt.isoformat(),
                },
            },
            actor_user_id=user.id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for snooze_reminder: %s", audit_err)

    return ReminderResponse(
        id=rem.id,
        profile_id=rem.profile_id,
        title=rem.title,
        description=rem.description,
        category=rem.category,
        rrule=rem.rrule,
        timezone=rem.timezone,
        next_due_at=rem.next_due_at,
        status=rem.status,
        last_triggered_at=rem.last_triggered_at,
        snooze_until=rem.snooze_until,
        created_at=rem.created_at,
        updated_at=rem.updated_at,
    )


__all__ = ["router", "set_profile_reminder_preference", "get_profile_reminder_preference"]
