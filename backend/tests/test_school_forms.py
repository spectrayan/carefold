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

"""Unit, tool, and REST API tests for Pediatric School Health Forms & Under-13 Safeguards (AU-39)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from carefold.api.deps import get_db
from carefold.api.school_forms import router as school_forms_router
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.clinical.school_forms import (
    SCHOOL_FORM_DISCLAIMER,
    check_under_13_safeguards,
    compile_school_form_prefill,
    create_school_form,
    regenerate_school_form_prefill,
)
from carefold.config import settings
from carefold.db.models import (
    AuditEventRecord,
    HealthResource,
    Profile,
    ProfileAccess,
    Reminder,
    SchoolForm,
)
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.tool_exec import ToolContext
from carefold.main import app
from carefold.tools.school_forms import (
    execute_create_school_form,
    execute_list_school_forms,
)


def run_async(coro):
    return asyncio.run(coro)


def _ensure_school_forms_router_mounted():
    routes = [getattr(r, "path", "") for r in app.routes]
    if not any("/school-forms" in p for p in routes):
        app.include_router(school_forms_router, prefix="/api")


# ============================================================================
# Section 1: Under-13 Safeguard Invariant Tests (E11.6)
# ============================================================================


def test_under_13_safeguards_enforcement():
    """Verifies under-13 child profile invariants vs teen and adult profiles."""
    ref = datetime(2026, 10, 13, tzinfo=timezone.utc)

    child_prof = Profile(
        id=str(uuid.uuid4()),
        name="Maya Child",
        relationship="child",
        role="guardian",
        date_of_birth="2018-04-10",  # 8 years old (102 months)
    )
    view_eval = check_under_13_safeguards(child_prof, action="view", reference_date=ref)
    assert view_eval["is_under_13"] is True
    assert view_eval["age_band"] == "child_under_13"
    assert view_eval["guardian_only"] is True
    assert view_eval["allow_child_login"] is False
    assert view_eval["allow_external_writes"] is False
    assert view_eval["telemetry_enabled"] is False
    assert view_eval["allowed"] is True

    for blocked_action in ("child_login", "external_write", "write_external", "enable_telemetry", "auto_submit"):
        blocked_eval = check_under_13_safeguards(child_prof, action=blocked_action, reference_date=ref)
        assert blocked_eval["allowed"] is False
        assert "prohibited" in blocked_eval["reason"].lower()

    # Teen profile (15 years old)
    teen_prof = Profile(
        id=str(uuid.uuid4()),
        name="Alex Teen",
        relationship="child",
        role="guardian",
        date_of_birth="2011-04-10",
    )
    teen_eval = check_under_13_safeguards(teen_prof, action="view", reference_date=ref)
    assert teen_eval["is_under_13"] is False
    assert teen_eval["age_band"] == "teen"
    assert teen_eval["guardian_only"] is False
    assert teen_eval["allow_child_login"] is True
    assert teen_eval["allow_external_writes"] is True
    assert teen_eval["telemetry_enabled"] is False

    # Adult profile (36 years old)
    adult_prof = Profile(
        id=str(uuid.uuid4()),
        name="Sam Adult",
        relationship="self",
        role="self",
        date_of_birth="1990-01-01",
    )
    adult_eval = check_under_13_safeguards(adult_prof, action="external_write", reference_date=ref)
    assert adult_eval["is_under_13"] is False
    assert adult_eval["age_band"] == "adult"
    assert adult_eval["allowed"] is True


# ============================================================================
# Section 2: Draft Prefill Compilation & Renewal Reminder Tests
# ============================================================================


@pytest.fixture
def school_forms_db_env(monkeypatch):
    """Provides an isolated in-memory database for school form domain and tool tests."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    run_async(init_db(engine))
    session_factory = get_session_factory(engine)
    monkeypatch.setattr("carefold.tools.school_forms.get_session_factory", lambda: session_factory)
    return {"session_factory": session_factory}


