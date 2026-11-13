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

"""REST API endpoints for Clinical & Wearable File Imports with Review-Before-Save (AU-38)."""

from __future__ import annotations

import json
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.api.deps import get_current_user, get_db, resolve_owner_user_id
from yarvelle_core.api.errors import ProblemDetailsRoute
from yarvelle_core.api.profiles import get_user_profile_access
from yarvelle_core.auth.ports import UserProfile
from carefold.errors import YarvelleError
from carefold.models import ImportBatch
from yarvelle_core.db.models import Profile
from carefold.importers.service import (
    commit_import_batch,
    discard_import_batch,
    get_import_batch,
    list_import_batches,
    stage_import,
)
from yarvelle_core.logging import get_logger

logger = get_logger("carefold.api.imports")

router = APIRouter(tags=["imports"], route_class=ProblemDetailsRoute)


# ============================================================================
# Section 1: Pydantic Request / Response Schemas
# ============================================================================


class StageImportRequest(BaseModel):
    """Request schema for staging a clinical or wearable import file."""

    filename: str = Field(..., min_length=1, max_length=255, description="Uploaded filename")
    content: str = Field(..., min_length=1, description="Raw file content (JSON or XML string)")
    format: Optional[str] = Field(
        None,
        description="Optional explicit format ('fhir_r4', 'ccda', 'apple_health')",
    )
    source_name: Optional[str] = Field(
        None,
        max_length=255,
        description="Optional human-readable provenance source label",
    )


class CommitImportRequest(BaseModel):
    """Optional request body for committing all or selected indices of a staged import batch."""

    selected_indices: Optional[List[int]] = Field(
        None,
        description="Optional 0-based indices of staged records to commit; commits all if omitted",
    )


def _serialize_batch(batch: ImportBatch, include_records: bool = True) -> Dict[str, Any]:
    """Serializes an `ImportBatch` entity to a JSON-compatible dictionary."""
    try:
        summary = json.loads(batch.summary_json or "{}")
    except Exception:
        summary = {}
    try:
        staged_records = json.loads(batch.staged_records_json or "[]") if include_records else []
    except Exception:
        staged_records = []
    try:
        committed_ids = json.loads(batch.committed_resource_ids_json or "[]")
    except Exception:
        committed_ids = []

    payload: Dict[str, Any] = {
        "id": batch.id,
        "batch_id": batch.id,
        "profile_id": batch.profile_id,
        "attachment_id": batch.attachment_id,
        "format": batch.format,
        "source_name": batch.source_name,
        "status": batch.status,
        "summary": summary,
        "committed_resource_ids": committed_ids,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }
    if include_records:
        payload["staged_records"] = staged_records
    return payload


# ============================================================================
# Section 2: Profile Access Dependency
# ============================================================================


def require_profile_access(
    required_access: Literal["manage", "view_records"] = "view_records",
) -> Callable[..., Coroutine[Any, Any, Profile]]:
    """FastAPI dependency enforcing profile-scoped clinical/management permissions."""

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
                detail="Access denied: management permissions required to modify clinical imports.",
            )

        if required_access == "view_records" and access not in ("manage", "view_records"):
            raise YarvelleError(
                "CFD-300-003",
                detail="Access denied: clinical view permissions required to inspect imports.",
            )

        return profile

    return _dependency


# ============================================================================
# Section 3: REST Endpoints
# ============================================================================


