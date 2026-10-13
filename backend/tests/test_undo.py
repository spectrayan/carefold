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

"""Unit and integration test suite for Single-Click Undo Engine (AU-40)."""

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
)
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.fixture
def sqlite_test_db() -> sqlite3.Connection:
    """Provides an in-memory SQLite database matching the production tables for synchronous tests."""
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
    """Provides an isolated AsyncSession with all SQLAlchemy models initialized."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


# ============================================================================
# Section 1: Synchronous SQLite Undo Tests (contracts_batch_3 compatible)
# ============================================================================

class TestSynchronousSQLiteUndo:
    """Verifies execute_single_click_undo boundaries, risk gates, and entity rollbacks."""

    def test_undo_window_immediate_success(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
            "VALUES (?, ?, 'Checkup', ?, ?, 'scheduled', ?, ?)",
            (appt_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (e_id, prof_id, f"appointment:{appt_id}", now.isoformat()),
        )
        sqlite_test_db.commit()

        res = execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now + timedelta(minutes=1))
        assert res["status"] == "undone"
        assert res["event_id"] == e_id
        assert res["external_ref"] == f"appointment:{appt_id}"

        cur.execute("SELECT status FROM appointments WHERE id = ?", (appt_id,))
        assert cur.fetchone()[0] == "cancelled"

    def test_undo_window_6d_23h_success(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        event_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        eval_time = event_time + timedelta(days=6, hours=23, minutes=59)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
            "VALUES (?, ?, 'Checkup', ?, ?, 'scheduled', ?, ?)",
            (appt_id, prof_id, event_time.isoformat(), event_time.isoformat(), event_time.isoformat(), event_time.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (e_id, prof_id, f"appointment:{appt_id}", event_time.isoformat()),
        )
        sqlite_test_db.commit()

        res = execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=eval_time)
        assert res["status"] == "undone"

    def test_undo_window_7d_1s_rejected(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        event_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        eval_time = event_time + timedelta(days=7, seconds=1)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
            "VALUES (?, ?, 'Checkup', ?, ?, 'scheduled', ?, ?)",
            (appt_id, prof_id, event_time.isoformat(), event_time.isoformat(), event_time.isoformat(), event_time.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (e_id, prof_id, f"appointment:{appt_id}", event_time.isoformat()),
        )
        sqlite_test_db.commit()

        with pytest.raises((UndoWindowExpiredError, _resolve_undo_window_expired_error())) as exc_info:
            execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=eval_time)
        assert "7-day undo window" in str(exc_info.value)

    def test_undo_rejects_read_risk(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'list', 'list_appointments', 'read', 'appointment:none', ?)",
            (e_id, prof_id, now.isoformat()),
        )
        sqlite_test_db.commit()

        with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())) as exc_info:
            execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now)
        assert "Only write_local actions are eligible" in str(exc_info.value)

    def test_undo_rejects_write_network_risk(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'send', 'portal_msg', 'write_network', 'portal:1', ?)",
            (e_id, prof_id, now.isoformat()),
        )
        sqlite_test_db.commit()

        with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())) as exc_info:
            execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now)
        assert "Only write_local actions are eligible" in str(exc_info.value)

    def test_undo_health_resource_tombstone(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        hr_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO health_resources (id, profile_id, resource_type, status, data, effective_at, created_at, updated_at) "
            "VALUES (?, ?, 'observation', 'active', '{}', ?, ?, ?)",
            (hr_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'record_vitals', 'write_local', ?, ?)",
            (e_id, prof_id, f"health_resource:{hr_id}", now.isoformat()),
        )
        sqlite_test_db.commit()

        execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now)

        cur.execute("SELECT status FROM health_resources WHERE id = ?", (hr_id,))
        assert cur.fetchone()[0] == "tombstone"

    def test_undo_reminder_cancelled(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        rem_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO reminders (id, profile_id, title, next_due_at, status, created_at, updated_at) "
            "VALUES (?, ?, 'Meds', ?, 'pending', ?, ?)",
            (rem_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_reminder', 'write_local', ?, ?)",
            (e_id, prof_id, f"reminder:{rem_id}", now.isoformat()),
        )
        sqlite_test_db.commit()

        execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now)

        cur.execute("SELECT status FROM reminders WHERE id = ?", (rem_id,))
        assert cur.fetchone()[0] == "cancelled"

    def test_undo_note_soft_delete_and_job(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        note_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO notes (id, profile_id, title, content, is_deleted, created_at, updated_at) "
            "VALUES (?, ?, 'Consult Note', 'Text', 0, ?, ?)",
            (note_id, prof_id, now.isoformat(), now.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_typed_note', 'write_local', ?, ?)",
            (e_id, prof_id, f"note:{note_id}", now.isoformat()),
        )
        sqlite_test_db.commit()

        execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now)

        cur.execute("SELECT is_deleted FROM notes WHERE id = ?", (note_id,))
        assert cur.fetchone()[0] == 1

        cur.execute("SELECT kind, payload FROM jobs WHERE profile_id = ? AND kind = 'delete_doc'", (prof_id,))
        job = cur.fetchone()
        assert job is not None
        assert note_id in job[1]

    def test_undo_records_reversal_audit_event(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
            "VALUES (?, ?, 'Checkup', ?, ?, 'scheduled', ?, ?)",
            (appt_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (e_id, prof_id, f"appointment:{appt_id}", now.isoformat()),
        )
        sqlite_test_db.commit()

        execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now)

        cur.execute("SELECT action, tool, external_ref FROM audit_events WHERE action = 'undo'")
        rev = cur.fetchone()
        assert rev is not None
        assert rev[0] == "undo"
        assert rev[1] == "undo"
        assert rev[2] == f"appointment:{appt_id}"

    def test_undo_idempotent_double_undo(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        prof_id = "prof-1"
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Test Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
            "VALUES (?, ?, 'Checkup', ?, ?, 'scheduled', ?, ?)",
            (appt_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (e_id, prof_id, f"appointment:{appt_id}", now.isoformat()),
        )
        sqlite_test_db.commit()

        execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now)
        # Second call does not crash, status remains cancelled
        execute_single_click_undo(sqlite_test_db, e_id, prof_id, current_time=now + timedelta(seconds=5))

        cur.execute("SELECT status FROM appointments WHERE id = ?", (appt_id,))
        assert cur.fetchone()[0] == "cancelled"

    def test_undo_profile_isolation_rejected(self, sqlite_test_db: sqlite3.Connection):
        cur = sqlite_test_db.cursor()
        p1 = "prof-1"
        p2 = "prof-2"
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Patient 1')", (p1,))
        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Patient 2')", (p2,))
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'record_vitals', 'write_local', 'health_resource:hr-1', ?)",
            (e_id, p1, now.isoformat()),
        )
        sqlite_test_db.commit()

        with pytest.raises(ValueError) as exc_info:
            execute_single_click_undo(sqlite_test_db, e_id, profile_id=p2, current_time=now)
        assert "not found for profile" in str(exc_info.value)


# ============================================================================
# Section 2: Asynchronous SQLAlchemy Session Undo Tests
# ============================================================================

@pytest.mark.asyncio
class TestAsynchronousSessionUndo:
    """Verifies execute_single_click_undo_async domain engine with SQLAlchemy models."""

    async def test_async_undo_appointment_cancelled(self, async_test_session: AsyncSession):
        now = datetime.now(timezone.utc)
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())

        async_test_session.add(Profile(id=prof_id, name="Test Patient"))
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
                id=e_id,
                profile_id=prof_id,
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

        res = await execute_single_click_undo_async(
            db=async_test_session,
            event_id=e_id,
            profile_id=prof_id,
            current_time=now + timedelta(minutes=5),
        )
        assert res["status"] == "undone"

        appt = (await async_test_session.execute(select(Appointment).where(Appointment.id == appt_id))).scalar_one()
        assert appt.status == "cancelled"

    async def test_async_undo_note_soft_deleted_and_job_queued(self, async_test_session: AsyncSession):
        now = datetime.now(timezone.utc)
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        note_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())

        async_test_session.add(Profile(id=prof_id, name="Test Patient"))
        async_test_session.add(
            Note(
                id=note_id,
                profile_id=prof_id,
                slug="visit-summary",
                title="Visit Summary",
                content="Notes",
            )
        )
        async_test_session.add(
            AuditEventRecord(
                id=e_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="create_typed_note",
                risk="write_local",
                external_ref=f"note:{note_id}",
                ts=now,
                detail_redacted=json.dumps({"title": "Visit Summary"}),
            )
        )
        await async_test_session.commit()

        await execute_single_click_undo_async(
            db=async_test_session,
            event_id=e_id,
            profile_id=prof_id,
            current_time=now + timedelta(minutes=5),
        )

        note_check = (await async_test_session.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()
        assert note_check is None


        jobs = (await async_test_session.execute(select(Job).where(Job.profile_id == prof_id, Job.kind == "delete_doc"))).scalars().all()
        assert len(jobs) == 1
        assert note_id in jobs[0].payload

    async def test_async_undo_expired_window_raises(self, async_test_session: AsyncSession):
        now = datetime.now(timezone.utc)
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        e_id = str(uuid.uuid4())
        ts = now - timedelta(days=7, seconds=2)

        async_test_session.add(Profile(id=prof_id, name="Test Patient"))
        async_test_session.add(
            AuditEventRecord(
                id=e_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="record_vitals",
                risk="write_local",
                external_ref="health_resource:hr-1",
                ts=ts,
                detail_redacted="{}",
            )
        )
        await async_test_session.commit()

        with pytest.raises((UndoWindowExpiredError, _resolve_undo_window_expired_error())):
            await execute_single_click_undo_async(
                db=async_test_session,
                event_id=e_id,
                profile_id=prof_id,
                current_time=now,
            )

    async def test_async_undo_non_write_local_raises(self, async_test_session: AsyncSession):
        now = datetime.now(timezone.utc)
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        e_id = str(uuid.uuid4())

        async_test_session.add(Profile(id=prof_id, name="Test Patient"))
        async_test_session.add(
            AuditEventRecord(
                id=e_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="list_reminders",
                risk="read",
                external_ref="reminder:none",
                ts=now,
                detail_redacted="{}",
            )
        )
        await async_test_session.commit()

        with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())):
            await execute_single_click_undo_async(
                db=async_test_session,
                event_id=e_id,
                profile_id=prof_id,
                current_time=now,
            )