def test_compile_school_form_prefill_and_renewal_reminder(school_forms_db_env):
    """Verifies compile_school_form_prefill aggregates vaccines, allergies, meds, and vitals, and create_school_form links a 30-day renewal reminder."""
    session_factory = school_forms_db_env["session_factory"]
    now = datetime.now(timezone.utc)

    async def _scenario():
        async with session_factory() as session:
            child = Profile(
                id=str(uuid.uuid4()),
                name="Leo Joshi",
                relationship="child",
                role="guardian",
                date_of_birth="2018-09-01",
                created_at=now,
                updated_at=now,
            )
            session.add(child)

            # 1. Immunization resource
            session.add(
                HealthResource(
                    id=str(uuid.uuid4()),
                    profile_id=child.id,
                    resource_type="immunization",
                    source_type="manual",
                    data={
                        "vaccineCode": {
                            "text": "MMR (Measles, Mumps, Rubella)",
                            "coding": [{"code": "03", "display": "MMR"}],
                        },
                        "occurrenceDateTime": "2023-09-15",
                        "status": "completed",
                    },
                    status="active",
                    effective_at=now - timedelta(days=300),
                    recorded_at=now,
                )
            )

            # 2. AllergyIntolerance resource
            session.add(
                HealthResource(
                    id=str(uuid.uuid4()),
                    profile_id=child.id,
                    resource_type="allergy_intolerance",
                    source_type="manual",
                    data={
                        "code": {"text": "Peanuts"},
                        "criticality": "high",
                        "reaction": "Hives and wheezing",
                    },
                    status="active",
                    effective_at=now - timedelta(days=200),
                    recorded_at=now,
                )
            )

            # 3. MedicationStatement resource
            session.add(
                HealthResource(
                    id=str(uuid.uuid4()),
                    profile_id=child.id,
                    resource_type="medication_statement",
                    source_type="manual",
                    data={
                        "medicationCodeableConcept": {"text": "Epinephrine Auto-Injector 0.15mg"},
                        "dosage": "0.15 mg IM as needed for anaphylaxis",
                        "status": "active",
                    },
                    status="active",
                    effective_at=now - timedelta(days=100),
                    recorded_at=now,
                )
            )

            # 4. Vitals Observations (height, weight, BP)
            session.add(
                HealthResource(
                    id=str(uuid.uuid4()),
                    profile_id=child.id,
                    resource_type="observation",
                    source_type="manual",
                    data={
                        "height": 128.5,
                        "weight": 26.4,
                        "systolic": 102,
                        "diastolic": 64,
                    },
                    status="active",
                    effective_at=now - timedelta(days=10),
                    recorded_at=now,
                )
            )
            await session.commit()

            prefill = await compile_school_form_prefill(session, child.id)
            assert prefill["student_name"] == "Leo Joshi"
            assert prefill["date_of_birth"] == "2018-09-01"
            assert prefill["relationship"] == "child"
            assert len(prefill["immunisations"]) == 1
            assert "MMR" in prefill["immunisations"][0]["vaccine"]
            assert len(prefill["allergies"]) == 1
            assert prefill["allergies"][0]["substance"] == "Peanuts"
            assert len(prefill["medications"]) == 1
            assert "Epinephrine" in prefill["medications"][0]["medication"]
            assert prefill["latest_vitals"]["height"]["value"] == 128.5
            assert prefill["latest_vitals"]["weight"]["value"] == 26.4
            assert prefill["latest_vitals"]["blood_pressure"]["systolic"] == 102
            assert prefill["auto_submitted"] is False
            assert prefill["disclaimer"] == SCHOOL_FORM_DISCLAIMER

            # Create school form with expires_at 90 days out -> renewal reminder 60 days out (expires_at - 30d)
            expires_dt = now + timedelta(days=90)
            form = await create_school_form(
                session,
                profile_id=child.id,
                title="Annual School Physical & Allergy Action Plan",
                school_or_camp_name="Oakridge Elementary",
                form_type="physical",
                expires_at=expires_dt,
                status="draft",
                actor_user_id="user-1",
            )
            assert form.reminder_id is not None
            rem = (
                await session.execute(select(Reminder).where(Reminder.id == form.reminder_id))
            ).scalar_one()
            assert rem.title == "Renew school form: Annual School Physical & Allergy Action Plan"
            assert rem.category == "prep"
            expected_due = expires_dt - timedelta(days=30)
            assert abs((rem.next_due_at.replace(tzinfo=timezone.utc) - expected_due).total_seconds()) < 5

            # Verify audit record
            audits = (
                await session.execute(
                    select(AuditEventRecord).where(
                        AuditEventRecord.external_ref == f"school_form:{form.id}"
                    )
                )
            ).scalars().all()
            assert len(audits) == 1
            assert audits[0].risk == "write_local"

    run_async(_scenario())


