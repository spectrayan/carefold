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

"""Empirical adversarial stress test suite for Milestone 5 (AU-40 Single-Click Undo Engine).

Dedicated test suite probing:
1. 7-Day Boundary Precision (6d 23h 59m, 7d 0s boundary, 7d 1s rejection, microsecond boundary, timezones).
2. Risk Tier Invariants (write_local allowed; read, write_network, admin, and invalid rejected).
3. Anti-Recursion & Idempotency (prevent undoing undo events, idempotent vs non-idempotent re-execution).
4. Entity Rollback State Integrity (health_resource tombstone, appointment cancelled, reminder cancelled,
   note deletion and delete_doc search indexing job enqueue, reversal audit trail, cross-profile isolation).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any, Dict
import uuid
from zoneinfo import ZoneInfo

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
)
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.fixture
def sqlite_stress_db() -> sqlite3.Connection:
    """Provides an isolated in-memory SQLite database matching production tables."""
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
async def async_stress_session():
    """Provides an isolated AsyncSession with SQLAlchemy models initialized."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


# ============================================================================
# Dimension 1: 7-Day Boundary Precision Stress Tests
# ============================================================================

class TestUndo7DayBoundaryPrecision:
    """Stress tests boundary precision of the 7-day undo eligibility window."""

    def test_sync_boundary_6d_23h_59m_must_succeed(self, sqlite_stress_db: sqlite3.Connection):
        cur = sqlite_stress_db.cursor()
        prof_id = "prof-test"
        appt_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        current_time = base_time + timedelta(days=6, hours=23, minutes=59)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
            "VALUES (?, ?, 'Cardiology', ?, ?, 'scheduled', ?, ?)",
            (appt_id, prof_id, base_time.isoformat(), base_time.isoformat(), base_time.isoformat(), base_time.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (event_id, prof_id, f"appointment:{appt_id}", base_time.isoformat()),
        )
        sqlite_stress_db.commit()

        res = execute_single_click_undo(sqlite_stress_db, event_id, prof_id, current_time=current_time)
        assert res["status"] == "undone"
        cur.execute("SELECT status FROM appointments WHERE id = ?", (appt_id,))
        assert cur.fetchone()[0] == "cancelled"

    @pytest.mark.asyncio
    async def test_async_boundary_6d_23h_59m_must_succeed(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        appt_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        current_time = base_time + timedelta(days=6, hours=23, minutes=59)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            Appointment(
                id=appt_id,
                profile_id=prof_id,
                title="Cardiology",
                start_time=base_time,
                end_time=base_time + timedelta(hours=1),
                status="scheduled",
            )
        )
        async_stress_session.add(
            AuditEventRecord(
                id=event_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="create_appointment",
                risk="write_local",
                external_ref=f"appointment:{appt_id}",
                ts=base_time,
            )
        )
        await async_stress_session.commit()

        res = await execute_single_click_undo_async(
            db=async_stress_session,
            event_id=event_id,
            profile_id=prof_id,
            current_time=current_time,
        )
        assert res["status"] == "undone"

        appt = (await async_stress_session.execute(select(Appointment).where(Appointment.id == appt_id))).scalar_one()
        assert appt.status == "cancelled"

    def test_sync_boundary_exact_7d_0s_boundary_check(self, sqlite_stress_db: sqlite3.Connection):
        cur = sqlite_stress_db.cursor()
        prof_id = "prof-test"
        appt_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        exact_7d_time = base_time + timedelta(days=7, seconds=0)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
            "VALUES (?, ?, 'Cardiology', ?, ?, 'scheduled', ?, ?)",
            (appt_id, prof_id, base_time.isoformat(), base_time.isoformat(), base_time.isoformat(), base_time.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (event_id, prof_id, f"appointment:{appt_id}", base_time.isoformat()),
        )
        sqlite_stress_db.commit()

        # Exact 7 days 0 seconds: delta > 7 days is False, so boundary condition succeeds
        res = execute_single_click_undo(sqlite_stress_db, event_id, prof_id, current_time=exact_7d_time)
        assert res["status"] == "undone"

    @pytest.mark.asyncio
    async def test_async_boundary_exact_7d_0s_boundary_check(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        appt_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        exact_7d_time = base_time + timedelta(days=7, seconds=0)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            Appointment(
                id=appt_id,
                profile_id=prof_id,
                title="Cardiology",
                start_time=base_time,
                end_time=base_time + timedelta(hours=1),
                status="scheduled",
            )
        )
        async_stress_session.add(
            AuditEventRecord(
                id=event_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="create_appointment",
                risk="write_local",
                external_ref=f"appointment:{appt_id}",
                ts=base_time,
            )
        )
        await async_stress_session.commit()

        res = await execute_single_click_undo_async(
            db=async_stress_session,
            event_id=event_id,
            profile_id=prof_id,
            current_time=exact_7d_time,
        )
        assert res["status"] == "undone"

    def test_sync_boundary_exact_7d_1s_must_be_rejected(self, sqlite_stress_db: sqlite3.Connection):
        cur = sqlite_stress_db.cursor()
        prof_id = "prof-test"
        appt_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        expired_time = base_time + timedelta(days=7, seconds=1)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) "
            "VALUES (?, ?, 'Cardiology', ?, ?, 'scheduled', ?, ?)",
            (appt_id, prof_id, base_time.isoformat(), base_time.isoformat(), base_time.isoformat(), base_time.isoformat()),
        )
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (event_id, prof_id, f"appointment:{appt_id}", base_time.isoformat()),
        )
        sqlite_stress_db.commit()

        with pytest.raises((UndoWindowExpiredError, _resolve_undo_window_expired_error())) as exc_info:
            execute_single_click_undo(sqlite_stress_db, event_id, prof_id, current_time=expired_time)
        assert "7-day undo window" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_boundary_exact_7d_1s_must_be_rejected(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        appt_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        expired_time = base_time + timedelta(days=7, seconds=1)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            Appointment(
                id=appt_id,
                profile_id=prof_id,
                title="Cardiology",
                start_time=base_time,
                end_time=base_time + timedelta(hours=1),
                status="scheduled",
            )
        )
        async_stress_session.add(
            AuditEventRecord(
                id=event_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="create_appointment",
                risk="write_local",
                external_ref=f"appointment:{appt_id}",
                ts=base_time,
            )
        )
        await async_stress_session.commit()

        with pytest.raises((UndoWindowExpiredError, _resolve_undo_window_expired_error())):
            await execute_single_click_undo_async(
                db=async_stress_session,
                event_id=event_id,
                profile_id=prof_id,
                current_time=expired_time,
            )

    @pytest.mark.asyncio
    async def test_subsecond_microsecond_boundary_precision(self, async_stress_session: AsyncSession):
        """Tests microsecond precision: +7d -1us succeeds; +7d +1us is rejected."""
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        base_time = datetime(2026, 10, 1, 12, 0, 0, 0, tzinfo=timezone.utc)
        async_stress_session.add(Profile(id=prof_id, name="Patient"))

        # Event 1: within 7 days by 1 microsecond
        e1_id = str(uuid.uuid4())
        a1_id = str(uuid.uuid4())
        async_stress_session.add(
            Appointment(id=a1_id, profile_id=prof_id, title="A1", start_time=base_time, end_time=base_time, status="scheduled")
        )
        async_stress_session.add(
            AuditEventRecord(id=e1_id, profile_id=prof_id, principal="user", event="tool", tool="create_appointment", risk="write_local", external_ref=f"appointment:{a1_id}", ts=base_time)
        )

        # Event 2: expired by 1 microsecond
        e2_id = str(uuid.uuid4())
        a2_id = str(uuid.uuid4())
        async_stress_session.add(
            Appointment(id=a2_id, profile_id=prof_id, title="A2", start_time=base_time, end_time=base_time, status="scheduled")
        )
        async_stress_session.add(
            AuditEventRecord(id=e2_id, profile_id=prof_id, principal="user", event="tool", tool="create_appointment", risk="write_local", external_ref=f"appointment:{a2_id}", ts=base_time)
        )
        await async_stress_session.commit()

        time_inside = base_time + timedelta(days=7) - timedelta(microseconds=1)
        res_inside = await execute_single_click_undo_async(
            db=async_stress_session, event_id=e1_id, profile_id=prof_id, current_time=time_inside
        )
        assert res_inside["status"] == "undone"

        time_expired = base_time + timedelta(days=7, microseconds=1)
        with pytest.raises((UndoWindowExpiredError, _resolve_undo_window_expired_error())):
            await execute_single_click_undo_async(
                db=async_stress_session, event_id=e2_id, profile_id=prof_id, current_time=time_expired
            )


