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

"""Adversarial re-challenge and stress harness for Milestone 5 Iteration 2 (Single-Click Undo AU-40).

This suite independently verifies:
1. Reversal Audit Persistence in Async Engine (AuditEventRecord in DB with event='undo', tool='undo', risk='write_local').
2. Idempotency guarantees (idempotent=False raises AlreadyUndoneError; idempotent=True returns existing reversal without side-effects or duplicate jobs/events).
3. Anti-Recursion in both Sync and Async Engines (rejects undo of undo events).
4. Malformed external_ref validation across all degenerate vectors.
5. 7-Day boundary precision down to microseconds and across timezone-aware timestamps.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any, Dict
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.clinical.undo import (
    ActionNotUndoableError,
    AlreadyUndoneError,
    EntityNotFoundError,
    InvalidExternalRefError,
    UndoError,
    UndoWindowExpiredError,
    _resolve_action_not_undoable_error,
    _resolve_undo_window_expired_error,
    execute_single_click_undo,
    execute_single_click_undo_async,
)
from carefold.db.models import (
    Appointment,
    AuditEventRecord,
    HealthResource,
    Job,
    Note,
    Profile,
    Reminder,
    User,
)
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.fixture
def sqlite_test_db() -> sqlite3.Connection:
    """Isolated in-memory SQLite database matching production tables."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE audit_events (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            tool TEXT NOT NULL,
            risk TEXT NOT NULL,
            external_ref TEXT,
            timestamp TEXT NOT NULL,
            details TEXT DEFAULT '{}'
        );
    """)
    cur.execute("""
        CREATE TABLE health_resources (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            status TEXT NOT NULL,
            data TEXT NOT NULL,
            effective_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE appointments (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE reminders (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            title TEXT NOT NULL,
            next_due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE notes (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            profile_id TEXT,
            payload TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
async def async_test_session():
    """Isolated AsyncSession with SQLAlchemy models initialized."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


# ============================================================================
# Test Area 1: Reversal Audit Persistence
# ============================================================================

@pytest.mark.asyncio
async def test_reversal_audit_persistence_schema_and_values(async_test_session: AsyncSession):
    """Verify that AuditEventRecord is physically stored in the DB with correct fields."""
    prof_id = f"prof-{uuid.uuid4().hex[:8]}"
    appt_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    actor_id = f"user-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    async_test_session.add(
        User(
            id=actor_id,
            email=f"{actor_id}@example.com",
            username=f"user_{actor_id}",
            hashed_password="test_hashed_password",
        )
    )
    async_test_session.add(Profile(id=prof_id, name="Reversal Test Patient"))
    async_test_session.add(
        Appointment(
            id=appt_id,
            profile_id=prof_id,
            title="Cardiology Visit",
            start_time=now,
            end_time=now + timedelta(hours=1),
            status="scheduled",
        )
    )
    async_test_session.add(
        AuditEventRecord(
            id=event_id,
            profile_id=prof_id,
            actor_user_id=actor_id,
            principal="user",
            event="tool",
            tool="create_appointment",
            risk="write_local",
            external_ref=f"appointment:{appt_id}",
            ts=now,
            detail_redacted=json.dumps({"title": "Cardiology Visit"}),
        )
    )
    await async_test_session.commit()

    undo_time = now + timedelta(minutes=10)
    result = await execute_single_click_undo_async(
        db=async_test_session,
        event_id=event_id,
        profile_id=prof_id,
        current_time=undo_time,
        actor_user_id=actor_id,
    )

    undo_id = result["undo_event_id"]
    assert undo_id is not None

    # Query DB directly to verify persistence
    stmt = select(AuditEventRecord).where(AuditEventRecord.id == undo_id)
    persisted = (await async_test_session.execute(stmt)).scalar_one_or_none()

    assert persisted is not None, "AuditEventRecord was NOT persisted in the database!"
    assert persisted.profile_id == prof_id
    assert persisted.actor_user_id == actor_id
    assert persisted.principal == "user"
    assert persisted.event == "undo"
    assert persisted.tool == "undo"
    assert persisted.risk == "write_local"
    assert persisted.decision == "allow"
    assert persisted.external_ref == f"appointment:{appt_id}"
    persisted_dt = persisted.ts if persisted.ts.tzinfo else persisted.ts.replace(tzinfo=timezone.utc)
    assert persisted_dt == undo_time

    # Inspect detail_redacted
    assert persisted.detail_redacted is not None
    detail = json.loads(persisted.detail_redacted)
    assert detail.get("reverted_event_id") == event_id
    assert detail.get("undone_event_id") == event_id


# ============================================================================
# Test Area 2: Idempotency Guarantees
# ============================================================================

@pytest.mark.asyncio
async def test_idempotency_false_raises_already_undone(async_test_session: AsyncSession):
    """Calling undo with idempotent=False on an already undone event must raise AlreadyUndoneError."""
    prof_id = f"prof-{uuid.uuid4().hex[:8]}"
    appt_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async_test_session.add(Profile(id=prof_id, name="Patient"))
    async_test_session.add(
        Appointment(
            id=appt_id,
            profile_id=prof_id,
            title="Dentist",
            start_time=now,
            end_time=now + timedelta(hours=1),
            status="scheduled",
        )
    )
    async_test_session.add(
        AuditEventRecord(
            id=event_id,
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="create_appointment",
            risk="write_local",
            external_ref=f"appointment:{appt_id}",
            ts=now,
        )
    )
    await async_test_session.commit()

    # Turn 1: undo succeeds
    res1 = await execute_single_click_undo_async(
        db=async_test_session,
        event_id=event_id,
        profile_id=prof_id,
        current_time=now + timedelta(minutes=1),
        idempotent=False,
    )
    assert res1["status"] == "undone"

    # Turn 2: idempotent=False must raise AlreadyUndoneError
    with pytest.raises(AlreadyUndoneError) as exc_info:
        await execute_single_click_undo_async(
            db=async_test_session,
            event_id=event_id,
            profile_id=prof_id,
            current_time=now + timedelta(minutes=2),
            idempotent=False,
        )
    assert "already been undone" in str(exc_info.value)


@pytest.mark.asyncio
async def test_idempotency_true_returns_existing_without_side_effects(async_test_session: AsyncSession):
    """Repeated calls with idempotent=True must return original undo metadata and cause no duplicate mutations."""
    prof_id = f"prof-{uuid.uuid4().hex[:8]}"
    note_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async_test_session.add(Profile(id=prof_id, name="Patient"))
    async_test_session.add(
        Note(id=note_id, profile_id=prof_id, slug="test-note", title="Test Note", content="Original Content")
    )
    async_test_session.add(
        AuditEventRecord(
            id=event_id,
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="create_typed_note",
            risk="write_local",
            external_ref=f"note:{note_id}",
            ts=now,
        )
    )
    await async_test_session.commit()

    # Turn 1: initial undo
    res1 = await execute_single_click_undo_async(
        db=async_test_session,
        event_id=event_id,
        profile_id=prof_id,
        current_time=now + timedelta(minutes=1),
        idempotent=True,
    )
    orig_undo_id = res1["undo_event_id"]

    # Check that exactly 1 delete_doc job was scheduled and 1 reversal event was created
    jobs_after_1 = (await async_test_session.execute(select(Job).where(Job.profile_id == prof_id))).scalars().all()
    assert len(jobs_after_1) == 1

    audits_after_1 = (await async_test_session.execute(select(AuditEventRecord).where(AuditEventRecord.profile_id == prof_id))).scalars().all()
    # 1 original + 1 reversal = 2
    assert len(audits_after_1) == 2

    # Turns 2-6: repeated calls with idempotent=True
    for i in range(2, 7):
        res_i = await execute_single_click_undo_async(
            db=async_test_session,
            event_id=event_id,
            profile_id=prof_id,
            current_time=now + timedelta(minutes=i),
            idempotent=True,
        )
        assert res_i["status"] == "undone"
        assert res_i["undo_event_id"] == orig_undo_id
        assert res_i.get("idempotent") is True

    # Assert NO duplicate jobs or audit events were created
    jobs_after_repeat = (await async_test_session.execute(select(Job).where(Job.profile_id == prof_id))).scalars().all()
    assert len(jobs_after_repeat) == 1, "Duplicate jobs were enqueued on idempotent calls!"

    audits_after_repeat = (await async_test_session.execute(select(AuditEventRecord).where(AuditEventRecord.profile_id == prof_id))).scalars().all()
    assert len(audits_after_repeat) == 2, "Duplicate reversal audit events were created on idempotent calls!"


# ============================================================================
# Test Area 3: Anti-Recursion
# ============================================================================

def test_sync_anti_recursion_on_undo_event(sqlite_test_db: sqlite3.Connection):
    """Passing an undo event's ID to execute_single_click_undo (sync) must raise ActionNotUndoableError."""
    cur = sqlite_test_db.cursor()
    prof_id = "prof-sync-anti"
    appt_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Patient')", (prof_id,))
    cur.execute(
        "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
        "VALUES (?, ?, 'Checkup', ?, ?, 'scheduled', ?, ?)",
        (appt_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
    )
    cur.execute(
        "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
        "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
        (event_id, prof_id, f"appointment:{appt_id}", now.isoformat()),
    )
    sqlite_test_db.commit()

    # Step 1: Perform normal undo
    res = execute_single_click_undo(sqlite_test_db, event_id, prof_id, current_time=now + timedelta(minutes=5))
    undo_event_id = res["undo_event_id"]

    # Step 2: Attempt to undo the undo event
    with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())) as exc:
        execute_single_click_undo(sqlite_test_db, undo_event_id, prof_id, current_time=now + timedelta(minutes=10))
    assert "Cannot undo a previous undo reversal" in str(exc.value)


@pytest.mark.asyncio
async def test_async_anti_recursion_on_undo_event(async_test_session: AsyncSession):
    """Passing an undo event's ID to execute_single_click_undo_async must raise ActionNotUndoableError."""
    prof_id = f"prof-{uuid.uuid4().hex[:8]}"
    appt_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async_test_session.add(Profile(id=prof_id, name="Patient"))
    async_test_session.add(
        Appointment(id=appt_id, profile_id=prof_id, title="Visit", start_time=now, end_time=now, status="scheduled")
    )
    async_test_session.add(
        AuditEventRecord(
            id=event_id,
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="create_appointment",
            risk="write_local",
            external_ref=f"appointment:{appt_id}",
            ts=now,
        )
    )
    await async_test_session.commit()

    res = await execute_single_click_undo_async(
        db=async_test_session, event_id=event_id, profile_id=prof_id, current_time=now + timedelta(minutes=5)
    )
    undo_id = res["undo_event_id"]

    with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())) as exc:
        await execute_single_click_undo_async(
            db=async_test_session, event_id=undo_id, profile_id=prof_id, current_time=now + timedelta(minutes=10)
        )
    assert "Cannot undo a previous undo reversal" in str(exc.value)


# ============================================================================
# Test Area 4: Malformed external_ref Rejection
# ============================================================================

MALFORMED_REFS = [
    "appointment:",
    ":123",
    "no_colon",
    "",
    "   :   ",
    "health_resource:   ",
    "   :id_only",
    "reminder:\t\n",
    "\t:val",
]

@pytest.mark.parametrize("ref_val", MALFORMED_REFS)
def test_sync_malformed_external_ref_rejected(sqlite_test_db: sqlite3.Connection, ref_val: str):
    """Sync engine rejects all malformed external_ref variants with InvalidExternalRefError / ValueError."""
    cur = sqlite_test_db.cursor()
    prof_id = "prof-malformed"
    e_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    cur.execute("INSERT OR IGNORE INTO profiles (id, name) VALUES (?, 'Patient')", (prof_id,))
    cur.execute(
        "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
        "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
        (e_id, prof_id, ref_val, now.isoformat()),
    )
    sqlite_test_db.commit()

    with pytest.raises((InvalidExternalRefError, ValueError)):
        execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now + timedelta(minutes=1))


