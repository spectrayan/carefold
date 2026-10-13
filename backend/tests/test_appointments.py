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

"""Unit, integration, and API test suite for Clinical Appointments & Scheduling (AU-29)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.clinical.appointments import (
    AppointmentStatus,
    InvalidStatusTransitionError,
    evaluate_post_visit_transitions,
    generate_how_to_book_drafts,
    sweep_post_visit_transitions,
    validate_status_transition,
)
from carefold.config import settings
from carefold.db.models import Appointment, Profile, ProfileAccess
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app
from carefold.engine.tool_exec import ToolContext
from carefold.tools.appointments import (
    execute_create_appointment,
    execute_list_appointments,
    execute_update_appointment_status,
)


def run_async(coro):
    return asyncio.run(coro)


# ============================================================================
# Section 1: Domain Logic & State Machine Tests
# ============================================================================


def test_valid_status_transitions():
    """Verifies that all legal status transitions succeed without error."""
    # requested -> scheduled, confirmed, cancelled
    validate_status_transition("requested", "scheduled")
    validate_status_transition("requested", "confirmed")
    validate_status_transition("requested", "cancelled")

    # scheduled -> confirmed, requested, completed, cancelled
    validate_status_transition("scheduled", "confirmed")
    validate_status_transition("scheduled", "requested")
    validate_status_transition("scheduled", "completed")
    validate_status_transition("scheduled", "cancelled")

    # confirmed -> completed, scheduled, cancelled
    validate_status_transition("confirmed", "completed")
    validate_status_transition("confirmed", "scheduled")
    validate_status_transition("confirmed", "cancelled")

    # completed -> cancelled (undo)
    validate_status_transition("completed", "cancelled")

    # cancelled -> requested (re-open)
    validate_status_transition("cancelled", "requested")


def test_invalid_status_transitions():
    """Verifies that illegal status transitions raise InvalidStatusTransitionError."""
    # Cannot jump requested directly to completed
    with pytest.raises(InvalidStatusTransitionError) as exc_info:
        validate_status_transition("requested", "completed")
    assert exc_info.value.from_status == "requested"
    assert exc_info.value.to_status == "completed"

    # Cannot transition completed back to scheduled or confirmed
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("completed", "scheduled")
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("completed", "confirmed")
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("completed", "requested")

    # Cannot transition cancelled directly to completed or confirmed
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("cancelled", "completed")
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("cancelled", "confirmed")


def test_idempotent_status_transitions():
    """Verifies that transitioning to the same status is an idempotent no-op."""
    validate_status_transition("requested", "requested")
    validate_status_transition("confirmed", "confirmed")
    validate_status_transition("completed", "completed")
    validate_status_transition("cancelled", "cancelled")


def test_unknown_status_raises_value_error():
    """Verifies that unknown status strings raise ValueError."""
    with pytest.raises(ValueError):
        validate_status_transition("non_existent", "confirmed")
    with pytest.raises(ValueError):
        validate_status_transition("confirmed", "bogus")


# ============================================================================
# Section 2: "How to Book" Drafts Formulation Tests
# ============================================================================


def test_generate_how_to_book_drafts_structure():
    """Verifies that booking drafts generator produces structured script and portal draft."""
    drafts = generate_how_to_book_drafts(
        title="Cardiology Consultation",
        provider_name="Dr. Sarah Connor",
        specialty="Cardiology",
        clinic_phone="555-0144",
        reason="Exertional palpitations",
    )
    assert drafts["status"] == "requested"
    assert "Dr. Sarah Connor" in drafts["phone_script"]
    assert "555-0144" in drafts["phone_script"]
    assert "INSURANCE CHECKLIST" in drafts["phone_script"]
    assert "Exertional palpitations" in drafts["portal_draft"]
    assert len(drafts["checklist"]) >= 3


def test_generate_how_to_book_drafts_custom_insurance_and_preferences():
    """Verifies inclusion of insurance member ID, group number, and scheduling preferences."""
    drafts = generate_how_to_book_drafts(
        title="Dermatology Skin Check",
        provider_name="Dr. House",
        specialty="Dermatology",
        clinic_phone="555-0199",
        reason="Atypical mole evaluation",
        insurance_name="Blue Cross Blue Shield",
        insurance_member_id="BCBS123456",
        insurance_group_number="GRP9988",
        preferred_days=["Tuesday", "Thursday"],
        preferred_time_of_day="Afternoon",
        visit_mode="in-person",
    )
    assert "BCBS123456" in drafts["phone_script"]
    assert "GRP9988" in drafts["phone_script"]
    assert "Tuesday, Thursday" in drafts["phone_script"]
    assert "Afternoon" in drafts["phone_script"]
    assert "BCBS123456" in drafts["portal_draft"]


# ============================================================================
# Section 3: Post-Visit Transition Evaluation Tests
# ============================================================================


def test_post_visit_transitions_past_confirmed_becomes_completed():
    """Verifies confirmed visits with end_time in the past transition to completed."""
    now = datetime.now(timezone.utc)
    past_appt = {
        "id": "appt-001",
        "title": "Annual Wellness Visit",
        "status": "confirmed",
        "end_time": (now - timedelta(hours=2)).isoformat(),
    }
    future_appt = {
        "id": "appt-002",
        "title": "Future Visit",
        "status": "confirmed",
        "end_time": (now + timedelta(days=2)).isoformat(),
    }
    completed_ids, prompts = evaluate_post_visit_transitions([past_appt, future_appt], current_time=now)
    assert "appt-001" in completed_ids
    assert "appt-002" not in completed_ids
    assert len(prompts) == 1
    assert prompts[0]["appointment_id"] == "appt-001"
    assert prompts[0]["prompt_type"] == "post_visit_followup"
    assert "visit notes" in prompts[0]["message"]
    assert len(prompts[0]["suggested_actions"]) >= 2


def test_post_visit_transitions_unconfirmed_past_does_not_transition():
    """Verifies scheduled or requested appointments in the past do not auto-complete."""
    now = datetime.now(timezone.utc)
    scheduled_past = {
        "id": "appt-sched",
        "title": "Unconfirmed Visit",
        "status": "scheduled",
        "end_time": (now - timedelta(hours=3)).isoformat(),
    }
    requested_past = {
        "id": "appt-req",
        "title": "Draft Request",
        "status": "requested",
        "end_time": (now - timedelta(hours=3)).isoformat(),
    }
    completed_ids, prompts = evaluate_post_visit_transitions([scheduled_past, requested_past], current_time=now)
    assert len(completed_ids) == 0
    assert len(prompts) == 0


# ============================================================================
# Section 4: ToolSpec Execution Tests
# ============================================================================


@pytest.fixture
def appointments_tool_env(monkeypatch):
    """Sets up an isolated in-memory DB and session factory for tool testing."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    run_async(init_db(engine))
    session_factory = get_session_factory(engine)
    monkeypatch.setattr("carefold.tools.appointments.get_session_factory", lambda: session_factory)

    profile_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async def _create_profile():
        async with session_factory() as session:
            p = Profile(
                id=profile_id,
                name="Test Patient",
                relationship="self",
                role="self",
                created_at=now,
                updated_at=now,
            )
            session.add(p)
            await session.commit()

    run_async(_create_profile())
    return {"session_factory": session_factory, "profile_id": profile_id}


