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

"""Coordinated v2 FastAPI Router for SMART Scheduling, Zocdoc Booking Preview, Gmail Approved Send, Audit Verification, and OS Service Packaging (AU-71..AU-81)."""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, get_db, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.audit.hash_chain import verify_profile_audit_chain
from carefold.auth.ports import UserProfile
from carefold.clinical.smart_scheduling import discover_smart_scheduling_slots
from carefold.connectors.gmail_mcp import (
    execute_gmail_send_message,
    prepare_gmail_send_approval_payload,
)
from carefold.db.models import Appointment, Approval, EmailDraft, Profile, utc_now
from carefold.packaging.service import list_os_service_descriptors
from connectors.manifest import ConnectorManifest
from connectors.starters.zocdoc import prepare_zocdoc_booking_payload

logger = logging.getLogger("carefold.api.coordinated")

router = APIRouter(tags=["coordinated-v2"])

_V2_MANIFEST_FILES = (
    ("zocdoc", "zocdoc.yaml"),
    ("oracle-health", "oracle_health.yaml"),
    ("athenahealth", "athenahealth.yaml"),
    ("cms-blue-button", "cms_blue_button.yaml"),
    ("oura", "oura.yaml"),
    ("google-health", "google_health.yaml"),
    ("microsoft-graph", "microsoft_graph.yaml"),
)


def require_profile_access(
    required_access: Literal["manage", "view_clinical"] = "view_clinical",
) -> Callable[..., Coroutine[Any, Any, Profile]]:
    """Enforces profile-scoped RBAC via `get_user_profile_access`."""

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


class SmartSlotsDiscoveryRequest(BaseModel):
    """Request schema for HL7 SMART Scheduling Links slot discovery (`AU-72`)."""

    manifest_payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="HL7 SMART Scheduling Links $bulk-publish payload containing schedules and slots",
    )
    specialty_filter: Optional[str] = Field(
        default=None,
        description="Optional clinical specialty filter",
    )
    busy_windows: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Optional additional busy calendar windows",
    )


class ZocdocBookingPreviewRequest(BaseModel):
    """Request schema for preparing an irreversible Zocdoc booking preview and pending Approval (`AU-71`)."""

    provider_id: str = Field(..., min_length=1)
    provider_name: str = Field(..., min_length=1)
    specialty: str = Field("General", min_length=1)
    slot_id: str = Field(..., min_length=1)
    start_time: str = Field(..., min_length=1)
    insurance_carrier: Optional[str] = Field(default=None)
    run_id: Optional[str] = Field(default=None)


class GmailSendRequest(BaseModel):
    """Request schema for dispatching or requesting approval for `gmail_send_message` (`AU-76`)."""

    approval_id: Optional[str] = Field(
        default=None,
        description="Approved Approval ID; when omitted, creates a pending irreversible Approval request",
    )
    run_id: Optional[str] = Field(default=None)


