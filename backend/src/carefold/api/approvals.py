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

"""Approvals REST API Router & Atomic Resumption Engine (AU-18, ADR-0004).

Exposes endpoints for human-in-the-loop tool execution approvals:
- GET /api/approvals?profile_id={profile_id}: lists pending approvals for the profile.
- POST /api/approvals/{approval_id}/decide: approves or rejects an approval request with optional edited arguments.
- consume_approval_atomic(): atomic SQL update query for single-use resume token consumption.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.db.models import Approval, Profile
from carefold.engine.tool_exec import (
    SqlApprovalStore,
    canonical_json,
    compute_payload_hash,
)
from carefold.logging import get_logger

logger = get_logger("carefold.api.approvals")

router = APIRouter(tags=["approvals"])


# ============================================================================
# Section 1: Pydantic Schemas
# ============================================================================


class ApprovalDecideRequest(BaseModel):
    """Payload for deciding a pending tool approval request."""

    decision: Literal["approved", "rejected", "approve", "reject"] = Field(
        ...,
        description="Decision: approved or rejected",
    )
    edited_args: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional edited arguments replacing original proposed tool arguments",
    )

    model_config = ConfigDict(extra="forbid")


class ApprovalResponse(BaseModel):
    """Serialized human-in-the-loop tool approval request."""

    id: str
    profile_id: str
    run_id: str
    thread_id: Optional[str] = None
    tool_name: str
    args_redacted: str
    args: Dict[str, Any]
    payload_hash: str
    destination_hosts: List[str]
    risk_tier: str
    status: str
    expires_at: datetime
    created_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Section 2: Helper Functions
# ============================================================================


def ensure_utc(dt: datetime) -> datetime:
    """Ensures a datetime is timezone-aware UTC, normalizing offset-naive datetimes from SQLite."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def serialize_approval(approval: Approval) -> ApprovalResponse:
    """Serializes an Approval ORM entity into a typed ApprovalResponse."""
    return ApprovalResponse(
        id=approval.id,
        profile_id=approval.profile_id,
        run_id=approval.run_id,
        thread_id=approval.thread_id,
        tool_name=approval.tool_name,
        args_redacted=approval.args_redacted,
        args=approval.args_dict,
        payload_hash=approval.payload_hash,
        destination_hosts=approval.hosts_list,
        risk_tier=approval.risk_tier,
        status=approval.status,
        expires_at=ensure_utc(approval.expires_at),
        created_at=ensure_utc(approval.created_at),
        decided_at=ensure_utc(approval.decided_at) if approval.decided_at else None,
        decided_by=approval.decided_by,
    )


def verify_csrf(request: Request) -> None:
    """Enforces CSRF protection on state-mutating requests.

    Requests authenticated via explicit Authorization headers are immune to ambient browser CSRF.
    For cookie-based sessions, blocks cross-site browser requests (Sec-Fetch-Site: cross-site).
    """
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header:
        # Explicit Bearer token header in place; browser ambient credentials not relied upon.
        return

    sec_fetch_site = request.headers.get("Sec-Fetch-Site")
    if sec_fetch_site == "cross-site":
        logger.warning("csrf_blocked_cross_site_request", path=str(request.url.path))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF protection: cross-site requests are forbidden.",
        )


async def verify_manage_access(
    profile: Profile,
    user: UserProfile,
    db: AsyncSession,
) -> None:
    """Verifies that the user has explicit 'manage' permission on the target profile.

    Invariant (AU-18): Admin bypasses are strictly disallowed. Even users with role='admin'
    must have account ownership or an explicit 'manage' access grant on the profile.
    """
    access = await get_user_profile_access(profile, user, db)
    if access != "manage":
        logger.warning(
            "approval_access_denied",
            profile_id=profile.id,
            user_id=getattr(user, "id", None),
            access_level=access,
            user_role=getattr(user, "role", None),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: management privileges required for profile.",
        )


# ============================================================================
# Section 3: REST API Endpoints
# ============================================================================


@router.get("", response_model=List[ApprovalResponse])
@router.get("/", response_model=List[ApprovalResponse], include_in_schema=False)
async def list_approvals(
    request: Request,
    profile_id: Optional[str] = None,
    status_filter: Optional[str] = Query(
        "pending",
        alias="status",
        description="Filter status: 'pending', 'approved', 'rejected', 'consumed', 'expired', or 'all'",
    ),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ApprovalResponse]:
    """Lists pending tool execution approvals for a given profile.

    Requires explicit 'manage' access on the target profile. Admin bypass is denied.
    """
    resolved_profile_id = profile_id or request.path_params.get("profile_id")
    if not resolved_profile_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'profile_id' is required.",
        )

    # 1. Fetch Profile and assert manage permissions
    p_stmt = select(Profile).where(Profile.id == resolved_profile_id)
    p_res = await db.execute(p_stmt)
    profile = p_res.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{resolved_profile_id}' not found.",
        )

    await verify_manage_access(profile, user, db)

    # 2. Query Approvals for Profile
    now = datetime.now(timezone.utc)
    stmt = select(Approval).where(Approval.profile_id == resolved_profile_id)

    target_status = (status_filter or "pending").lower()
    if target_status != "all":
        if target_status == "pending":
            stmt = stmt.where(Approval.status == "pending", Approval.expires_at > now)
        else:
            stmt = stmt.where(Approval.status == target_status)

    stmt = stmt.order_by(Approval.created_at.desc())
    res = await db.execute(stmt)
    approvals = list(res.scalars().all())

    return [serialize_approval(appr) for appr in approvals]


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """Retrieves a specific approval request by ID."""
    stmt = select(Approval).where(Approval.id == approval_id)
    res = await db.execute(stmt)
    approval = res.scalar_one_or_none()
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )

    p_stmt = select(Profile).where(Profile.id == approval.profile_id)
    p_res = await db.execute(p_stmt)
    profile = p_res.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target profile '{approval.profile_id}' not found.",
        )

    await verify_manage_access(profile, user, db)
    return serialize_approval(approval)


