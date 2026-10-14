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

"""REST API endpoints for iOS Companion Pairing, Pinned TLS Verification, HealthKit Sync & Reminders (AU-62)."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_auth, get_current_user, get_db, resolve_owner_user_id
from carefold.api.profiles import get_user_profile_access
from carefold.auth.ports import AuthPort, UserProfile
from carefold.companion.pairing import (
    CompanionPairingError,
    authenticate_companion_device,
    complete_companion_pairing,
    initiate_companion_pairing,
    revoke_companion_device,
)
from carefold.companion.sync import (
    ingest_companion_sync,
    list_companion_reminders,
)
from carefold.config import settings
from carefold.db.models import CompanionDevice, Profile

router = APIRouter(tags=["companion"])


# ============================================================================
# Section 1: Pydantic Request Schemas
# ============================================================================


class InitiateCompanionPairingRequest(BaseModel):
    """Request payload for initiating QR-based iOS companion pairing."""

    device_name: str = Field(..., min_length=1, max_length=255, description="Human-readable iOS device name")
    host: str = Field("127.0.0.1", min_length=1, max_length=255, description="Carefold host/IP encoded in QR")
    port: int = Field(8000, ge=1, le=65535, description="Carefold port encoded in QR")
    cert_fingerprint_sha256: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Pinned TLS server certificate SHA-256 fingerprint",
    )
    allowed_categories: Optional[List[str]] = Field(
        None,
        description="Consented companion categories (vitals, clinical_records, reminders)",
    )
    auth_provider: Optional[str] = Field(None, description="Optional override for active auth_provider")
    bind_host: Optional[str] = Field(None, description="Optional override for server network bind host")
    explicit_lan_opt_in: bool = Field(False, description="Whether Mode L LAN opt-in is explicitly enabled")


class CompleteCompanionPairingRequest(BaseModel):
    """Request payload sent by the iOS companion app to complete QR pairing."""

    device_id: str = Field(..., min_length=1, description="CompanionDevice UUID from QR payload")
    pairing_code: str = Field(..., min_length=1, description="One-time pairing code from QR payload")
    client_cert_fingerprint_sha256: str = Field(
        ...,
        min_length=1,
        description="Observed TLS server certificate SHA-256 fingerprint verified by the iOS client",
    )


class CompanionSyncRequest(BaseModel):
    """Request payload for syncing aggregated HealthKit Observations and HKClinicalRecords."""

    device_id: Optional[str] = Field(None, description="CompanionDevice ID when authenticated via user session")
    device_token: Optional[str] = Field(None, description="Optional companion bearer token")
    observations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Aggregated HealthKit Observation payloads",
    )
    clinical_records: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="HKClinicalRecord FHIR R4 resources (Condition, MedicationRequest, AllergyIntolerance, Immunization, Observation)",
    )


# ============================================================================
# Section 2: Helpers & Dependencies
# ============================================================================


def _serialize_companion_device(device: CompanionDevice) -> Dict[str, Any]:
    """Serializes a `CompanionDevice` ORM model to a JSON dictionary."""
    return {
        "id": device.id,
        "device_id": device.id,
        "user_id": device.user_id,
        "profile_id": device.profile_id,
        "device_name": device.device_name,
        "platform": device.platform,
        "cert_fingerprint_sha256": device.cert_fingerprint_sha256,
        "allowed_categories": list(device.allowed_categories),
        "status": device.status,
        "paired_at": device.paired_at.isoformat() if device.paired_at else None,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "expires_at": device.expires_at.isoformat() if device.expires_at else None,
        "created_at": device.created_at.isoformat() if device.created_at else None,
        "updated_at": device.updated_at.isoformat() if device.updated_at else None,
    }


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
                detail="Access denied: management permissions required for companion device administration.",
            )

        if required_access == "view_clinical" and access not in ("manage", "view_clinical"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: clinical view permissions required.",
            )

        return profile

    return _dependency


def _extract_companion_bearer_token(
    request: Request,
    explicit_token: Optional[str] = None,
) -> Optional[str]:
    """Extracts a `cf-ios-...` companion bearer token from headers or explicit payload parameter."""
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()

    comp_header = request.headers.get("X-Companion-Token") or request.headers.get("x-companion-token")
    if comp_header and comp_header.strip():
        return comp_header.strip()

    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header:
        raw = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else auth_header.strip()
        if raw.startswith("cf-ios-"):
            return raw

    return None


async def _resolve_sync_companion_device(
    request: Request,
    profile_id: str,
    db: AsyncSession,
    auth: AuthPort,
    device_id: Optional[str] = None,
    explicit_token: Optional[str] = None,
) -> CompanionDevice:
    """Resolves an active `CompanionDevice` via either its `cf-ios-...` bearer token or an authenticated steward session."""
    clean_profile_id = (profile_id or "").strip()
    comp_token = _extract_companion_bearer_token(request, explicit_token=explicit_token)
    if comp_token:
        try:
            return await authenticate_companion_device(
                session=db,
                profile_id=clean_profile_id,
                device_token=comp_token,
            )
        except CompanionPairingError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc

    # Fall back to standard user session authentication
    user = await get_current_user(request=request, auth=auth, db=db)
    prof_res = await db.execute(select(Profile).where(Profile.id == clean_profile_id))
    profile = prof_res.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{clean_profile_id}' not found.",
        )

    access = await get_user_profile_access(profile, user, db)
    if access not in ("manage", "view_clinical"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this profile.",
        )

    stmt = select(CompanionDevice).where(CompanionDevice.profile_id == clean_profile_id)
    if device_id and device_id.strip():
        stmt = stmt.where(CompanionDevice.id == device_id.strip())
    else:
        stmt = stmt.where(CompanionDevice.status == "active").order_by(CompanionDevice.created_at.desc())

    res = await db.execute(stmt)
    device = res.scalars().first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active companion device not found for this profile.",
        )
    return device


# ============================================================================
# Section 3: REST Endpoints
# ============================================================================


@router.post(
    "/profiles/{profile_id}/companion/pair/initiate",
    status_code=status.HTTP_201_CREATED,
    summary="Initiate QR-based iOS companion pairing with Mode S guard and pinned TLS fingerprint",
)
async def initiate_companion_pairing_endpoint(
    profile_id: str,
    payload: InitiateCompanionPairingRequest,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Enforces Mode S network guard and creates a `pending_pair` `CompanionDevice` with a 10-minute code."""
    owner_id = resolve_owner_user_id(user) or profile.user_id or getattr(user, "id", "local-steward")
    active_auth_provider = payload.auth_provider or getattr(settings, "auth_provider", "local") or "local"
    active_bind_host = payload.bind_host or payload.host or "127.0.0.1"

    try:
        return await initiate_companion_pairing(
            session=db,
            user_id=str(owner_id),
            profile_id=profile.id,
            device_name=payload.device_name,
            host=payload.host,
            port=payload.port,
            cert_fingerprint_sha256=payload.cert_fingerprint_sha256,
            allowed_categories=payload.allowed_categories,
            auth_provider=active_auth_provider,
            bind_host=active_bind_host,
            explicit_lan_opt_in=payload.explicit_lan_opt_in,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/profiles/{profile_id}/companion/pair/complete",
    summary="Complete iOS companion pairing by verifying one-time code and pinned TLS certificate fingerprint",
)
async def complete_companion_pairing_endpoint(
    profile_id: str,
    payload: CompleteCompanionPairingRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Verifies the one-time pairing code and pinned TLS fingerprint, issuing a scoped `cf-ios-...` token."""
    clean_profile_id = (profile_id or "").strip()
    dev_res = await db.execute(
        select(CompanionDevice).where(CompanionDevice.id == payload.device_id.strip())
    )
    device = dev_res.scalar_one_or_none()
    if device is None or device.profile_id != clean_profile_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Companion device '{payload.device_id}' not found for profile '{clean_profile_id}'.",
        )

    try:
        return await complete_companion_pairing(
            session=db,
            device_id=payload.device_id,
            pairing_code=payload.pairing_code,
            client_cert_fingerprint_sha256=payload.client_cert_fingerprint_sha256,
        )
    except CompanionPairingError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get(
    "/profiles/{profile_id}/companion/devices",
    summary="List paired and pending iOS companion devices for a care profile",
)
async def list_profile_companion_devices(
    profile_id: str,
    profile: Profile = Depends(require_profile_access("view_clinical")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Lists all `CompanionDevice` records for `profile_id`."""
    stmt = (
        select(CompanionDevice)
        .where(CompanionDevice.profile_id == profile.id)
        .order_by(CompanionDevice.created_at.desc())
    )
    res = await db.execute(stmt)
    items = [_serialize_companion_device(d) for d in res.scalars().all()]
    return {
        "devices": items,
        "items": items,
        "total": len(items),
    }


@router.delete(
    "/profiles/{profile_id}/companion/devices/{device_id}",
    summary="Revoke a paired iOS companion device and invalidate its bearer token",
)
async def revoke_profile_companion_device(
    profile_id: str,
    device_id: str,
    profile: Profile = Depends(require_profile_access("manage")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Revokes `device_id` on `profile_id`, clears `token_hash`, and revokes the companion `ConsentGrant`."""
    owner_id = resolve_owner_user_id(user) or profile.user_id
    try:
        device = await revoke_companion_device(
            session=db,
            profile_id=profile.id,
            device_id=device_id,
            actor_user_id=owner_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return {
        **_serialize_companion_device(device),
        "revoked": True,
    }


@router.post(
    "/profiles/{profile_id}/companion/sync",
    summary="Ingest aggregated HealthKit Observations and HKClinicalRecord FHIR R4 resources from iOS companion",
)
async def sync_companion_records_endpoint(
    profile_id: str,
    payload: CompanionSyncRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Validates and ingests HealthKit `Observation` readings and `HKClinicalRecord` resources."""
    device = await _resolve_sync_companion_device(
        request=request,
        profile_id=profile_id,
        db=db,
        auth=auth,
        device_id=payload.device_id,
        explicit_token=payload.device_token,
    )

    try:
        return await ingest_companion_sync(
            session=db,
            device=device,
            observations=payload.observations,
            clinical_records=payload.clinical_records,
        )
    except CompanionPairingError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/profiles/{profile_id}/companion/reminders",
    summary="Poll PHI-safe reminder notification schedules for iOS companion local notifications",
)
async def list_companion_reminders_endpoint(
    profile_id: str,
    request: Request,
    device_id: Optional[str] = Query(None, description="Optional CompanionDevice ID"),
    db: AsyncSession = Depends(get_db),
    auth: AuthPort = Depends(get_auth),
) -> Dict[str, Any]:
    """Returns PHI-redacted local notification schedules (`E4.5`) for a paired iOS companion device."""
    device = await _resolve_sync_companion_device(
        request=request,
        profile_id=profile_id,
        db=db,
        auth=auth,
        device_id=device_id,
    )

    try:
        items = await list_companion_reminders(session=db, device=device)
    except CompanionPairingError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    return {
        "reminders": items,
        "items": items,
        "total": len(items),
    }


__all__ = ["router"]