@router.post(
    "/profiles/{profile_id}/scheduling/smart-slots",
    summary="Discover open HL7 SMART Scheduling Links slots cross-referenced against profile appointments",
)
async def post_discover_smart_scheduling_slots(
    profile_id: str,
    payload: SmartSlotsDiscoveryRequest,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Discovers free SMART Scheduling Links slots and marks calendar conflicts against profile appointments (`AU-72`)."""
    stmt = select(Appointment).where(
        Appointment.profile_id == profile.id,
        Appointment.status != "cancelled",
    )
    res = await db.execute(stmt)
    existing_appts = list(res.scalars().all())

    combined_busy: List[Dict[str, str]] = [
        {
            "start": appt.start_time.isoformat(),
            "end": appt.end_time.isoformat(),
        }
        for appt in existing_appts
        if appt.start_time and appt.end_time
    ]
    if payload.busy_windows:
        combined_busy.extend(payload.busy_windows)

    try:
        slots = discover_smart_scheduling_slots(
            manifest_payload=payload.manifest_payload,
            specialty_filter=payload.specialty_filter,
            busy_windows=combined_busy,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "profile_id": profile.id,
        "specialty_filter": payload.specialty_filter,
        "slots": slots,
        "total": len(slots),
        "source": "smart_scheduling_links",
    }


@router.post(
    "/profiles/{profile_id}/scheduling/zocdoc-preview",
    summary="Prepare an irreversible Zocdoc booking preview and create a pending Approval record",
)
async def post_zocdoc_booking_preview(
    profile_id: str,
    payload: ZocdocBookingPreviewRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Prepares a canonical Zocdoc booking payload and creates a pending `irreversible` `Approval` row (`AU-71`)."""
    try:
        preview = prepare_zocdoc_booking_payload(
            profile_id=profile.id,
            provider_id=payload.provider_id,
            provider_name=payload.provider_name,
            specialty=payload.specialty,
            slot_id=payload.slot_id,
            start_time=payload.start_time,
            insurance_carrier=payload.insurance_carrier,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    now = utc_now()
    approval = Approval(
        id=str(uuid.uuid4()),
        profile_id=profile.id,
        run_id=payload.run_id or f"zocdoc-{uuid.uuid4().hex[:8]}",
        tool_name="zocdoc_book_appointment",
        args_redacted=preview["args_redacted"],
        payload_hash=preview["payload_hash"],
        destination_hosts=preview["destination_hosts"],
        risk_tier="irreversible",
        status="pending",
        expires_at=now + timedelta(hours=24),
        created_at=now,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)

    result = dict(preview)
    result["approval_id"] = approval.id
    result["approval_status"] = approval.status
    return result


@router.post(
    "/profiles/{profile_id}/email-drafts/{draft_id}/send",
    summary="Send a reviewed EmailDraft via gmail_send_message with irreversible human approval enforcement",
)
async def post_send_profile_email_draft(
    profile_id: str,
    draft_id: str,
    payload: Optional[GmailSendRequest] = Body(default=None),
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Executes `execute_gmail_send_message` when `approval_id` is provided, or creates a pending `Approval` row (`AU-76`)."""
    req = payload or GmailSendRequest()
    actor_id = resolve_owner_user_id(user) or getattr(user, "id", None)

    if req.approval_id:
        try:
            return await execute_gmail_send_message(
                session=db,
                profile_id=profile.id,
                draft_id=draft_id,
                approval_id=req.approval_id,
                actor_user_id=actor_id,
            )
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            msg = str(exc)
            code = status.HTTP_404_NOT_FOUND if "not found" in msg.lower() else status.HTTP_400_BAD_REQUEST
            raise HTTPException(status_code=code, detail=msg) from exc

    stmt = select(EmailDraft).where(
        EmailDraft.id == (draft_id or "").strip(),
        EmailDraft.profile_id == profile.id,
    )
    res = await db.execute(stmt)
    draft = res.scalar_one_or_none()
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EmailDraft '{draft_id}' not found for profile '{profile.id}'.",
        )

    try:
        prepared = prepare_gmail_send_approval_payload(
            draft_id=draft.id,
            recipient=draft.recipient or "",
            subject=draft.subject,
            body=draft.body,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    now = utc_now()
    approval = Approval(
        id=str(uuid.uuid4()),
        profile_id=profile.id,
        run_id=req.run_id or f"gmail-send-{uuid.uuid4().hex[:8]}",
        tool_name="gmail_send_message",
        args_redacted=prepared["args_redacted"],
        payload_hash=prepared["payload_hash"],
        destination_hosts=prepared["destination_hosts"],
        risk_tier="irreversible",
        status="pending",
        expires_at=now + timedelta(hours=24),
        created_at=now,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)

    return {
        "status": "needs_approval",
        "requires_approval": True,
        "risk_tier": "irreversible",
        "tool_name": "gmail_send_message",
        "approval_id": approval.id,
        "approval_status": approval.status,
        "draft_id": draft.id,
        "profile_id": profile.id,
        "payload_hash": prepared["payload_hash"],
    }


@router.get(
    "/profiles/{profile_id}/audit/verify",
    summary="Verify tamper-evident SHA-256 audit hash chain integrity for a profile",
)
async def get_verify_profile_audit_chain(
    profile_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Verifies the profile's `AuditEventRecord` SHA-256 hash chain (`AU-78`)."""
    return await verify_profile_audit_chain(db, profile.id)


@router.get(
    "/system/service-descriptors",
    summary="List OS background service descriptors (launchd, systemd, Windows Task Scheduler)",
)
async def get_system_service_descriptors(
    port: int = Query(8000, ge=1, le=65535, description="Local loopback service port"),
    _user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Returns local-first OS service descriptors bound to `127.0.0.1` (`AU-81`)."""
    descriptors = list_os_service_descriptors(port=port)
    return {
        "descriptors": descriptors,
        "total": len(descriptors),
    }


@router.get(
    "/connectors/v2-catalog",
    summary="List Carefold v2 starter connectors and their trust/auth metadata",
)
async def get_v2_connectors_catalog(
    _user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Lists the 7 Batch 7 v2 starter connectors (`zocdoc`, `oracle-health`, `athenahealth`, `cms-blue-button`, `oura`, `google-health`, `microsoft-graph`)."""
    manifests_dir = (
        Path(__file__).resolve().parents[4]
        / "libs"
        / "connectors"
        / "connectors"
        / "starters"
        / "manifests"
    )
    items: List[Dict[str, Any]] = []
    for cid, filename in _V2_MANIFEST_FILES:
        manifest_path = manifests_dir / filename
        if manifest_path.is_file():
            manifest = ConnectorManifest.from_yaml(manifest_path)
            items.append(
                {
                    "id": manifest.id,
                    "name": manifest.name,
                    "version": manifest.version,
                    "description": manifest.description,
                    "categories": list(manifest.categories),
                    "allowed_hosts": list(manifest.data_flows.allowed_hosts),
                    "trust_level": manifest.trust.trust_level,
                    "pkce": manifest.auth.pkce,
                    "tools": [t.name for t in manifest.tools],
                }
            )
        else:
            items.append({"id": cid, "name": cid})

    return {
        "connectors": items,
        "connector_ids": [item["id"] for item in items],
        "total": len(items),
    }


__all__ = ["router"]