# ============================================================================
# Dimension 2: Risk Tier Invariant Stress Tests
# ============================================================================

class TestUndoRiskTierInvariants:
    """Stress tests strict enforcement that only risk='write_local' is undoable."""

    @pytest.mark.parametrize("disallowed_risk", ["read", "write_network", "admin", "unknown", "", "sudo"])
    def test_sync_rejects_non_write_local_risks(self, sqlite_stress_db: sqlite3.Connection, disallowed_risk: str):
        cur = sqlite_stress_db.cursor()
        prof_id = "prof-test"
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT OR IGNORE INTO profiles (id, name) VALUES (?, 'Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'op', 'test_tool', ?, 'appointment:123', ?)",
            (e_id, prof_id, disallowed_risk, now.isoformat()),
        )
        sqlite_stress_db.commit()

        with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())) as exc:
            execute_single_click_undo(sqlite_stress_db, e_id, prof_id, current_time=now)
        assert "Only write_local actions are eligible" in str(exc.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("disallowed_risk", ["read", "write_network", "admin", "unknown", "", "sudo"])
    async def test_async_rejects_non_write_local_risks(self, async_stress_session: AsyncSession, disallowed_risk: str):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            AuditEventRecord(
                id=e_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="disallowed_op",
                risk=disallowed_risk,
                external_ref="appointment:123",
                ts=now,
            )
        )
        await async_stress_session.commit()

        with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())) as exc:
            await execute_single_click_undo_async(
                db=async_stress_session,
                event_id=e_id,
                profile_id=prof_id,
                current_time=now,
            )
        assert "Only write_local actions are eligible" in str(exc.value)


