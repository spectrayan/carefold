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

"""Unit and integration test suite for Activity Timeline and Undo REST APIs (AU-40)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import (
    Appointment,
    AuditEventRecord,
    HealthResource,
    Note,
    Profile,
    ProfileAccess,
    Reminder,
)
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app


def run_async(coro):
    """Executes asynchronous coroutine synchronously."""
    return asyncio.run(coro)


@pytest.fixture
def activity_api_env(monkeypatch):
    """Sets up an isolated in-memory DB, SQL auth provider, and test users/profiles."""
    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        # 1. Alice (Account Owner, 'manage' access)
        alice = await auth_adapter.register_user(
            email="alice@activity.test",
            username="alice",
            password="AlicePassword123!",
            full_name="Alice Owner",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # 2. Bob (Delegate with explicit 'manage' access)
        bob = await auth_adapter.register_user(
            email="bob@activity.test",
            username="bob",
            password="BobPassword123!",
            full_name="Bob Manager",
            role="member",
            auth_provider="local",
        )
        bob_session = await auth_adapter.create_session(bob.id)

        # 3. Charlie (Clinician with 'view_clinical' access only)
        charlie = await auth_adapter.register_user(
            email="charlie@activity.test",
            username="charlie",
            password="CharliePassword123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # 4. Dan (Biller with 'view_paperwork' access only)
        dan = await auth_adapter.register_user(
            email="dan@activity.test",
            username="dan",
            password="DanPassword123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # 5. Eve (Unauthorized external user)
        eve = await auth_adapter.register_user(
            email="eve@activity.test",
            username="eve",
            password="EvePassword123!",
            full_name="Eve Attacker",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        # Create Profile
        profile_id = str(uuid.uuid4())
        foreign_profile_id = str(uuid.uuid4())

        async with session_factory() as session:
            prof = Profile(
                id=profile_id,
                user_id=alice.id,
                name="Alice Profile",
            )
            session.add(prof)

            foreign_prof = Profile(
                id=foreign_profile_id,
                user_id=eve.id,
                name="Eve Profile",
            )
            session.add(foreign_prof)

            # Grants on profile_id
            session.add(ProfileAccess(profile_id=profile_id, user_id=bob.id, access_level="manage"))
            session.add(ProfileAccess(profile_id=profile_id, user_id=charlie.id, access_level="view_clinical"))
            session.add(ProfileAccess(profile_id=profile_id, user_id=dan.id, access_level="view_paperwork"))

            await session.commit()

        return {
            "engine": engine,
            "session_factory": session_factory,
            "profile_id": profile_id,
            "foreign_profile_id": foreign_profile_id,
            "alice": alice,
            "alice_token": alice_session.token,
            "bob": bob,
            "bob_token": bob_session.token,
            "charlie": charlie,
            "charlie_token": charlie_session.token,
            "dan": dan,
            "dan_token": dan_session.token,
            "eve": eve,
            "eve_token": eve_session.token,
        }

    env = run_async(_setup())

    async def _override_get_db():
        async with env["session_factory"]() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    yield env

    app.dependency_overrides.pop(get_db, None)
    reset_auth_port()
    run_async(env["engine"].dispose())


# ============================================================================
# Section 1: GET /api/profiles/{profile_id}/activity Timeline Endpoint Tests
# ============================================================================

class TestActivityTimelineAPI:
    """Verifies GET /api/profiles/{profile_id}/activity endpoints and RBAC."""

    def test_get_activity_timeline_200_ok(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        token = activity_api_env["alice_token"]
        session_factory = activity_api_env["session_factory"]

        now = datetime.now(timezone.utc)
        # Seed an audit event
        async def _seed():
            async with session_factory() as db:
                db.add(
                    AuditEventRecord(
                        id=str(uuid.uuid4()),
                        profile_id=prof_id,
                        principal="user",
                        event="tool",
                        tool="record_vitals",
                        risk="write_local",
                        external_ref="health_resource:hr-101",
                        ts=now,
                        detail_redacted=json.dumps({"vitals": {"systolic": 120, "diastolic": 80}}),
                    )
                )
                await db.commit()

        run_async(_seed())

        resp = client.get(
            f"/api/profiles/{prof_id}/activity",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_id"] == prof_id
        assert data["total"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["summary"] == "Logged blood pressure 120/80 mmHg"
        assert item["undoable"] is True

    def test_get_activity_timeline_pagination(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        token = activity_api_env["alice_token"]
        session_factory = activity_api_env["session_factory"]

        now = datetime.now(timezone.utc)
        async def _seed():
            async with session_factory() as db:
                for i in range(5):
                    db.add(
                        AuditEventRecord(
                            id=f"page-evt-{i}",
                            profile_id=prof_id,
                            principal="user",
                            event="tool",
                            tool="create_reminder",
                            risk="write_local",
                            external_ref=f"reminder:rem-{i}",
                            ts=now + timedelta(minutes=i),
                            detail_redacted=json.dumps({"title": f"Meds {i}"}),
                        )
                    )
                await db.commit()

        run_async(_seed())

        # Page 1
        resp = client.get(
            f"/api/profiles/{prof_id}/activity?limit=2&offset=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["items"][0]["id"] == "page-evt-4"

    def test_get_activity_timeline_view_clinical_allowed(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        charlie_token = activity_api_env["charlie_token"]  # view_clinical

        resp = client.get(
            f"/api/profiles/{prof_id}/activity",
            headers={"Authorization": f"Bearer {charlie_token}"},
        )
        assert resp.status_code == 200

    def test_get_activity_timeline_view_paperwork_forbidden_403(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        dan_token = activity_api_env["dan_token"]  # view_paperwork only

        resp = client.get(
            f"/api/profiles/{prof_id}/activity",
            headers={"Authorization": f"Bearer {dan_token}"},
        )
        assert resp.status_code == 403
        assert "clinical view permissions required" in resp.json()["detail"]

    def test_get_activity_timeline_unauthorized_401(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]

        resp = client.get(f"/api/profiles/{prof_id}/activity")
        assert resp.status_code == 401

    def test_get_activity_timeline_foreign_user_forbidden_403(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        eve_token = activity_api_env["eve_token"]  # no access

        resp = client.get(
            f"/api/profiles/{prof_id}/activity",
            headers={"Authorization": f"Bearer {eve_token}"},
        )
        assert resp.status_code == 403

    def test_get_activity_timeline_nonexistent_profile_404(self, activity_api_env):
        client = TestClient(app)
        token = activity_api_env["alice_token"]

        resp = client.get(
            f"/api/profiles/{uuid.uuid4()}/activity",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


# ============================================================================
# Section 2: POST /api/profiles/{profile_id}/activity/{event_id}/undo Tests
# ============================================================================

class TestActivityUndoAPI:
    """Verifies POST /api/profiles/{profile_id}/activity/{event_id}/undo execution and RBAC."""

    def test_post_undo_appointment_success(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        token = activity_api_env["alice_token"]
        session_factory = activity_api_env["session_factory"]

        appt_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async def _seed():
            async with session_factory() as db:
                db.add(
                    Appointment(
                        id=appt_id,
                        profile_id=prof_id,
                        title="Dental Checkup",
                        start_time=now,
                        end_time=now + timedelta(hours=1),
                        status="scheduled",
                    )
                )
                db.add(
                    AuditEventRecord(
                        id=event_id,
                        profile_id=prof_id,
                        principal="user",
                        event="tool",
                        tool="create_appointment",
                        risk="write_local",
                        external_ref=f"appointment:{appt_id}",
                        ts=now,
                        detail_redacted=json.dumps({"title": "Dental Checkup"}),
                    )
                )
                await db.commit()

        run_async(_seed())

        resp = client.post(
            f"/api/profiles/{prof_id}/activity/{event_id}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "undone"
        assert data["event_id"] == event_id
        assert data["external_ref"] == f"appointment:{appt_id}"

        # Verify appointment is cancelled
        async def _check():
            async with session_factory() as db:
                appt = (await db.execute(select(Appointment).where(Appointment.id == appt_id))).scalar_one()
                assert appt.status == "cancelled"

        run_async(_check())

    def test_post_undo_health_resource_success(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        token = activity_api_env["alice_token"]
        session_factory = activity_api_env["session_factory"]

        hr_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async def _seed():
            async with session_factory() as db:
                db.add(
                    HealthResource(
                        id=hr_id,
                        profile_id=prof_id,
                        resource_type="observation",
                        source_type="manual",
                        status="active",
                        data={"systolic": 130, "diastolic": 85},
                        effective_at=now,
                        recorded_at=now,
                    )
                )
                db.add(
                    AuditEventRecord(
                        id=event_id,
                        profile_id=prof_id,
                        principal="user",
                        event="tool",
                        tool="record_vitals",
                        risk="write_local",
                        external_ref=f"health_resource:{hr_id}",
                        ts=now,
                        detail_redacted=json.dumps({"vitals": {"systolic": 130}}),
                    )
                )
                await db.commit()

        run_async(_seed())

        resp = client.post(
            f"/api/profiles/{prof_id}/activity/{event_id}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "undone"

        async def _check():
            async with session_factory() as db:
                hr = (await db.execute(select(HealthResource).where(HealthResource.id == hr_id))).scalar_one()
                assert hr.status == "tombstone"

        run_async(_check())

    def test_post_undo_expired_window_400(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        token = activity_api_env["alice_token"]
        session_factory = activity_api_env["session_factory"]

        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        ts_expired = now - timedelta(days=7, seconds=2)

        async def _seed():
            async with session_factory() as db:
                db.add(
                    AuditEventRecord(
                        id=event_id,
                        profile_id=prof_id,
                        principal="user",
                        event="tool",
                        tool="record_vitals",
                        risk="write_local",
                        external_ref="health_resource:hr-expired",
                        ts=ts_expired,
                        detail_redacted="{}",
                    )
                )
                await db.commit()

        run_async(_seed())

        resp = client.post(
            f"/api/profiles/{prof_id}/activity/{event_id}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "7-day undo window" in resp.json()["detail"]

    def test_post_undo_non_write_local_risk_400(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        token = activity_api_env["alice_token"]
        session_factory = activity_api_env["session_factory"]

        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async def _seed():
            async with session_factory() as db:
                db.add(
                    AuditEventRecord(
                        id=event_id,
                        profile_id=prof_id,
                        principal="user",
                        event="tool",
                        tool="list_appointments",
                        risk="read",
                        external_ref="appointment:none",
                        ts=now,
                        detail_redacted="{}",
                    )
                )
                await db.commit()

        run_async(_seed())

        resp = client.post(
            f"/api/profiles/{prof_id}/activity/{event_id}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "Only write_local actions are eligible" in resp.json()["detail"]

    def test_post_undo_view_clinical_forbidden_403(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        charlie_token = activity_api_env["charlie_token"]  # view_clinical only

        resp = client.post(
            f"/api/profiles/{prof_id}/activity/some-event-id/undo",
            headers={"Authorization": f"Bearer {charlie_token}"},
        )
        assert resp.status_code == 403
        assert "management permissions required" in resp.json()["detail"]

    def test_post_undo_unauthenticated_401(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]

        resp = client.post(f"/api/profiles/{prof_id}/activity/some-event-id/undo")
        assert resp.status_code == 401

    def test_post_undo_missing_event_404(self, activity_api_env):
        client = TestClient(app)
        prof_id = activity_api_env["profile_id"]
        token = activity_api_env["alice_token"]

        resp = client.post(
            f"/api/profiles/{prof_id}/activity/{uuid.uuid4()}/undo",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
