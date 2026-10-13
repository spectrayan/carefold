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

"""Unit, integration, and API test suite for Reminders, Recurrence, and Snooze (AU-28)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict
import uuid
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.api.reminders import set_profile_reminder_preference
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.clinical.reminders import (
    advance_rrule_occurrence,
    apply_reminder_snooze,
    coalesce_overdue_reminders,
    generate_ics_calendar,
    handle_reminder_job,
)
from carefold.config import settings
from carefold.db.models import Job, Profile, ProfileAccess, Reminder
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.job_runner import JobRunner
from carefold.engine.tool_exec import ToolContext
from carefold.main import app
from carefold.tools.reminders import execute_create_reminder, execute_list_reminders


def run_async(coro):
    return asyncio.run(coro)


# ============================================================================
# Section 1: RRULE Recurrence Expansion Tests
# ============================================================================


def test_daily_recurrence_expansion():
    """Verifies that DAILY recurrence advances by specified interval days."""
    base = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    # 1 day interval
    next_1 = advance_rrule_occurrence(base, "FREQ=DAILY;INTERVAL=1", "UTC")
    assert next_1 == base + timedelta(days=1)

    # 3 days interval
    next_3 = advance_rrule_occurrence(base, "FREQ=DAILY;INTERVAL=3", "UTC")
    assert next_3 == base + timedelta(days=3)


def test_weekly_recurrence_without_byday():
    """Verifies that WEEKLY recurrence without BYDAY advances by interval weeks."""
    base = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    next_w = advance_rrule_occurrence(base, "FREQ=WEEKLY;INTERVAL=1", "UTC")
    assert next_w == base + timedelta(weeks=1)

    next_2w = advance_rrule_occurrence(base, "FREQ=WEEKLY;INTERVAL=2", "UTC")
    assert next_2w == base + timedelta(weeks=2)


def test_weekly_recurrence_with_byday():
    """Verifies that WEEKLY recurrence with BYDAY=MO,WE,FR advances across days."""
    # 2026-10-12 is a Monday (0)
    mon = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)
    wed = advance_rrule_occurrence(mon, "FREQ=WEEKLY;BYDAY=MO,WE,FR", "UTC")
    assert wed == datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)

    fri = advance_rrule_occurrence(wed, "FREQ=WEEKLY;BYDAY=MO,WE,FR", "UTC")
    assert fri == datetime(2026, 10, 16, 9, 0, 0, tzinfo=timezone.utc)

    # Wrap around to next Monday
    next_mon = advance_rrule_occurrence(fri, "FREQ=WEEKLY;BYDAY=MO,WE,FR", "UTC")
    assert next_mon == datetime(2026, 10, 19, 9, 0, 0, tzinfo=timezone.utc)


def test_monthly_recurrence_and_clamping():
    """Verifies that MONTHLY recurrence advances months and clamps day to month length."""
    # Standard 1 month advance
    dt1 = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    dt2 = advance_rrule_occurrence(dt1, "FREQ=MONTHLY;INTERVAL=1", "UTC")
    assert dt2 == datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc)

    # Clamping Jan 31 -> Feb 28 in common year 2026
    jan31 = datetime(2026, 1, 31, 10, 0, 0, tzinfo=timezone.utc)
    feb28 = advance_rrule_occurrence(jan31, "FREQ=MONTHLY;INTERVAL=1", "UTC")
    assert feb28 == datetime(2026, 2, 28, 10, 0, 0, tzinfo=timezone.utc)

    # Clamping Jan 31 -> Feb 29 in leap year 2028
    jan31_leap = datetime(2028, 1, 31, 10, 0, 0, tzinfo=timezone.utc)
    feb29 = advance_rrule_occurrence(jan31_leap, "FREQ=MONTHLY;INTERVAL=1", "UTC")
    assert feb29 == datetime(2028, 2, 29, 10, 0, 0, tzinfo=timezone.utc)


def test_yearly_recurrence_leap_year_clamp():
    """Verifies that YEARLY recurrence clamps Feb 29 to Feb 28 in non-leap year."""
    feb29_2028 = datetime(2028, 2, 29, 12, 0, 0, tzinfo=timezone.utc)
    feb28_2029 = advance_rrule_occurrence(feb29_2028, "FREQ=YEARLY;INTERVAL=1", "UTC")
    assert feb28_2029 == datetime(2029, 2, 28, 12, 0, 0, tzinfo=timezone.utc)


def test_dst_spring_forward_wall_clock_stable():
    """Verifies that local wall-clock time is preserved across US spring-forward transition."""
    # 2026-03-07 is EST (UTC-5), 2026-03-08 is EDT (UTC-4)
    tz_ny = "America/New_York"
    tz = ZoneInfo(tz_ny)
    dt1 = datetime(2026, 3, 7, 8, 0, 0, tzinfo=tz)  # 13:00 UTC
    dt2 = advance_rrule_occurrence(dt1, "FREQ=DAILY;INTERVAL=1", tz_ny)
    assert dt2 is not None
    # Converted back to America/New_York, wall-clock must still be 08:00
    dt2_local = dt2.astimezone(tz)
    assert dt2_local.hour == 8
    assert dt2_local.minute == 0
    # UTC shifts from 13:00 to 12:00
    assert dt2.hour == 12


def test_dst_fall_back_wall_clock_stable():
    """Verifies that local wall-clock time is preserved across US fall-back transition."""
    # 2026-10-31 is EDT (UTC-4), 2026-11-01 is EST (UTC-5)
    tz_ny = "America/New_York"
    tz = ZoneInfo(tz_ny)
    dt1 = datetime(2026, 10, 31, 8, 0, 0, tzinfo=tz)  # 12:00 UTC
    dt2 = advance_rrule_occurrence(dt1, "FREQ=DAILY;INTERVAL=1", tz_ny)
    assert dt2 is not None
    dt2_local = dt2.astimezone(tz)
    assert dt2_local.hour == 8
    assert dt2_local.minute == 0
    # UTC shifts from 12:00 to 13:00
    assert dt2.hour == 13


def test_until_exhaustion():
    """Verifies that recurrence halts (returns None) once UNTIL boundary is crossed."""
    base = datetime(2026, 10, 14, 8, 0, 0, tzinfo=timezone.utc)
    # UNTIL set to Oct 14 23:59:59 UTC
    rrule = "FREQ=DAILY;INTERVAL=1;UNTIL=20261014T235959Z"
    # Next would be Oct 15 08:00, which is past UNTIL
    next_dt = advance_rrule_occurrence(base, rrule, "UTC")
    assert next_dt is None


# ============================================================================
# Section 2: Snooze Engine Tests
# ============================================================================


def test_snooze_presets_and_aliases():
    """Verifies snooze presets +15m, +1h, +24h and their aliases."""
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    rem = {"id": "r-1", "status": "pending", "next_due_at": now.isoformat()}

    s15 = apply_reminder_snooze(rem, "+15m", now)
    assert s15["status"] == "snoozed"
    assert s15["snooze_until"] == (now + timedelta(minutes=15)).isoformat()

    s15_alias = apply_reminder_snooze(rem, "15m", now)
    assert s15_alias["snooze_until"] == s15["snooze_until"]

    s1h = apply_reminder_snooze(rem, "+1h", now)
    assert s1h["snooze_until"] == (now + timedelta(hours=1)).isoformat()

    s1h_alias = apply_reminder_snooze(rem, "1h", now)
    assert s1h_alias["snooze_until"] == s1h["snooze_until"]

    s24h = apply_reminder_snooze(rem, "+24h", now)
    assert s24h["snooze_until"] == (now + timedelta(hours=24)).isoformat()

    s24h_alias = apply_reminder_snooze(rem, "24h", now)
    assert s24h_alias["snooze_until"] == s24h["snooze_until"]


def test_snooze_invalid_intervals_rejected():
    """Verifies that negative or unsupported snooze strings raise ValueError."""
    now = datetime.now(timezone.utc)
    rem = {"id": "r-1", "status": "pending"}

    with pytest.raises(ValueError):
        apply_reminder_snooze(rem, "-10m", now)
    with pytest.raises(ValueError):
        apply_reminder_snooze(rem, "+3d", now)
    with pytest.raises(ValueError):
        apply_reminder_snooze(rem, "tomorrow", now)


def test_snooze_consecutive_recalculates():
    """Verifies consecutive snoozes recalculate relative to the new action timestamp."""
    now1 = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    rem = {"id": "r-1", "status": "pending", "next_due_at": now1.isoformat()}
    s1 = apply_reminder_snooze(rem, "+15m", now1)

    # 10 minutes later, user snoozes +1h
    now2 = datetime(2026, 10, 10, 8, 10, 0, tzinfo=timezone.utc)
    s2 = apply_reminder_snooze(s1, "+1h", now2)
    assert s2["snooze_until"] == (now2 + timedelta(hours=1)).isoformat()


def test_cannot_snooze_completed_or_cancelled_reminder():
    """Verifies terminal reminder statuses cannot be snoozed."""
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="Cannot snooze reminder with status 'completed'"):
        apply_reminder_snooze({"id": "r-comp", "status": "completed"}, "+15m", now)

    with pytest.raises(ValueError, match="Cannot snooze reminder with status 'cancelled'"):
        apply_reminder_snooze({"id": "r-canc", "status": "cancelled"}, "+1h", now)


# ============================================================================
# Section 3: Sleep/Wake Overdue Coalescing Tests
# ============================================================================


def test_overdue_coalescing_boundaries():
    """Verifies strict 24-hour boundary for coalescing overdue reminders to missed."""
    now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

    # 23h 59m overdue -> remains pending
    r_23h59 = {"id": "r1", "status": "pending", "next_due_at": (now - timedelta(hours=23, minutes=59)).isoformat()}
    # 24h 01m overdue -> coalesces to missed
    r_24h01 = {"id": "r2", "status": "pending", "next_due_at": (now - timedelta(hours=24, minutes=1)).isoformat()}

    res = coalesce_overdue_reminders([r_23h59, r_24h01], current_time=now)
    assert res[0]["status"] == "pending"
    assert res[1]["status"] == "missed"


def test_overdue_snoozed_measures_from_snooze_until():
    """Verifies that snoozed reminder overdue duration measures from snooze_until."""
    now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
    r_snoozed = {
        "id": "r-snz",
        "status": "snoozed",
        "next_due_at": (now - timedelta(days=5)).isoformat(),
        "snooze_until": (now - timedelta(hours=10)).isoformat(),  # Only 10h overdue
    }
    res = coalesce_overdue_reminders([r_snoozed], current_time=now)
    assert res[0]["status"] == "snoozed"

    # Snooze expired > 24 hours
    r_snz_expired = {
        "id": "r-snz-exp",
        "status": "snoozed",
        "next_due_at": (now - timedelta(days=5)).isoformat(),
        "snooze_until": (now - timedelta(hours=25)).isoformat(),
    }
    res_exp = coalesce_overdue_reminders([r_snz_expired], current_time=now)
    assert res_exp[0]["status"] == "missed"


def test_completed_and_cancelled_never_missed():
    """Verifies completed and cancelled reminders are invariant to overdue sweep."""
    now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
    r_comp = {"id": "rc", "status": "completed", "next_due_at": (now - timedelta(hours=72)).isoformat()}
    r_canc = {"id": "rx", "status": "cancelled", "next_due_at": (now - timedelta(hours=72)).isoformat()}

    res = coalesce_overdue_reminders([r_comp, r_canc], current_time=now)
    assert res[0]["status"] == "completed"
    assert res[1]["status"] == "cancelled"


# ============================================================================
# Section 4: RFC 5545 .ics Export Tests
# ============================================================================


def test_ics_export_sanitized_phi_default():
    """Verifies default-on PHI sanitization in RFC 5545 calendar export."""
    reminders = [{
        "id": "rem-onco",
        "title": "Oncology chemotherapy infusion session",
        "category": "appointment",
        "next_due_at": "2026-10-15T14:00:00Z",
        "description": "Port flush and IV infusion protocol",
        "rrule": "FREQ=DAILY;INTERVAL=1",
    }]
    ics_sanitized = generate_ics_calendar(reminders, sanitize_phi=True)
    assert "BEGIN:VCALENDAR" in ics_sanitized
    assert "BEGIN:VEVENT" in ics_sanitized
    assert "Carefold Appointment Reminder" in ics_sanitized
    assert "chemotherapy" not in ics_sanitized  # PHI stripped
    assert "Port flush" not in ics_sanitized
    assert "RRULE:FREQ=DAILY;INTERVAL=1" in ics_sanitized
    assert "\r\n" in ics_sanitized


def test_ics_export_unsanitized_opt_in():
    """Verifies verbatim calendar export when sanitize_phi=False."""
    reminders = [{
        "id": "rem-med",
        "title": "Metformin 500mg with breakfast",
        "category": "medication",
        "next_due_at": "2026-10-15T08:00:00Z",
        "description": "Take with meal to reduce GI upset.",
    }]
    ics_raw = generate_ics_calendar(reminders, sanitize_phi=False)
    assert "Metformin 500mg with breakfast" in ics_raw
    assert "Take with meal to reduce GI upset." in ics_raw


# ============================================================================
# Section 5: JobRunner Handler Bridge Tests
# ============================================================================


def test_job_runner_registers_reminder_handler():
    """Verifies JobRunner registers the default reminder handler on init."""
    runner = JobRunner()
    assert runner.has_handler("reminder") is True


def test_handle_reminder_job_in_memory_recurring():
    """Verifies handle_reminder_job advances recurring reminder in in-memory mode."""
    t0 = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    job = Job(
        id=str(uuid.uuid4()),
        profile_id="p-1",
        kind="reminder",
        payload=json.dumps({"reminder_id": "r-1"}),
        rrule="FREQ=DAILY;INTERVAL=1",
        next_run_at=t0,
        status="pending",
    )
    run_async(handle_reminder_job(job, session_factory=None))
    assert job.status == "pending"
    assert job.next_run_at == t0 + timedelta(days=1)


def test_handle_reminder_job_in_memory_one_shot():
    """Verifies handle_reminder_job marks one-shot reminder job completed."""
    t0 = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    job = Job(
        id=str(uuid.uuid4()),
        profile_id="p-1",
        kind="reminder",
        payload=json.dumps({"reminder_id": "r-one"}),
        rrule=None,
        next_run_at=t0,
        status="pending",
    )
    run_async(handle_reminder_job(job, session_factory=None))
    assert job.status == "completed"


# ============================================================================
# Section 6: ToolSpec Execution Tests
# ============================================================================


@pytest.fixture
def reminders_tool_env(monkeypatch):
    """Sets up an isolated in-memory DB and session factory for reminder tools."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    run_async(init_db(engine))
    session_factory = get_session_factory(engine)
    monkeypatch.setattr("carefold.tools.reminders.get_session_factory", lambda: session_factory)

    profile_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async def _create_profile():
        async with session_factory() as session:
            p = Profile(
                id=profile_id,
                name="Reminder Test Patient",
                relationship="self",
                role="self",
                created_at=now,
                updated_at=now,
            )
            session.add(p)
            await session.commit()

    run_async(_create_profile())
    return {"session_factory": session_factory, "profile_id": profile_id}


