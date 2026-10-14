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

"""iOS Companion Pairing, Mode S Network Guard, Pinned TLS Verification, and HealthKit Sync (AU-62).

Implements:
- Mode S & non-loopback network guard (`check_companion_mode_guard`, `DESIGN §7` & `§13`).
- QR pairing initiation with 10-minute single-use pairing code and SHA-256 certificate fingerprint pinning (`E8.1`).
- Constant-time pairing completion issuing a profile-scoped bearer token (`cf-ios-...`) and `ConsentGrant`.
- Companion device revocation with token invalidation and consent revocation.
"""

from __future__ import annotations

from datetime import timedelta
import hashlib
import hmac
import json
import secrets
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import (
    AuditEventRecord,
    CompanionDevice,
    ConsentGrant,
    utc_now,
)

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
DEFAULT_COMPANION_CATEGORIES = ("vitals", "clinical_records", "reminders")
VALID_COMPANION_CATEGORIES = frozenset({"vitals", "clinical_records", "reminders"})
PAIRING_CODE_TTL_MINUTES = 10
DEVICE_TOKEN_TTL_DAYS = 90


class CompanionPairingError(PermissionError, ValueError):
    """Raised when companion pairing or authentication fails security verification."""


def _sha256_hex(value: str) -> str:
    """Computes lowercase SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_fingerprint(fingerprint: str) -> str:
    """Normalizes a SHA-256 certificate fingerprint for constant-time comparison."""
    clean = (fingerprint or "").strip().lower()
    if clean.startswith("sha256:"):
        clean = clean[7:].strip()
    return clean.replace(":", "")


def check_companion_mode_guard(
    auth_provider: str,
    bind_host: str,
    explicit_lan_opt_in: bool = False,
) -> None:
    """Enforces the Mode S / LAN security guard before allowing companion pairing (`DESIGN §7` & `§13`).

    Pairing is disabled when `auth_provider == 'disabled'` and `bind_host` is not a loopback address.

    Raises:
        PermissionError: If authentication is disabled on a non-loopback network bind.
    """
    clean_auth = (auth_provider or "local").strip().lower()
    clean_host = (bind_host or "127.0.0.1").strip().lower()

    if clean_auth == "disabled" and clean_host not in LOOPBACK_HOSTS:
        raise PermissionError(
            "Companion pairing is disabled when authentication is disabled on a non-loopback network bind."
        )


async def initiate_companion_pairing(
    session: AsyncSession,
    user_id: str,
    profile_id: str,
    device_name: str,
    host: str,
    port: int,
    cert_fingerprint_sha256: str,
    allowed_categories: Optional[List[str]] = None,
    auth_provider: str = "local",
    bind_host: str = "127.0.0.1",
    explicit_lan_opt_in: bool = False,
) -> Dict[str, Any]:
    """Initiates QR-based iOS companion pairing and persists a `pending_pair` `CompanionDevice` (`E8.1`)."""
    check_companion_mode_guard(
        auth_provider=auth_provider,
        bind_host=bind_host,
        explicit_lan_opt_in=explicit_lan_opt_in,
    )

    clean_user_id = (user_id or "").strip()
    clean_profile_id = (profile_id or "").strip()
    clean_device_name = (device_name or "").strip()
    clean_host = (host or "").strip() or "127.0.0.1"
    clean_fingerprint = (cert_fingerprint_sha256 or "").strip()

    if not clean_user_id:
        raise ValueError("user_id is required to initiate companion pairing.")
    if not clean_profile_id:
        raise ValueError("profile_id is required to initiate companion pairing.")
    if not clean_device_name:
        raise ValueError("device_name is required to initiate companion pairing.")
    if not clean_fingerprint or not _normalize_fingerprint(clean_fingerprint):
        raise ValueError("cert_fingerprint_sha256 is required for pinned TLS companion pairing.")
    if int(port) < 1 or int(port) > 65535:
        raise ValueError(f"Invalid port: {port}. Must be between 1 and 65535.")

    if allowed_categories is None:
        categories = list(DEFAULT_COMPANION_CATEGORIES)
    else:
        categories = []
        for cat in allowed_categories:
            clean_cat = str(cat or "").strip().lower()
            if not clean_cat or clean_cat not in VALID_COMPANION_CATEGORIES:
                raise ValueError(
                    f"Invalid companion category '{cat}'. Allowed: {sorted(VALID_COMPANION_CATEGORIES)}"
                )
            if clean_cat not in categories:
                categories.append(clean_cat)

    now = utc_now()
    expires_at = now + timedelta(minutes=PAIRING_CODE_TTL_MINUTES)
    pairing_code = f"cf-pair-{secrets.token_urlsafe(16)}"
    pairing_code_hash = _sha256_hex(pairing_code)

    device = CompanionDevice(
        id=str(uuid.uuid4()),
        user_id=clean_user_id,
        profile_id=clean_profile_id,
        device_name=clean_device_name,
        platform="ios",
        pairing_code_hash=pairing_code_hash,
        token_hash=None,
        cert_fingerprint_sha256=clean_fingerprint,
        allowed_categories=categories,
        status="pending_pair",
        paired_at=None,
        last_seen_at=None,
        expires_at=expires_at,
        created_at=now,
        updated_at=now,
    )
    session.add(device)

    payload_hash = _sha256_hex(
        json.dumps(
            {
                "device_id": device.id,
                "profile_id": clean_profile_id,
                "device_name": clean_device_name,
                "allowed_categories": categories,
            },
            sort_keys=True,
        )
    )
    audit_record = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=clean_user_id,
        principal="user",
        event="companion_pair_initiated",
        tool="initiate_companion_pairing",
        risk="admin",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"companion_device:{device.id}",
        detail_redacted=json.dumps({
            "device_id": device.id,
            "device_name": clean_device_name,
            "allowed_categories": categories,
            "expires_at": expires_at.isoformat(),
        }),
    )
    session.add(audit_record)
    await session.commit()
    await session.refresh(device)

    return {
        "device_id": device.id,
        "profile_id": clean_profile_id,
        "device_name": device.device_name,
        "host": clean_host,
        "port": int(port),
        "pairing_code": pairing_code,
        "cert_fingerprint_sha256": clean_fingerprint,
        "allowed_categories": device.allowed_categories,
        "expires_at": expires_at.isoformat(),
        "status": device.status,
    }


async def complete_companion_pairing(
    session: AsyncSession,
    device_id: str,
    pairing_code: str,
    client_cert_fingerprint_sha256: str,
) -> Dict[str, Any]:
    """Completes companion pairing after verifying the one-time code and pinned TLS certificate fingerprint (`E8.1`)."""
    clean_device_id = (device_id or "").strip()
    clean_code = (pairing_code or "").strip()
    clean_client_fp = (client_cert_fingerprint_sha256 or "").strip()

    if not clean_device_id or not clean_code or not clean_client_fp:
        raise CompanionPairingError(
            "device_id, pairing_code, and client_cert_fingerprint_sha256 are required."
        )

    stmt = select(CompanionDevice).where(CompanionDevice.id == clean_device_id)
    res = await session.execute(stmt)
    device = res.scalar_one_or_none()
    if device is None:
        raise CompanionPairingError(f"Companion device '{clean_device_id}' not found.")

    if device.status != "pending_pair" or not device.pairing_code_hash:
        raise CompanionPairingError(
            f"Companion device '{clean_device_id}' is not awaiting pairing (status='{device.status}')."
        )

    now = utc_now()
    if device.expires_at is not None:
        exp = (
            device.expires_at
            if device.expires_at.tzinfo is not None
            else device.expires_at.replace(tzinfo=now.tzinfo)
        )
        if now > exp:
            raise CompanionPairingError("Companion pairing code has expired.")

    provided_code_hash = _sha256_hex(clean_code)
    if not hmac.compare_digest(
        provided_code_hash.encode("ascii"),
        device.pairing_code_hash.encode("ascii"),
    ):
        raise CompanionPairingError("Invalid companion pairing code.")

    expected_fp_norm = _normalize_fingerprint(device.cert_fingerprint_sha256)
    provided_fp_norm = _normalize_fingerprint(clean_client_fp)
    if not expected_fp_norm or not hmac.compare_digest(
        expected_fp_norm.encode("ascii"),
        provided_fp_norm.encode("ascii"),
    ):
        raise CompanionPairingError(
            "Pinned TLS certificate fingerprint verification failed: client fingerprint does not match server certificate."
        )

    device_token = f"cf-ios-{secrets.token_urlsafe(32)}"
    device.token_hash = _sha256_hex(device_token)
    device.pairing_code_hash = None
    device.status = "active"
    device.paired_at = now
    device.last_seen_at = now
    device.expires_at = now + timedelta(days=DEVICE_TOKEN_TTL_DAYS)
    device.updated_at = now

    consent_grant = ConsentGrant(
        id=str(uuid.uuid4()),
        profile_id=device.profile_id,
        connection_id=None,
        connector_id="ios-companion",
        granted_by_user_id=device.user_id,
        categories=device.allowed_categories,
        scopes=["companion:sync"],
        allowed_hosts=[],
        purpose="companion_sync",
        terms_version="1.0.0",
        connector_version="0.1.0",
        status="active",
        granted_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(consent_grant)

    payload_hash = _sha256_hex(
        json.dumps(
            {
                "device_id": device.id,
                "profile_id": device.profile_id,
                "allowed_categories": device.allowed_categories,
            },
            sort_keys=True,
        )
    )
    audit_record = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=device.profile_id,
        actor_user_id=device.user_id,
        principal="user",
        event="companion_paired",
        tool="complete_companion_pairing",
        risk="write_local",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"companion_device:{device.id}",
        detail_redacted=json.dumps({
            "device_id": device.id,
            "device_name": device.device_name,
            "allowed_categories": device.allowed_categories,
            "consent_grant_id": consent_grant.id,
        }),
    )
    session.add(audit_record)
    await session.commit()
    await session.refresh(device)

    return {
        "device_id": device.id,
        "profile_id": device.profile_id,
        "device_name": device.device_name,
        "device_token": device_token,
        "status": device.status,
        "allowed_categories": device.allowed_categories,
        "paired_at": device.paired_at.isoformat() if device.paired_at else None,
    }


async def authenticate_companion_device(
    session: AsyncSession,
    profile_id: str,
    device_token: str,
) -> CompanionDevice:
    """Authenticates an active `CompanionDevice` using its scoped bearer token and verifies profile isolation."""
    clean_profile_id = (profile_id or "").strip()
    clean_token = (device_token or "").strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_profile_id or not clean_token:
        raise CompanionPairingError("profile_id and device_token are required.")

    token_hash = _sha256_hex(clean_token)
    stmt = select(CompanionDevice).where(
        CompanionDevice.token_hash == token_hash,
        CompanionDevice.status == "active",
    )
    res = await session.execute(stmt)
    device = res.scalar_one_or_none()
    if device is None:
        raise CompanionPairingError("Invalid or revoked companion device token.")

    if device.profile_id != clean_profile_id:
        raise CompanionPairingError(
            f"Companion device token is scoped to profile '{device.profile_id}', not '{clean_profile_id}'."
        )

    now = utc_now()
    if device.expires_at is not None:
        exp = (
            device.expires_at
            if device.expires_at.tzinfo is not None
            else device.expires_at.replace(tzinfo=now.tzinfo)
        )
        if now > exp:
            raise CompanionPairingError("Companion device token has expired.")

    return device


async def revoke_companion_device(
    session: AsyncSession,
    profile_id: str,
    device_id: str,
    actor_user_id: Optional[str] = None,
) -> CompanionDevice:
    """Revokes a `CompanionDevice`, clears its bearer token hash, revokes matching `ConsentGrant`, and logs audit."""
    clean_profile_id = (profile_id or "").strip()
    clean_device_id = (device_id or "").strip()
    if not clean_profile_id or not clean_device_id:
        raise ValueError("profile_id and device_id are required.")

    stmt = select(CompanionDevice).where(
        CompanionDevice.id == clean_device_id,
        CompanionDevice.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    device = res.scalar_one_or_none()
    if device is None:
        raise ValueError(
            f"Companion device '{clean_device_id}' not found for profile '{clean_profile_id}'."
        )

    now = utc_now()
    device.status = "revoked"
    device.token_hash = None
    device.pairing_code_hash = None
    device.updated_at = now

    consent_stmt = select(ConsentGrant).where(
        ConsentGrant.profile_id == clean_profile_id,
        ConsentGrant.connector_id == "ios-companion",
        ConsentGrant.status == "active",
    )
    consent_res = await session.execute(consent_stmt)
    for grant in consent_res.scalars().all():
        grant.status = "revoked"
        grant.revoked_at = now
        grant.updated_at = now

    payload_hash = _sha256_hex(
        json.dumps(
            {
                "profile_id": clean_profile_id,
                "device_id": device.id,
            },
            sort_keys=True,
        )
    )
    audit_record = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id or device.user_id,
        principal="user",
        event="companion_revoked",
        tool="revoke_companion_device",
        risk="irreversible",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"companion_device:{device.id}",
        detail_redacted=json.dumps({
            "device_id": device.id,
            "device_name": device.device_name,
            "status": "revoked",
        }),
    )
    session.add(audit_record)
    await session.commit()
    await session.refresh(device)
    return device


__all__ = [
    "LOOPBACK_HOSTS",
    "DEFAULT_COMPANION_CATEGORIES",
    "VALID_COMPANION_CATEGORIES",
    "CompanionPairingError",
    "check_companion_mode_guard",
    "initiate_companion_pairing",
    "complete_companion_pairing",
    "authenticate_companion_device",
    "revoke_companion_device",
]