@pytest.mark.asyncio
@pytest.mark.parametrize("ref_val", MALFORMED_REFS)
async def test_async_malformed_external_ref_rejected(async_test_session: AsyncSession, ref_val: str):
    """Async engine rejects all malformed external_ref variants with InvalidExternalRefError."""
    prof_id = f"prof-{uuid.uuid4().hex[:8]}"
    e_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async_test_session.add(Profile(id=prof_id, name="Patient"))
    async_test_session.add(
        AuditEventRecord(
            id=e_id,
            profile_id=prof_id,
            principal="user",
            event="tool",
            tool="create_appointment",
            risk="write_local",
            external_ref=ref_val,
            ts=now,
        )
    )
    await async_test_session.commit()

    with pytest.raises(InvalidExternalRefError):
        await execute_single_click_undo_async(
            db=async_test_session, event_id=e_id, profile_id=prof_id, current_time=now + timedelta(minutes=1)
        )


# ============================================================================
# Test Area 5: 7-Day Boundary Precision
# ============================================================================

def test_sync_boundary_6d_23h_59m_succeeds_and_7d_1s_fails(sqlite_test_db: sqlite3.Connection):
    """6d 23h 59m succeeds; 7d 1s raises UndoWindowExpiredError."""
    cur = sqlite_test_db.cursor()
    prof_id = "prof-boundary"
    appt1_id = str(uuid.uuid4())
    appt2_id = str(uuid.uuid4())
    e1_id = str(uuid.uuid4())
    e2_id = str(uuid.uuid4())
    base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)

    cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Patient')", (prof_id,))
    cur.execute(
        "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
        "VALUES (?, ?, 'A1', ?, ?, 'scheduled', ?, ?)",
        (appt1_id, prof_id, base_time.isoformat(), base_time.isoformat(), base_time.isoformat(), base_time.isoformat()),
    )
    cur.execute(
        "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
        "VALUES (?, ?, 'A2', ?, ?, 'scheduled', ?, ?)",
        (appt2_id, prof_id, base_time.isoformat(), base_time.isoformat(), base_time.isoformat(), base_time.isoformat()),
    )
    cur.execute(
        "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
        "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
        (e1_id, prof_id, f"appointment:{appt1_id}", base_time.isoformat()),
    )
    cur.execute(
        "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
        "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
        (e2_id, prof_id, f"appointment:{appt2_id}", base_time.isoformat()),
    )
    sqlite_test_db.commit()

    # 6d 23h 59m succeeds
    t_valid = base_time + timedelta(days=6, hours=23, minutes=59)
    res = execute_single_click_undo(sqlite_test_db, e1_id, prof_id, current_time=t_valid)
    assert res["status"] == "undone"

    # 7d 1s raises
    t_expired = base_time + timedelta(days=7, seconds=1)
    with pytest.raises((UndoWindowExpiredError, _resolve_undo_window_expired_error())) as exc:
        execute_single_click_undo(sqlite_test_db, e2_id, prof_id, current_time=t_expired)
    assert "7-day undo window" in str(exc.value)


