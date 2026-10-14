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

"""Granular Viewer Section Scoping & Teen Connection Handover with DEK Re-Encryption (AU-63 / E12.3, E12.4).

Implements:
- `VALID_VIEWER_SECTIONS` and `update_viewer_sections` (`E12.3`): per-section read-only scoping stored in
  `ProfileAccess.allowed_sections_json`.
- `check_profile_section_access`: evaluates owner/manage bypass, explicit `allowed_sections`, or legacy
  `view_clinical` / `view_paperwork` fallback mapping.
- `execute_teen_handover` (`E12.4`): promotes `teen_user_id` to profile steward (`role="self"`, `access_level="manage"`),
  executes `"keep"` vs `"revoke"` decisions across all profile `Connection` records, rotates the profile's
  256-bit DEK (`dek_version = old_dek_version + 1`), re-encrypts all kept `Credential` rows with updated AAD
  binding `f"{profile_id}|{conn.id}|{new_dek_version}"`, and logs an irreversible `AuditEventRecord`.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Literal, Optional, Tuple
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.connectors.lifecycle import revoke_connection
from carefold.connectors.oauth import resolve_oauth_kek
from carefold.db.models import (
    AuditEventRecord,
    Connection,
    ConsentGrant,
    Credential,
    Profile,
    ProfileAccess,
    ProfileConsent,
    ProfileKey,
    utc_now,
)
from carefold.vault import (
    compute_dek_wrapping_aad,
    decrypt_credential,
    encrypt,
    encrypt_credential,
    get_or_create_dek,
)

VALID_VIEWER_SECTIONS = (
    "vitals",
    "preventive",
    "appointments",
    "reminders",
    "connections",
    "school_forms",
    "notes",
    "documents",
)

CLINICAL_FALLBACK_SECTIONS = frozenset({
    "vitals",
    "preventive",
    "appointments",
    "reminders",
    "notes",
})

PAPERWORK_FALLBACK_SECTIONS = frozenset({
    "appointments",
    "reminders",
    "school_forms",
    "documents",
})


def encrypt_dek(
    kek: bytes,
    raw_dek: bytes,
    profile_id: str,
    dek_version: int,
) -> bytes:
    """Wraps a 32-byte profile DEK under the master KEK with contextual AAD binding."""
    aad = compute_dek_wrapping_aad(profile_id, dek_version)
    return encrypt(bytes(kek), bytes(raw_dek), aad)


async def update_viewer_sections(
    session: AsyncSession,
    profile_id: str,
    target_user_id: str,
    allowed_sections: List[str],
    grantor_user_id: Optional[str] = None,
) -> ProfileAccess:
    """Validates and updates `ProfileAccess.allowed_sections_json` for a viewer (`E12.3`)."""
    clean_profile_id = (profile_id or "").strip()
    clean_target_user_id = (target_user_id or "").strip()
    if not clean_profile_id or not clean_target_user_id:
        raise ValueError("profile_id and target_user_id are required.")

    if not isinstance(allowed_sections, (list, tuple)):
        raise ValueError("allowed_sections must be a list of section names.")

    normalized_sections: List[str] = []
    for sec in allowed_sections:
        clean_sec = str(sec or "").strip().lower()
        if clean_sec not in VALID_VIEWER_SECTIONS:
            raise ValueError(
                f"Invalid viewer section '{sec}'. Allowed sections: {list(VALID_VIEWER_SECTIONS)}"
            )
        if clean_sec not in normalized_sections:
            normalized_sections.append(clean_sec)

    now = utc_now()
    stmt = select(ProfileAccess).where(
        ProfileAccess.profile_id == clean_profile_id,
        ProfileAccess.user_id == clean_target_user_id,
    )
    res = await session.execute(stmt)
    grant = res.scalar_one_or_none()

    if grant is None:
        grant = ProfileAccess(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            user_id=clean_target_user_id,
            granted_by=grantor_user_id,
            role="viewer",
            access_level="view_clinical",
            allowed_sections_json=json.dumps(normalized_sections),
            granted_at=now,
        )
        session.add(grant)
    else:
        grant.allowed_sections_json = json.dumps(normalized_sections)
        if grantor_user_id:
            grant.granted_by = grantor_user_id
        grant.granted_at = now

    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "profile_id": clean_profile_id,
                "target_user_id": clean_target_user_id,
                "allowed_sections": normalized_sections,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit_record = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=grantor_user_id,
        principal="user",
        event="viewer_sections_updated",
        tool="update_viewer_sections",
        risk="admin",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"profile_access:{grant.id}",
        detail_redacted=json.dumps({
            "target_user_id": clean_target_user_id,
            "allowed_sections": normalized_sections,
        }),
    )
    session.add(audit_record)
    await session.commit()
    await session.refresh(grant)
    return grant


async def check_profile_section_access(
    session: AsyncSession,
    profile: Profile,
    user_id: str,
    section: str,
) -> bool:
    """Checks whether `user_id` is authorized to view `section` on `profile` (`E12.3`)."""
    clean_user_id = (user_id or "").strip()
    clean_section = (section or "").strip().lower()
    if not clean_user_id or clean_section not in VALID_VIEWER_SECTIONS:
        return False

    if profile.user_id is not None and profile.user_id == clean_user_id:
        return True

    stmt = select(ProfileAccess).where(
        ProfileAccess.profile_id == profile.id,
        ProfileAccess.user_id == clean_user_id,
    )
    res = await session.execute(stmt)
    grant = res.scalar_one_or_none()
    if grant is None:
        return False

    if grant.access_level == "manage":
        return True

    explicit_sections = grant.allowed_sections
    if explicit_sections is not None:
        return clean_section in explicit_sections

    if grant.access_level == "view_clinical":
        return clean_section in CLINICAL_FALLBACK_SECTIONS
    if grant.access_level == "view_paperwork":
        return clean_section in PAPERWORK_FALLBACK_SECTIONS

    return False


async def execute_teen_handover(
    session: AsyncSession,
    profile_id: str,
    teen_user_id: str,
    connection_decisions: Dict[str, Literal["keep", "revoke"]],
    actor_user_id: Optional[str] = None,
    kek: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Executes Teen Connection Handover (`E12.4`) with DEK rotation and credential re-encryption.

    1. Promotes `teen_user_id` to `ProfileAccess(role='self', access_level='manage')` and `profile.user_id = teen_user_id`.
    2. Loads the current profile DEK using `get_or_create_dek`.
    3. For each `Connection` on `profile_id`:
       - Decision `'revoke'` (or not `'keep'`): executes `revoke_connection(..., delete_imported_data=False)`.
       - Decision `'keep'`: decrypts existing `Credential` row(s) using the old DEK and old `(profile_id, conn.id, cred.dek_version)`.
    4. Rotates the Profile DEK: generates a fresh 256-bit DEK (`os.urandom(32)`), increments
       `ProfileKey.dek_version = old_dek_version + 1`, wraps the new DEK under the KEK (`encrypt_dek`),
       and re-encrypts all kept `Credential` rows under the new DEK with updated AAD binding
       `f"{profile_id}|{conn.id}|{new_dek_version}"` and `cred.dek_version = new_dek_version`, updating
       `conn.user_id = teen_user_id`.
    5. Logs an `AuditEventRecord` (`event='teen_handover'`, `tool='teen_handover'`, `risk='irreversible'`, `decision='allow'`).
    """
    clean_profile_id = (profile_id or "").strip()
    clean_teen_user_id = (teen_user_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required for teen handover.")
    if not clean_teen_user_id:
        raise ValueError("teen_user_id is required for teen handover.")

    prof_stmt = select(Profile).where(Profile.id == clean_profile_id)
    prof_res = await session.execute(prof_stmt)
    profile = prof_res.scalar_one_or_none()
    if profile is None:
        raise ValueError(f"Profile '{clean_profile_id}' not found.")

    decisions = dict(connection_decisions or {})
    for conn_id, dec in decisions.items():
        if dec not in ("keep", "revoke"):
            raise ValueError(
                f"Invalid connection decision '{dec}' for connection '{conn_id}'. Must be 'keep' or 'revoke'."
            )

    effective_kek = resolve_oauth_kek(kek)
    old_dek, old_dek_version = await get_or_create_dek(session, clean_profile_id, effective_kek)

    conn_stmt = (
        select(Connection)
        .where(
            Connection.profile_id == clean_profile_id,
            Connection.status != "deleted",
        )
        .order_by(Connection.created_at.asc())
    )
    conn_res = await session.execute(conn_stmt)
    connections = list(conn_res.scalars().all())

    kept_ids: List[str] = []
    revoked_ids: List[str] = []
    decrypted_credentials: List[Tuple[str, str, bytes]] = []  # (conn_id, cred_id, plaintext_bytes)

    # First pass: decrypt kept credentials under old_dek before any revoke commits
    to_revoke_ids: List[str] = []
    for conn in connections:
        decision = decisions.get(conn.id, "revoke")
        if decision == "keep":
            kept_ids.append(conn.id)
            cred_stmt = select(Credential).where(
                Credential.connection_id == conn.id,
                Credential.profile_id == clean_profile_id,
            )
            cred_res = await session.execute(cred_stmt)
            for cred in cred_res.scalars().all():
                plaintext_bytes = decrypt_credential(
                    old_dek,
                    cred.encrypted_blob,
                    clean_profile_id,
                    conn.id,
                    cred.dek_version,
                )
                decrypted_credentials.append((conn.id, cred.id, plaintext_bytes))
        else:
            to_revoke_ids.append(conn.id)

    # Execute 4-step revoke cascade on revoked connections
    for rev_conn_id in to_revoke_ids:
        await revoke_connection(
            session=session,
            profile_id=clean_profile_id,
            connection_id=rev_conn_id,
            actor_user_id=clean_teen_user_id,
            delete_imported_data=False,
        )
        revoked_ids.append(rev_conn_id)

    now = utc_now()

    # Promote teen_user_id on Profile and ProfileAccess
    prof_res_after = await session.execute(select(Profile).where(Profile.id == clean_profile_id))
    profile_row = prof_res_after.scalar_one()
    profile_row.user_id = clean_teen_user_id
    profile_row.role = "self"
    profile_row.relationship = "self"
    profile_row.updated_at = now

    access_stmt = select(ProfileAccess).where(
        ProfileAccess.profile_id == clean_profile_id,
        ProfileAccess.user_id == clean_teen_user_id,
    )
    access_res = await session.execute(access_stmt)
    teen_grant = access_res.scalar_one_or_none()
    if teen_grant is None:
        teen_grant = ProfileAccess(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            user_id=clean_teen_user_id,
            granted_by=actor_user_id or clean_teen_user_id,
            role="self",
            access_level="manage",
            allowed_sections_json=None,
            granted_at=now,
        )
        session.add(teen_grant)
    else:
        teen_grant.role = "self"
        teen_grant.access_level = "manage"
        teen_grant.allowed_sections_json = None
        teen_grant.granted_by = actor_user_id or clean_teen_user_id
        teen_grant.granted_at = now

    consent_stmt = select(ProfileConsent).where(ProfileConsent.profile_id == clean_profile_id)
    consent_res = await session.execute(consent_stmt)
    prof_consent = consent_res.scalar_one_or_none()
    if prof_consent is not None:
        prof_consent.teen_handover_notified = True
        prof_consent.updated_at = now

    # Rotate Profile DEK to new_dek_version = old_dek_version + 1
    new_dek_version = old_dek_version + 1
    new_dek = os.urandom(32)
    wrapped_new_dek = encrypt_dek(effective_kek, new_dek, clean_profile_id, new_dek_version)

    key_stmt = select(ProfileKey).where(ProfileKey.profile_id == clean_profile_id)
    key_res = await session.execute(key_stmt)
    key_record = key_res.scalar_one_or_none()
    if key_record is not None:
        key_record.encrypted_dek = wrapped_new_dek.hex()
        key_record.dek_version = new_dek_version
        key_record.updated_at = now
    else:
        key_record = ProfileKey(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            encrypted_dek=wrapped_new_dek.hex(),
            dek_version=new_dek_version,
            created_at=now,
            updated_at=now,
        )
        session.add(key_record)

    # Update kept connections and re-encrypt kept credentials under new_dek and new_dek_version
    for kept_conn_id in kept_ids:
        c_res = await session.execute(
            select(Connection).where(
                Connection.id == kept_conn_id,
                Connection.profile_id == clean_profile_id,
            )
        )
        c_row = c_res.scalar_one_or_none()
        if c_row is not None:
            c_row.user_id = clean_teen_user_id
            c_row.updated_at = now

        cg_res = await session.execute(
            select(ConsentGrant).where(
                ConsentGrant.profile_id == clean_profile_id,
                ConsentGrant.connection_id == kept_conn_id,
                ConsentGrant.status == "active",
            )
        )
        for cg in cg_res.scalars().all():
            cg.granted_by_user_id = clean_teen_user_id
            cg.updated_at = now

    for conn_id, cred_id, plaintext_bytes in decrypted_credentials:
        cr_res = await session.execute(select(Credential).where(Credential.id == cred_id))
        cr_row = cr_res.scalar_one_or_none()
        if cr_row is not None:
            new_ct = encrypt_credential(
                new_dek,
                plaintext_bytes,
                clean_profile_id,
                conn_id,
                new_dek_version,
            )
            cr_row.encrypted_blob = new_ct.hex()
            cr_row.dek_version = new_dek_version
            cr_row.aad_binding = f"{clean_profile_id}|{conn_id}|{new_dek_version}"
            cr_row.user_id = clean_teen_user_id
            cr_row.rotated_at = now
            cr_row.updated_at = now

    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "profile_id": clean_profile_id,
                "teen_user_id": clean_teen_user_id,
                "new_dek_version": new_dek_version,
                "kept_connections": kept_ids,
                "revoked_connections": revoked_ids,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit_record = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id or clean_teen_user_id,
        principal="user",
        event="teen_handover",
        tool="teen_handover",
        risk="irreversible",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"profile:{clean_profile_id}",
        detail_redacted=json.dumps({
            "profile_id": clean_profile_id,
            "new_steward_user_id": clean_teen_user_id,
            "old_dek_version": old_dek_version,
            "new_dek_version": new_dek_version,
            "kept_connections": kept_ids,
            "revoked_connections": revoked_ids,
        }),
    )
    session.add(audit_record)
    await session.commit()

    return {
        "profile_id": clean_profile_id,
        "new_steward_user_id": clean_teen_user_id,
        "new_dek_version": new_dek_version,
        "kept_connections": kept_ids,
        "revoked_connections": revoked_ids,
    }


__all__ = [
    "VALID_VIEWER_SECTIONS",
    "CLINICAL_FALLBACK_SECTIONS",
    "PAPERWORK_FALLBACK_SECTIONS",
    "encrypt_dek",
    "update_viewer_sections",
    "check_profile_section_access",
    "execute_teen_handover",
]
