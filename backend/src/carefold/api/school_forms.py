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

"""REST API endpoints for Pediatric School Health Forms & Draft Prefill (AU-39)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.clinical.school_forms import (
    SchoolFormStatusLiteral,
    SchoolFormTypeLiteral,
    VALID_SCHOOL_FORM_STATUSES,
    VALID_SCHOOL_FORM_TYPES,
    check_under_13_safeguards,
    create_school_form,
    regenerate_school_form_prefill,
    serialize_school_form,
)
from carefold.db.models import AuditEventRecord, Job, Profile, Reminder, SchoolForm

logger = logging.getLogger("carefold.api.school_forms")

router = APIRouter(tags=["school-forms"])


# ============================================================================
# Section 1: Access Control Dependency
# ============================================================================


def require_profile_access(
    required_access: Literal["manage", "view_clinical"] = "view_clinical",
) -> Callable[..., Coroutine[Any, Any, Profile]]:
    """Enforces profile-scoped role-based access control for school health forms."""
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
                detail="Access denied: management permissions required to modify school forms.",
            )

        if required_access == "view_clinical" and access not in ("manage", "view_clinical"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required to inspect school forms.",
            )

        return profile

    return _dependency


# ============================================================================
# Section 2: Pydantic Request & Response Models
# ============================================================================


class SchoolFormCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="School or camp health form title")
    school_or_camp_name: Optional[str] = Field(None, max_length=255, description="Institution name")
    form_type: SchoolFormTypeLiteral = Field("general", description="Form classification")
    attachment_id: Optional[str] = Field(None, description="Optional CAS attachment ID")
    expires_at: Optional[datetime] = Field(None, description="Optional expiration/renewal timestamp (UTC)")
    status: SchoolFormStatusLiteral = Field("draft", description="Initial form lifecycle status")


class SchoolFormUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    school_or_camp_name: Optional[str] = Field(None, max_length=255)
    form_type: Optional[SchoolFormTypeLiteral] = None
    attachment_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    status: Optional[SchoolFormStatusLiteral] = None
    prefill_draft: Optional[Dict[str, Any]] = None


class SchoolFormResponse(BaseModel):
    id: str
    profile_id: str
    attachment_id: Optional[str] = None
    title: str
    school_or_camp_name: Optional[str] = None
    form_type: str
    expires_at: Optional[str] = None
    reminder_id: Optional[str] = None
    prefill_draft: Dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    safeguards: Optional[Dict[str, Any]] = None


class SchoolFormListResponse(BaseModel):
    profile_id: str
    forms: List[SchoolFormResponse]
    total: int
    safeguards: Dict[str, Any]


# ============================================================================
# Section 3: REST API Endpoints
# ============================================================================


@router.get(
    "/profiles/{profile_id}/school-forms",
    response_model=SchoolFormListResponse,
    summary="List school and camp health forms for a profile",
)
async def list_profile_school_forms(
    profile_id: str,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by form status"),
    form_type: Optional[str] = Query(None, description="Filter by form type"),
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> SchoolFormListResponse:
    """Lists all school/camp health forms for a profile alongside under-13 safeguard status."""
    stmt = select(SchoolForm).where(SchoolForm.profile_id == profile.id)
    if status_filter and status_filter.strip():
        stmt = stmt.where(SchoolForm.status == status_filter.strip().lower())
    if form_type and form_type.strip():
        stmt = stmt.where(SchoolForm.form_type == form_type.strip().lower())

    stmt = stmt.order_by(SchoolForm.created_at.desc())
    res = await db.execute(stmt)
    records = list(res.scalars().all())

    safeguards = check_under_13_safeguards(profile, action="view")
    items = [
        SchoolFormResponse(**serialize_school_form(f), safeguards=safeguards)
        for f in records
    ]

    return SchoolFormListResponse(
        profile_id=profile.id,
        forms=items,
        total=len(items),
        safeguards=safeguards,
    )


@router.post(
    "/profiles/{profile_id}/school-forms",
    response_model=SchoolFormResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new school/camp health form with compiled draft prefill",
)
async def create_profile_school_form(
    profile_id: str,
    payload: SchoolFormCreateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> SchoolFormResponse:
    """Creates a school form, compiles draft prefill from health_resources, and schedules renewal reminder."""
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    try:
        form = await create_school_form(
            db,
            profile_id=profile.id,
            title=payload.title,
            school_or_camp_name=payload.school_or_camp_name,
            form_type=payload.form_type,
            attachment_id=payload.attachment_id,
            expires_at=payload.expires_at,
            status=payload.status,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    safeguards = check_under_13_safeguards(profile, action="create_school_form")
    return SchoolFormResponse(**serialize_school_form(form), safeguards=safeguards)


@router.get(
    "/profiles/{profile_id}/school-forms/{form_id}",
    response_model=SchoolFormResponse,
    summary="Get a single school/camp health form by ID",
)
async def get_profile_school_form(
    profile_id: str,
    form_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> SchoolFormResponse:
    """Retrieves a single school health form and its draft prefill packet."""
    stmt = select(SchoolForm).where(
        SchoolForm.id == form_id.strip(),
        SchoolForm.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    form = res.scalar_one_or_none()
    if form is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School form '{form_id}' not found.",
        )

    safeguards = check_under_13_safeguards(profile, action="view")
    return SchoolFormResponse(**serialize_school_form(form), safeguards=safeguards)


@router.post(
    "/profiles/{profile_id}/school-forms/{form_id}/prefill",
    response_model=SchoolFormResponse,
    summary="Regenerate draft prefill for a school health form from latest records",
)
async def post_regenerate_school_form_prefill(
    profile_id: str,
    form_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> SchoolFormResponse:
    """Recompiles the draft prefill JSON from the profile's latest active HealthResources."""
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    try:
        form = await regenerate_school_form_prefill(
            db,
            profile_id=profile.id,
            form_id=form_id,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    safeguards = check_under_13_safeguards(profile, action="prefill")
    return SchoolFormResponse(**serialize_school_form(form), safeguards=safeguards)


@router.patch(
    "/profiles/{profile_id}/school-forms/{form_id}",
    response_model=SchoolFormResponse,
    summary="Update school health form metadata, expiration, or status",
)
async def patch_profile_school_form(
    profile_id: str,
    form_id: str,
    payload: SchoolFormUpdateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> SchoolFormResponse:
    """Updates a school health form and creates/updates its renewal reminder if expires_at changes."""
    stmt = select(SchoolForm).where(
        SchoolForm.id == form_id.strip(),
        SchoolForm.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    form = res.scalar_one_or_none()
    if form is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School form '{form_id}' not found.",
        )

    now_utc = datetime.now(timezone.utc)
    if payload.title is not None:
        form.title = payload.title.strip()
    if payload.school_or_camp_name is not None:
        form.school_or_camp_name = payload.school_or_camp_name.strip() if payload.school_or_camp_name else None
    if payload.form_type is not None:
        if payload.form_type not in VALID_SCHOOL_FORM_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid form_type.")
        form.form_type = payload.form_type
    if payload.attachment_id is not None:
        form.attachment_id = payload.attachment_id
    if payload.status is not None:
        if payload.status not in VALID_SCHOOL_FORM_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status.")
        form.status = payload.status
    if payload.prefill_draft is not None:
        form.prefill_draft_json = json.dumps(payload.prefill_draft)

    if payload.expires_at is not None:
        exp_dt = payload.expires_at
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        else:
            exp_dt = exp_dt.astimezone(timezone.utc)
        form.expires_at = exp_dt

        candidate_due = exp_dt - timedelta(days=30)
        next_due_dt = candidate_due if candidate_due > now_utc else exp_dt

        if form.reminder_id:
            rem_stmt = select(Reminder).where(Reminder.id == form.reminder_id)
            rem_res = await db.execute(rem_stmt)
            existing_rem = rem_res.scalar_one_or_none()
            if existing_rem is not None:
                existing_rem.title = f"Renew school form: {form.title}"
                existing_rem.next_due_at = next_due_dt
                existing_rem.updated_at = now_utc
        else:
            rem_id = str(uuid.uuid4())
            reminder = Reminder(
                id=rem_id,
                profile_id=profile.id,
                title=f"Renew school form: {form.title}",
                description=f"Annual renewal for {form.title}.",
                category="prep",
                timezone="UTC",
                next_due_at=next_due_dt,
                status="pending",
                created_at=now_utc,
                updated_at=now_utc,
            )
            db.add(reminder)
            db.add(
                Job(
                    id=str(uuid.uuid4()),
                    profile_id=profile.id,
                    kind="reminder",
                    payload=json.dumps({"reminder_id": rem_id, "school_form_id": form.id}),
                    timezone="UTC",
                    next_run_at=next_due_dt,
                    status="pending",
                    idempotency_key=f"reminder:{rem_id}",
                    created_at=now_utc,
                    updated_at=now_utc,
                )
            )
            await db.flush()
            form.reminder_id = rem_id

    form.updated_at = now_utc
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    db.add(
        AuditEventRecord(
            id=str(uuid.uuid4()),
            ts=now_utc,
            profile_id=profile.id,
            actor_user_id=actor_id,
            principal="user",
            event="tool",
            tool="update_school_form",
            risk="write_local",
            decision="allow",
            external_ref=f"school_form:{form.id}",
            detail_redacted=json.dumps({"form_id": form.id, "status": form.status}),
        )
    )
    await db.commit()
    await db.refresh(form)

    safeguards = check_under_13_safeguards(profile, action="update_school_form")
    return SchoolFormResponse(**serialize_school_form(form), safeguards=safeguards)


@router.delete(
    "/profiles/{profile_id}/school-forms/{form_id}",
    summary="Delete a school health form",
)
async def delete_profile_school_form(
    profile_id: str,
    form_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Deletes a school health form record and logs an audit event."""
    stmt = select(SchoolForm).where(
        SchoolForm.id == form_id.strip(),
        SchoolForm.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    form = res.scalar_one_or_none()
    if form is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School form '{form_id}' not found.",
        )

    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    now_utc = datetime.now(timezone.utc)
    await db.delete(form)
    db.add(
        AuditEventRecord(
            id=str(uuid.uuid4()),
            ts=now_utc,
            profile_id=profile.id,
            actor_user_id=actor_id,
            principal="user",
            event="tool",
            tool="delete_school_form",
            risk="write_local",
            decision="allow",
            external_ref=f"school_form:{form_id}",
            detail_redacted=json.dumps({"form_id": form_id, "action": "delete"}),
        )
    )
    await db.commit()

    return {"deleted": True, "id": form_id, "profile_id": profile.id}


__all__ = ["router"]