def test_create_and_list_reminder_tools(reminders_tool_env):
    """Verifies execute_create_reminder and execute_list_reminders tools."""
    prof_id = reminders_tool_env["profile_id"]
    ctx = ToolContext(profile_id=prof_id, user_id="user-1")

    now = datetime.now(timezone.utc)
    due_str = (now + timedelta(hours=4)).isoformat()

    # 1. Create reminder tool
    c_res = run_async(execute_create_reminder({
        "title": "Evening Lisinopril",
        "next_due_at": due_str,
        "category": "medication",
        "rrule": "FREQ=DAILY;INTERVAL=1",
    }, ctx))
    assert c_res.success is True
    assert c_res.output["title"] == "Evening Lisinopril"
    assert c_res.output["category"] == "medication"
    rem_id = c_res.output["id"]
    assert c_res.output["job_id"] is not None

    # 2. List reminders tool
    l_res = run_async(execute_list_reminders({"category": "medication"}, ctx))
    assert l_res.success is True
    assert l_res.output["total"] >= 1
    assert any(r["id"] == rem_id for r in l_res.output["reminders"])


def test_create_reminder_tool_fail_closed():
    """Verifies create_reminder fails closed if profile_id is missing."""
    with pytest.raises(ValueError, match="Security invariant violation"):
        ToolContext(profile_id="", user_id="user-1")

    class DummyCtx:
        profile_id = ""
        user_id = "user-1"

    res = run_async(execute_create_reminder({"title": "Test", "next_due_at": "2026-10-15T09:00:00Z"}, DummyCtx()))
    assert res.success is False
    assert "Security violation" in res.error