def test_create_appointment_tool_success(appointments_tool_env):
    """Verifies execute_create_appointment succeeds and creates valid appointment."""
    prof_id = appointments_tool_env["profile_id"]
    ctx = ToolContext(profile_id=prof_id, user_id="user-1")

    now = datetime.now(timezone.utc)
    start_str = (now + timedelta(days=1)).isoformat()
    end_str = (now + timedelta(days=1, hours=1)).isoformat()

    args = {
        "title": "Cardiology Checkup",
        "start_time": start_str,
        "end_time": end_str,
        "provider_name": "Dr. Smith",
        "specialty": "Cardiology",
        "status": "confirmed",
        "reason": "Routine screening",
    }
    res = run_async(execute_create_appointment(args, ctx))
    assert res.success is True
    assert res.output["title"] == "Cardiology Checkup"
    assert res.output["status"] == "confirmed"
    assert res.output["undo_reference"].startswith("appointment:")


def test_create_appointment_tool_fail_closed():
    """Verifies that missing profile_id fails closed immediately."""
    with pytest.raises(ValueError, match="Security invariant violation"):
        ToolContext(profile_id="", user_id="user-1")

    class DummyCtx:
        profile_id = ""
        user_id = "user-1"

    res_empty = run_async(execute_create_appointment({"title": "Test"}, DummyCtx()))
    assert res_empty.success is False
    assert "Security violation" in res_empty.error

    res_none = run_async(execute_create_appointment({"title": "Test"}, None))
    assert res_none.success is False
    assert "Security violation" in res_none.error


