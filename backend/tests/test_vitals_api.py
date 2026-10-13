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

"""Unit and integration test suite for Vitals REST API, Diurnal Trends, and Safety Red Flags (AU-30, AU-31, AU-32)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.db.models import HealthResource, Profile, ProfileAccess
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


def run_async(coro):
    """Runs an asynchronous coroutine synchronously in an isolated event loop."""
    return asyncio.run(coro)


@pytest.fixture
def vitals_test_env(monkeypatch):
    """Sets up an isolated in-memory DB, SQL auth provider, test users and profiles."""

    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        # 1. Alice (Account Owner, 'manage' access)
        alice = await auth_adapter.register_user(
            email="alice@test.local",
            username="alice",
            password="AlicePassword123!",
            full_name="Alice Owner",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # 2. Bob (Delegate with explicit 'manage' access)
        bob = await auth_adapter.register_user(
            email="bob@test.local",
            username="bob",
            password="BobPassword123!",
            full_name="Bob Manager",
            role="member",
            auth_provider="local",
        )
        bob_session = await auth_adapter.create_session(bob.id)

        # 3. Charlie (Viewer with 'view_clinical' access only)
        charlie = await auth_adapter.register_user(
            email="charlie@test.local",
            username="charlie",
            password="CharliePassword123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # 4. Dan (Viewer with 'view_paperwork' access only)
        dan = await auth_adapter.register_user(
            email="dan@test.local",
            username="dan",
            password="DanPassword123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # 5. Eve (Unauthorized external user)
        eve = await auth_adapter.register_user(
            email="eve@test.local",
            username="eve",
            password="EvePassword123!",
            full_name="Eve Attacker",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        # Provision profiles
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            # Adult profile (Alice)
            alice_profile = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Alice Adult",
                date_of_birth="1985-06-15",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
            session.add(alice_profile)

            # Child profile (Leo, 5 years old)
            leo_profile = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Leo Child",
                date_of_birth=(now.date() - timedelta(days=5 * 365)).isoformat(),
                relationship="child",
                role="self",
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
            session.add(leo_profile)

            # Infant profile (Baby, 14 months old)
            infant_profile = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Baby Infant",
                date_of_birth=(now.date() - timedelta(days=14 * 30)).isoformat(),
                relationship="child",
                role="self",
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
            session.add(infant_profile)

            # Profile with hide_weight preference
            hidden_profile = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Private Profile",
                date_of_birth="1990-01-01",
                relationship="self",
                role="self",
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
            setattr(hidden_profile, "hide_weight", True)
            session.add(hidden_profile)

            from carefold.api.vitals import set_profile_preference
            set_profile_preference(hidden_profile.id, "hide_weight", True)

            # Grants on alice_profile
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
                "alice_profile_id": alice_profile.id,
                "leo_profile_id": leo_profile.id,
                "infant_profile_id": infant_profile.id,
                "hidden_profile_id": hidden_profile.id,
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


# ============================================================================
# Section 1: POST /api/profiles/{profile_id}/vitals Tests
# ============================================================================


def test_post_vitals_normal_reading(vitals_test_env):
    """POST /vitals successfully records normal blood pressure and returns FHIR Observation."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {
        "vitals": {
            "systolic": 118,
            "diastolic": 76,
            "heart_rate": 72,
        },
        "source_type": "manual",
    }
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["profile_id"] == pid
    assert data["resource_type"] == "observation"
    assert data["status"] == "active"
    assert data["safety_flag"]["triggered"] is False
    assert data["safety_flag"]["severity"] == "normal"
    assert "data" in data
    assert data["data"]["resourceType"] == "Observation"


def test_post_vitals_hypertensive_crisis_symptomatic(vitals_test_env):
    """POST /vitals detects acute symptomatic hypertensive crisis with Call 911 directive."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {
        "vitals": {
            "systolic": 195,
            "diastolic": 125,
        },
        "reported_symptoms": ["chest pain", "shortness of breath"],
    }
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    flag = resp.json()["safety_flag"]
    assert flag["triggered"] is True
    assert flag["category"] == "bp_crisis_symptomatic"
    assert flag["severity"] == "emergency"
    assert flag["prompt_recheck"] is False
    assert "Call 911" in flag["directive"]


def test_post_vitals_hypertensive_crisis_asymptomatic(vitals_test_env):
    """POST /vitals detects asymptomatic hypertensive crisis with 5-minute recheck directive."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {
        "vitals": {
            "systolic": 185,
            "diastolic": 115,
        },
        "reported_symptoms": [],
    }
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    flag = resp.json()["safety_flag"]
    assert flag["triggered"] is True
    assert flag["category"] == "bp_crisis_asymptomatic"
    assert flag["severity"] == "urgent"
    assert flag["prompt_recheck"] is True
    assert "Rest quietly for 5 minutes" in flag["directive"]