# ============================================================================
# Section 7: REST API Integration & Permissions Tests
# ============================================================================


@pytest.fixture
def reminders_api_env(monkeypatch):
    """Sets up an isolated database, auth adapter, test profiles and role grants."""
    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        # Alice: Owner ('manage')
        alice = await auth_adapter.register_user(
            email="alice_rem@test.local",
            username="alice_rem",
            password="Password123!",
            full_name="Alice Owner",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # Bob: Manage grant
        bob = await auth_adapter.register_user(
            email="bob_rem@test.local",
            username="bob_rem",
            password="Password123!",
            full_name="Bob Manager",
            role="member",
            auth_provider="local",
        )
        bob_session = await auth_adapter.create_session(bob.id)

        # Charlie: Clinical view only
        charlie = await auth_adapter.register_user(
            email="charlie_rem@test.local",
            username="charlie_rem",
            password="Password123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # Dan: Paperwork only
        dan = await auth_adapter.register_user(
            email="dan_rem@test.local",
            username="dan_rem",
            password="Password123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # Eve: Unauthorized
        eve = await auth_adapter.register_user(
            email="eve_rem@test.local",
            username="eve_rem",
            password="Password123!",
            full_name="Eve Unauthorized",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        now = datetime.now(timezone.utc)
        feed_token = "valid_calendar_feed_token_xyz123"
        async with session_factory() as session:
            alice_profile = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Alice Reminders Profile",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
            session.add(alice_profile)
            set_profile_reminder_preference(alice_profile.id, "calendar_feed_token", feed_token)

            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=alice_profile.id,
                user_id=bob.id,
                access_level="manage",
                granted_by=alice.id,
                granted_at=now,
            ))
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=alice_profile.id,
                user_id=charlie.id,
                access_level="view_clinical",
                granted_by=alice.id,
                granted_at=now,
            ))
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=alice_profile.id,
                user_id=dan.id,
                access_level="view_paperwork",
                granted_by=alice.id,
                granted_at=now,
            ))
            await session.commit()

            return {
                "session_factory": session_factory,
                "profile_id": alice_profile.id,
                "feed_token": feed_token,
                "alice_token": alice_session.token,
                "bob_token": bob_session.token,
                "charlie_token": charlie_session.token,
                "dan_token": dan_session.token,
                "eve_token": eve_session.token,
            }

    env_data = run_async(_setup())
    session_factory = env_data["session_factory"]

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield env_data
    finally:
        app.dependency_overrides.pop(get_db, None)
        reset_auth_port()