def test_create_appointment_tool_invalid_times(appointments_tool_env):
    """Verifies that start_time >= end_time is rejected."""
    prof_id = appointments_tool_env["profile_id"]
    ctx = ToolContext(profile_id=prof_id, user_id="user-1")
    now = datetime.now(timezone.utc)

    res = run_async(execute_create_appointment({
        "title": "Bad Times",
        "start_time": now.isoformat(),
        "end_time": (now - timedelta(hours=1)).isoformat(),
    }, ctx))
    assert res.success is False
    assert "strictly after" in res.error


def test_list_and_update_appointment_tools(appointments_tool_env):
    """Verifies list_appointments and update_appointment_status tools."""
    prof_id = appointments_tool_env["profile_id"]
    ctx = ToolContext(profile_id=prof_id, user_id="user-1")
    now = datetime.now(timezone.utc)

    # 1. Create
    c_res = run_async(execute_create_appointment({
        "title": "Initial Consult",
        "start_time": (now + timedelta(days=2)).isoformat(),
        "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
        "status": "requested",
    }, ctx))
    assert c_res.success is True
    appt_id = c_res.output["id"]

    # 2. List
    l_res = run_async(execute_list_appointments({"status": "requested"}, ctx))
    assert l_res.success is True
    assert l_res.output["total"] >= 1
    assert any(a["id"] == appt_id for a in l_res.output["appointments"])

    # 3. Update status (requested -> confirmed)
    u_res = run_async(execute_update_appointment_status({
        "appointment_id": appt_id,
        "status": "confirmed",
    }, ctx))
    assert u_res.success is True
    assert u_res.output["status"] == "confirmed"

    # 4. Invalid update (confirmed -> requested is prohibited)
    bad_res = run_async(execute_update_appointment_status({
        "appointment_id": appt_id,
        "status": "requested",
    }, ctx))
    assert bad_res.success is False
    assert "Invalid status transition" in bad_res.error


# ============================================================================
# Section 5: REST API Integration & Permissions Tests
# ============================================================================