def test_post_vitals_severe_hypoxemia(vitals_test_env):
    """POST /vitals detects severe hypoxemia when SpO2 < 90%."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {"vitals": {"spo2": 87.0}}
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    flag = resp.json()["safety_flag"]
    assert flag["triggered"] is True
    assert flag["category"] == "severe_hypoxemia"
    assert flag["severity"] == "emergency"


def test_post_vitals_severe_hypoglycemia(vitals_test_env):
    """POST /vitals detects severe hypoglycemia when glucose < 54 mg/dL."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {"vitals": {"blood_glucose": 48.0}}
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    flag = resp.json()["safety_flag"]
    assert flag["triggered"] is True
    assert flag["category"] == "severe_hypoglycemia"
    assert flag["severity"] == "urgent"
    assert "Rule of 15" in flag["directive"]


def test_post_vitals_symptomatic_hypotension(vitals_test_env):
    """POST /vitals detects symptomatic hypotension (<90/60 with dizziness)."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {
        "vitals": {"systolic": 84, "diastolic": 56},
        "reported_symptoms": ["dizziness"],
    }
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    flag = resp.json()["safety_flag"]
    assert flag["triggered"] is True
    assert flag["category"] == "symptomatic_hypotension"


def test_post_vitals_adult_bmi_derivation(vitals_test_env):
    """POST /vitals computes adult BMI when height and weight are provided."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {
        "vitals": {
            "weight": 70.0,
            "height": 175.0,
            "unit": "kg",
        }
    }
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    bmi = resp.json()["bmi"]
    assert bmi is not None
    assert round(bmi["bmi"], 1) == 22.9
    assert bmi["classification"] == "Normal weight"


def test_post_vitals_pediatric_lms_percentile(vitals_test_env):
    """POST /vitals computes CDC pediatric LMS percentiles for child under 20."""
    client = TestClient(app)
    pid = vitals_test_env["leo_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {
        "vitals": {
            "weight": 18.5,
            "height": 110.0,
        }
    }
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    bmi = resp.json()["bmi"]
    assert bmi is not None
    assert bmi["percentile"] is not None
    assert bmi["classification"] in ("Healthy weight", "Normal weight")


def test_post_vitals_pediatric_infant_suppression(vitals_test_env):
    """POST /vitals clinically suppresses BMI for infants under 24 months."""
    client = TestClient(app)
    pid = vitals_test_env["infant_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {
        "vitals": {
            "weight": 10.2,
            "height": 78.0,
        }
    }
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    bmi = resp.json()["bmi"]
    assert bmi is not None
    assert bmi["suppressed"] is True
    assert bmi["bmi"] is None
    assert "under 24 months" in bmi["reason"]


def test_post_vitals_hide_weight_privacy_toggle(vitals_test_env):
    """POST /vitals respects hide_weight privacy toggle and suppresses BMI output."""
    client = TestClient(app)
    pid = vitals_test_env["hidden_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {
        "vitals": {
            "weight": 65.0,
            "height": 170.0,
        }
    }
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    bmi = resp.json()["bmi"]
    assert bmi is not None
    assert bmi["suppressed"] is True
    assert bmi["weight_hidden"] is True
    assert bmi["bmi"] is None


def test_post_vitals_physiological_validation_errors(vitals_test_env):
    """POST /vitals rejects invalid physiological values with HTTP 400."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    # 1. Systolic <= Diastolic (80/120)
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json={"vitals": {"systolic": 80, "diastolic": 120}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "strictly greater" in resp.json()["detail"]

    # 2. Systolic without diastolic
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json={"vitals": {"systolic": 120}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "together" in resp.json()["detail"]

    # 3. Non-positive weight
    resp = client.post(
        f"/api/profiles/{pid}/vitals",
        json={"vitals": {"weight": -5.0, "height": 170}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "strictly positive" in resp.json()["detail"]


def test_post_vitals_idempotency_conflict(vitals_test_env):
    """POST /vitals returns HTTP 409 Conflict on duplicate source identifier."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    payload = {
        "vitals": {"systolic": 120, "diastolic": 80},
        "source_type": "device",
        "source_ref": "omron_connect_1",
        "source_id": "reading_99812",
    }
    r1 = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 201

    # Second insert with identical source_ref and source_id
    r2 = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 409
    assert "Duplicate" in r2.json()["detail"]