# ============================================================================
# Dimension 3: Anti-Recursion & Idempotency Stress Tests
# ============================================================================

class TestUndoAntiRecursionAndIdempotency:
    """Stress tests prevention of undoing undo events, and repeated execution handling."""

    @pytest.mark.asyncio
    async def test_async_anti_recursion_cannot_undo_undo_event(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        undo_event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            AuditEventRecord(
                id=undo_event_id,
                profile_id=prof_id,
                principal="user",
                event="undo",
                tool="undo",
                risk="write_local",
                external_ref="appointment:appt-1",
                ts=now,
                detail_redacted=json.dumps({"reverted_event_id": "orig-event-1"}),
            )
        )
        await async_stress_session.commit()

        with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())) as exc:
            await execute_single_click_undo_async(
                db=async_stress_session,
                event_id=undo_event_id,
                profile_id=prof_id,
                current_time=now + timedelta(minutes=1),
            )
        assert "Cannot undo a previous undo reversal" in str(exc.value)

    def test_sync_anti_recursion_attempt_fails(self, sqlite_stress_db: sqlite3.Connection):
        """EXPOSES DEFECT: sync execute_single_click_undo lacks check for action='undo' / tool='undo'."""
        cur = sqlite_stress_db.cursor()
        prof_id = "prof-test"
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT INTO profiles (id, name) VALUES (?, 'Patient')", (prof_id,))
        cur.execute("INSERT INTO appointments (id, profile_id, title, start_time, end_time, status, created_at, updated_at) VALUES (?, ?, 'A', ?, ?, 'scheduled', ?, ?)", (appt_id, prof_id, now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()))
        cur.execute("INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)", (e_id, prof_id, f"appointment:{appt_id}", now.isoformat()))
        sqlite_stress_db.commit()

        res1 = execute_single_click_undo(sqlite_stress_db, e_id, prof_id, current_time=now)
        undo_event_id = res1["undo_event_id"]

        # Attempting to undo the undo event MUST raise ActionNotUndoableError per Requirement 3
        with pytest.raises((ActionNotUndoableError, _resolve_action_not_undoable_error())):
            execute_single_click_undo(sqlite_stress_db, undo_event_id, prof_id, current_time=now)

    @pytest.mark.asyncio
    async def test_async_idempotent_false_raises_already_undone_error(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            Appointment(id=appt_id, profile_id=prof_id, title="Cardiology", start_time=now, end_time=now, status="scheduled")
        )
        async_stress_session.add(
            AuditEventRecord(
                id=e_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="create_appointment",
                risk="write_local",
                external_ref=f"appointment:{appt_id}",
                ts=now,
            )
        )
        await async_stress_session.commit()

        # First undo succeeds
        res1 = await execute_single_click_undo_async(
            db=async_stress_session,
            event_id=e_id,
            profile_id=prof_id,
            current_time=now + timedelta(minutes=1),
            idempotent=False,
        )
        assert res1["status"] == "undone"

        # Second undo with idempotent=False must raise AlreadyUndoneError
        with pytest.raises(AlreadyUndoneError):
            await execute_single_click_undo_async(
                db=async_stress_session,
                event_id=e_id,
                profile_id=prof_id,
                current_time=now + timedelta(minutes=2),
                idempotent=False,
            )

    @pytest.mark.asyncio
    async def test_async_idempotent_true_returns_existing_reversal(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        appt_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            Appointment(id=appt_id, profile_id=prof_id, title="Cardiology", start_time=now, end_time=now, status="scheduled")
        )
        async_stress_session.add(
            AuditEventRecord(
                id=e_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="create_appointment",
                risk="write_local",
                external_ref=f"appointment:{appt_id}",
                ts=now,
            )
        )
        await async_stress_session.commit()

        # First undo succeeds
        res1 = await execute_single_click_undo_async(
            db=async_stress_session,
            event_id=e_id,
            profile_id=prof_id,
            current_time=now + timedelta(minutes=1),
            idempotent=True,
        )
        undo_id_1 = res1["undo_event_id"]

        # Second undo with idempotent=True returns existing undo details
        res2 = await execute_single_click_undo_async(
            db=async_stress_session,
            event_id=e_id,
            profile_id=prof_id,
            current_time=now + timedelta(minutes=2),
            idempotent=True,
        )
        assert res2["status"] == "undone"
        assert res2["undo_event_id"] == undo_id_1
        assert res2.get("idempotent") is True

    @pytest.mark.parametrize("malformed_ref", ["appointment:", ":123", "no_colon_here", "", "   :   "])
    def test_sync_malformed_external_ref_rejected(self, sqlite_stress_db: sqlite3.Connection, malformed_ref: str):
        cur = sqlite_stress_db.cursor()
        prof_id = "prof-test"
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        cur.execute("INSERT OR IGNORE INTO profiles (id, name) VALUES (?, 'Patient')", (prof_id,))
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp) "
            "VALUES (?, ?, 'user', 'create', 'create_appointment', 'write_local', ?, ?)",
            (e_id, prof_id, malformed_ref, now.isoformat()),
        )
        sqlite_stress_db.commit()

        with pytest.raises((InvalidExternalRefError, ValueError)):
            execute_single_click_undo(sqlite_stress_db, e_id, prof_id, current_time=now)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("malformed_ref", ["appointment:", ":123", "no_colon_here", "", "   :   "])
    async def test_async_malformed_external_ref_rejected(self, async_stress_session: AsyncSession, malformed_ref: str):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            AuditEventRecord(
                id=e_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="create_appointment",
                risk="write_local",
                external_ref=malformed_ref,
                ts=now,
            )
        )
        await async_stress_session.commit()

        with pytest.raises(InvalidExternalRefError):
            await execute_single_click_undo_async(
                db=async_stress_session,
                event_id=e_id,
                profile_id=prof_id,
                current_time=now,
            )


