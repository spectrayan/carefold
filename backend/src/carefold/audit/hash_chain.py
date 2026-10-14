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

"""Tamper-evident SHA-256 audit event hash chain per care profile (AU-78).

Links every `AuditEventRecord` row for a profile into an append-only
cryptographic hash chain anchored at `GENESIS_HASH = "GENESIS"`, enabling
deterministic detection of post-hoc row modification, deletion, or splicing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import AuditEventRecord

GENESIS_HASH: str = "GENESIS"


def compute_audit_entry_hash(
    prev_hash: str,
    event_id: str,
    profile_id: Optional[str],
    event: str,
    tool: Optional[str],
    risk: Optional[str],
    decision: Optional[str],
    payload_hash: Optional[str],
) -> str:
    """Computes a deterministic SHA-256 hex digest over canonical audit event fields.

    Canonical preimage format:
        `{prev_hash or GENESIS_HASH}|{event_id}|{profile_id or ''}|{event}|{tool or ''}|{risk or ''}|{decision or ''}|{payload_hash or ''}`
    """
    canonical = (
        f"{prev_hash or GENESIS_HASH}|"
        f"{event_id}|"
        f"{profile_id or ''}|"
        f"{event}|"
        f"{tool or ''}|"
        f"{risk or ''}|"
        f"{decision or ''}|"
        f"{payload_hash or ''}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def append_chained_audit_event(
    session: AsyncSession,
    *,
    profile_id: Optional[str],
    actor_user_id: Optional[str] = None,
    principal: str = "user",
    run_id: Optional[str] = None,
    event: str = "tool",
    tool: Optional[str] = None,
    risk: Optional[str] = None,
    decision: Optional[str] = "allow",
    payload_hash: Optional[str] = None,
    external_ref: Optional[str] = None,
    detail_redacted: Optional[str] = None,
    event_id: Optional[str] = None,
) -> AuditEventRecord:
    """Appends a cryptographically chained `AuditEventRecord` to the profile's hash chain."""
    clean_profile_id = str(profile_id).strip() if profile_id else None

    stmt = (
        select(AuditEventRecord)
        .where(
            AuditEventRecord.profile_id == clean_profile_id,
            AuditEventRecord.entry_hash.is_not(None),
        )
        .order_by(AuditEventRecord.ts.desc(), AuditEventRecord.id.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    latest = result.scalar_one_or_none()

    prev_hash = latest.entry_hash if (latest and latest.entry_hash) else GENESIS_HASH
    new_id = str(event_id).strip() if event_id else str(uuid.uuid4())

    now_utc = datetime.now(timezone.utc)
    if latest is not None and latest.ts is not None:
        latest_ts = latest.ts if latest.ts.tzinfo else latest.ts.replace(tzinfo=timezone.utc)
        if now_utc <= latest_ts:
            now_utc = latest_ts + timedelta(microseconds=1)

    entry_hash = compute_audit_entry_hash(
        prev_hash=prev_hash,
        event_id=new_id,
        profile_id=clean_profile_id,
        event=event,
        tool=tool,
        risk=risk,
        decision=decision,
        payload_hash=payload_hash,
    )

    record = AuditEventRecord(
        id=new_id,
        ts=now_utc,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id,
        principal=principal,
        run_id=run_id,
        event=event,
        tool=tool,
        risk=risk,
        decision=decision,
        payload_hash=payload_hash,
        external_ref=external_ref,
        detail_redacted=detail_redacted,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    session.add(record)
    await session.flush()
    return record


async def verify_profile_audit_chain(
    session: AsyncSession,
    profile_id: str,
) -> Dict[str, Any]:
    """Verifies the cryptographic integrity of a profile's `AuditEventRecord` hash chain.

    Returns:
        Dictionary with `profile_id`, `valid`, `checked_count`, `head_hash`,
        `broken_at_event_id`, and `reason`.
    """
    clean_profile_id = (profile_id or "").strip()
    stmt = (
        select(AuditEventRecord)
        .where(
            AuditEventRecord.profile_id == clean_profile_id,
            AuditEventRecord.entry_hash.is_not(None),
        )
        .order_by(AuditEventRecord.ts.asc(), AuditEventRecord.id.asc())
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    expected_prev = GENESIS_HASH
    for idx, row in enumerate(rows):
        if row.prev_hash != expected_prev:
            return {
                "profile_id": clean_profile_id,
                "valid": False,
                "checked_count": idx + 1,
                "head_hash": None,
                "broken_at_event_id": row.id,
                "reason": "prev_hash_mismatch",
            }

        recomputed_hash = compute_audit_entry_hash(
            prev_hash=row.prev_hash or GENESIS_HASH,
            event_id=row.id,
            profile_id=row.profile_id,
            event=row.event,
            tool=row.tool,
            risk=row.risk,
            decision=row.decision,
            payload_hash=row.payload_hash,
        )
        if row.entry_hash != recomputed_hash:
            return {
                "profile_id": clean_profile_id,
                "valid": False,
                "checked_count": idx + 1,
                "head_hash": None,
                "broken_at_event_id": row.id,
                "reason": "hash_mismatch",
            }

        expected_prev = row.entry_hash

    return {
        "profile_id": clean_profile_id,
        "valid": True,
        "checked_count": len(rows),
        "head_hash": rows[-1].entry_hash if rows else GENESIS_HASH,
        "broken_at_event_id": None,
        "reason": None,
    }