def test_post_vitals_permissions(vitals_test_env):
    """POST /vitals enforces 'manage' access and blocks unauthorized users."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]

    payload = {"vitals": {"systolic": 120, "diastolic": 80}}

    # Bob has 'manage' -> Allowed
    r_bob = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {vitals_test_env['bob_token']}"},
    )
    assert r_bob.status_code == 201

    # Charlie has 'view_clinical' only -> Forbidden (403)
    r_charlie = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {vitals_test_env['charlie_token']}"},
    )
    assert r_charlie.status_code == 403

    # Dan has 'view_paperwork' only -> Forbidden (403)
    r_dan = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {vitals_test_env['dan_token']}"},
    )
    assert r_dan.status_code == 403

    # Eve has no grant -> Forbidden (403)
    r_eve = client.post(
        f"/api/profiles/{pid}/vitals",
        json=payload,
        headers={"Authorization": f"Bearer {vitals_test_env['eve_token']}"},
    )
    assert r_eve.status_code == 403


# ============================================================================
# Section 2: GET /api/profiles/{profile_id}/vitals Tests
# ============================================================================


def test_get_vitals_list_and_filters(vitals_test_env):
    """GET /vitals lists historical readings, supports pagination, and date filtering."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["alice_token"]

    # Query list
    resp = client.get(
        f"/api/profiles/{pid}/vitals?limit=10&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["limit"] == 10
    assert data["offset"] == 0


def test_get_vitals_permissions(vitals_test_env):
    """GET /vitals allows 'view_clinical' and blocks 'view_paperwork'."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]

    # Charlie ('view_clinical') -> 200 OK
    r_charlie = client.get(
        f"/api/profiles/{pid}/vitals",
        headers={"Authorization": f"Bearer {vitals_test_env['charlie_token']}"},
    )
    assert r_charlie.status_code == 200

    # Dan ('view_paperwork' only) -> 403 Forbidden
    r_dan = client.get(
        f"/api/profiles/{pid}/vitals",
        headers={"Authorization": f"Bearer {vitals_test_env['dan_token']}"},
    )
    assert r_dan.status_code == 403


# ============================================================================
# Section 3: GET /api/profiles/{profile_id}/vitals/trends Tests
# ============================================================================


def test_get_vitals_trends_diurnal_partitioning(vitals_test_env):
    """GET /vitals/trends partitions readings into AM and PM windows in local timezone."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["charlie_token"]  # Charlie has view_clinical

    # Seed observations in AM (08:00 UTC) and PM (14:00 UTC) from yesterday
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    am_time = yesterday.replace(hour=8, minute=30, second=0, microsecond=0)
    pm_time = yesterday.replace(hour=14, minute=30, second=0, microsecond=0)

    # Post AM reading
    client.post(
        f"/api/profiles/{pid}/vitals",
        json={"vitals": {"systolic": 122, "diastolic": 78}, "effective_at": am_time.isoformat()},
        headers={"Authorization": f"Bearer {vitals_test_env['alice_token']}"},
    )
    # Post PM reading
    client.post(
        f"/api/profiles/{pid}/vitals",
        json={"vitals": {"systolic": 134, "diastolic": 86}, "effective_at": pm_time.isoformat()},
        headers={"Authorization": f"Bearer {vitals_test_env['alice_token']}"},
    )

    # Query trends with timezone UTC
    resp = client.get(
        f"/api/profiles/{pid}/vitals/trends?timezone=UTC",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["profile_id"] == pid
    assert data["timezone"] == "UTC"
    assert "trends" in data
    trends = data["trends"]
    assert "7_day" in trends
    assert "30_day" in trends
    assert "90_day" in trends

    t_7d = trends["7_day"]
    assert t_7d["am"]["count"] >= 1
    assert t_7d["am"]["systolic"] is not None
    assert t_7d["pm"]["count"] >= 1
    assert t_7d["pm"]["systolic"] is not None


def test_get_vitals_trends_invalid_timezone(vitals_test_env):
    """GET /vitals/trends returns HTTP 400 Bad Request on invalid IANA timezone."""
    client = TestClient(app)
    pid = vitals_test_env["alice_profile_id"]
    token = vitals_test_env["charlie_token"]

    resp = client.get(
        f"/api/profiles/{pid}/vitals/trends?timezone=Mars/Olympus",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "Invalid IANA timezone identifier" in resp.json()["detail"]
