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

"""REST API endpoints for Clinical Appointments & Scheduling Navigation (AU-29)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Literal, Optional
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db
from carefold.api.profiles import get_user_profile_access
from carefold.audit.logger import record_audit
from carefold.auth.ports import UserProfile
from carefold.clinical.appointments import (
    AppointmentStatus,
    InvalidStatusTransitionError,
    generate_how_to_book_drafts,
    sweep_post_visit_transitions,
    validate_status_transition,
)
from carefold.db.models import Appointment, Profile

logger = logging.getLogger("carefold.api.appointments")

router = APIRouter(tags=["appointments"])

AppointmentStatusLiteral = Literal["requested", "scheduled", "confirmed", "completed", "cancelled"]


# ============================================================================
# Section 1: Access Control Dependency
# ============================================================================


def require_profile_access(required_access: str):
    """Enforces profile-scoped role-based access control for appointments."""
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
                detail="Access denied: management permissions required to modify appointments for this profile.",
            )

        if required_access == "view_clinical" and access not in ("manage", "view_clinical"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required to inspect appointments.",
            )

        return profile

    return _dependency


# ============================================================================
# Section 2: Pydantic Request & Response Schemas
# ============================================================================


class AppointmentCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Appointment title or encounter description")
    start_time: datetime = Field(..., description="Scheduled start timestamp (ISO-8601)")
    end_time: datetime = Field(..., description="Scheduled end timestamp (ISO-8601)")
    timezone: str = Field("UTC", max_length=64, description="Local IANA timezone identifier")
    provider_name: Optional[str] = Field(None, max_length=255, description="Healthcare provider or clinic name")
    specialty: Optional[str] = Field(None, max_length=128, description="Medical specialty (e.g. Cardiology)")
    location: Optional[str] = Field(None, max_length=255, description="Clinic address or telehealth link")
    clinic_phone: Optional[str] = Field(None, max_length=64, description="Clinic telephone contact")
    status: Literal["requested", "scheduled", "confirmed"] = Field("scheduled", description="Initial lifecycle status")
    reason: Optional[str] = Field(None, description="Chief complaint or purpose of appointment")
    preparation_notes: Optional[str] = Field(None, description="Pre-visit preparation checklist or draft script")

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, v: str) -> str:
        tz_str = v.strip() or "UTC"
        try:
            ZoneInfo(tz_str)
        except Exception as exc:
            raise ValueError(f"Invalid IANA timezone identifier: '{tz_str}'.") from exc
        return tz_str

    @model_validator(mode="after")
    def validate_times(self) -> AppointmentCreateRequest:
        if self.start_time >= self.end_time:
            raise ValueError("Parameter 'end_time' must be strictly after 'start_time'.")
        return self


class AppointmentUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    timezone: Optional[str] = None
    provider_name: Optional[str] = None
    specialty: Optional[str] = None
    location: Optional[str] = None
    clinic_phone: Optional[str] = None
    status: Optional[AppointmentStatusLiteral] = None
    reason: Optional[str] = None
    preparation_notes: Optional[str] = None

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

    @model_validator(mode="after")
    def validate_times(self) -> AppointmentUpdateRequest:
        if self.start_time is not None and self.end_time is not None:
            if self.start_time >= self.end_time:
                raise ValueError("Parameter 'end_time' must be strictly after 'start_time'.")
        return self


class DraftBookingRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    provider_name: str = Field(..., min_length=1, max_length=255)
    specialty: str = Field(..., min_length=1, max_length=128)
    clinic_phone: str = Field(..., min_length=1, max_length=64)
    reason: str = Field(..., min_length=1)
    insurance_name: Optional[str] = "Carefold Health Plan"
    insurance_member_id: Optional[str] = None
    insurance_group_number: Optional[str] = None
    preferred_days: Optional[List[str]] = None
    preferred_time_of_day: Optional[str] = "Morning"
    visit_mode: Optional[str] = "in-person"
    tentative_start_time: Optional[datetime] = None
    tentative_end_time: Optional[datetime] = None


class AppointmentResponse(BaseModel):
    id: str
    profile_id: str
    title: str
    provider_name: Optional[str] = None
    specialty: Optional[str] = None
    location: Optional[str] = None
    clinic_phone: Optional[str] = None
    start_time: datetime
    end_time: datetime
    timezone: str
    status: str
    reason: Optional[str] = None
    preparation_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AppointmentListResponse(BaseModel):
    appointments: List[AppointmentResponse]
    total: int
    followup_prompts: List[Dict[str, Any]] = Field(default_factory=list)


class DraftBookingResponse(BaseModel):
    appointment: AppointmentResponse
    phone_script: str
    portal_draft: str
    checklist: List[str]


# ============================================================================
# Section 3: REST API Endpoints
# ============================================================================


@router.post(
    "/profiles/{profile_id}/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new clinical appointment",
)
async def create_appointment(
    profile_id: str,
    payload: AppointmentCreateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> AppointmentResponse:
    """Creates a new appointment for a profile with validation and audit logging."""
    start_dt = payload.start_time
    end_dt = payload.end_time

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    else:
        start_dt = start_dt.astimezone(timezone.utc)

    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    else:
        end_dt = end_dt.astimezone(timezone.utc)

    appt_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)

    appt = Appointment(
        id=appt_id,
        profile_id=profile.id,
        title=payload.title.strip(),
        provider_name=payload.provider_name.strip() if payload.provider_name else None,
        specialty=payload.specialty.strip() if payload.specialty else None,
        location=payload.location.strip() if payload.location else None,
        clinic_phone=payload.clinic_phone.strip() if payload.clinic_phone else None,
        start_time=start_dt,
        end_time=end_dt,
        timezone=payload.timezone,
        status=payload.status,
        reason=payload.reason,
        preparation_notes=payload.preparation_notes,
        created_at=now_utc,
        updated_at=now_utc,
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)

    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "create",
                "tool": "create_appointment",
                "risk": "write_local",
                "external_ref": f"appointment:{appt.id}",
                "details": {
                    "title": appt.title,
                    "status": appt.status,
                    "start_time": appt.start_time.isoformat(),
                    "end_time": appt.end_time.isoformat(),
                },
            },
            actor_user_id=user.id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for appointment %s: %s", appt.id, audit_err)

    return AppointmentResponse(
        id=appt.id,
        profile_id=appt.profile_id,
        title=appt.title,
        provider_name=appt.provider_name,
        specialty=appt.specialty,
        location=appt.location,
        clinic_phone=appt.clinic_phone,
        start_time=appt.start_time,
        end_time=appt.end_time,
        timezone=appt.timezone,
        status=appt.status,
        reason=appt.reason,
        preparation_notes=appt.preparation_notes,
        created_at=appt.created_at,
        updated_at=appt.updated_at,
    )


@router.get(
    "/profiles/{profile_id}/appointments",
    response_model=AppointmentListResponse,
    summary="List appointments for a profile",
)
async def list_appointments(
    profile_id: str,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    start_after: Optional[str] = Query(None, description="ISO-8601 start lower bound"),
    start_before: Optional[str] = Query(None, description="ISO-8601 start upper bound"),
    specialty: Optional[str] = Query(None, description="Filter by specialty"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> AppointmentListResponse:
    """Lists appointments with filtering and automatically sweeps post-visit transitions."""
    # Run post-visit auto-transition sweep
    completed_ids, prompts = await sweep_post_visit_transitions(db, profile.id)

    query = select(Appointment).where(Appointment.profile_id == profile.id)

    if status_filter:
        query = query.where(Appointment.status == status_filter.strip().lower())
    if specialty:
        query = query.where(Appointment.specialty == specialty.strip())
    if start_after:
        try:
            dt_a = datetime.fromisoformat(start_after)
            if dt_a.tzinfo is None:
                dt_a = dt_a.replace(tzinfo=timezone.utc)
            query = query.where(Appointment.start_time >= dt_a.astimezone(timezone.utc))
        except Exception:
            pass
    if start_before:
        try:
            dt_b = datetime.fromisoformat(start_before)
            if dt_b.tzinfo is None:
                dt_b = dt_b.replace(tzinfo=timezone.utc)
            query = query.where(Appointment.start_time <= dt_b.astimezone(timezone.utc))
        except Exception:
            pass

    count_stmt = select(func.count()).select_from(query.subquery())
    count_res = await db.execute(count_stmt)
    total = count_res.scalar_one()

    query = query.order_by(Appointment.start_time.asc()).limit(limit).offset(offset)
    res = await db.execute(query)
    records = list(res.scalars().all())

    return AppointmentListResponse(
        appointments=[
            AppointmentResponse(
                id=a.id,
                profile_id=a.profile_id,
                title=a.title,
                provider_name=a.provider_name,
                specialty=a.specialty,
                location=a.location,
                clinic_phone=a.clinic_phone,
                start_time=a.start_time,
                end_time=a.end_time,
                timezone=a.timezone,
                status=a.status,
                reason=a.reason,
                preparation_notes=a.preparation_notes,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in records
        ],
        total=total,
        followup_prompts=prompts,
    )


@router.get(
    "/profiles/{profile_id}/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    summary="Get single appointment details",
)
async def get_appointment(
    profile_id: str,
    appointment_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> AppointmentResponse:
    """Fetches single appointment record by ID."""
    stmt = select(Appointment).where(
        Appointment.id == appointment_id,
        Appointment.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    appt = res.scalar_one_or_none()
    if appt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment '{appointment_id}' not found.",
        )

    return AppointmentResponse(
        id=appt.id,
        profile_id=appt.profile_id,
        title=appt.title,
        provider_name=appt.provider_name,
        specialty=appt.specialty,
        location=appt.location,
        clinic_phone=appt.clinic_phone,
        start_time=appt.start_time,
        end_time=appt.end_time,
        timezone=appt.timezone,
        status=appt.status,
        reason=appt.reason,
        preparation_notes=appt.preparation_notes,
        created_at=appt.created_at,
        updated_at=appt.updated_at,
    )


@router.patch(
    "/profiles/{profile_id}/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    summary="Update appointment details or status",
)
async def update_appointment(
    profile_id: str,
    appointment_id: str,
    payload: AppointmentUpdateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> AppointmentResponse:
    """Updates appointment fields with state machine validation and temporal consistency."""
    stmt = select(Appointment).where(
        Appointment.id == appointment_id,
        Appointment.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    appt = res.scalar_one_or_none()
    if appt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment '{appointment_id}' not found.",
        )

    now_utc = datetime.now(timezone.utc)
    previous_status = appt.status

    # Validate status transition if provided
    if payload.status is not None:
        try:
            validate_status_transition(previous_status, payload.status)
        except InvalidStatusTransitionError as err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(err),
            )
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            )
        appt.status = payload.status

    # Validate and update temporal fields
    effective_start = payload.start_time or appt.start_time
    effective_end = payload.end_time or appt.end_time

    if effective_start.tzinfo is None:
        effective_start = effective_start.replace(tzinfo=timezone.utc)
    else:
        effective_start = effective_start.astimezone(timezone.utc)

    if effective_end.tzinfo is None:
        effective_end = effective_end.replace(tzinfo=timezone.utc)
    else:
        effective_end = effective_end.astimezone(timezone.utc)

    if effective_end <= effective_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Updated start_time ({effective_start.isoformat()}) would be after end_time ({effective_end.isoformat()}).",
        )

    if payload.title is not None:
        appt.title = payload.title.strip()
    if payload.start_time is not None:
        appt.start_time = effective_start
    if payload.end_time is not None:
        appt.end_time = effective_end
    if payload.timezone is not None:
        appt.timezone = payload.timezone
    if payload.provider_name is not None:
        appt.provider_name = payload.provider_name.strip() if payload.provider_name else None
    if payload.specialty is not None:
        appt.specialty = payload.specialty.strip() if payload.specialty else None
    if payload.location is not None:
        appt.location = payload.location.strip() if payload.location else None
    if payload.clinic_phone is not None:
        appt.clinic_phone = payload.clinic_phone.strip() if payload.clinic_phone else None
    if payload.reason is not None:
        appt.reason = payload.reason
    if payload.preparation_notes is not None:
        appt.preparation_notes = payload.preparation_notes

    appt.updated_at = now_utc
    await db.commit()
    await db.refresh(appt)

    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "update",
                "tool": "update_appointment",
                "risk": "write_local",
                "external_ref": f"appointment:{appt.id}",
                "details": {
                    "previous_status": previous_status,
                    "new_status": appt.status,
                    "start_time": appt.start_time.isoformat(),
                    "end_time": appt.end_time.isoformat(),
                },
            },
            actor_user_id=user.id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for update_appointment %s: %s", appt.id, audit_err)

    return AppointmentResponse(
        id=appt.id,
        profile_id=appt.profile_id,
        title=appt.title,
        provider_name=appt.provider_name,
        specialty=appt.specialty,
        location=appt.location,
        clinic_phone=appt.clinic_phone,
        start_time=appt.start_time,
        end_time=appt.end_time,
        timezone=appt.timezone,
        status=appt.status,
        reason=appt.reason,
        preparation_notes=appt.preparation_notes,
        created_at=appt.created_at,
        updated_at=appt.updated_at,
    )


@router.delete(
    "/profiles/{profile_id}/appointments/{appointment_id}",
    summary="Delete or cancel appointment",
)
async def delete_appointment(
    profile_id: str,
    appointment_id: str,
    hard_delete: bool = Query(False, description="Set True to permanently remove record"),
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cancels (soft) or permanently deletes (hard) an appointment."""
    stmt = select(Appointment).where(
        Appointment.id == appointment_id,
        Appointment.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    appt = res.scalar_one_or_none()
    if appt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment '{appointment_id}' not found.",
        )

    now_utc = datetime.now(timezone.utc)
    if hard_delete:
        await db.delete(appt)
        await db.commit()
        status_result = "deleted"
    else:
        appt.status = "cancelled"
        appt.updated_at = now_utc
        await db.commit()
        status_result = "cancelled"

    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "delete" if hard_delete else "cancel",
                "tool": "delete_appointment",
                "risk": "write_local",
                "external_ref": f"appointment:{appointment_id}",
                "details": {"hard_delete": hard_delete, "status": status_result},
            },
            actor_user_id=user.id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for delete_appointment: %s", audit_err)

    return {"status": status_result, "appointment_id": appointment_id}