# ============================================================================
# Dimension 4: Entity Rollback Verification Stress Tests
# ============================================================================

class TestUndoEntityRollbackVerifications:
    """Stress tests state mutations, deletion job scheduling, and audit trail consistency."""

    @pytest.mark.asyncio
    async def test_health_resource_rollback_to_tombstone(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        hr_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            HealthResource(
                id=hr_id,
                profile_id=prof_id,
                resource_type="observation",
                source_type="manual",
                status="active",
                data={"resourceType": "Observation"},
                effective_at=now,
                recorded_at=now,
            )
        )
        async_stress_session.add(
            AuditEventRecord(
                id=e_id,
                profile_id=prof_id,
                principal="user",
                event="tool",
                tool="record_vitals",
                risk="write_local",
                external_ref=f"health_resource:{hr_id}",
                ts=now,
            )
        )
        await async_stress_session.commit()

        res = await execute_single_click_undo_async(
            db=async_stress_session, event_id=e_id, profile_id=prof_id, current_time=now + timedelta(minutes=1)
        )
        assert res["status"] == "undone"

        hr = (await async_stress_session.execute(select(HealthResource).where(HealthResource.id == hr_id))).scalar_one()
        assert hr.status == "tombstone"

    @pytest.mark.asyncio
    async def test_appointment_rollback_to_cancelled(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        a_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            Appointment(id=a_id, profile_id=prof_id, title="Dentist", start_time=now, end_time=now + timedelta(hours=1), status="confirmed")
        )
        async_stress_session.add(
            AuditEventRecord(id=e_id, profile_id=prof_id, principal="user", event="tool", tool="create_appointment", risk="write_local", external_ref=f"appointment:{a_id}", ts=now)
        )
        await async_stress_session.commit()

        await execute_single_click_undo_async(
            db=async_stress_session, event_id=e_id, profile_id=prof_id, current_time=now + timedelta(minutes=5)
        )

        appt = (await async_stress_session.execute(select(Appointment).where(Appointment.id == a_id))).scalar_one()
        assert appt.status == "cancelled"

    @pytest.mark.asyncio
    async def test_reminder_rollback_to_cancelled(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        rem_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            Reminder(id=rem_id, profile_id=prof_id, title="Take Meds", next_due_at=now + timedelta(hours=4), status="pending")
        )
        async_stress_session.add(
            AuditEventRecord(id=e_id, profile_id=prof_id, principal="user", event="tool", tool="create_reminder", risk="write_local", external_ref=f"reminder:{rem_id}", ts=now)
        )
        await async_stress_session.commit()

        await execute_single_click_undo_async(
            db=async_stress_session, event_id=e_id, profile_id=prof_id, current_time=now + timedelta(minutes=5)
        )

        rem = (await async_stress_session.execute(select(Reminder).where(Reminder.id == rem_id))).scalar_one()
        assert rem.status == "cancelled"

    @pytest.mark.asyncio
    async def test_note_rollback_and_delete_doc_job_enqueued(self, async_stress_session: AsyncSession):
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        note_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(
            Note(id=note_id, profile_id=prof_id, slug="clin-note", title="Clinical Note", content="Extracted text")
        )
        async_stress_session.add(
            AuditEventRecord(id=e_id, profile_id=prof_id, principal="user", event="tool", tool="create_typed_note", risk="write_local", external_ref=f"note:{note_id}", ts=now)
        )
        await async_stress_session.commit()

        await execute_single_click_undo_async(
            db=async_stress_session, event_id=e_id, profile_id=prof_id, current_time=now + timedelta(minutes=5)
        )

        note_check = (await async_stress_session.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()
        assert note_check is None

        jobs = (await async_stress_session.execute(select(Job).where(Job.profile_id == prof_id, Job.kind == "delete_doc"))).scalars().all()
        assert len(jobs) == 1
        payload = json.loads(jobs[0].payload)
        assert payload["document_id"] == note_id
        assert payload["profile_id"] == prof_id
        assert jobs[0].idempotency_key == f"undo:delete_doc:note:{note_id}"

    @pytest.mark.asyncio
    async def test_reversal_audit_event_logged_in_db(self, async_stress_session: AsyncSession):
        """EXPOSES DEFECT: record_audit raises ValidationError on ts/agent_id/event='undo', swallowed by undo.py."""
        prof_id = f"prof-{uuid.uuid4().hex[:8]}"
        a_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=prof_id, name="Patient"))
        async_stress_session.add(Appointment(id=a_id, profile_id=prof_id, title="Appt", start_time=now, end_time=now, status="scheduled"))
        async_stress_session.add(AuditEventRecord(id=e_id, profile_id=prof_id, principal="user", event="tool", tool="create_appointment", risk="write_local", external_ref=f"appointment:{a_id}", ts=now))
        await async_stress_session.commit()

        res = await execute_single_click_undo_async(
            db=async_stress_session, event_id=e_id, profile_id=prof_id, current_time=now + timedelta(minutes=5)
        )
        undo_e_id = res["undo_event_id"]

        # Reversal audit event MUST be persisted in database
        undo_record = (await async_stress_session.execute(select(AuditEventRecord).where(AuditEventRecord.id == undo_e_id))).scalar_one_or_none()
        assert undo_record is not None, "Reversal audit event was not saved to database!"
        assert undo_record.event == "undo"
        assert undo_record.tool == "undo"
        assert undo_record.risk == "write_local"
        assert undo_record.external_ref == f"appointment:{a_id}"

    @pytest.mark.asyncio
    async def test_cross_profile_isolation_cannot_undo_other_patient_event(self, async_stress_session: AsyncSession):
        p_alice = f"prof-alice-{uuid.uuid4().hex[:6]}"
        p_bob = f"prof-bob-{uuid.uuid4().hex[:6]}"
        a_id = str(uuid.uuid4())
        e_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async_stress_session.add(Profile(id=p_alice, name="Alice"))
        async_stress_session.add(Profile(id=p_bob, name="Bob"))
        async_stress_session.add(Appointment(id=a_id, profile_id=p_alice, title="Alice Appt", start_time=now, end_time=now, status="scheduled"))
        async_stress_session.add(AuditEventRecord(id=e_id, profile_id=p_alice, principal="user", event="tool", tool="create_appointment", risk="write_local", external_ref=f"appointment:{a_id}", ts=now))
        await async_stress_session.commit()

        # Bob attempts to undo Alice's event -> Must raise EntityNotFoundError
        with pytest.raises(EntityNotFoundError):
            await execute_single_click_undo_async(
                db=async_stress_session,
                event_id=e_id,
                profile_id=p_bob,
                current_time=now + timedelta(minutes=5),
            )

        # Alice's appointment must remain intact
        appt = (await async_stress_session.execute(select(Appointment).where(Appointment.id == a_id))).scalar_one()
        assert appt.status == "scheduled"
