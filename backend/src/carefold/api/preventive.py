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

"""REST API endpoints for Preventive Care & Immunisation Engine (AU-36)."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.clinical.preventive import (
    PreventiveActionLiteral,
    PreventiveStatusLiteral,
    ScheduleSourceLiteral,
    create_preventive_action,
    evaluate_preventive_care,
    set_profile_schedule_source,
    update_preventive_record,
)
from carefold.db.models import Profile

logger = logging.getLogger("carefold.api.preventive")

router = APIRouter(tags=["preventive"])


# ============================================================================
# Section 1: Access Control Dependency
# ============================================================================


def require_profile_access(
    required_access: Literal["manage", "view_clinical"] = "view_clinical",
) -> Callable[..., Coroutine[Any, Any, Profile]]:
    """Enforces profile-scoped role-based access control for preventive care."""
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
                detail="Access denied: management permissions required to modify preventive care records.",
            )

        if required_access == "view_clinical" and access not in ("manage", "view_clinical"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required to inspect preventive care.",
            )

        return profile

    return _dependency


# ============================================================================
# Section 2: Pydantic Request & Response Models
# ============================================================================


class PreventiveItemResponse(BaseModel):
    id: str
    rule_id: str
    record_id: Optional[str] = None
    title: str
    category: str
    status: str
    framing: str
    clinical_summary: str
    target_age_min_months: int
    target_age_max_months: int
    sex: str
    schedule_variant: str
    schedule_source: str
    interval_months: Optional[int] = None
    codes: List[str] = Field(default_factory=list)
    source: str
    citation_url: str
    reviewed_by: str
    reviewed_at: str
    completed_at: Optional[str] = None
    notes: Optional[str] = None
    matched_resource_id: Optional[str] = None


class PreventiveChecklistResponse(BaseModel):
    profile_id: str
    age_months: int
    is_pediatric: bool
    schedule_source: str
    items: List[PreventiveItemResponse]
    total: int
    due_count: int
    completed_count: int
    disclaimer: str


class PreventiveStatusUpdateRequest(BaseModel):
    status: PreventiveStatusLiteral = Field(..., description="Target status: due, completed, not_applicable, declined")
    notes: Optional[str] = Field(None, description="Optional patient or clinician notes")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp (UTC)")
    schedule_source: Optional[ScheduleSourceLiteral] = Field(None, description="Schedule variant override")


class PreventiveRecordResponse(BaseModel):
    id: str
    profile_id: str
    rule_id: str
    status: str
    completed_at: Optional[str] = None
    notes: Optional[str] = None
    schedule_source: str
    updated_at: str
    external_ref: str


class PreventiveSettingsUpdateRequest(BaseModel):
    schedule_source: ScheduleSourceLiteral = Field(
        ...,
        description="Pediatric immunisation schedule source ('aap_2026' or 'cdc')",
    )


class PreventiveSettingsResponse(BaseModel):
    profile_id: str
    schedule_source: str


class PreventiveActionRequest(BaseModel):
    action_type: PreventiveActionLiteral = Field(
        ...,
        description="Action conversion type: 'reminder' or 'prep_question'",
    )
    due_at: Optional[str] = Field(None, description="Optional ISO-8601 due timestamp for reminder")
    appointment_id: Optional[str] = Field(None, description="Optional target appointment ID for prep question")


# ============================================================================
# Section 3: REST API Endpoints
# ============================================================================


@router.get(
    "/profiles/{profile_id}/preventive",
    response_model=PreventiveChecklistResponse,
    summary="Evaluate preventive care screenings and immunisations for a profile",
)
async def get_profile_preventive_care(
    profile_id: str,
    schedule_source: Optional[str] = Query(None, description="Schedule variant: aap_2026 or cdc"),
    sex: Optional[str] = Query(None, description="Optional biological sex filter: female, male, any"),
    category: Optional[str] = Query(None, description="Optional category filter: screening, immunisation, well_visit"),
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> PreventiveChecklistResponse:
    """Evaluates age-appropriate USPSTF screenings or AAP/CDC pediatric immunisations."""
    try:
        result = await evaluate_preventive_care(
            db,
            profile,
            schedule_source=schedule_source,
            sex=sex,
            category=category,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return PreventiveChecklistResponse(**result)


@router.patch(
    "/profiles/{profile_id}/preventive/{rule_id}",
    response_model=PreventiveRecordResponse,
    summary="Update status for a preventive care rule",
)
async def patch_profile_preventive_rule(
    profile_id: str,
    rule_id: str,
    payload: PreventiveStatusUpdateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> PreventiveRecordResponse:
    """Marks a preventive screening or immunisation as completed, due, not_applicable, or declined."""
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    try:
        record = await update_preventive_record(
            db,
            profile_id=profile.id,
            rule_id=rule_id,
            status=payload.status,
            notes=payload.notes,
            completed_at=payload.completed_at,
            schedule_source=payload.schedule_source,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return PreventiveRecordResponse(
        id=record.id,
        profile_id=record.profile_id,
        rule_id=record.rule_id,
        status=record.status,
        completed_at=record.completed_at.isoformat() if record.completed_at else None,
        notes=record.notes,
        schedule_source=record.schedule_source,
        updated_at=record.updated_at.isoformat(),
        external_ref=f"preventive_record:{record.id}",
    )


@router.put(
    "/profiles/{profile_id}/preventive-settings",
    response_model=PreventiveSettingsResponse,
    summary="Update immunisation schedule source preference for a profile",
)
async def put_profile_preventive_settings(
    profile_id: str,
    payload: PreventiveSettingsUpdateRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> PreventiveSettingsResponse:
    """Switches the profile's pediatric immunisation schedule source between 'aap_2026' and 'cdc'."""
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    try:
        updated_source = await set_profile_schedule_source(
            db,
            profile_id=profile.id,
            schedule_source=payload.schedule_source,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return PreventiveSettingsResponse(
        profile_id=profile.id,
        schedule_source=updated_source,
    )


@router.post(
    "/profiles/{profile_id}/preventive/{rule_id}/action",
    status_code=status.HTTP_201_CREATED,
    summary="Convert a preventive care item into a reminder or visit prep question",
)
async def post_profile_preventive_action(
    profile_id: str,
    rule_id: str,
    payload: PreventiveActionRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Creates a reminder or appends a clinician discussion question to an upcoming appointment."""
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", "user") or "user"
    try:
        action_res = await create_preventive_action(
            db,
            profile_id=profile.id,
            rule_id=rule_id,
            action_type=payload.action_type,
            due_at=payload.due_at,
            appointment_id=payload.appointment_id,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        detail_msg = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail_msg.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail_msg) from exc

    return action_res


__all__ = ["router"]
