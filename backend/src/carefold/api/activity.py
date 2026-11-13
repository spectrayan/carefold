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

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yarvelle_core.api.errors import ProblemDetailsRoute

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
from carefold.errors import YarvelleError

from carefold.db.models import Profile
from carefold.schemas.activity import (
    ActivityTimelineResponse,
    ActivityUndoResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["activity"], route_class=ProblemDetailsRoute)


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
            raise YarvelleError(
                "YRV-100-004",
                detail="profile_id path parameter is required.",
                context={'parameter': "profile_id"},
            )

        stmt = select(Profile).where(Profile.id == clean_id)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()
        if profile is None:
            raise YarvelleError(
                "YRV-500-002",
                detail=f"Profile '{clean_id}' not found.",
                context={'profile_id': clean_id},
            )

        access = await get_user_profile_access(profile, user, db)
        if access is None:
            raise YarvelleError(
                "YRV-300-007",
                detail="Access denied: you do not have permission for this profile.",
                context={'profile_id': clean_id},
            )

        if required_access == "manage" and access != "manage":
            raise YarvelleError(
                "CFD-300-003",
                detail="Access denied: management permissions required to undo actions for this profile.",
            )

        if required_access == "view_records" and access not in ("manage", "view_records"):
            raise YarvelleError(
                "CFD-300-003",
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
    profile: Profile = Depends(require_profile_access("view_records")),
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
    except YarvelleError:
        raise
    except Exception as exc:
        logger.exception("Failed to retrieve activity timeline")
        raise YarvelleError(
            "CFD-900-003",
            detail="Failed to retrieve activity timeline.",
            cause=exc,
        ) from exc


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
        raise YarvelleError("CFD-700-002", detail=str(err), cause=err) from err
    except tuple({ActionNotUndoableError, _resolve_action_not_undoable_error()}) as err:
        raise YarvelleError("CFD-700-002", detail=str(err), cause=err) from err
    except AlreadyUndoneError as err:
        raise YarvelleError("CFD-700-002", detail=str(err), cause=err) from err
    except InvalidExternalRefError as err:
        raise YarvelleError("CFD-700-002", detail=str(err), cause=err) from err
    except EntityNotFoundError as err:
        raise YarvelleError("CFD-700-003", detail=str(err), cause=err) from err
    except ValueError as err:
        raise YarvelleError("CFD-700-002", detail=str(err), cause=err) from err


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
