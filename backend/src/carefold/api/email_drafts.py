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

"""REST API endpoints for Email Drafts, Gmail Read-Only Staging, and School ICS Feeds (AU-59, AU-60, AU-61)."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.clinical.email_drafts import (
    NO_AUTO_SEND_NOTICE,
    build_mailto_uri,
    create_email_draft,
    delete_email_draft,
    export_draft_as_eml,
    get_email_draft,
    list_email_drafts,
    serialize_email_draft,
)
from carefold.clinical.school_ics import (
    create_school_ics_feed,
    delete_school_ics_feed,
    list_school_ics_feeds,
    serialize_school_ics_feed,
    sync_school_ics_feed,
)
from carefold.connectors.gmail_mcp import (
    confirm_gmail_staged_item,
    stage_gmail_extractions,
)
from carefold.db.models import ImportBatch, Profile, utc_now

logger = logging.getLogger("carefold.api.email_drafts")

router = APIRouter(tags=["email-and-school"])


# ============================================================================
# Section 1: Profile Access Dependency
# ============================================================================


def require_profile_access(
    required_access: Literal["manage", "view_clinical"] = "view_clinical",
) -> Callable[..., Coroutine[Any, Any, Profile]]:
    """Enforces profile-scoped role-based access control for email drafts, Gmail staging, and school ICS feeds."""

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

        if required_access == "view_clinical" and access not in ("manage", "view_clinical"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required.",
            )

        return profile

    return _dependency


# ============================================================================
# Section 2: Request Schemas
# ============================================================================


class CreateEmailDraftRequest(BaseModel):
    """Request schema for creating a local-only email draft (AU-60)."""

    recipient: Optional[str] = Field(None, max_length=320, description="Optional recipient email address")
    subject: str = Field(..., min_length=1, max_length=500, description="Email subject line")
    body: str = Field(..., min_length=1, description="Email plaintext body")
    category: str = Field("general", max_length=64, description="Draft category: appointment, school, insurance, general")


class StageGmailRequest(BaseModel):
    """Request schema for staging read-only Gmail messages via curated MCP (AU-59)."""

    messages: List[Dict[str, Any]] = Field(default_factory=list, description="Gmail messages from curated MCP")
    label_filter: str = Field("appointments", description="Allowed Gmail label filter")


class CreateSchoolIcsFeedRequest(BaseModel):
    """Request schema for registering a child school calendar ICS feed (AU-61)."""

    label: str = Field(..., min_length=1, max_length=255, description="School or calendar feed display name")
    feed_url: str = Field(..., min_length=1, max_length=1024, description="HTTPS or webcal .ics subscription URL")


class SyncSchoolIcsFeedRequest(BaseModel):
    """Optional request body for syncing a school ICS feed with inline `.ics` payload in tests/offline mode."""

    raw_ics_content: Optional[str] = Field(None, description="Optional raw RFC 5545 .ics content")


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
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


# ============================================================================
# Section 3: Email Drafts Endpoints (AU-60 / E9.3)
# ============================================================================


@router.get(
    "/profiles/{profile_id}/email-drafts",
    summary="List local-only email drafts for a profile",
)
async def get_profile_email_drafts(
    profile_id: str,
    category: Optional[str] = Query(None, description="Optional category filter"),
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Lists all local email drafts for `profile_id`."""
    drafts = await list_email_drafts(db, profile_id=profile.id, category=category)
    items = [serialize_email_draft(d) for d in drafts]
    return {
        "profile_id": profile.id,
        "items": items,
        "drafts": items,
        "total": len(items),
        "auto_send": False,
        "notice": NO_AUTO_SEND_NOTICE,
    }