@router.post(
    "/profiles/{profile_id}/appointments/draft-booking",
    response_model=DraftBookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate 'How to Book' scripts and create requested appointment draft",
)
async def draft_booking(
    profile_id: str,
    payload: DraftBookingRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> DraftBookingResponse:
    """Generates structured call script, portal draft, and creates appointment row with status 'requested'."""
    drafts = generate_how_to_book_drafts(
        title=payload.title,
        provider_name=payload.provider_name,
        specialty=payload.specialty,
        clinic_phone=payload.clinic_phone,
        reason=payload.reason,
        insurance_name=payload.insurance_name,
        insurance_member_id=payload.insurance_member_id,
        insurance_group_number=payload.insurance_group_number,
        preferred_days=payload.preferred_days,
        preferred_time_of_day=payload.preferred_time_of_day,
        visit_mode=payload.visit_mode,
    )

    now_utc = datetime.now(timezone.utc)
    start_dt = payload.tentative_start_time or (now_utc + timedelta(days=7))
    end_dt = payload.tentative_end_time or (start_dt + timedelta(hours=1))

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    else:
        start_dt = start_dt.astimezone(timezone.utc)

    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    else:
        end_dt = end_dt.astimezone(timezone.utc)

    appt_id = str(uuid.uuid4())
    appt = Appointment(
        id=appt_id,
        profile_id=profile.id,
        title=payload.title.strip(),
        provider_name=payload.provider_name.strip(),
        specialty=payload.specialty.strip(),
        clinic_phone=payload.clinic_phone.strip(),
        start_time=start_dt,
        end_time=end_dt,
        timezone="UTC",
        status="requested",
        reason=payload.reason,
        preparation_notes=drafts["phone_script"],
        created_at=now_utc,
        updated_at=now_utc,
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)

    try:
        await record_audit(
            {
                "profile_id": profile.id,
                "action": "create",
                "tool": "draft_booking",
                "risk": "write_local",
                "external_ref": f"appointment:{appt.id}",
                "details": {"title": appt.title, "status": "requested"},
            },
            actor_user_id=user.id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for draft_booking: %s", audit_err)

    return DraftBookingResponse(
        appointment=AppointmentResponse(
            id=appt.id,
            profile_id=appt.profile_id,
            title=appt.title,
            provider_name=appt.provider_name,
            specialty=appt.specialty,
            location=appt.location,
            clinic_phone=appt.clinic_phone,
            start_time=appt.start_time,
            end_time=appt.end_time,
            timezone=appt.timezone,
            status=appt.status,
            reason=appt.reason,
            preparation_notes=appt.preparation_notes,
            created_at=appt.created_at,
            updated_at=appt.updated_at,
        ),
        phone_script=drafts["phone_script"],
        portal_draft=drafts["portal_draft"],
        checklist=drafts["checklist"],
    )


@router.post(
    "/profiles/{profile_id}/appointments/evaluate-transitions",
    summary="Explicitly sweep and transition completed appointments",
)
async def evaluate_transitions(
    profile_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Manually triggers evaluation of concluded visits past end_time."""
    completed_ids, prompts = await sweep_post_visit_transitions(db, profile.id)
    return {"completed_ids": completed_ids, "followup_prompts": prompts}


__all__ = ["router"]
