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

"""REST API endpoints for A2 Standing Routines, Per-Connector Autonomy, and MCP Schema Pins (AU-57, AU-58)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.connections import require_profile_access
from carefold.api.deps import get_current_user, get_db, resolve_owner_user_id
from carefold.auth.ports import UserProfile
from carefold.clinical.routines import (
    create_standing_routine,
    execute_standing_routine,
    set_connection_autonomy,
    update_standing_routine_status,
)
from carefold.connectors.mcp_remote import reapprove_mcp_tool_pin
from carefold.db.models import McpToolPin, Profile, Routine
from carefold.logging import get_logger

logger = get_logger("carefold.api.routines")

router = APIRouter(tags=["routines"])


# ============================================================================
# Section 1: Pydantic Request Schemas
# ============================================================================


class CreateRoutineRequest(BaseModel):
    """Request payload for creating a standing A2 routine."""

    name: str = Field(..., min_length=1, max_length=255)
    tool_name: str = Field(..., min_length=1, max_length=128)
    rrule: str = Field(..., min_length=1, max_length=255)
    timezone: str = Field(default="UTC", max_length=64)
    args: Optional[Dict[str, Any]] = Field(default=None)
    connection_id: Optional[str] = Field(default=None)
    expires_in_days: int = Field(default=30)
    description: Optional[str] = Field(default=None)


class UpdateRoutineStatusRequest(BaseModel):
    """Request payload for pausing, resuming, or revoking a routine."""

    status: Optional[str] = Field(default=None, description="Target status: active, paused, or revoked")
    action: Optional[str] = Field(default=None, description="Alias action: pause, resume, or revoke")


class RunRoutineRequest(BaseModel):
    """Optional request payload for triggering a manual routine execution."""

    taint: bool = Field(default=False, description="Simulated or propagated taint flag")


class UpdateConnectionAutonomyRequest(BaseModel):
    """Request payload for updating per-connector autonomy level."""

    autonomy_level: str = Field(..., description="Target autonomy level: inherit, A0, A1, or A2")


class ReapproveMcpPinRequest(BaseModel):
    """Request payload for re-approving a drifted remote MCP tool schema pin."""

    description: str = Field(default="", description="Updated MCP tool description")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="Updated MCP tool input schema")


# ============================================================================
# Section 2: Serialization Helpers
# ============================================================================


def _serialize_routine(routine: Routine) -> Dict[str, Any]:
    """Serializes a `Routine` ORM instance into a JSON dictionary."""
    return {
        "id": routine.id,
        "profile_id": routine.profile_id,
        "connection_id": routine.connection_id,
        "created_by_user_id": routine.created_by_user_id,
        "name": routine.name,
        "description": routine.description,
        "tool_name": routine.tool_name,
        "args": routine.args,
        "rrule": routine.rrule,
        "timezone": routine.timezone,
        "status": routine.status,
        "last_run_at": routine.last_run_at.isoformat() if routine.last_run_at else None,
        "next_run_at": routine.next_run_at.isoformat() if routine.next_run_at else None,
        "expires_at": routine.expires_at.isoformat() if routine.expires_at else None,
        "created_at": routine.created_at.isoformat() if routine.created_at else None,
        "updated_at": routine.updated_at.isoformat() if routine.updated_at else None,
    }


def _serialize_mcp_pin(pin: McpToolPin) -> Dict[str, Any]:
    """Serializes an `McpToolPin` ORM instance into a JSON dictionary."""
    try:
        schema_data = json.loads(pin.schema_json or "{}")
    except Exception:
        schema_data = {}
    return {
        "id": pin.id,
        "profile_id": pin.profile_id,
        "connection_id": pin.connection_id,
        "tool_name": pin.tool_name,
        "risk_tier": pin.risk_tier,
        "schema_hash": pin.schema_hash,
        "schema": schema_data,
        "status": pin.status,
        "pinned_at": pin.pinned_at.isoformat() if pin.pinned_at else None,
        "verified_at": pin.verified_at.isoformat() if pin.verified_at else None,
    }


# ============================================================================
# Section 3: REST Endpoints
# ============================================================================


@router.get(
    "/profiles/{profile_id}/routines",
    summary="List A2 standing routines for a care profile",
)
async def list_profile_routines(
    profile_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Lists all `Routine` records for `profile_id`."""
    stmt = (
        select(Routine)
        .where(Routine.profile_id == profile.id)
        .order_by(Routine.created_at.desc())
    )
    res = await db.execute(stmt)
    items = [_serialize_routine(r) for r in res.scalars().all()]
    return {
        "routines": items,
        "items": items,
        "total": len(items),
    }