# ============================================================================
# Section 3: Tool Execution & Fail-Closed Security Tests
# ============================================================================


def test_school_form_tools_fail_closed_and_execution(school_forms_db_env):
    """Verifies execute_create_school_form and execute_list_school_forms fail closed and execute cleanly."""
    session_factory = school_forms_db_env["session_factory"]
    now = datetime.now(timezone.utc)

    # 1. Fail-closed checks
    res_create_none = run_async(execute_create_school_form({"title": "Camp Form"}, None))
    assert res_create_none.success is False
    assert "Security violation" in res_create_none.error

    res_list_none = run_async(execute_list_school_forms({}, None))
    assert res_list_none.success is False
    assert "Security violation" in res_list_none.error

    # 2. Seed profile and execute tools
    prof_id = str(uuid.uuid4())

    async def _seed():
        async with session_factory() as session:
            session.add(
                Profile(
                    id=prof_id,
                    name="Camp Kid",
                    relationship="child",
                    role="guardian",
                    date_of_birth="2017-03-20",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

    run_async(_seed())
    ctx = ToolContext(profile_id=prof_id, user_id="user-1")

    create_res = run_async(
        execute_create_school_form(
            {
                "title": "Summer Camp Immunization & Physical Packet",
                "school_or_camp_name": "Camp Pinewood",
                "form_type": "sports_clearance",
                "expires_at": (now + timedelta(days=60)).isoformat(),
            },
            ctx,
        )
    )
    assert create_res.success is True
    assert create_res["title"] == "Summer Camp Immunization & Physical Packet"
    assert create_res["reminder_id"] is not None
    assert create_res["prefill_draft"]["disclaimer"] == SCHOOL_FORM_DISCLAIMER

    list_res = run_async(execute_list_school_forms({}, ctx))
    assert list_res.success is True
    assert list_res["total"] == 1
    assert list_res["forms"][0]["school_or_camp_name"] == "Camp Pinewood"


# ============================================================================
# Section 4: REST API & Access Control Tests
# ============================================================================


@pytest.fixture
def school_forms_api_env(monkeypatch):
    """Sets up an isolated FastAPI test environment with RBAC users for school form endpoints."""
    _ensure_school_forms_router_mounted()

    async def _setup():
        engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = get_session_factory(engine)
        auth_adapter = SqlAuthAdapter(session_factory=session_factory)

        monkeypatch.setattr(settings, "auth_provider", "local")
        set_auth_port(auth_adapter)

        alice = await auth_adapter.register_user(
            email="alice_sf@test.local",
            username="alice_sf",
            password="Password123!",
            full_name="Alice Parent",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        charlie = await auth_adapter.register_user(
            email="charlie_sf@test.local",
            username="charlie_sf",
            password="Password123!",
            full_name="Charlie Viewer",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        dan = await auth_adapter.register_user(
            email="dan_sf@test.local",
            username="dan_sf",
            password="Password123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            prof = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Zoe Child",
                relationship="child",
                role="guardian",
                date_of_birth="2019-02-14",
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
            session.add(prof)
            session.add(
                ProfileAccess(
                    id=str(uuid.uuid4()),
                    profile_id=prof.id,
                    user_id=charlie.id,
                    access_level="view_clinical",
                    granted_by=alice.id,
                    granted_at=now,
                )
            )
            session.add(
                ProfileAccess(
                    id=str(uuid.uuid4()),
                    profile_id=prof.id,
                    user_id=dan.id,
                    access_level="view_paperwork",
                    granted_by=alice.id,
                    granted_at=now,
                )
            )
            await session.commit()
            return {
                "session_factory": session_factory,
                "profile_id": prof.id,
                "alice_token": alice_session.token,
                "charlie_token": charlie_session.token,
                "dan_token": dan_session.token,
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


def test_school_forms_rest_api_crud_and_prefill_regeneration(school_forms_api_env):
    """Tests POST, GET, POST /prefill, PATCH, and DELETE school-forms REST endpoints and RBAC."""
    client = TestClient(app)
    prof_id = school_forms_api_env["profile_id"]
    session_factory = school_forms_api_env["session_factory"]
    alice_h = {"Authorization": f"Bearer {school_forms_api_env['alice_token']}"}
    charlie_h = {"Authorization": f"Bearer {school_forms_api_env['charlie_token']}"}
    dan_h = {"Authorization": f"Bearer {school_forms_api_env['dan_token']}"}

    now = datetime.now(timezone.utc)
    expires_iso = (now + timedelta(days=120)).isoformat()

    # 1. POST create school form
    post_res = client.post(
        f"/api/profiles/{prof_id}/school-forms",
        json={
            "title": "Kindergarten Health & Immunization Record",
            "school_or_camp_name": "Lincoln Elementary",
            "form_type": "immunization",
            "expires_at": expires_iso,
            "status": "draft",
        },
        headers=alice_h,
    )
    assert post_res.status_code == 201
    created = post_res.json()
    form_id = created["id"]
    assert created["reminder_id"] is not None
    assert created["safeguards"]["is_under_13"] is True
    assert created["safeguards"]["guardian_only"] is True
    assert created["prefill_draft"]["immunisations"] == []

    # Charlie (view_clinical) cannot POST
    charlie_post = client.post(
        f"/api/profiles/{prof_id}/school-forms",
        json={"title": "Unauthorized Create"},
        headers=charlie_h,
    )
    assert charlie_post.status_code == 403

    # Dan (view_paperwork) cannot GET
    dan_get = client.get(f"/api/profiles/{prof_id}/school-forms", headers=dan_h)
    assert dan_get.status_code == 403

    # 2. Add a new HealthResource immunization and regenerate prefill via POST /prefill
    async def _add_vaccine():
        async with session_factory() as session:
            session.add(
                HealthResource(
                    id=str(uuid.uuid4()),
                    profile_id=prof_id,
                    resource_type="immunization",
                    source_type="manual",
                    data={"vaccineCode": {"text": "DTaP Booster"}, "occurrenceDateTime": "2026-08-10"},
                    status="active",
                    effective_at=now,
                    recorded_at=now,
                )
            )
            await session.commit()

    run_async(_add_vaccine())

    prefill_res = client.post(
        f"/api/profiles/{prof_id}/school-forms/{form_id}/prefill",
        headers=alice_h,
    )
    assert prefill_res.status_code == 200
    regenerated = prefill_res.json()
    assert len(regenerated["prefill_draft"]["immunisations"]) == 1
    assert regenerated["prefill_draft"]["immunisations"][0]["vaccine"] == "DTaP Booster"

    # 3. GET single & list
    get_res = client.get(f"/api/profiles/{prof_id}/school-forms/{form_id}", headers=charlie_h)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == form_id

    list_res = client.get(f"/api/profiles/{prof_id}/school-forms", headers=charlie_h)
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1

    # 4. PATCH status to active
    patch_res = client.patch(
        f"/api/profiles/{prof_id}/school-forms/{form_id}",
        json={"status": "active", "school_or_camp_name": "Lincoln Unified Elementary"},
        headers=alice_h,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "active"
    assert patch_res.json()["school_or_camp_name"] == "Lincoln Unified Elementary"

    # 5. DELETE form
    del_res = client.delete(f"/api/profiles/{prof_id}/school-forms/{form_id}", headers=alice_h)
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True
