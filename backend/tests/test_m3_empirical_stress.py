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

"""Adversarial stress testing harness for Milestone 3: Temporal Recurrence, DST, Snooze, and Overdue Coalescing (AU-28)."""

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

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.clinical.reminders import (
    SNOOZE_DELTAS,
    advance_rrule_occurrence,
    apply_reminder_snooze,
    coalesce_overdue_reminders,
    generate_ics_calendar,
    handle_reminder_job,
)
from carefold.config import settings
from carefold.db.models import Job, Profile, Reminder
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


def run_async(coro):
    return asyncio.run(coro)


# ============================================================================
# Section 1: RRULE Recurrence Math & Timezone Shifts Stress Suite
# ============================================================================


class TestRRuleMathStress:
    """Stress tests covering RFC 5545 RRULE arithmetic, DST, leap years, and timezones."""

    def test_dst_spring_forward_wall_clock_invariance(self):
        """Verifies wall-clock hour and minute stay invariant across DST spring-forward (08:00 EST -> 08:00 EDT)."""
        tz_ny = "America/New_York"
        tz = ZoneInfo(tz_ny)
        # Saturday March 7, 2026: EST (UTC-5)
        dt_sat = datetime(2026, 3, 7, 8, 0, 0, tzinfo=tz)
        assert dt_sat.utcoffset() == timedelta(hours=-5)
        assert dt_sat.astimezone(timezone.utc).hour == 13

        # Sunday March 8, 2026: 02:00 EST jumps to 03:00 EDT (UTC-4)
        next_sun = advance_rrule_occurrence(dt_sat, "FREQ=DAILY;INTERVAL=1", tz_ny)
        assert next_sun is not None
        sun_local = next_sun.astimezone(tz)
        assert sun_local.year == 2026
        assert sun_local.month == 3
        assert sun_local.day == 8
        assert sun_local.hour == 8
        assert sun_local.minute == 0
        assert sun_local.second == 0
        assert sun_local.utcoffset() == timedelta(hours=-4)
        # In UTC, 08:00 EDT is 12:00 UTC (offset changed from 13:00 to 12:00)
        assert next_sun.hour == 12

        # Monday March 9, 2026: remains EDT
        next_mon = advance_rrule_occurrence(next_sun, "FREQ=DAILY;INTERVAL=1", tz_ny)
        assert next_mon is not None
        mon_local = next_mon.astimezone(tz)
        assert mon_local.day == 9
        assert mon_local.hour == 8
        assert mon_local.minute == 0
        assert mon_local.utcoffset() == timedelta(hours=-4)
        assert next_mon.hour == 12

    def test_dst_fall_back_wall_clock_invariance(self):
        """Verifies wall-clock hour and minute stay invariant across DST fall-back (08:00 EDT -> 08:00 EST)."""
        tz_ny = "America/New_York"
        tz = ZoneInfo(tz_ny)
        # Saturday October 31, 2026: EDT (UTC-4)
        dt_sat = datetime(2026, 10, 31, 8, 0, 0, tzinfo=tz)
        assert dt_sat.utcoffset() == timedelta(hours=-4)
        assert dt_sat.astimezone(timezone.utc).hour == 12

        # Sunday November 1, 2026: 02:00 EDT falls back to 01:00 EST (UTC-5)
        next_sun = advance_rrule_occurrence(dt_sat, "FREQ=DAILY;INTERVAL=1", tz_ny)
        assert next_sun is not None
        sun_local = next_sun.astimezone(tz)
        assert sun_local.year == 2026
        assert sun_local.month == 11
        assert sun_local.day == 1
        assert sun_local.hour == 8
        assert sun_local.minute == 0
        assert sun_local.second == 0
        assert sun_local.utcoffset() == timedelta(hours=-5)
        # In UTC, 08:00 EST is 13:00 UTC (offset changed from 12:00 to 13:00)
        assert next_sun.hour == 13

        # Monday November 2, 2026: remains EST
        next_mon = advance_rrule_occurrence(next_sun, "FREQ=DAILY;INTERVAL=1", tz_ny)
        assert next_mon is not None
        mon_local = next_mon.astimezone(tz)
        assert mon_local.day == 2
        assert mon_local.hour == 8
        assert mon_local.minute == 0
        assert mon_local.utcoffset() == timedelta(hours=-5)
        assert next_mon.hour == 13

    def test_leap_year_february_29_advancement(self):
        """Verifies February 29 advances properly in leap years and clamps in non-leap years."""
        # 1. 2028 is a leap year (Feb 29 exists)
        d28 = datetime(2028, 2, 28, 9, 30, 0, tzinfo=timezone.utc)
        d29 = advance_rrule_occurrence(d28, "FREQ=DAILY;INTERVAL=1", "UTC")
        assert d29 == datetime(2028, 2, 29, 9, 30, 0, tzinfo=timezone.utc)

        d01 = advance_rrule_occurrence(d29, "FREQ=DAILY;INTERVAL=1", "UTC")
        assert d01 == datetime(2028, 3, 1, 9, 30, 0, tzinfo=timezone.utc)

        # 2. 2026 is NOT a leap year (Feb 29 does NOT exist)
        d28_nl = datetime(2026, 2, 28, 9, 30, 0, tzinfo=timezone.utc)
        d01_nl = advance_rrule_occurrence(d28_nl, "FREQ=DAILY;INTERVAL=1", "UTC")
        assert d01_nl == datetime(2026, 3, 1, 9, 30, 0, tzinfo=timezone.utc)

        # 3. Yearly recurrence from Feb 29 2028 to non-leap 2029 clamps to Feb 28
        y_nl = advance_rrule_occurrence(d29, "FREQ=YEARLY;INTERVAL=1", "UTC")
        assert y_nl == datetime(2029, 2, 28, 9, 30, 0, tzinfo=timezone.utc)

        # 4. Yearly recurrence with INTERVAL=4 from Feb 29 2028 to leap year 2032 preserves Feb 29
        y_leap = advance_rrule_occurrence(d29, "FREQ=YEARLY;INTERVAL=4", "UTC")
        assert y_leap == datetime(2032, 2, 29, 9, 30, 0, tzinfo=timezone.utc)

    def test_month_end_clamping_across_all_short_months(self):
        """Verifies monthly recurrence clamping from day 31 to shorter month lengths."""
        # Jan 31 -> Feb 28 (common year 2026)
        jan31_2026 = datetime(2026, 1, 31, 10, 0, 0, tzinfo=timezone.utc)
        feb28 = advance_rrule_occurrence(jan31_2026, "FREQ=MONTHLY;INTERVAL=1", "UTC")
        assert feb28 == datetime(2026, 2, 28, 10, 0, 0, tzinfo=timezone.utc)

        # Jan 31 -> Feb 29 (leap year 2028)
        jan31_2028 = datetime(2028, 1, 31, 10, 0, 0, tzinfo=timezone.utc)
        feb29 = advance_rrule_occurrence(jan31_2028, "FREQ=MONTHLY;INTERVAL=1", "UTC")
        assert feb29 == datetime(2028, 2, 29, 10, 0, 0, tzinfo=timezone.utc)

        # Mar 31 -> Apr 30 (30-day month)
        mar31 = datetime(2026, 3, 31, 10, 0, 0, tzinfo=timezone.utc)
        apr30 = advance_rrule_occurrence(mar31, "FREQ=MONTHLY;INTERVAL=1", "UTC")
        assert apr30 == datetime(2026, 4, 30, 10, 0, 0, tzinfo=timezone.utc)

        # May 31 -> Jun 30 (30-day month)
        may31 = datetime(2026, 5, 31, 10, 0, 0, tzinfo=timezone.utc)
        jun30 = advance_rrule_occurrence(may31, "FREQ=MONTHLY;INTERVAL=1", "UTC")
        assert jun30 == datetime(2026, 6, 30, 10, 0, 0, tzinfo=timezone.utc)

        # Aug 31 -> Sep 30 (30-day month)
        aug31 = datetime(2026, 8, 31, 10, 0, 0, tzinfo=timezone.utc)
        sep30 = advance_rrule_occurrence(aug31, "FREQ=MONTHLY;INTERVAL=1", "UTC")
        assert sep30 == datetime(2026, 9, 30, 10, 0, 0, tzinfo=timezone.utc)

        # Oct 31 -> Nov 30 (30-day month)
        oct31 = datetime(2026, 10, 31, 10, 0, 0, tzinfo=timezone.utc)
        nov30 = advance_rrule_occurrence(oct31, "FREQ=MONTHLY;INTERVAL=1", "UTC")
        assert nov30 == datetime(2026, 11, 30, 10, 0, 0, tzinfo=timezone.utc)

    def test_cross_timezone_daily_recurrence(self):
        """Verifies identical RRULE preserves local wall-clock time across 4 target IANA timezones."""
        timezones = ["UTC", "America/New_York", "Asia/Tokyo", "Pacific/Honolulu"]
        rrule = "FREQ=DAILY;INTERVAL=1"

        for tz_name in timezones:
            tz = ZoneInfo(tz_name)
            base_local = datetime(2026, 6, 1, 8, 15, 30, tzinfo=tz)
            curr = base_local

            for step in range(1, 15):  # 14 consecutive daily iterations
                nxt = advance_rrule_occurrence(curr, rrule, tz_name)
                assert nxt is not None
                nxt_local = nxt.astimezone(tz)
                assert (nxt_local.hour, nxt_local.minute, nxt_local.second) == (8, 15, 30), (
                    f"Wall-clock drift detected in {tz_name} at step {step}: {nxt_local}"
                )
                curr = nxt

    def test_weekly_byday_recurrence(self):
        """Verifies weekly recurrence with BYDAY advances correctly through weekdays and weekends."""
        # Weekend recurrence: BYDAY=SA,SU
        tue = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)  # Tuesday
        sat = advance_rrule_occurrence(tue, "FREQ=WEEKLY;BYDAY=SA,SU", "UTC")
        assert sat is not None
        assert sat.weekday() == 5  # Saturday Oct 17
        assert sat == datetime(2026, 10, 17, 10, 0, 0, tzinfo=timezone.utc)

        sun = advance_rrule_occurrence(sat, "FREQ=WEEKLY;BYDAY=SA,SU", "UTC")
        assert sun is not None
        assert sun.weekday() == 6  # Sunday Oct 18
        assert sun == datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)

        next_sat = advance_rrule_occurrence(sun, "FREQ=WEEKLY;BYDAY=SA,SU", "UTC")
        assert next_sat is not None
        assert next_sat.weekday() == 5  # Next Saturday Oct 24
        assert next_sat == datetime(2026, 10, 24, 10, 0, 0, tzinfo=timezone.utc)

    def test_until_expiration_boundaries(self):
        """Verifies UNTIL boundary halts recurrence when reached or exceeded."""
        base = datetime(2026, 10, 14, 8, 0, 0, tzinfo=timezone.utc)

        # UNTIL exactly on next occurrence: next is Oct 15 08:00, UNTIL is Oct 15 08:00
        rrule_exact = "FREQ=DAILY;INTERVAL=1;UNTIL=20261015T080000Z"
        nxt = advance_rrule_occurrence(base, rrule_exact, "UTC")
        assert nxt == datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone.utc)

        # From Oct 15 08:00, next would be Oct 16 08:00, which exceeds UNTIL
        after_nxt = advance_rrule_occurrence(nxt, rrule_exact, "UTC")
        assert after_nxt is None


