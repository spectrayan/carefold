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

"""Adversarial stress harness by Challenger M2 Iter 2: Pediatric BMI boundary, Diurnal Timezones, and API Idempotency/RBAC."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.clinical.bmi import (
    calculate_adult_bmi,
    calculate_pediatric_bmi_percentile,
)
from carefold.clinical.vitals import calculate_diurnal_bp_trends
from carefold.config import settings
from carefold.db.models import Profile, ProfileAccess
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


# ============================================================================
# FOCUS AREA 1: PEDIATRIC-TO-ADULT BMI BOUNDARY ALIGNMENT STRESS TESTS
# ============================================================================


class TestPediatricToAdultBmiBoundaryAlignment:
    """Stress tests for the age 240 months boundary, negative ages, non-binary gender, and corrupted DOB."""

    def test_pediatric_to_adult_exact_boundary_curve_transition(self):
        """Boundary test: 239 months (pediatric LMS curve) vs 240 months (adult formula) vs 241 months."""
        # 1. Age 239 months: Must calculate pediatric LMS percentile and NOT adult
        res_239 = calculate_pediatric_bmi_percentile(
            age_months=239,
            gender="male",
            weight_kg=70.0,
            height_cm=175.0,
        )
        assert res_239["suppressed"] is False
        assert res_239["bmi"] == 22.9
        assert isinstance(res_239["percentile"], float)
        assert 0.1 <= res_239["percentile"] <= 99.9
        assert res_239.get("is_adult") is not True

        # 2. Age 240 months (exact 20.0 years): Smooth transition to adult BMI per CDC guidelines
        res_240 = calculate_pediatric_bmi_percentile(
            age_months=240,
            gender="male",
            weight_kg=70.0,
            height_cm=175.0,
        )
        assert res_240["suppressed"] is False
        assert res_240["bmi"] == 22.9
        assert res_240["percentile"] is None
        assert res_240["classification"] == "Normal weight"
        assert res_240.get("is_adult") is True

        # 3. Age 241 months: Still adult fallback
        res_241 = calculate_pediatric_bmi_percentile(
            age_months=241,
            gender="female",
            weight_kg=60.0,
            height_cm=165.0,
        )
        assert res_241["suppressed"] is False
        assert res_241["bmi"] == 22.0
        assert res_241["percentile"] is None
        assert res_241["classification"] == "Normal weight"
        assert res_241.get("is_adult") is True

    def test_pediatric_direct_negative_age_and_invalid_gender_rejections(self):
        """Direct unit rejection: calculate_pediatric_bmi_percentile rejects negative ages and non-binary strings."""
        with pytest.raises(ValueError, match="non-negative"):
            calculate_pediatric_bmi_percentile(
                age_months=-1,
                gender="male",
                weight_kg=15.0,
                height_cm=100.0,
            )

        with pytest.raises(ValueError, match="Invalid gender"):
            calculate_pediatric_bmi_percentile(
                age_months=60,
                gender="non-binary",  # type: ignore
                weight_kg=18.0,
                height_cm=110.0,
            )

        with pytest.raises(ValueError, match="Invalid gender"):
            calculate_pediatric_bmi_percentile(
                age_months=60,
                gender="other",  # type: ignore
                weight_kg=18.0,
                height_cm=110.0,
            )


# ============================================================================
# FOCUS AREA 2: DIURNAL BP TIMEZONE STRESS TESTS (24-HOUR SWEEP & BOUNDARIES)
# ============================================================================


class TestDiurnalBpTimezoneComprehensiveStress:
    """Stress tests diurnal BP partitioning across UTC, America/New_York, Asia/Tokyo, Pacific/Honolulu."""

    @pytest.mark.parametrize(
        "tz_name, utc_hour, expected_window",
        [
            # UTC (offset 0)
            ("UTC", 4, "night"),
            ("UTC", 5, "am"),
            ("UTC", 8, "am"),
            ("UTC", 11, "am"),
            ("UTC", 12, "pm"),
            ("UTC", 16, "pm"),
            ("UTC", 21, "pm"),
            ("UTC", 22, "pm_sharp"),  # at 22:00
            ("UTC", 23, "night"),
            # America/New_York (EDT, UTC-4 in October)
            # Local = UTC - 4
            ("America/New_York", 9, "am"),      # 09:00 UTC -> 05:00 EDT (AM start)
            ("America/New_York", 15, "am"),     # 15:00 UTC -> 11:00 EDT (AM)
            ("America/New_York", 16, "pm"),     # 16:00 UTC -> 12:00 EDT (PM start)
            ("America/New_York", 2, "pm_sharp"), # 02:00 UTC (+1d) -> 22:00 EDT (PM end)
            ("America/New_York", 3, "night"),   # 03:00 UTC (+1d) -> 23:00 EDT (Night)
            ("America/New_York", 8, "night"),   # 08:00 UTC -> 04:00 EDT (Night)
            # Asia/Tokyo (JST, UTC+9)
            # Local = UTC + 9
            ("Asia/Tokyo", 20, "am"),     # 20:00 UTC -> 05:00 JST (+1d) (AM start)
            ("Asia/Tokyo", 2, "am"),      # 02:00 UTC -> 11:00 JST (AM)
            ("Asia/Tokyo", 3, "pm"),      # 03:00 UTC -> 12:00 JST (PM start)
            ("Asia/Tokyo", 13, "pm_sharp"), # 13:00 UTC -> 22:00 JST (PM end)
            ("Asia/Tokyo", 14, "night"),  # 14:00 UTC -> 23:00 JST (Night)
            ("Asia/Tokyo", 19, "night"),  # 19:00 UTC -> 04:00 JST (Night)
            # Pacific/Honolulu (HST, UTC-10)
            # Local = UTC - 10
            ("Pacific/Honolulu", 15, "am"),    # 15:00 UTC -> 05:00 HST (AM start)
            ("Pacific/Honolulu", 21, "am"),    # 21:00 UTC -> 11:00 HST (AM)
            ("Pacific/Honolulu", 22, "pm"),    # 22:00 UTC -> 12:00 HST (PM start)
            ("Pacific/Honolulu", 8, "pm_sharp"), # 08:00 UTC (+1d) -> 22:00 HST (PM end)
            ("Pacific/Honolulu", 9, "night"),  # 09:00 UTC (+1d) -> 23:00 HST (Night)
            ("Pacific/Honolulu", 14, "night"), # 14:00 UTC -> 04:00 HST (Night)
        ],
    )
    def test_timezone_hourly_partitioning_matrix(self, tz_name, utc_hour, expected_window):
        """Systematically validates hour-by-hour UTC conversion to AM, PM, or night across 4 zones."""
        now_dt = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
        minute = 0 if expected_window == "pm_sharp" else 30
        reading_dt = datetime(2026, 10, 14, utc_hour, minute, 0, tzinfo=timezone.utc)

        reading = {
            "effective_at": reading_dt,
            "data": {
                "component": [
                    {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 124}},
                    {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 82}},
                ]
            },
        }

        trends = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz=tz_name)
        am_count = trends["7_day"]["am"]["count"]
        pm_count = trends["7_day"]["pm"]["count"]

        if expected_window == "am":
            assert am_count == 1, f"Expected AM for {tz_name} at UTC {utc_hour}:{minute}, got am={am_count}"
            assert pm_count == 0
        elif expected_window in ("pm", "pm_sharp"):
            assert pm_count == 1, f"Expected PM for {tz_name} at UTC {utc_hour}:{minute}, got pm={pm_count}"
            assert am_count == 0
        elif expected_window == "night":
            assert am_count == 0, f"Expected night exclusion for {tz_name} at UTC {utc_hour}:{minute}"
            assert pm_count == 0

    def test_minute_level_night_exclusion_at_22_00_vs_22_01(self):
        """Precision boundary test: 22:00:00 is PM, 22:00:59 is PM, but 22:01:00 is strictly excluded as night."""
        tz_name = "UTC"
        now_dt = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)

        def make_bp(h, m, s):
            return {
                "effective_at": datetime(2026, 10, 14, h, m, s, tzinfo=timezone.utc),
                "data": {
                    "component": [
                        {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 120}},
                        {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 80}},
                    ]
                },
            }

        # 22:00:00 -> PM
        r_22_00 = make_bp(22, 0, 0)
        trends = calculate_diurnal_bp_trends([r_22_00], now_dt=now_dt, user_tz=tz_name)
        assert trends["7_day"]["pm"]["count"] == 1

        # 22:00:59 -> PM (minute is 0)
        r_22_00_59 = make_bp(22, 0, 59)
        trends = calculate_diurnal_bp_trends([r_22_00_59], now_dt=now_dt, user_tz=tz_name)
        assert trends["7_day"]["pm"]["count"] == 1

        # 22:01:00 -> Excluded (Night)
        r_22_01 = make_bp(22, 1, 0)
        trends = calculate_diurnal_bp_trends([r_22_01], now_dt=now_dt, user_tz=tz_name)
        assert trends["7_day"]["pm"]["count"] == 0
        assert trends["7_day"]["am"]["count"] == 0

        # 04:59:59 -> Excluded (Night)
        r_04_59 = make_bp(4, 59, 59)
        trends = calculate_diurnal_bp_trends([r_04_59], now_dt=now_dt, user_tz=tz_name)
        assert trends["7_day"]["am"]["count"] == 0
        assert trends["7_day"]["pm"]["count"] == 0

        # 05:00:00 -> AM
        r_05_00 = make_bp(5, 0, 0)
        trends = calculate_diurnal_bp_trends([r_05_00], now_dt=now_dt, user_tz=tz_name)
        assert trends["7_day"]["am"]["count"] == 1

    def test_multi_window_moving_average_cutoffs(self):
        """Verifies 7-day, 30-day, and 90-day moving average cutoff thresholds."""
        now_dt = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)

        def make_timed_bp(days_ago, sys_val):
            dt = now_dt - timedelta(days=days_ago)
            # Set to 14:00 (PM window)
            dt = dt.replace(hour=14, minute=0, second=0)
            return {
                "effective_at": dt,
                "data": {
                    "component": [
                        {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": sys_val}},
                        {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 80}},
                    ]
                },
            }

        readings = [
            make_timed_bp(3, 120),    # within 7d, 30d, 90d
            make_timed_bp(15, 130),   # outside 7d, within 30d, 90d
            make_timed_bp(45, 140),   # outside 7d, 30d, within 90d
            make_timed_bp(100, 150),  # outside 90d (excluded from all)
            make_timed_bp(-1, 160),   # future reading (excluded from all)
        ]

        trends = calculate_diurnal_bp_trends(readings, now_dt=now_dt, user_tz="UTC")

        # 7-day: only reading at day 3 (sys=120)
        assert trends["7_day"]["pm"]["count"] == 1
        assert trends["7_day"]["pm"]["systolic"] == 120.0

        # 30-day: reading at day 3 and day 15 (sys=120, 130 -> avg 125.0)
        assert trends["30_day"]["pm"]["count"] == 2
        assert trends["30_day"]["pm"]["systolic"] == 125.0

        # 90-day: readings at day 3, 15, 45 (sys=120, 130, 140 -> avg 130.0)
        assert trends["90_day"]["pm"]["count"] == 3
        assert trends["90_day"]["pm"]["systolic"] == 130.0

    def test_diurnal_dst_transitions_america_new_york(self):
        """Stress tests DST transitions in America/New_York (Spring Forward in March, Fall Back in Nov)."""
        # 1. Spring forward: 2026-03-08 (EST -> EDT)
        # At 07:00 UTC on 2026-03-08: before 2 AM EST (UTC-5), 07:00 UTC is 02:00 -> 03:00 EDT
        # At 14:00 UTC on 2026-03-08: now in EDT (UTC-4), 14:00 UTC is 10:00 EDT (AM)
        # At 17:00 UTC on 2026-03-08: in EDT (UTC-4), 17:00 UTC is 13:00 EDT (PM)
        now_spring = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
        reading_am = {
            "effective_at": datetime(2026, 3, 8, 14, 0, 0, tzinfo=timezone.utc),
            "data": {
                "component": [
                    {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 118}},
                    {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 78}},
                ]
            },
        }
        reading_pm = {
            "effective_at": datetime(2026, 3, 8, 17, 0, 0, tzinfo=timezone.utc),
            "data": {
                "component": [
                    {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 128}},
                    {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 82}},
                ]
            },
        }
        trends_spring = calculate_diurnal_bp_trends([reading_am, reading_pm], now_dt=now_spring, user_tz="America/New_York")
        assert trends_spring["7_day"]["am"]["count"] == 1
        assert trends_spring["7_day"]["pm"]["count"] == 1

        # 2. Fall back: 2026-11-01 (EDT -> EST)
        # On 2026-11-02, offset is EST (UTC-5).
        # At 15:00 UTC on 2026-11-02: 15:00 - 5 = 10:00 EST (AM)
        now_fall = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        reading_fall_am = {
            "effective_at": datetime(2026, 11, 2, 15, 0, 0, tzinfo=timezone.utc),
            "data": {
                "component": [
                    {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 122}},
                    {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 80}},
                ]
            },
        }
        trends_fall = calculate_diurnal_bp_trends([reading_fall_am], now_dt=now_fall, user_tz="America/New_York")
        assert trends_fall["7_day"]["am"]["count"] == 1

    def test_diurnal_unparseable_timezone_fallback_to_utc(self):
        """Stress test: Unparseable/bogus timezone string falls back gracefully to UTC without crashing."""
        now_dt = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
        reading = {
            "effective_at": datetime(2026, 10, 14, 8, 0, 0, tzinfo=timezone.utc),
            "data": {
                "component": [
                    {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 120}},
                    {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 80}},
                ]
            },
        }
        trends = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz="Atlantis/Deep_Ocean")
        assert trends["7_day"]["am"]["count"] == 1

    def test_diurnal_resilience_to_malformed_readings(self):
        """Stress test: Ingesting readings with missing timestamps, invalid strings, or no BP components does not crash."""
        now_dt = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
        dirty_readings = [
            {"effective_at": None, "data": {}},
            {"effective_at": "invalid-timestamp-string", "data": {}},
            {"effective_at": datetime(2026, 10, 14, 14, 0, 0, tzinfo=timezone.utc), "data": {"component": []}},
            {"effective_at": datetime(2026, 10, 14, 14, 0, 0, tzinfo=timezone.utc), "data": None},
            # One valid reading
            {
                "effective_at": datetime(2026, 10, 14, 14, 0, 0, tzinfo=timezone.utc),
                "data": {
                    "component": [
                        {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 122}},
                        {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 82}},
                    ]
                },
            },
        ]
        trends = calculate_diurnal_bp_trends(dirty_readings, now_dt=now_dt, user_tz="UTC")
        assert trends["7_day"]["pm"]["count"] == 1
        assert trends["7_day"]["pm"]["systolic"] == 122.0


# ============================================================================
# FOCUS AREA 3: API IDEMPOTENCY & RBAC PERMISSION MATRIX STRESS TESTS
# ============================================================================


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def challenger_api_env(monkeypatch):
    """Sets up an isolated environment with multi-tenant profiles and fine-grained RBAC grants."""

    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        # Users:
        # 1. Owner (Alice) -> manage
        alice = await auth_adapter.register_user(
            email="chal_alice@test.local",
            username="chal_alice",
            password="AlicePass123!",
            full_name="Alice Owner",
            role="member",
            auth_provider="local",
        )
        alice_sess = await auth_adapter.create_session(alice.id)

        # 2. Clinician (Bob) -> view_clinical
        bob = await auth_adapter.register_user(
            email="chal_bob@test.local",
            username="chal_bob",
            password="BobPass123!",
            full_name="Bob Clinician",
            role="member",
            auth_provider="local",
        )
        bob_sess = await auth_adapter.create_session(bob.id)

        # 3. Clerk (Carol) -> view_paperwork
        carol = await auth_adapter.register_user(
            email="chal_carol@test.local",
            username="chal_carol",
            password="CarolPass123!",
            full_name="Carol Clerk",
            role="member",
            auth_provider="local",
        )
        carol_sess = await auth_adapter.create_session(carol.id)

        # 4. Outsider (Dave) -> no access
        dave = await auth_adapter.register_user(
            email="chal_dave@test.local",
            username="chal_dave",
            password="DavePass123!",
            full_name="Dave Outsider",
            role="member",
            auth_provider="local",
        )
        dave_sess = await auth_adapter.create_session(dave.id)

        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            # 1. Profile Adult (Alice)
            p_adult = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Alice Adult Profile",
                date_of_birth="1980-01-01",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
            session.add(p_adult)

            # 2. Profile Boundary 240 months
            # If now is approx 2026-10, 240 months ago is 2006-10
            # Let's set DOB to exactly 2006-10-15
            p_boundary_240 = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Boundary 240 Months",
                date_of_birth="2006-10-15",
                relationship="child",
                role="self",
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
            session.add(p_boundary_240)

            # 3. Profile Future DOB (Negative age_months)
            p_future_dob = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Future Baby",
                date_of_birth="2030-01-01",
                relationship="child",
                role="self",
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
            session.add(p_future_dob)

            # 4. Profile Non-Binary Gender
            p_nonbinary = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Jordan Nonbinary",
                date_of_birth="2020-05-10",  # ~6 years old
                relationship="child",
                role="self",
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
            setattr(p_nonbinary, "gender", "non-binary")
            session.add(p_nonbinary)

            # Access grants on p_adult:
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=p_adult.id,
                user_id=bob.id,
                access_level="view_clinical",
                granted_by=alice.id,
                granted_at=now,
            ))
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=p_adult.id,
                user_id=carol.id,
                access_level="view_paperwork",
                granted_by=alice.id,
                granted_at=now,
            ))

            await session.commit()

            return {
                "session_factory": session_factory,
                "p_adult_id": p_adult.id,
                "p_boundary_240_id": p_boundary_240.id,
                "p_future_dob_id": p_future_dob.id,
                "p_nonbinary_id": p_nonbinary.id,
                "alice_token": alice_sess.token,
                "bob_token": bob_sess.token,
                "carol_token": carol_sess.token,
                "dave_token": dave_sess.token,
            }

    data = run_async(_setup())
    session_factory = data["session_factory"]

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
        yield data
    finally:
        app.dependency_overrides.pop(get_db, None)
        reset_auth_port()


class TestApiPediatricAndIdempotencyStress:
    """API-level adversarial tests for BMI boundary, future DOB, non-binary gender, and idempotency."""

    def test_api_bmi_age_240_months_boundary_smooth_transition(self, challenger_api_env):
        """API stress: Age exactly 240 months transitions smoothly to adult BMI without 500 error."""
        client = TestClient(app)
        pid = challenger_api_env["p_boundary_240_id"]
        token = challenger_api_env["alice_token"]

        # Effective date: 2026-10-15 (exactly 240 months from 2006-10-15)
        payload = {
            "vitals": {
                "weight": 68.0,
                "height": 172.0,
                "unit": "kg",
            },
            "effective_at": "2026-10-15T10:00:00Z",
        }

        resp = client.post(
            f"/api/profiles/{pid}/vitals",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, f"Expected 201 Created, got {resp.status_code}: {resp.text}"
        data = resp.json()
        bmi = data["bmi"]
        assert bmi is not None
        assert bmi["bmi"] == 23.0  # 68 / (1.72^2) = 22.98 -> 23.0
        assert bmi["suppressed"] is False
        assert bmi["classification"] == "Normal weight"
        # Since age is 240 months, it transitions to adult BMI: percentile is None
        assert bmi["percentile"] is None

    def test_api_bmi_future_dob_graceful_suppression(self, challenger_api_env):
        """API stress: Profile with future DOB produces negative age_months; API gracefully suppresses BMI with 201 (no 500)."""
        client = TestClient(app)
        pid = challenger_api_env["p_future_dob_id"]
        token = challenger_api_env["alice_token"]

        payload = {
            "vitals": {
                "weight": 5.0,
                "height": 55.0,
                "unit": "kg",
            },
            "effective_at": "2026-10-15T10:00:00Z",
        }

        resp = client.post(
            f"/api/profiles/{pid}/vitals",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, f"Expected 201 Created, got {resp.status_code}: {resp.text}"
        data = resp.json()
        bmi = data["bmi"]
        assert bmi is not None
        assert bmi["suppressed"] is True
        assert bmi["bmi"] is None
        assert bmi["percentile"] is None
        assert "future" in bmi["reason"].lower()

    def test_api_bmi_non_binary_gender_graceful_adult_fallback(self, challenger_api_env, monkeypatch):
        """API stress: Pediatric profile with non-binary gender falls back to adult BMI and suppresses LMS percentile (no 500)."""
        pid = challenger_api_env["p_nonbinary_id"]
        token = challenger_api_env["alice_token"]

        # Simulate profile with non-binary gender
        monkeypatch.setattr(
            Profile,
            "gender",
            property(lambda self: "non-binary" if self.id == pid else "male"),
            raising=False,
        )

        client = TestClient(app)
        payload = {
            "vitals": {
                "weight": 22.0,
                "height": 115.0,
                "unit": "kg",
            },
            "effective_at": "2026-10-15T10:00:00Z",
        }

        resp = client.post(
            f"/api/profiles/{pid}/vitals",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, f"Expected 201 Created, got {resp.status_code}: {resp.text}"
        data = resp.json()
        bmi = data["bmi"]
        assert bmi is not None
        assert bmi["bmi"] is not None  # Adult BMI computed
        assert bmi["percentile"] is None  # CDC biological sex percentile suppressed
        assert "non-binary" in bmi["reason"].lower() or "biological sex" in bmi["reason"].lower()

    def test_api_idempotency_duplicate_returns_409(self, challenger_api_env):
        """API stress: Re-posting duplicate source_ref & source_id returns HTTP 409 Conflict with clear detail."""
        client = TestClient(app)
        pid = challenger_api_env["p_adult_id"]
        token = challenger_api_env["alice_token"]

        payload = {
            "vitals": {"systolic": 126, "diastolic": 82},
            "source_type": "device",
            "source_ref": "challenger_bp_gauge",
            "source_id": "reading_stress_unique_99",
        }

        # 1. First post -> 201 Created
        r1 = client.post(
            f"/api/profiles/{pid}/vitals",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 201

        # 2. Immediate duplicate post -> 409 Conflict
        r2 = client.post(
            f"/api/profiles/{pid}/vitals",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 409
        assert "Duplicate" in r2.json()["detail"]

        # 3. Post with DIFFERENT source_id -> 201 Created
        payload_diff = dict(payload)
        payload_diff["source_id"] = "reading_stress_unique_100"
        r3 = client.post(
            f"/api/profiles/{pid}/vitals",
            json=payload_diff,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 201

    def test_api_rbac_strict_role_matrix(self, challenger_api_env):
        """API stress: Exhaustive verification of RBAC permissions across manage, view_clinical, view_paperwork, outsider, unauthenticated."""
        client = TestClient(app)
        pid = challenger_api_env["p_adult_id"]
        alice_tok = challenger_api_env["alice_token"]
        bob_tok = challenger_api_env["bob_token"]
        carol_tok = challenger_api_env["carol_token"]
        dave_tok = challenger_api_env["dave_token"]

        write_data = {"vitals": {"systolic": 120, "diastolic": 80}}

        # --- A. Unauthenticated ---
        assert client.post(f"/api/profiles/{pid}/vitals", json=write_data).status_code == 401
        assert client.get(f"/api/profiles/{pid}/vitals").status_code == 401
        assert client.get(f"/api/profiles/{pid}/vitals/trends").status_code == 401

        # --- B. Dave (Authenticated but ungranted) ---
        assert client.post(f"/api/profiles/{pid}/vitals", json=write_data, headers={"Authorization": f"Bearer {dave_tok}"}).status_code == 403
        assert client.get(f"/api/profiles/{pid}/vitals", headers={"Authorization": f"Bearer {dave_tok}"}).status_code == 403
        assert client.get(f"/api/profiles/{pid}/vitals/trends", headers={"Authorization": f"Bearer {dave_tok}"}).status_code == 403

        # --- C. Carol ('view_paperwork' access only) ---
        assert client.post(f"/api/profiles/{pid}/vitals", json=write_data, headers={"Authorization": f"Bearer {carol_tok}"}).status_code == 403
        assert client.get(f"/api/profiles/{pid}/vitals", headers={"Authorization": f"Bearer {carol_tok}"}).status_code == 403
        assert client.get(f"/api/profiles/{pid}/vitals/trends", headers={"Authorization": f"Bearer {carol_tok}"}).status_code == 403

        # --- D. Bob ('view_clinical' access only) ---
        assert client.post(f"/api/profiles/{pid}/vitals", json=write_data, headers={"Authorization": f"Bearer {bob_tok}"}).status_code == 403
        assert client.get(f"/api/profiles/{pid}/vitals", headers={"Authorization": f"Bearer {bob_tok}"}).status_code == 200
        assert client.get(f"/api/profiles/{pid}/vitals/trends", headers={"Authorization": f"Bearer {bob_tok}"}).status_code == 200

        # --- E. Alice ('manage' access / owner) ---
        assert client.post(f"/api/profiles/{pid}/vitals", json=write_data, headers={"Authorization": f"Bearer {alice_tok}"}).status_code == 201
        assert client.get(f"/api/profiles/{pid}/vitals", headers={"Authorization": f"Bearer {alice_tok}"}).status_code == 200
        assert client.get(f"/api/profiles/{pid}/vitals/trends", headers={"Authorization": f"Bearer {alice_tok}"}).status_code == 200

    def test_api_manual_readings_without_source_identifiers_no_collision(self, challenger_api_env):
        """API stress: Repeated manual readings without source_ref and source_id do NOT conflict (both 201)."""
        client = TestClient(app)
        pid = challenger_api_env["p_adult_id"]
        alice_tok = challenger_api_env["alice_token"]

        payload = {
            "vitals": {"systolic": 119, "diastolic": 77},
            "source_type": "manual",
            "source_ref": None,
            "source_id": None,
        }

        r1 = client.post(f"/api/profiles/{pid}/vitals", json=payload, headers={"Authorization": f"Bearer {alice_tok}"})
        assert r1.status_code == 201

        r2 = client.post(f"/api/profiles/{pid}/vitals", json=payload, headers={"Authorization": f"Bearer {alice_tok}"})
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]

    def test_api_corrupted_dob_falls_back_to_adult_bmi_without_500(self, challenger_api_env, monkeypatch):
        """API stress: Profile with corrupted date_of_birth string falls back to adult BMI gracefully without 500 error."""
        pid = challenger_api_env["p_adult_id"]
        alice_tok = challenger_api_env["alice_token"]

        # Simulate profile with unparseable date_of_birth
        monkeypatch.setattr(
            Profile,
            "date_of_birth",
            property(lambda self: "invalid-dob-string" if self.id == pid else "1980-01-01"),
            raising=False,
        )

        client = TestClient(app)
        payload = {
            "vitals": {"weight": 70.0, "height": 175.0, "unit": "kg"},
        }
        resp = client.post(
            f"/api/profiles/{pid}/vitals",
            json=payload,
            headers={"Authorization": f"Bearer {alice_tok}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["bmi"] is not None
        assert data["bmi"]["bmi"] == 22.9
        assert data["bmi"]["suppressed"] is False

    def test_api_invalid_bearer_token_returns_401(self, challenger_api_env):
        """API stress: Malformed or forged Bearer tokens return HTTP 401 Unauthorized across all endpoints."""
        client = TestClient(app)
        pid = challenger_api_env["p_adult_id"]
        bad_token = "Bearer forged_secret_token_never_issued"

        assert client.post(f"/api/profiles/{pid}/vitals", json={"vitals": {"systolic": 120, "diastolic": 80}}, headers={"Authorization": bad_token}).status_code == 401
        assert client.get(f"/api/profiles/{pid}/vitals", headers={"Authorization": bad_token}).status_code == 401
        assert client.get(f"/api/profiles/{pid}/vitals/trends", headers={"Authorization": bad_token}).status_code == 401