@pytest.fixture
def appointments_api_env(monkeypatch):
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
            email="alice_appt@test.local",
            username="alice_appt",
            password="Password123!",
            full_name="Alice Owner",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # Bob: Manage grant
        bob = await auth_adapter.register_user(
            email="bob_appt@test.local",
            username="bob_appt",
            password="Password123!",
            full_name="Bob Manager",
            role="member",
            auth_provider="local",
        )
        bob_session = await auth_adapter.create_session(bob.id)

        # Charlie: Clinical view only
        charlie = await auth_adapter.register_user(
            email="charlie_appt@test.local",
            username="charlie_appt",
            password="Password123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # Dan: Paperwork only
        dan = await auth_adapter.register_user(
            email="dan_appt@test.local",
            username="dan_appt",
            password="Password123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # Eve: Unauthorized
        eve = await auth_adapter.register_user(
            email="eve_appt@test.local",
            username="eve_appt",
            password="Password123!",
            full_name="Eve Unauthorized",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            alice_profile = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Alice Primary",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
            session.add(alice_profile)

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


def test_appointments_rest_api_lifecycle(appointments_api_env):
    """End-to-end test of appointments CRUD REST APIs."""
    client = TestClient(app)
    prof_id = appointments_api_env["profile_id"]
    token = appointments_api_env["alice_token"]
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)
    start_dt = now + timedelta(days=3)
    end_dt = start_dt + timedelta(hours=1)

    # 1. POST create appointment
    create_payload = {
        "title": "Neurology Evaluation",
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "provider_name": "Dr. Xavier",
        "specialty": "Neurology",
        "location": "Suite 400",
        "clinic_phone": "555-0999",
        "status": "scheduled",
        "reason": "Chronic migraines",
    }
    res = client.post(f"/api/profiles/{prof_id}/appointments", json=create_payload, headers=headers)
    assert res.status_code == 201
    appt_data = res.json()
    appt_id = appt_data["id"]
    assert appt_data["title"] == "Neurology Evaluation"
    assert appt_data["status"] == "scheduled"

    # 2. GET single appointment
    get_res = client.get(f"/api/profiles/{prof_id}/appointments/{appt_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["specialty"] == "Neurology"

    # 3. GET list appointments with filter
    list_res = client.get(f"/api/profiles/{prof_id}/appointments?specialty=Neurology", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["total"] >= 1

    # 4. PATCH update status (scheduled -> confirmed)
    patch_res = client.patch(
        f"/api/profiles/{prof_id}/appointments/{appt_id}",
        json={"status": "confirmed", "location": "Room 402"},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "confirmed"
    assert patch_res.json()["location"] == "Room 402"

    # 5. POST draft-booking
    draft_res = client.post(
        f"/api/profiles/{prof_id}/appointments/draft-booking",
        json={
            "title": "Endocrinology Visit",
            "provider_name": "Dr. Banner",
            "specialty": "Endocrinology",
            "clinic_phone": "555-0888",
            "reason": "Thyroid nodule follow-up",
            "insurance_name": "Carefold Silver Plan",
        },
        headers=headers,
    )
    assert draft_res.status_code == 201
    draft_body = draft_res.json()
    assert draft_body["appointment"]["status"] == "requested"
    assert "INSURANCE CHECKLIST" in draft_body["phone_script"]
    assert len(draft_body["checklist"]) >= 3

    # 6. DELETE appointment
    del_res = client.delete(f"/api/profiles/{prof_id}/appointments/{appt_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "cancelled"


def test_appointments_api_permissions(appointments_api_env):
    """Verifies role-based access matrix on appointment endpoints."""
    client = TestClient(app)
    prof_id = appointments_api_env["profile_id"]

    alice_h = {"Authorization": f"Bearer {appointments_api_env['alice_token']}"}
    bob_h = {"Authorization": f"Bearer {appointments_api_env['bob_token']}"}
    charlie_h = {"Authorization": f"Bearer {appointments_api_env['charlie_token']}"}
    dan_h = {"Authorization": f"Bearer {appointments_api_env['dan_token']}"}
    eve_h = {"Authorization": f"Bearer {appointments_api_env['eve_token']}"}

    now = datetime.now(timezone.utc)
    payload = {
        "title": "Cardiology Checkup",
        "start_time": (now + timedelta(days=1)).isoformat(),
        "end_time": (now + timedelta(days=1, hours=1)).isoformat(),
        "status": "scheduled",
    }

    # 1. Bob (manage) can POST
    bob_res = client.post(f"/api/profiles/{prof_id}/appointments", json=payload, headers=bob_h)
    assert bob_res.status_code == 201
    appt_id = bob_res.json()["id"]

    # 2. Charlie (view_clinical) can GET
    charlie_get = client.get(f"/api/profiles/{prof_id}/appointments", headers=charlie_h)
    assert charlie_get.status_code == 200

    # 3. Charlie (view_clinical) CANNOT POST or PATCH or DELETE (403)
    charlie_post = client.post(f"/api/profiles/{prof_id}/appointments", json=payload, headers=charlie_h)
    assert charlie_post.status_code == 403

    charlie_patch = client.patch(f"/api/profiles/{prof_id}/appointments/{appt_id}", json={"status": "confirmed"}, headers=charlie_h)
    assert charlie_patch.status_code == 403

    charlie_del = client.delete(f"/api/profiles/{prof_id}/appointments/{appt_id}", headers=charlie_h)
    assert charlie_del.status_code == 403

    # 4. Dan (view_paperwork) CANNOT GET (403)
    dan_get = client.get(f"/api/profiles/{prof_id}/appointments", headers=dan_h)
    assert dan_get.status_code == 403

    # 5. Eve (unauthorized) CANNOT access (403)
    eve_get = client.get(f"/api/profiles/{prof_id}/appointments", headers=eve_h)
    assert eve_get.status_code == 403