# ============================================================================
# Section 2: Snooze Engine Stress Suite
# ============================================================================


class TestSnoozeEngineStress:
    """Stress tests covering snooze presets, aliases, invalid strings, and re-snooze behavior."""

    def test_snooze_presets_and_aliases(self):
        """Verifies +15m, +1h, +24h presets and their aliases."""
        now = datetime(2026, 10, 13, 14, 0, 0, tzinfo=timezone.utc)
        rem = {"id": "r-snz", "status": "pending", "next_due_at": now.isoformat()}

        # Presets and aliases
        cases = [
            ("+15m", timedelta(minutes=15)),
            ("15m", timedelta(minutes=15)),
            ("+1h", timedelta(hours=1)),
            ("1h", timedelta(hours=1)),
            ("+24h", timedelta(hours=24)),
            ("24h", timedelta(hours=24)),
            (" +15M ", timedelta(minutes=15)),
            ("1H", timedelta(hours=1)),
            (" 24H ", timedelta(hours=24)),
        ]
        for interval_str, expected_delta in cases:
            res = apply_reminder_snooze(rem, interval_str, now)
            assert res["status"] == "snoozed"
            assert res["snooze_until"] == (now + expected_delta).isoformat()

    def test_snooze_invalid_and_negative_intervals_rejected(self):
        """Verifies that negative, zero, and unsupported snooze strings raise ValueError."""
        now = datetime(2026, 10, 13, 14, 0, 0, tzinfo=timezone.utc)
        rem = {"id": "r-inv", "status": "pending"}

        invalid_inputs = [
            "-15m",
            "-1h",
            "-24h",
            "+0m",
            "0m",
            "+0h",
            "0h",
            "+3d",
            "3d",
            "2d",
            "+10s",
            "invalid",
            "tomorrow",
            "next week",
            "",
            "   ",
            "None",
            "null",
        ]
        for inv in invalid_inputs:
            with pytest.raises(ValueError, match="Invalid snooze interval"):
                apply_reminder_snooze(rem, inv, now)

    def test_resnooze_from_current_time(self):
        """Verifies re-snoozing an already snoozed reminder calculates strictly from current action time."""
        t0 = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)
        rem = {"id": "r-resnz", "status": "pending", "next_due_at": t0.isoformat()}

        # 1. First snooze: +15m at t0
        s1 = apply_reminder_snooze(rem, "+15m", t0)
        assert s1["status"] == "snoozed"
        assert s1["snooze_until"] == (t0 + timedelta(minutes=15)).isoformat()

        # 2. Re-snooze 5 minutes later: +1h at t1 = t0 + 5m
        t1 = t0 + timedelta(minutes=5)
        s2 = apply_reminder_snooze(s1, "+1h", t1)
        assert s2["status"] == "snoozed"
        # Must be t1 + 1h = 10:05 + 1:00 = 11:05
        assert s2["snooze_until"] == (t1 + timedelta(hours=1)).isoformat()
        # Must NOT be t0 + 15m + 1h (11:15)
        assert s2["snooze_until"] != (t0 + timedelta(minutes=15, hours=1)).isoformat()

    def test_snooze_terminal_status_rejection(self):
        """Verifies terminal reminder statuses cannot be snoozed."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="Cannot snooze reminder with status 'completed'"):
            apply_reminder_snooze({"id": "r-1", "status": "completed"}, "+15m", now)

        with pytest.raises(ValueError, match="Cannot snooze reminder with status 'cancelled'"):
            apply_reminder_snooze({"id": "r-2", "status": "cancelled"}, "+1h", now)


# ============================================================================
# Section 3: Overdue Coalescing Boundaries Stress Suite
# ============================================================================


class TestOverdueCoalescingStress:
    """Stress tests covering strict 24h overdue coalescing boundaries and invariant statuses."""

    def test_exact_24h_boundary_coalescing(self):
        """Verifies boundary: overdue by 23h59m59s remains pending; 24h00m01s transitions to missed."""
        now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Overdue by exactly 23h 59m 59s -> remains pending
        r_23h59m59s = {
            "id": "r-23h59m59s",
            "status": "pending",
            "next_due_at": (now - timedelta(hours=23, minutes=59, seconds=59)).isoformat(),
        }
        # 2. Overdue by exactly 24h 00m 00s -> remains pending (strict > 24h)
        r_24h00m00s = {
            "id": "r-24h00m00s",
            "status": "pending",
            "next_due_at": (now - timedelta(hours=24)).isoformat(),
        }
        # 3. Overdue by exactly 24h 00m 01s -> transitions to missed
        r_24h00m01s = {
            "id": "r-24h00m01s",
            "status": "pending",
            "next_due_at": (now - timedelta(hours=24, seconds=1)).isoformat(),
        }

        results = coalesce_overdue_reminders([r_23h59m59s, r_24h00m00s, r_24h00m01s], current_time=now)
        res_map = {r["id"]: r["status"] for r in results}

        assert res_map["r-23h59m59s"] == "pending"
        assert res_map["r-24h00m00s"] == "pending"
        assert res_map["r-24h00m01s"] == "missed"

    def test_snoozed_reminder_measures_from_snooze_until(self):
        """Verifies that snoozed reminders measure overdue duration strictly from snooze_until, NOT next_due_at."""
        now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

        # next_due_at was 7 days ago, but snooze_until is only 23h 59m 59s ago -> remains snoozed
        r_snz_active = {
            "id": "r-snz-active",
            "status": "snoozed",
            "next_due_at": (now - timedelta(days=7)).isoformat(),
            "snooze_until": (now - timedelta(hours=23, minutes=59, seconds=59)).isoformat(),
        }
        # next_due_at was 7 days ago, but snooze_until is 24h 00m 01s ago -> transitions to missed
        r_snz_missed = {
            "id": "r-snz-missed",
            "status": "snoozed",
            "next_due_at": (now - timedelta(days=7)).isoformat(),
            "snooze_until": (now - timedelta(hours=24, seconds=1)).isoformat(),
        }

        results = coalesce_overdue_reminders([r_snz_active, r_snz_missed], current_time=now)
        res_map = {r["id"]: r["status"] for r in results}

        assert res_map["r-snz-active"] == "snoozed"
        assert res_map["r-snz-missed"] == "missed"

    def test_completed_and_cancelled_invariance(self):
        """Verifies completed and cancelled reminders are strictly invariant and never transition to missed."""
        now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

        r_comp = {
            "id": "r-comp",
            "status": "completed",
            "next_due_at": (now - timedelta(days=365)).isoformat(),
            "snooze_until": (now - timedelta(days=364)).isoformat(),
        }
        r_canc = {
            "id": "r-canc",
            "status": "cancelled",
            "next_due_at": (now - timedelta(days=365)).isoformat(),
            "snooze_until": (now - timedelta(days=364)).isoformat(),
        }

        results = coalesce_overdue_reminders([r_comp, r_canc], current_time=now)
        res_map = {r["id"]: r["status"] for r in results}

        assert res_map["r-comp"] == "completed"
        assert res_map["r-canc"] == "cancelled"


# ============================================================================
# Section 4: REST API Snooze & RBAC Boundary Tests
# ============================================================================


class TestRemindersApiStress:
    """Stress tests covering REST API HTTP 400 rejection for invalid snoozes and RBAC enforcement."""

    @pytest.fixture
    def api_stress_env(self, monkeypatch):
        async def _setup():
            engine = create_db_engine("sqlite+aiosqlite:///:memory:")
            await init_db(engine)
            session_factory = get_session_factory(engine)
            auth_adapter = SqlAuthAdapter(session_factory=session_factory)

            monkeypatch.setattr(settings, "auth_provider", "local")
            set_auth_port(auth_adapter)

            user = await auth_adapter.register_user(
                email="tester_stress@carefold.local",
                username="tester_stress",
                password="Password123!",
                full_name="Tester Stress",
                role="member",
                auth_provider="local",
            )
            session_obj = await auth_adapter.create_session(user.id)

            now = datetime.now(timezone.utc)
            profile_id = str(uuid.uuid4())
            rem_id = str(uuid.uuid4())

            async with session_factory() as session:
                p = Profile(
                    id=profile_id,
                    user_id=user.id,
                    name="Stress Patient",
                    relationship="self",
                    role="self",
                    created_at=now,
                    updated_at=now,
                )
                r = Reminder(
                    id=rem_id,
                    profile_id=profile_id,
                    title="Stress Test Reminder",
                    category="medication",
                    next_due_at=now,
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
                session.add(p)
                session.add(r)
                await session.commit()

            return {
                "session_factory": session_factory,
                "profile_id": profile_id,
                "reminder_id": rem_id,
                "token": session_obj.token,
            }

        data = run_async(_setup())
        session_factory = data["session_factory"]

        async def _override_get_db():
            async with session_factory() as session:
                yield session
                await session.commit()

        app.dependency_overrides[get_db] = _override_get_db
        try:
            yield data
        finally:
            app.dependency_overrides.pop(get_db, None)
            reset_auth_port()

    def test_api_snooze_invalid_intervals_return_400(self, api_stress_env):
        """Verifies API returns HTTP 400 Bad Request on invalid snooze intervals."""
        client = TestClient(app)
        prof_id = api_stress_env["profile_id"]
        rem_id = api_stress_env["reminder_id"]
        token = api_stress_env["token"]
        headers = {"Authorization": f"Bearer {token}"}

        invalids = ["-15m", "+0m", "0m", "+3d", "invalid", "tomorrow", ""]
        for inv in invalids:
            res = client.post(
                f"/api/profiles/{prof_id}/reminders/{rem_id}/snooze",
                json={"interval": inv},
                headers=headers,
            )
            assert res.status_code == 400, f"Expected HTTP 400 for '{inv}', got {res.status_code}: {res.text}"
            assert "Invalid snooze interval" in res.json()["detail"]

    def test_api_snooze_valid_and_resnooze(self, api_stress_env):
        """Verifies API successfully snoozes and re-snoozes with status 200."""
        client = TestClient(app)
        prof_id = api_stress_env["profile_id"]
        rem_id = api_stress_env["reminder_id"]
        token = api_stress_env["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Snooze +15m
        res1 = client.post(
            f"/api/profiles/{prof_id}/reminders/{rem_id}/snooze",
            json={"interval": "+15m"},
            headers=headers,
        )
        assert res1.status_code == 200
        assert res1.json()["status"] == "snoozed"
        assert res1.json()["snooze_until"] is not None

        # 2. Re-snooze +1h
        res2 = client.post(
            f"/api/profiles/{prof_id}/reminders/{rem_id}/snooze",
            json={"interval": "+1h"},
            headers=headers,
        )
        assert res2.status_code == 200
        assert res2.json()["status"] == "snoozed"
        assert res2.json()["snooze_until"] is not None
