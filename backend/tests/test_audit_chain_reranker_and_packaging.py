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

"""Unit tests for Batch 7 Stream 1: OAuth Relay (AU-70), Audit Hash Chain (AU-78),
Local Hybrid Search Reranker (AU-79), OS Service Packaging (AU-81), and Compliance Docs (AU-64, AU-65).
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.audit.hash_chain import (
    GENESIS_HASH,
    append_chained_audit_event,
    compute_audit_entry_hash,
    verify_profile_audit_chain,
)
from carefold.connectors.relay import (
    create_relay_ticket,
    resolve_stateless_relay_callback,
)
from carefold.db.base import Base
from carefold.db.models import AuditEventRecord, Profile, User
from carefold.packaging import (
    generate_linux_systemd_unit,
    generate_macos_launchd_plist,
    generate_windows_task_xml,
    list_os_service_descriptors,
)
from carefold.search.base import SearchResult
from carefold.search.reranker import LocalCrossReranker


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides an isolated in-memory SQLite async session for audit chain testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        user = User(
            id="user-stream1-test",
            email="steward@carefold.local",
            username="steward_stream1",
            hashed_password="argon2id$test",
        )
        profile = Profile(
            id="profile-stream1-test",
            user_id=user.id,
            name="Alex Care Profile",
            relationship="self",
            role="owner",
        )
        session.add_all([user, profile])
        await session.commit()
        yield session

    await engine.dispose()


def test_stateless_relay_valid_bounce_and_companion_scheme() -> None:
    """Verifies valid loopback and companion relay ticket creation and stateless resolution."""
    secret = b"0123456789abcdef0123456789abcdef"
    loopback_url = "http://127.0.0.1:8000/api/v1/oauth/callback"
    consumed: set[str] = set()

    ticket = create_relay_ticket(
        user_id="user-1",
        profile_id="prof-1",
        connection_id="conn-1",
        loopback_callback_url=loopback_url,
        secret_key=secret,
        ttl_seconds=120,
        now_ts=1_700_000_000,
    )
    resolved = resolve_stateless_relay_callback(
        relay_ticket=ticket,
        authorization_code="auth_code_xyz",
        secret_key=secret,
        consumed_nonces=consumed,
        now_ts=1_700_000_060,
    )

    assert resolved["stateless"] is True
    assert resolved["tokens_stored"] is False
    assert resolved["connection_id"] == "conn-1"
    assert resolved["profile_id"] == "prof-1"
    assert resolved["redirect_target"] == f"{loopback_url}?code=auth_code_xyz&state={ticket}"
    assert len(consumed) == 1

    # Verify carefold:// companion deep-link callback target is also permitted
    companion_ticket = create_relay_ticket(
        user_id="user-1",
        profile_id="prof-1",
        connection_id="conn-2",
        loopback_callback_url="carefold://oauth/callback",
        secret_key=secret,
        ttl_seconds=90,
        now_ts=1_700_000_000,
    )
    companion_resolved = resolve_stateless_relay_callback(
        relay_ticket=companion_ticket,
        authorization_code="code_ios_123",
        secret_key=secret,
        consumed_nonces=consumed,
        now_ts=1_700_000_030,
    )
    assert companion_resolved["redirect_target"].startswith("carefold://oauth/callback?code=code_ios_123&state=")


def test_stateless_relay_rejects_expired_tampered_replayed_and_non_loopback() -> None:
    """Verifies relay rejects expired tickets, tampered HMACs, replayed nonces, and external redirect URLs."""
    secret = b"super-secret-relay-hmac-key-32b!"
    loopback_url = "http://127.0.0.1:8000/api/v1/oauth/callback"

    # 1. Non-loopback redirect URL rejected at creation
    with pytest.raises(ValueError, match="127.0.0.1"):
        create_relay_ticket(
            user_id="user-1",
            profile_id="prof-1",
            connection_id="conn-1",
            loopback_callback_url="http://example.com/callback",
            secret_key=secret,
        )

    with pytest.raises(ValueError, match="Unsupported relay callback URL"):
        create_relay_ticket(
            user_id="user-1",
            profile_id="prof-1",
            connection_id="conn-1",
            loopback_callback_url="https://evil.example.org/steal",
            secret_key=secret,
        )

    # 2. TTL > 120s rejected
    with pytest.raises(ValueError, match="ttl_seconds"):
        create_relay_ticket(
            user_id="user-1",
            profile_id="prof-1",
            connection_id="conn-1",
            loopback_callback_url=loopback_url,
            secret_key=secret,
            ttl_seconds=300,
        )

    ticket = create_relay_ticket(
        user_id="user-1",
        profile_id="prof-1",
        connection_id="conn-1",
        loopback_callback_url=loopback_url,
        secret_key=secret,
        ttl_seconds=120,
        now_ts=1_700_000_000,
    )

    # 3. Expired ticket rejected
    with pytest.raises(ValueError, match="expired"):
        resolve_stateless_relay_callback(
            relay_ticket=ticket,
            authorization_code="code123",
            secret_key=secret,
            now_ts=1_700_000_121,
        )

    # 4. Tampered HMAC rejected
    tampered_ticket = ticket[:-4] + ("0000" if not ticket.endswith("0000") else "ffff")
    with pytest.raises(ValueError, match="HMAC signature"):
        resolve_stateless_relay_callback(
            relay_ticket=tampered_ticket,
            authorization_code="code123",
            secret_key=secret,
            now_ts=1_700_000_010,
        )

    # 5. Replay nonce rejected
    consumed_nonces: set[str] = set()
    first = resolve_stateless_relay_callback(
        relay_ticket=ticket,
        authorization_code="code123",
        secret_key=secret,
        consumed_nonces=consumed_nonces,
        now_ts=1_700_000_010,
    )
    assert first["stateless"] is True

    with pytest.raises(ValueError, match="Replay detected"):
        resolve_stateless_relay_callback(
            relay_ticket=ticket,
            authorization_code="code123",
            secret_key=secret,
            consumed_nonces=consumed_nonces,
            now_ts=1_700_000_015,
        )


@pytest.mark.asyncio
async def test_audit_hash_chain_append_and_tamper_detection(db_session: AsyncSession) -> None:
    """Appends 4 chained audit events, verifies chain integrity, and detects row tampering."""
    profile_id = "profile-stream1-test"

    ev1 = await append_chained_audit_event(
        db_session,
        profile_id=profile_id,
        actor_user_id="user-stream1-test",
        event="tool",
        tool="attach-read",
        risk="read",
        decision="allow",
        payload_hash="sha256_payload_1",
    )
    ev2 = await append_chained_audit_event(
        db_session,
        profile_id=profile_id,
        actor_user_id="user-stream1-test",
        event="tool",
        tool="workspace-note",
        risk="write_local",
        decision="allow",
        payload_hash="sha256_payload_2",
    )
    ev3 = await append_chained_audit_event(
        db_session,
        profile_id=profile_id,
        actor_user_id="user-stream1-test",
        event="tool",
        tool="gmail_send_message",
        risk="irreversible",
        decision="allow",
        payload_hash="sha256_payload_3",
    )
    ev4 = await append_chained_audit_event(
        db_session,
        profile_id=profile_id,
        actor_user_id="user-stream1-test",
        event="run",
        tool=None,
        risk="clinical_assist",
        decision="allow",
        payload_hash="sha256_payload_4",
    )
    await db_session.commit()

    assert ev1.prev_hash == GENESIS_HASH
    assert ev2.prev_hash == ev1.entry_hash
    assert ev3.prev_hash == ev2.entry_hash
    assert ev4.prev_hash == ev3.entry_hash

    verification = await verify_profile_audit_chain(db_session, profile_id)
    assert verification["valid"] is True
    assert verification["checked_count"] == 4
    assert verification["head_hash"] == ev4.entry_hash
    assert verification["broken_at_event_id"] is None
    assert verification["reason"] is None

    # Tamper with event #2's payload_hash directly in SQLite
    await db_session.execute(
        update(AuditEventRecord)
        .where(AuditEventRecord.id == ev2.id)
        .values(payload_hash="tampered_payload_hash_999")
    )
    await db_session.commit()

    broken_check = await verify_profile_audit_chain(db_session, profile_id)
    assert broken_check["valid"] is False
    assert broken_check["checked_count"] == 2
    assert broken_check["head_hash"] is None
    assert broken_check["broken_at_event_id"] == ev2.id
    assert broken_check["reason"] == "hash_mismatch"

    # Restore payload_hash and tamper with event #3's prev_hash to verify prev_hash_mismatch
    expected_ev2_hash = compute_audit_entry_hash(
        prev_hash=ev1.entry_hash or GENESIS_HASH,
        event_id=ev2.id,
        profile_id=profile_id,
        event="tool",
        tool="workspace-note",
        risk="write_local",
        decision="allow",
        payload_hash="sha256_payload_2",
    )
    await db_session.execute(
        update(AuditEventRecord)
        .where(AuditEventRecord.id == ev2.id)
        .values(payload_hash="sha256_payload_2", entry_hash=expected_ev2_hash)
    )
    await db_session.execute(
        update(AuditEventRecord)
        .where(AuditEventRecord.id == ev3.id)
        .values(prev_hash="forged_prev_hash")
    )
    await db_session.commit()

    prev_broken_check = await verify_profile_audit_chain(db_session, profile_id)
    assert prev_broken_check["valid"] is False
    assert prev_broken_check["checked_count"] == 3
    assert prev_broken_check["broken_at_event_id"] == ev3.id
    assert prev_broken_check["reason"] == "prev_hash_mismatch"


def test_local_cross_reranker_boosts_loinc_code_and_clinical_section() -> None:
    """Verifies LocalCrossReranker promotes exact LOINC code (85354-9) and section match over generic hits."""
    reranker = LocalCrossReranker()
    candidates = [
        SearchResult(
            document_id="doc-generic",
            chunk_id="doc-generic#c0",
            content="General clinic welcome handout discussing routine wellness checkups and office hours.",
            score=0.72,
            lexical_score=0.70,
            semantic_score=0.74,
            metadata={"section": "Introduction"},
            profile_id="prof-1",
        ),
        SearchResult(
            document_id="doc-vitals-loinc",
            chunk_id="doc-vitals-loinc#item_one",
            content="Vital Signs: Blood pressure panel (LOINC 85354-9) recorded at 128/82 mmHg during Cardiology Assessment.",
            score=0.55,
            lexical_score=0.60,
            semantic_score=0.50,
            metadata={"section": "Vital Signs"},
            profile_id="prof-1",
        ),
    ]

    reranked = reranker.rerank(
        query="blood pressure panel LOINC 85354-9 vital signs",
        results=candidates,
        top_k=2,
    )

    assert len(reranked) == 2
    assert reranked[0].document_id == "doc-vitals-loinc"
    assert reranked[0].metadata["reranked"] is True
    assert reranked[0].metadata["clinical_code_match"] is True
    assert reranked[0].score > reranked[1].score
    assert reranked[1].metadata["reranked"] is True
    assert reranked[1].metadata["clinical_code_match"] is False


def test_os_service_packaging_descriptors_and_compliance_docs() -> None:
    """Verifies macOS launchd, Linux systemd, and Windows Task Scheduler descriptors and compliance docs."""
    descriptors = list_os_service_descriptors(port=8000)
    assert len(descriptors) == 3

    platforms = {d["platform"]: d for d in descriptors}
    assert set(platforms.keys()) == {"macos_launchd", "linux_systemd", "windows_task_scheduler"}

    macos = generate_macos_launchd_plist(port=8000)
    assert macos["filename"] == "com.spectrayan.carefold.plist"
    assert "127.0.0.1" in macos["content"]
    assert "<key>KeepAlive</key>" in macos["content"]
    assert "launchctl load -w" in macos["install_command"]

    linux = generate_linux_systemd_unit(port=8000)
    assert linux["filename"] == "carefold.service"
    assert "127.0.0.1" in linux["content"]
    assert "Restart=on-failure" in linux["content"]
    assert "systemctl --user enable --now" in linux["install_command"]

    windows = generate_windows_task_xml(port=8000)
    assert windows["filename"] == "carefold-task.xml"
    assert "127.0.0.1" in windows["content"]
    assert "<RestartOnFailure>" in windows["content"]
    assert "schtasks /Create" in windows["install_command"]

    repo_root = Path(__file__).resolve().parents[2]
    assert (repo_root / "docs" / "adr" / "0008-oauth-relay-and-stateless-callback.md").is_file()
    assert (repo_root / "docs" / "compliance" / "google-verification-and-casa.md").is_file()
    assert (repo_root / "docs" / "compliance" / "legal-and-regulatory-pack.md").is_file()
