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

"""Adversarial stress testing harness for Milestone 2: Temporal Diurnal BP, Pediatric BMI, and API Security/RBAC."""

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
    calculate_adult_bmi_imperial,
    calculate_pediatric_bmi_percentile,
)
from carefold.clinical.vitals import (
    calculate_diurnal_bp_trends,
    classify_blood_pressure,
    normalize_fhir_vitals,
)
from carefold.config import settings
from carefold.db.models import HealthResource, Profile, ProfileAccess
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


# ============================================================================
# PART 1: DIURNAL BP TIMEZONE & AM/PM/NIGHT STRESS TESTING
# ============================================================================


class TestDiurnalBpTimezoneStress:
    """Adversarial empirical testing of diurnal BP trends across global timezones."""

    def test_timezone_shifts_across_four_major_zones(self):
        """Tests that a single UTC timestamp is correctly partitioned across 4 distinct timezones.

        Timezones:
        1. UTC (offset 0)
        2. America/New_York (EDT, offset -4)
        3. Asia/Tokyo (JST, offset +9)
        4. Pacific/Honolulu (HST, offset -10)
        """
        # Timestamp: 2026-10-10 10:00:00 UTC
        # - UTC: 10:00 -> AM (05:00 - 11:59)
        # - New York (-4): 06:00 -> AM (05:00 - 11:59)
        # - Tokyo (+9): 19:00 -> PM (12:00 - 22:00)
        # - Honolulu (-10): 00:00 -> Night reading (EXCLUDED)
        now_dt = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
        reading_dt = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)
        reading = {
            "effective_at": reading_dt,
            "data": {
                "resourceType": "Observation",
                "component": [
                    {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 120}},
                    {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 80}},
                ],
            },
        }

        # 1. UTC
        trends_utc = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz="UTC")
        assert trends_utc["7_day"]["am"]["count"] == 1
        assert trends_utc["7_day"]["pm"]["count"] == 0

        # 2. America/New_York
        trends_ny = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz="America/New_York")
        assert trends_ny["7_day"]["am"]["count"] == 1
        assert trends_ny["7_day"]["pm"]["count"] == 0

        # 3. Asia/Tokyo
        trends_tokyo = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz="Asia/Tokyo")
        assert trends_tokyo["7_day"]["am"]["count"] == 0
        assert trends_tokyo["7_day"]["pm"]["count"] == 1

        # 4. Pacific/Honolulu
        trends_honolulu = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz="Pacific/Honolulu")
        assert trends_honolulu["7_day"]["am"]["count"] == 0
        assert trends_honolulu["7_day"]["pm"]["count"] == 0

    def test_pm_shift_across_timezones(self):
        """Tests reading at 17:00 UTC partitioned across New York, Tokyo, and Honolulu."""
        # 2026-10-10 17:00:00 UTC
        # - UTC: 17:00 -> PM
        # - New York (-4): 13:00 -> PM
        # - Tokyo (+9): 02:00 (+1 day) -> Night (EXCLUDED)
        # - Honolulu (-10): 07:00 -> AM
        now_dt = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        reading_dt = datetime(2026, 10, 10, 17, 0, 0, tzinfo=timezone.utc)
        reading = {
            "effective_at": reading_dt,
            "data": {
                "component": [
                    {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 130}},
                    {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 85}},
                ]
            },
        }

        trends_utc = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz="UTC")
        assert trends_utc["7_day"]["pm"]["count"] == 1
        assert trends_utc["7_day"]["am"]["count"] == 0

        trends_ny = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz="America/New_York")
        assert trends_ny["7_day"]["pm"]["count"] == 1
        assert trends_ny["7_day"]["am"]["count"] == 0

        trends_tokyo = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz="Asia/Tokyo")
        assert trends_tokyo["7_day"]["pm"]["count"] == 0
        assert trends_tokyo["7_day"]["am"]["count"] == 0

        trends_honolulu = calculate_diurnal_bp_trends([reading], now_dt=now_dt, user_tz="Pacific/Honolulu")
        assert trends_honolulu["7_day"]["am"]["count"] == 1
        assert trends_honolulu["7_day"]["pm"]["count"] == 0

    def test_strict_wall_clock_am_pm_and_night_boundaries(self):
        """Stress tests exact boundary times for AM, PM, and AHA/ACC night exclusion."""
        tz_str = "America/New_York"
        tz = ZoneInfo(tz_str)
        ref_day = datetime(2026, 10, 10, tzinfo=tz)
        now_dt = ref_day + timedelta(days=2)

        def make_reading(hour, minute, second, sys=120, dia=80):
            dt = ref_day.replace(hour=hour, minute=minute, second=second)
            return {
                "effective_at": dt.astimezone(timezone.utc),
                "data": {
                    "component": [
                        {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": sys}},
                        {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": dia}},
                    ]
                },
            }

        readings = [
            # Night boundary before AM
            make_reading(4, 59, 59),  # 04:59:59 -> Night (EXCLUDED)
            # AM start
            make_reading(5, 0, 0),    # 05:00:00 -> AM
            # AM end
            make_reading(11, 59, 59), # 11:59:59 -> AM
            # PM start
            make_reading(12, 0, 0),   # 12:00:00 -> PM
            # PM middle
            make_reading(18, 30, 0),  # 18:30:00 -> PM
            # PM end
            make_reading(22, 0, 0),   # 22:00:00 -> PM
            # Night boundary after PM
            make_reading(22, 1, 0),   # 22:01:00 -> Night (EXCLUDED)
            make_reading(23, 30, 0),  # 23:30:00 -> Night (EXCLUDED)
            make_reading(0, 0, 0),    # 00:00:00 -> Night (EXCLUDED)
            make_reading(2, 15, 0),   # 02:15:00 -> Night (EXCLUDED)
        ]

        trends = calculate_diurnal_bp_trends(readings, now_dt=now_dt, user_tz=tz_str)
        am_metrics = trends["7_day"]["am"]
        pm_metrics = trends["7_day"]["pm"]

        # Exactly 2 readings in AM: 05:00:00 and 11:59:59
        assert am_metrics["count"] == 2
        # Exactly 3 readings in PM: 12:00:00, 18:30:00, 22:00:00
        assert pm_metrics["count"] == 3
        # Exactly 5 readings excluded as night readings

    def test_all_night_readings_yield_insufficient_data(self):
        """Verifies that a cohort containing only night readings (22:01 to 04:59) produces count=0 and Insufficient Data."""
        tz_str = "UTC"
        now_dt = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        night_readings = [
            {
                "effective_at": datetime(2026, 10, 9, 22, 5, 0, tzinfo=timezone.utc),
                "data": {"component": [{"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 150}}, {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 95}}]},
            },
            {
                "effective_at": datetime(2026, 10, 9, 23, 45, 0, tzinfo=timezone.utc),
                "data": {"component": [{"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 140}}, {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 90}}]},
            },
            {
                "effective_at": datetime(2026, 10, 10, 1, 30, 0, tzinfo=timezone.utc),
                "data": {"component": [{"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 135}}, {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 85}}]},
            },
            {
                "effective_at": datetime(2026, 10, 10, 4, 30, 0, tzinfo=timezone.utc),
                "data": {"component": [{"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 130}}, {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 80}}]},
            },
        ]
        trends = calculate_diurnal_bp_trends(night_readings, now_dt=now_dt, user_tz=tz_str)
        assert trends["7_day"]["am"]["count"] == 0
        assert trends["7_day"]["am"]["classification"] == "Insufficient Data"
        assert trends["7_day"]["pm"]["count"] == 0
        assert trends["7_day"]["pm"]["classification"] == "Insufficient Data"


# ============================================================================
# PART 2: PEDIATRIC CDC LMS BMI STRESS TESTING
# ============================================================================


class TestPediatricBmiCdcLmsStress:
    """Adversarial stress testing of CDC LMS Box-Cox curves and age boundaries."""

    def test_age_23_months_is_suppressed(self):
        """Clinical Invariant: Exact age 23 months must be suppressed."""
        res = calculate_pediatric_bmi_percentile(
            age_months=23,
            gender="male",
            weight_kg=12.0,
            height_cm=86.0,
        )
        assert res["suppressed"] is True
        assert res["bmi"] is None
        assert res["percentile"] is None
        assert "under 24 months" in res["reason"]

    def test_age_24_months_first_valid_pediatric_percentile(self):
        """Boundary: Exact age 24 months (2nd birthday) computes valid percentile and category."""
        res = calculate_pediatric_bmi_percentile(
            age_months=24,
            gender="female",
            weight_kg=12.2,
            height_cm=86.5,
        )
        assert res["suppressed"] is False
        assert res["bmi"] is not None
        assert isinstance(res["percentile"], float)
        assert 0.1 <= res["percentile"] <= 99.9
        assert res["classification"] in ("Underweight", "Healthy weight", "Overweight", "Obesity")
        assert res.get("is_adult") is not True

    def test_age_239_months_last_valid_pediatric_curve(self):
        """Boundary: Exact age 239 months (19 years 11 months) calculates pediatric curve."""
        res = calculate_pediatric_bmi_percentile(
            age_months=239,
            gender="male",
            weight_kg=68.0,
            height_cm=176.0,
        )
        assert res["suppressed"] is False
        assert res["bmi"] is not None
        assert isinstance(res["percentile"], float)
        assert res.get("is_adult") is not True

    def test_age_240_months_behavior_check(self):
        """Empirical Investigation: Test exact age 240 months behavior.

        CDC pediatric curves cover ages 2 to 19 (24 to 239 months).
        Age 240 months (20.0 years) is the transition point to adult BMI.
        Checks whether calculate_pediatric_bmi_percentile(240) transitions to adult BMI or calculates pediatric curve.
        """
        res = calculate_pediatric_bmi_percentile(
            age_months=240,
            gender="male",
            weight_kg=75.0,
            height_cm=178.0,
        )
        # Record actual empirical return structure
        assert res["suppressed"] is False
        assert res["bmi"] is not None

    def test_extreme_low_and_high_bmi_percentiles(self):
        """Tests that extreme BMI percentiles are bounded within [0.1, 99.9] and classified correctly."""
        # Extreme low BMI: age 5, male, 9kg, 120cm -> BMI = 6.25
        low_res = calculate_pediatric_bmi_percentile(
            age_months=60,
            gender="male",
            weight_kg=9.0,
            height_cm=120.0,
        )
        assert low_res["percentile"] == 0.1
        assert low_res["classification"] == "Underweight"
        assert low_res["z_score"] < -3.0

        # Extreme high BMI: age 10, male, 85kg, 130cm -> BMI = 50.3
        high_res = calculate_pediatric_bmi_percentile(
            age_months=120,
            gender="male",
            weight_kg=85.0,
            height_cm=130.0,
        )
        assert high_res["percentile"] == 99.9
        assert high_res["classification"] == "Obesity"
        assert high_res["z_score"] > 3.0

    def test_invalid_input_rejections(self):
        """Tests that negative or zero measurements raise ValueError."""
        with pytest.raises(ValueError, match="strictly positive"):
            calculate_pediatric_bmi_percentile(48, "male", -10.0, 100.0)

        with pytest.raises(ValueError, match="strictly positive"):
            calculate_pediatric_bmi_percentile(48, "male", 15.0, 0.0)

        with pytest.raises(ValueError, match="non-negative"):
            calculate_pediatric_bmi_percentile(-1, "male", 15.0, 100.0)

        with pytest.raises(ValueError, match="Invalid gender"):
            calculate_pediatric_bmi_percentile(48, "other", 15.0, 100.0)  # type: ignore


# ============================================================================
# PART 3: API IDEMPOTENCY & ROLE-BASED ACCESS CONTROL STRESS TESTING
# ============================================================================


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def api_stress_env(monkeypatch):
    """Sets up an isolated database and test users with granular RBAC permissions."""

    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        # 1. Owner (Alice) -> manage
        alice = await auth_adapter.register_user(
            email="stress_alice@test.local",
            username="stress_alice",
            password="AlicePassword123!",
            full_name="Alice Owner",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # 2. Clinician (Charlie) -> view_clinical
        charlie = await auth_adapter.register_user(
            email="stress_charlie@test.local",
            username="stress_charlie",
            password="CharliePassword123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # 3. Paperwork Clerk (Dan) -> view_paperwork
        dan = await auth_adapter.register_user(
            email="stress_dan@test.local",
            username="stress_dan",
            password="DanPassword123!",
            full_name="Dan Clerk",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # 4. Outsider (Eve) -> ungranted
        eve = await auth_adapter.register_user(
            email="stress_eve@test.local",
            username="stress_eve",
            password="EvePassword123!",
            full_name="Eve Outsider",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            # Primary profile for Alice
            alice_p = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Alice Primary",
                date_of_birth="1992-04-10",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
            session.add(alice_p)

            # Secondary profile for Alice
            second_p = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Alice Secondary",
                date_of_birth="2018-05-15",
                relationship="child",
                role="self",
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
            session.add(second_p)

            # Access grants
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=alice_p.id,
                user_id=charlie.id,
                access_level="view_clinical",
                granted_by=alice.id,
                granted_at=now,
            ))
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=alice_p.id,
                user_id=dan.id,
                access_level="view_paperwork",
                granted_by=alice.id,
                granted_at=now,
            ))
            await session.commit()

            return {
                "session_factory": session_factory,
                "alice_profile_id": alice_p.id,
                "second_profile_id": second_p.id,
                "alice_token": alice_session.token,
                "charlie_token": charlie_session.token,
                "dan_token": dan_session.token,
                "eve_token": eve_session.token,
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


class TestApiIdempotencyAndRbacStress:
    """Empirical tests for API idempotency collisions and multi-tenant access control."""

    def test_idempotency_collision_returns_409(self, api_stress_env):
        """Repeated submission with identical (profile_id, source_type, source_ref, source_id) returns HTTP 409."""
        client = TestClient(app)
        pid = api_stress_env["alice_profile_id"]
        token = api_stress_env["alice_token"]

        payload = {
            "vitals": {"systolic": 122, "diastolic": 78},
            "source_type": "device",
            "source_ref": "withings_bpm_core",
            "source_id": "reading_adversarial_001",
        }

        # First request -> 201 Created
        r1 = client.post(
            f"/api/profiles/{pid}/vitals",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 201

        # Second request with identical identifiers -> 409 Conflict
        r2 = client.post(
            f"/api/profiles/{pid}/vitals",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 409
        assert "Duplicate" in r2.json()["detail"]

        # Third request with same source_id on DIFFERENT profile -> 201 Created (scoped per profile)
        p2_id = api_stress_env["second_profile_id"]
        r3 = client.post(
            f"/api/profiles/{p2_id}/vitals",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 201

    def test_rbac_matrix_enforcement(self, api_stress_env):
        """Verifies access permissions across all 4 roles: manage, view_clinical, view_paperwork, and unauthenticated."""
        client = TestClient(app)
        pid = api_stress_env["alice_profile_id"]
        alice_tok = api_stress_env["alice_token"]
        charlie_tok = api_stress_env["charlie_token"]
        dan_tok = api_stress_env["dan_token"]
        eve_tok = api_stress_env["eve_token"]

        write_payload = {"vitals": {"systolic": 118, "diastolic": 76}}

        # 1. Unauthenticated (no token) -> 401 Unauthorized
        r_unauth_write = client.post(f"/api/profiles/{pid}/vitals", json=write_payload)
        assert r_unauth_write.status_code == 401

        r_unauth_read = client.get(f"/api/profiles/{pid}/vitals")
        assert r_unauth_read.status_code == 401

        r_unauth_trends = client.get(f"/api/profiles/{pid}/vitals/trends")
        assert r_unauth_trends.status_code == 401

        # 2. Eve (Authenticated user with NO access to profile) -> 403 Forbidden
        r_eve_write = client.post(
            f"/api/profiles/{pid}/vitals",
            json=write_payload,
            headers={"Authorization": f"Bearer {eve_tok}"},
        )
        assert r_eve_write.status_code == 403

        r_eve_read = client.get(
            f"/api/profiles/{pid}/vitals",
            headers={"Authorization": f"Bearer {eve_tok}"},
        )
        assert r_eve_read.status_code == 403

        # 3. Dan ('view_paperwork' access only) -> 403 Forbidden on all clinical vitals endpoints
        r_dan_write = client.post(
            f"/api/profiles/{pid}/vitals",
            json=write_payload,
            headers={"Authorization": f"Bearer {dan_tok}"},
        )
        assert r_dan_write.status_code == 403

        r_dan_read = client.get(
            f"/api/profiles/{pid}/vitals",
            headers={"Authorization": f"Bearer {dan_tok}"},
        )
        assert r_dan_read.status_code == 403

        r_dan_trends = client.get(
            f"/api/profiles/{pid}/vitals/trends",
            headers={"Authorization": f"Bearer {dan_tok}"},
        )
        assert r_dan_trends.status_code == 403

        # 4. Charlie ('view_clinical' access only) -> 403 on write, 200 on read & trends
        r_charlie_write = client.post(
            f"/api/profiles/{pid}/vitals",
            json=write_payload,
            headers={"Authorization": f"Bearer {charlie_tok}"},
        )
        assert r_charlie_write.status_code == 403

        r_charlie_read = client.get(
            f"/api/profiles/{pid}/vitals",
            headers={"Authorization": f"Bearer {charlie_tok}"},
        )
        assert r_charlie_read.status_code == 200

        r_charlie_trends = client.get(
            f"/api/profiles/{pid}/vitals/trends",
            headers={"Authorization": f"Bearer {charlie_tok}"},
        )
        assert r_charlie_trends.status_code == 200

        # 5. Alice ('manage' access) -> 201 on write, 200 on read & trends
        r_alice_write = client.post(
            f"/api/profiles/{pid}/vitals",
            json=write_payload,
            headers={"Authorization": f"Bearer {alice_tok}"},
        )
        assert r_alice_write.status_code == 201

        r_alice_read = client.get(
            f"/api/profiles/{pid}/vitals",
            headers={"Authorization": f"Bearer {alice_tok}"},
        )
        assert r_alice_read.status_code == 200

        r_alice_trends = client.get(
            f"/api/profiles/{pid}/vitals/trends",
            headers={"Authorization": f"Bearer {alice_tok}"},
        )
        assert r_alice_trends.status_code == 200