@router.post(
    "/profiles/{profile_id}/email-drafts",
    status_code=status.HTTP_201_CREATED,
    summary="Create a local-only email draft (no automatic send)",
)
async def post_profile_email_draft(
    profile_id: str,
    payload: CreateEmailDraftRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Creates a local email draft and returns its `mailto:` URI."""
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", None)
    try:
        draft = await create_email_draft(
            session=db,
            profile_id=profile.id,
            subject=payload.subject,
            body=payload.body,
            recipient=payload.recipient,
            category=payload.category,
            created_by_user_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return serialize_email_draft(draft)


@router.get(
    "/profiles/{profile_id}/email-drafts/{draft_id}/eml",
    summary="Export a local email draft as an RFC 5322 .eml payload",
)
async def get_profile_email_draft_eml(
    profile_id: str,
    draft_id: str,
    raw: bool = Query(False, description="Return raw message/rfc822 response body instead of JSON wrapper"),
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Exports an `EmailDraft` as an RFC 5322 `.eml` message with `X-Unsent: 1`."""
    draft = await get_email_draft(db, profile_id=profile.id, draft_id=draft_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EmailDraft '{draft_id}' not found for profile '{profile.id}'.",
        )

    eml_content = export_draft_as_eml(draft)
    draft.status = "exported"
    draft.updated_at = utc_now()
    await db.commit()
    await db.refresh(draft)

    filename = f"carefold-draft-{draft.id[:8]}.eml"
    if raw:
        return Response(
            content=eml_content,
            media_type="message/rfc822",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return {
        "id": draft.id,
        "draft_id": draft.id,
        "profile_id": profile.id,
        "filename": filename,
        "content_type": "message/rfc822",
        "status": draft.status,
        "eml": eml_content,
        "mailto_uri": build_mailto_uri(draft),
        "auto_send": False,
        "notice": NO_AUTO_SEND_NOTICE,
    }


@router.delete(
    "/profiles/{profile_id}/email-drafts/{draft_id}",
    summary="Delete a local email draft",
)
async def delete_profile_email_draft(
    profile_id: str,
    draft_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a local `EmailDraft` row."""
    deleted = await delete_email_draft(db, profile_id=profile.id, draft_id=draft_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EmailDraft '{draft_id}' not found for profile '{profile.id}'.",
        )
    return {
        "id": draft_id,
        "draft_id": draft_id,
        "profile_id": profile.id,
        "deleted": True,
    }


# ============================================================================
# Section 4: Gmail Read-Only Staging & Confirmation Endpoints (AU-59 / E9.2, E11.4)
# ============================================================================


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
    try:
        batch = await stage_gmail_extractions(
            session=db,
            profile_id=profile.id,
            messages=payload.messages,
            label_filter=payload.label_filter,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
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
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", None)
    try:
        result = await confirm_gmail_staged_item(
            session=db,
            profile_id=profile.id,
            batch_id=batch_id,
            item_index=item_index,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in msg.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg) from exc

    return result


# ============================================================================
# Section 5: School Calendar ICS Feed Endpoints (AU-61 / E4.4)
# ============================================================================


@router.get(
    "/profiles/{profile_id}/school-ics",
    summary="List school calendar ICS feeds for a child profile",
)
async def get_profile_school_ics_feeds(
    profile_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Returns all registered `SchoolIcsFeed` subscriptions for `profile_id`."""
    feeds = await list_school_ics_feeds(db, profile_id=profile.id)
    items = [serialize_school_ics_feed(f) for f in feeds]
    return {
        "profile_id": profile.id,
        "items": items,
        "feeds": items,
        "total": len(items),
    }


@router.post(
    "/profiles/{profile_id}/school-ics",
    status_code=status.HTTP_201_CREATED,
    summary="Register a read-only school calendar ICS subscription feed",
)
async def post_profile_school_ics_feed(
    profile_id: str,
    payload: CreateSchoolIcsFeedRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Validates `feed_url` (`https://` or `webcal://`) and registers a `SchoolIcsFeed`."""
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", None)
    try:
        feed = await create_school_ics_feed(
            session=db,
            profile_id=profile.id,
            label=payload.label,
            feed_url=payload.feed_url,
            actor_user_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return serialize_school_ics_feed(feed)


@router.post(
    "/profiles/{profile_id}/school-ics/{feed_id}/sync",
    summary="Synchronize VEVENTs from a school calendar ICS feed into Appointments",
)
async def post_sync_profile_school_ics_feed(
    profile_id: str,
    feed_id: str,
    payload: Optional[SyncSchoolIcsFeedRequest] = Body(default=None),
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Parses RFC 5545 VEVENTs and upserts school calendar events into `Appointment` rows."""
    raw_ics = payload.raw_ics_content if payload is not None else None
    try:
        result = await sync_school_ics_feed(
            session=db,
            profile_id=profile.id,
            feed_id=feed_id,
            raw_ics_content=raw_ics,
        )
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in msg.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg) from exc

    return result


@router.delete(
    "/profiles/{profile_id}/school-ics/{feed_id}",
    summary="Delete a school calendar ICS subscription feed",
)
async def delete_profile_school_ics_feed(
    profile_id: str,
    feed_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a `SchoolIcsFeed` subscription."""
    deleted = await delete_school_ics_feed(db, profile_id=profile.id, feed_id=feed_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SchoolIcsFeed '{feed_id}' not found for profile '{profile.id}'.",
        )
    return {
        "id": feed_id,
        "feed_id": feed_id,
        "profile_id": profile.id,
        "deleted": True,
    }


__all__ = ["router"]