def test_reminders_rest_api_lifecycle(reminders_api_env):
    """End-to-end test of reminders CRUD, snooze, export, and feed REST APIs."""
    client = TestClient(app)
    prof_id = reminders_api_env["profile_id"]
    token = reminders_api_env["alice_token"]
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)
    due_dt = now + timedelta(days=1)

    # 1. POST create reminder
    create_payload = {
        "title": "Daily Blood Pressure Check",
        "description": "Log morning systolic/diastolic reading",
        "category": "vitals",
        "rrule": "FREQ=DAILY;INTERVAL=1",
        "next_due_at": due_dt.isoformat(),
    }
    res = client.post(f"/api/profiles/{prof_id}/reminders", json=create_payload, headers=headers)
    assert res.status_code == 201
    rem_data = res.json()
    rem_id = rem_data["id"]
    assert rem_data["category"] == "vitals"
    assert rem_data["status"] == "pending"

    # 2. GET single reminder
    get_res = client.get(f"/api/profiles/{prof_id}/reminders/{rem_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Daily Blood Pressure Check"

    # 3. GET list reminders
    list_res = client.get(f"/api/profiles/{prof_id}/reminders?category=vitals", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["total"] >= 1

    # 4. POST snooze +15m
    snooze_res = client.post(
        f"/api/profiles/{prof_id}/reminders/{rem_id}/snooze",
        json={"interval": "+15m"},
        headers=headers,
    )
    assert snooze_res.status_code == 200
    assert snooze_res.json()["status"] == "snoozed"
    assert snooze_res.json()["snooze_until"] is not None

    # 5. PATCH complete recurring reminder (advances occurrence)
    patch_res = client.patch(
        f"/api/profiles/{prof_id}/reminders/{rem_id}",
        json={"status": "completed"},
        headers=headers,
    )
    assert patch_res.status_code == 200
    # Since it is recurring with FREQ=DAILY, completing it resets status to pending and advances next_due_at
    assert patch_res.json()["status"] == "pending"

    # 6. GET export.ics
    ics_res = client.get(f"/api/profiles/{prof_id}/reminders/export.ics?sanitize_phi=true", headers=headers)
    assert ics_res.status_code == 200
    assert "BEGIN:VCALENDAR" in ics_res.text
    assert "Carefold Vitals Reminder" in ics_res.text

    # 7. GET feed.ics (authenticated via token)
    feed_token = reminders_api_env["feed_token"]
    feed_res = client.get(f"/api/profiles/{prof_id}/reminders/feed.ics?token={feed_token}")
    assert feed_res.status_code == 200
    assert "BEGIN:VCALENDAR" in feed_res.text

    # Bad token on feed.ics -> 401
    bad_feed = client.get(f"/api/profiles/{prof_id}/reminders/feed.ics?token=wrong_token")
    assert bad_feed.status_code == 401

    # 8. DELETE reminder
    del_res = client.delete(f"/api/profiles/{prof_id}/reminders/{rem_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "cancelled"


def test_reminders_api_permissions(reminders_api_env):
    """Verifies role-based access matrix on reminder endpoints."""
    client = TestClient(app)
    prof_id = reminders_api_env["profile_id"]

    bob_h = {"Authorization": f"Bearer {reminders_api_env['bob_token']}"}
    charlie_h = {"Authorization": f"Bearer {reminders_api_env['charlie_token']}"}
    dan_h = {"Authorization": f"Bearer {reminders_api_env['dan_token']}"}
    eve_h = {"Authorization": f"Bearer {reminders_api_env['eve_token']}"}

    now = datetime.now(timezone.utc)
    payload = {
        "title": "Medication Reminder",
        "next_due_at": (now + timedelta(hours=2)).isoformat(),
        "category": "medication",
    }

    # 1. Bob (manage) can POST
    bob_res = client.post(f"/api/profiles/{prof_id}/reminders", json=payload, headers=bob_h)
    assert bob_res.status_code == 201
    rem_id = bob_res.json()["id"]

    # 2. Charlie (view_clinical) can GET
    charlie_get = client.get(f"/api/profiles/{prof_id}/reminders", headers=charlie_h)
    assert charlie_get.status_code == 200

    # 3. Charlie (view_clinical) CANNOT POST or SNOOZE or DELETE (403)
    charlie_post = client.post(f"/api/profiles/{prof_id}/reminders", json=payload, headers=charlie_h)
    assert charlie_post.status_code == 403

    charlie_snooze = client.post(f"/api/profiles/{prof_id}/reminders/{rem_id}/snooze", json={"interval": "+15m"}, headers=charlie_h)
    assert charlie_snooze.status_code == 403

    charlie_del = client.delete(f"/api/profiles/{prof_id}/reminders/{rem_id}", headers=charlie_h)
    assert charlie_del.status_code == 403

    # 4. Dan (view_paperwork) CANNOT GET (403)
    dan_get = client.get(f"/api/profiles/{prof_id}/reminders", headers=dan_h)
    assert dan_get.status_code == 403

    # 5. Eve (unauthorized) CANNOT access (403)
    eve_get = client.get(f"/api/profiles/{prof_id}/reminders", headers=eve_h)
    assert eve_get.status_code == 403