@router.post(
    "/profiles/{profile_id}/routines",
    status_code=status.HTTP_201_CREATED,
    summary="Create a scoped A2 standing routine (<=90-day expiry, >=2 active connectors required)",
)
async def create_profile_routine(
    profile_id: str,
    payload: CreateRoutineRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Creates a standing routine and schedules its recurring `Job`."""
    creator_id = resolve_owner_user_id(user) or profile.user_id or getattr(user, "id", "local-steward")
    try:
        routine = await create_standing_routine(
            session=db,
            profile_id=profile.id,
            created_by_user_id=str(creator_id),
            name=payload.name,
            tool_name=payload.tool_name,
            rrule=payload.rrule,
            timezone_str=payload.timezone,
            args=payload.args,
            connection_id=payload.connection_id,
            expires_in_days=payload.expires_in_days,
            description=payload.description,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    serialized = _serialize_routine(routine)
    return {
        **serialized,
        "routine": serialized,
    }


@router.patch(
    "/profiles/{profile_id}/routines/{routine_id}",
    summary="Pause, resume, or revoke a standing routine",
)
async def update_profile_routine(
    profile_id: str,
    routine_id: str,
    payload: UpdateRoutineStatusRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Updates routine status (`active`, `paused`, `revoked`)."""
    target = (payload.status or payload.action or "").strip()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'status' or 'action' is required.",
        )

    actor_id = resolve_owner_user_id(user) or profile.user_id
    try:
        routine = await update_standing_routine_status(
            session=db,
            profile_id=profile.id,
            routine_id=routine_id,
            status=target,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        code = status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    serialized = _serialize_routine(routine)
    return {
        **serialized,
        "routine": serialized,
    }


@router.post(
    "/profiles/{profile_id}/routines/{routine_id}/run",
    summary="Trigger immediate execution of a standing routine with fire-time re-check",
)
async def trigger_profile_routine_run(
    profile_id: str,
    routine_id: str,
    payload: Optional[RunRoutineRequest] = Body(default=None),
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Executes `execute_standing_routine` with fire-time permission, expiry, and taint checks (`E1.10`)."""
    stmt = select(Routine).where(
        Routine.id == routine_id.strip(),
        Routine.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    routine = res.scalar_one_or_none()
    if routine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Routine '{routine_id}' not found for profile '{profile.id}'.",
        )

    taint_flag = bool(payload.taint) if payload is not None else False
    try:
        return await execute_standing_routine(
            session=db,
            routine_id=routine.id,
            taint=taint_flag,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.patch(
    "/profiles/{profile_id}/connections/{connection_id}/autonomy",
    summary="Set per-connector autonomy override (inherit, A0, A1, A2)",
)
async def update_profile_connection_autonomy(
    profile_id: str,
    connection_id: str,
    payload: UpdateConnectionAutonomyRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Updates `Connection.autonomy_level` (`AU-58`)."""
    actor_id = resolve_owner_user_id(user) or profile.user_id
    try:
        conn = await set_connection_autonomy(
            session=db,
            profile_id=profile.id,
            connection_id=connection_id,
            autonomy_level=payload.autonomy_level,
            actor_user_id=actor_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        code = status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    return {
        "id": conn.id,
        "connection_id": conn.id,
        "profile_id": conn.profile_id,
        "connector_id": conn.connector_id,
        "autonomy_level": conn.autonomy_level,
        "status": conn.status,
    }


@router.get(
    "/profiles/{profile_id}/connections/{connection_id}/mcp-pins",
    summary="List pinned remote MCP tool schema hashes for a connection",
)
async def list_connection_mcp_pins(
    profile_id: str,
    connection_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Lists all `McpToolPin` records for `(profile_id, connection_id)` (`AU-57`)."""
    stmt = (
        select(McpToolPin)
        .where(
            McpToolPin.profile_id == profile.id,
            McpToolPin.connection_id == connection_id.strip(),
        )
        .order_by(McpToolPin.tool_name.asc())
    )
    res = await db.execute(stmt)
    items = [_serialize_mcp_pin(p) for p in res.scalars().all()]
    return {
        "pins": items,
        "mcp_pins": items,
        "items": items,
        "total": len(items),
    }


@router.post(
    "/profiles/{profile_id}/connections/{connection_id}/mcp-pins/{tool_name}/reapprove",
    summary="Re-approve a drift-blocked MCP tool schema pin",
)
async def reapprove_connection_mcp_pin(
    profile_id: str,
    connection_id: str,
    tool_name: str,
    payload: ReapproveMcpPinRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Re-approves an `McpToolPin` after upstream schema drift and restores connection status (`Titan S7`)."""
    actor_id = resolve_owner_user_id(user) or profile.user_id
    try:
        pin = await reapprove_mcp_tool_pin(
            session=db,
            profile_id=profile.id,
            connection_id=connection_id,
            tool_name=tool_name,
            new_description=payload.description,
            new_input_schema=payload.input_schema,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    serialized = _serialize_mcp_pin(pin)
    return {
        **serialized,
        "pin": serialized,
    }
