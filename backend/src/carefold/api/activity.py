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

"""REST API endpoints for Activity Timeline and Single-Click Undo (AU-40)."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.clinical.activity import get_profile_activity_timeline
from carefold.clinical.undo import (
    ActionNotUndoableError,
    AlreadyUndoneError,
    EntityNotFoundError,
    InvalidExternalRefError,
    UndoError,
    UndoWindowExpiredError,
    _resolve_action_not_undoable_error,
    _resolve_undo_window_expired_error,
    execute_single_click_undo,
    execute_single_click_undo_async,
)

from carefold.db.models import Profile
from carefold.schemas.activity import (
    ActivityTimelineResponse,
    ActivityUndoResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["activity"])


# ============================================================================
# Section 1: Role-Based Access Control Dependency
# ============================================================================

def require_profile_access(required_access: str):
    """Enforces profile-scoped role-based access control for activity timeline and undo."""
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
                detail="Access denied: management permissions required to undo actions for this profile.",
            )

        if required_access == "view_clinical" and access not in ("manage", "view_clinical"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required to inspect activity timeline.",
            )

        return profile

    return _dependency


# ============================================================================
# Section 2: REST Endpoints
# ============================================================================

@router.get(
    "/profiles/{profile_id}/activity",
    response_model=ActivityTimelineResponse,
    summary="Retrieve chronological activity timeline with human-readable descriptions",
)
async def get_activity_timeline(
    profile_id: str,
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    undoable_only: bool = Query(False, description="Filter for undoable actions only"),
    event: Optional[str] = Query(None, description="Filter by event type"),
    tool: Optional[str] = Query(None, description="Filter by tool name"),
    profile: Profile = Depends(require_profile_access("view_clinical")),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivityTimelineResponse:
    """Retrieves chronological activity timeline items for a profile with human-readable descriptions."""
    try:
        return await get_profile_activity_timeline(
            db=db,
            profile_id=profile.id,
            limit=limit,
            offset=offset,
            undoable_only=undoable_only,
            event=event,
            tool=tool,
        )
    except Exception:
        logger.exception("Failed to retrieve activity timeline")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve activity timeline.",
        )


@router.post(
    "/profiles/{profile_id}/activity/{event_id}/undo",
    response_model=ActivityUndoResponse,
    summary="Execute single-click undo for write_local actions within 7 days",
)
async def post_activity_undo(
    profile_id: str,
    event_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivityUndoResponse:
    """Executes single-click undo for an eligible write_local audit event within 7 days."""
    try:
        result = await execute_single_click_undo_async(
            db=db,
            event_id=event_id,
            profile_id=profile.id,
            actor_user_id=getattr(user, "id", None),
        )
        return ActivityUndoResponse(**result)
    except tuple({UndoWindowExpiredError, _resolve_undo_window_expired_error()}) as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
    except tuple({ActionNotUndoableError, _resolve_action_not_undoable_error()}) as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    except AlreadyUndoneError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
    except InvalidExternalRefError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
    except EntityNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


__all__ = [
    "ActionNotUndoableError",
    "AlreadyUndoneError",
    "EntityNotFoundError",
    "InvalidExternalRefError",
    "UndoError",
    "UndoWindowExpiredError",
    "execute_single_click_undo",
    "execute_single_click_undo_async",
    "get_activity_timeline",
    "post_activity_undo",
    "router",
]
