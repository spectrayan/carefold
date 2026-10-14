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

"""REST API endpoints for Granular Viewer Section Scoping and Teen Connection Handover (AU-63 / E12.3, E12.4)."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.clinical.handover import (
    VALID_VIEWER_SECTIONS,
    check_profile_section_access,
    execute_teen_handover,
    update_viewer_sections,
)
from carefold.db.models import Profile, ProfileAccess

router = APIRouter(tags=["handover"])


# ============================================================================
# Section 1: Pydantic Request Schemas
# ============================================================================


class UpdateViewerSectionsRequest(BaseModel):
    """Request payload for updating granular viewer section permissions."""

    allowed_sections: List[str] = Field(
        ...,
        description="Permitted viewer sections (vitals, preventive, appointments, reminders, connections, school_forms, notes, documents)",
    )


class TeenHandoverRequest(BaseModel):
    """Request payload for executing Teen Connection Handover with DEK re-encryption."""

    teen_user_id: str = Field(..., min_length=1, description="User ID of the teen assuming profile stewardship")
    connection_decisions: Dict[str, Literal["keep", "revoke"]] = Field(
        default_factory=dict,
        description="Per-connection keep/revoke map keyed by connection_id",
    )


# ============================================================================
# Section 2: Profile Access Dependency
# ============================================================================


def require_profile_access(
    required_access: Literal["manage", "view_clinical"] = "view_clinical",
) -> Callable[..., Coroutine[Any, Any, Profile]]:
    """FastAPI dependency enforcing profile-scoped clinical/management permissions."""

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
                detail="Access denied: management permissions required.",
            )

        return profile

    return _dependency


# ============================================================================
# Section 3: REST Endpoints
# ============================================================================


@router.put(
    "/profiles/{profile_id}/access/{target_user_id}/sections",
    summary="Update granular viewer section permissions for a user on a care profile",
)
async def update_profile_viewer_sections_endpoint(
    profile_id: str,
    target_user_id: str,
    payload: UpdateViewerSectionsRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Updates `ProfileAccess.allowed_sections_json` for `(profile_id, target_user_id)` (`E12.3`)."""
    owner_id = resolve_owner_user_id(user) or profile.user_id or getattr(user, "id", None)
    try:
        grant = await update_viewer_sections(
            session=db,
            profile_id=profile.id,
            target_user_id=target_user_id,
            allowed_sections=payload.allowed_sections,
            grantor_user_id=owner_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "id": grant.id,
        "profile_id": grant.profile_id,
        "user_id": grant.user_id,
        "role": grant.role,
        "access_level": grant.access_level,
        "allowed_sections": grant.allowed_sections or [],
        "granted_by": grant.granted_by,
        "granted_at": grant.granted_at.isoformat() if grant.granted_at else None,
    }


@router.get(
    "/profiles/{profile_id}/access/{target_user_id}/sections",
    summary="Get effective and explicit viewer section permissions for a user on a care profile",
)
async def get_profile_viewer_sections_endpoint(
    profile_id: str,
    target_user_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Returns effective permitted sections across `VALID_VIEWER_SECTIONS` for `(profile_id, target_user_id)`."""
    clean_target_id = (target_user_id or "").strip()
    stmt = select(ProfileAccess).where(
        ProfileAccess.profile_id == profile.id,
        ProfileAccess.user_id == clean_target_id,
    )
    res = await db.execute(stmt)
    grant = res.scalar_one_or_none()

    effective_sections: List[str] = []
    for sec in VALID_VIEWER_SECTIONS:
        if await check_profile_section_access(db, profile, clean_target_id, sec):
            effective_sections.append(sec)

    return {
        "profile_id": profile.id,
        "user_id": clean_target_id,
        "role": grant.role if grant is not None else None,
        "access_level": grant.access_level if grant is not None else None,
        "allowed_sections": effective_sections,
        "explicit_sections": grant.allowed_sections if grant is not None else None,
    }


@router.post(
    "/profiles/{profile_id}/handover",
    summary="Execute Teen Connection Handover with per-connection keep/revoke and DEK rotation",
)
async def execute_profile_teen_handover_endpoint(
    profile_id: str,
    payload: TeenHandoverRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Promotes `teen_user_id` to profile steward, revokes rejected connections, and re-encrypts kept credentials under a rotated DEK (`E12.4`)."""
    owner_id = resolve_owner_user_id(user) or profile.user_id or getattr(user, "id", None)
    try:
        return await execute_teen_handover(
            session=db,
            profile_id=profile.id,
            teen_user_id=payload.teen_user_id,
            connection_decisions=payload.connection_decisions,
            actor_user_id=owner_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


__all__ = ["router"]