@router.post("/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecideRequest,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """Decides (approves or rejects) a pending tool approval request.

    - decision: 'approved' or 'rejected'
    - edited_args: optional dictionary of modified tool arguments.
      If supplied, recomputes and updates payload_hash = compute_payload_hash(edited_args)
      and updates args_redacted = canonical_json(edited_args).
    - Requires explicit 'manage' permission on the profile. Admin bypass is denied.
    """
    verify_csrf(request)

    # 1. Fetch Approval record
    stmt = select(Approval).where(Approval.id == approval_id)
    res = await db.execute(stmt)
    approval = res.scalar_one_or_none()
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )

    # 2. Fetch associated Profile and assert 'manage' permission (admin bypass denied)
    p_stmt = select(Profile).where(Profile.id == approval.profile_id)
    p_res = await db.execute(p_stmt)
    profile = p_res.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target profile '{approval.profile_id}' not found.",
        )

    await verify_manage_access(profile, user, db)

    # 3. Check lifecycle invariants: must be currently 'pending'
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Approval request '{approval_id}' is already in status '{approval.status}' and cannot be decided.",
        )

    # 4. Check TTL expiration
    now = datetime.now(timezone.utc)
    if ensure_utc(approval.expires_at) <= now:
        approval.status = "expired"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approval request has expired and cannot be decided.",
        )

    # 5. Apply decision
    normalized_decision = "approved" if payload.decision in ("approved", "approve") else "rejected"
    approval.status = normalized_decision
    approval.decided_at = now
    approval.decided_by = getattr(user, "id", None) or "steward"

    # 6. If approved with edited arguments, recompute payload hash and canonical JSON
    if normalized_decision == "approved" and payload.edited_args is not None:
        approval.payload_hash = compute_payload_hash(payload.edited_args)
        approval.args_redacted = canonical_json(payload.edited_args)

    await db.commit()
    await db.refresh(approval)

    logger.info(
        "approval_decided",
        approval_id=approval.id,
        decision=approval.status,
        decided_by=approval.decided_by,
        tool=approval.tool_name,
        payload_hash=approval.payload_hash,
    )

    return serialize_approval(approval)


# ============================================================================
# Section 4: Atomic Resumption Engine (AU-18, ADR-0004)
# ============================================================================


async def consume_approval_atomic(
    db: AsyncSession,
    approval_id: str,
    current_args: Dict[str, Any],
) -> str:
    """Atomically consumes an approved tool approval token during workflow resume.

    Enforces the single-use token lifecycle invariant:
        UPDATE approvals
        SET status = 'consumed'
        WHERE id = :id AND status = 'approved'
        RETURNING id;

    Fails closed:
    - Raises ValueError if record is not found.
    - Raises ValueError if record is not in 'approved' status.
    - Raises ValueError if token is expired.
    - Raises ValueError if SHA-256 canonical payload hash does not match current_args.
    - Raises ValueError if 0 rows returned (already consumed / replay attack).

    Returns:
        The consumed approval ID on success.
    """
    # 1. Fetch record to verify existence, status, TTL, and payload hash
    stmt = select(Approval).where(Approval.id == approval_id)
    res = await db.execute(stmt)
    approval = res.scalar_one_or_none()
    if approval is None:
        raise ValueError(f"Approval request '{approval_id}' not found.")

    if approval.status != "approved":
        raise ValueError(
            f"Approval is in status '{approval.status}', cannot consume (fail-closed)."
        )

    now = datetime.now(timezone.utc)
    if ensure_utc(approval.expires_at) <= now:
        approval.status = "expired"
        await db.commit()
        raise ValueError("Approval request has expired (fail-closed).")

    # 2. Cryptographic payload hash verification (RFC-8785 canonical JSON SHA-256)
    curr_hash = compute_payload_hash(current_args)
    if curr_hash != approval.payload_hash:
        raise ValueError(
            f"Payload hash mismatch! Expected {approval.payload_hash}, got {curr_hash} (fail-closed)."
        )

    # 3. Atomic transition: approved -> consumed with RETURNING id
    stmt_atomic = text(
        "UPDATE approvals SET status = 'consumed' WHERE id = :id AND status = 'approved' RETURNING id"
    )
    res_atomic = await db.execute(stmt_atomic, {"id": approval_id})
    consumed_id = res_atomic.scalar_one_or_none()

    if not consumed_id:
        raise ValueError(
            "Approval token has already been consumed or is invalid (fail-closed)."
        )

    await db.commit()
    logger.info("approval_consumed_atomically", approval_id=approval_id)
    return str(consumed_id)


__all__ = [
    "router",
    "ApprovalDecideRequest",
    "ApprovalResponse",
    "SqlApprovalStore",
    "serialize_approval",
    "verify_csrf",
    "verify_manage_access",
    "consume_approval_atomic",
]