@router.post(
    "/profiles/{profile_id}/imports/stage",
    status_code=status.HTTP_201_CREATED,
    summary="Stage a clinical or wearable import file for review-before-save",
)
async def stage_profile_import(
    profile_id: str,
    payload: StageImportRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Parses and stages a FHIR R4 Bundle, C-CDA XML, or Apple Health export."""
    owner_id = resolve_owner_user_id(user) or profile.user_id
    try:
        batch = await stage_import(
            session=db,
            profile_id=profile.id,
            filename=payload.filename,
            content=payload.content,
            source_name=payload.source_name,
            fmt=payload.format,
            user_id=owner_id,
        )
    except ValueError as exc:
        raise YarvelleError(
            "CFD-100-006",
            detail=str(exc),
            cause=exc,
        ) from exc

    return _serialize_batch(batch, include_records=True)


@router.get(
    "/profiles/{profile_id}/imports",
    summary="List clinical and wearable import batches for a profile",
)
async def list_profile_imports(
    profile_id: str,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by batch status"),
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Returns all staged, committed, or discarded import batches for the profile."""
    batches = await list_import_batches(db, profile_id=profile.id, status=status_filter)
    items = [_serialize_batch(b, include_records=False) for b in batches]
    return {
        "items": items,
        "total": len(items),
    }


@router.get(
    "/profiles/{profile_id}/imports/{batch_id}",
    summary="Inspect a single import batch and its staged records",
)
async def get_profile_import_batch(
    profile_id: str,
    batch_id: str,
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Returns full details and staged records for an import batch."""
    batch = await get_import_batch(db, profile_id=profile.id, batch_id=batch_id)
    if batch is None:
        raise YarvelleError(
            "CFD-500-003",
            detail=f"ImportBatch '{batch_id}' not found for profile '{profile.id}'.",
            context={'batch_id': batch_id, 'profile_id': profile.id},
        )
    return _serialize_batch(batch, include_records=True)


@router.post(
    "/profiles/{profile_id}/imports/{batch_id}/commit",
    summary="Confirm and commit a staged import batch into health_resources",
)
async def commit_profile_import_batch(
    profile_id: str,
    batch_id: str,
    payload: Optional[CommitImportRequest] = Body(default=None),
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Commits all or selected staged records from an `ImportBatch` into `HealthResource`."""
    selected = payload.selected_indices if payload is not None else None
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", None)
    try:
        result = await commit_import_batch(
            session=db,
            profile_id=profile.id,
            batch_id=batch_id,
            selected_indices=selected,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        msg = str(exc)
        err_code = "CFD-500-003" if "not found" in msg.lower() else "CFD-100-006"
        raise YarvelleError(
            err_code,
            detail=msg,
            cause=exc,
            context={'batch_id': batch_id, 'profile_id': profile.id},
        ) from exc

    return result


@router.delete(
    "/profiles/{profile_id}/imports/{batch_id}",
    summary="Discard a staged import batch without saving to health_resources",
)
async def discard_profile_import_batch(
    profile_id: str,
    batch_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Marks an `ImportBatch` as `'discarded'`."""
    found = await discard_import_batch(db, profile_id=profile.id, batch_id=batch_id)
    if not found:
        raise YarvelleError(
            "CFD-500-003",
            detail=f"ImportBatch '{batch_id}' not found for profile '{profile.id}'.",
            context={'batch_id': batch_id, 'profile_id': profile.id},
        )
    return {
        "id": batch_id,
        "batch_id": batch_id,
        "profile_id": profile.id,
        "status": "discarded",
        "discarded": True,
    }


class StageGmailRequest(BaseModel):
    """Request schema for staging read-only Gmail messages via curated MCP (AU-59)."""

    messages: List[Dict[str, Any]] = Field(default_factory=list, description="Gmail messages from curated MCP")
    label_filter: str = Field("appointments", description="Allowed Gmail label filter")


def _serialize_gmail_batch(batch: ImportBatch) -> Dict[str, Any]:
    try:
        summary = json.loads(batch.summary_json or "{}")
    except Exception:
        summary = {}
    try:
        staged_records = json.loads(batch.staged_records_json or "[]")
    except Exception:
        staged_records = []
    try:
        committed_ids = json.loads(batch.committed_resource_ids_json or "[]")
    except Exception:
        committed_ids = []

    return {
        "id": batch.id,
        "batch_id": batch.id,
        "profile_id": batch.profile_id,
        "format": batch.format,
        "source_name": batch.source_name,
        "status": batch.status,
        "summary": summary,
        "staged_records": staged_records,
        "committed_resource_ids": committed_ids,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else None,
    }


@router.post(
    "/profiles/{profile_id}/gmail/stage",
    status_code=status.HTTP_201_CREATED,
    summary="Stage label-filtered Gmail messages into an ImportBatch for review-before-save",
)
async def post_stage_gmail_messages(
    profile_id: str,
    payload: StageGmailRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Stages candidate appointments or school action items from read-only Gmail messages."""
    from carefold.connectors.gmail_mcp import stage_gmail_extractions

    try:
        batch = await stage_gmail_extractions(
            session=db,
            profile_id=profile.id,
            messages=payload.messages,
            label_filter=payload.label_filter,
        )
    except ValueError as exc:
        raise YarvelleError(
            "CFD-100-006",
            detail=str(exc),
            cause=exc,
        ) from exc

    return _serialize_gmail_batch(batch)


@router.post(
    "/profiles/{profile_id}/gmail/batches/{batch_id}/confirm/{item_index}",
    summary="Confirm a single staged Gmail candidate item into an Appointment or Reminder",
)
async def post_confirm_gmail_staged_item(
    profile_id: str,
    batch_id: str,
    item_index: int,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Confirms a single extracted Gmail candidate item at `item_index`."""
    from carefold.connectors.gmail_mcp import confirm_gmail_staged_item

    actor_id = resolve_owner_user_id(user) or getattr(user, "id", None)
    try:
        return await confirm_gmail_staged_item(
            session=db,
            profile_id=profile.id,
            batch_id=batch_id,
            item_index=item_index,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        msg = str(exc)
        err_code = "CFD-500-003" if "not found" in msg.lower() else "CFD-100-006"
        raise YarvelleError(
            err_code,
            detail=msg,
            cause=exc,
            context={'batch_id': batch_id, 'profile_id': profile.id},
        ) from exc


__all__ = ["router"]