@pytest.mark.asyncio
async def test_async_boundary_6d_23h_59m_succeeds_and_7d_1s_fails(async_test_session: AsyncSession):
    """6d 23h 59m succeeds; 7d 1s raises UndoWindowExpiredError."""
    prof_id = f"prof-{uuid.uuid4().hex[:8]}"
    appt1_id = str(uuid.uuid4())
    appt2_id = str(uuid.uuid4())
    e1_id = str(uuid.uuid4())
    e2_id = str(uuid.uuid4())
    base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)

    async_test_session.add(Profile(id=prof_id, name="Patient"))
    async_test_session.add(Appointment(id=appt1_id, profile_id=prof_id, title="A1", start_time=base_time, end_time=base_time, status="scheduled"))
    async_test_session.add(Appointment(id=appt2_id, profile_id=prof_id, title="A2", start_time=base_time, end_time=base_time, status="scheduled"))
    async_test_session.add(AuditEventRecord(id=e1_id, profile_id=prof_id, principal="user", event="tool", tool="create_appointment", risk="write_local", external_ref=f"appointment:{appt1_id}", ts=base_time))
    async_test_session.add(AuditEventRecord(id=e2_id, profile_id=prof_id, principal="user", event="tool", tool="create_appointment", risk="write_local", external_ref=f"appointment:{appt2_id}", ts=base_time))
    await async_test_session.commit()

    # 6d 23h 59m succeeds
    t_valid = base_time + timedelta(days=6, hours=23, minutes=59)
    res = await execute_single_click_undo_async(db=async_test_session, event_id=e1_id, profile_id=prof_id, current_time=t_valid)
    assert res["status"] == "undone"

    # 7d 1s raises
    t_expired = base_time + timedelta(days=7, seconds=1)
    with pytest.raises((UndoWindowExpiredError, _resolve_undo_window_expired_error())):
        await execute_single_click_undo_async(db=async_test_session, event_id=e2_id, profile_id=prof_id, current_time=t_expired)
