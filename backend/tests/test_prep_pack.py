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

"""Unit, integration, and API test suite for Clinical Visit Preparation Packs (AU-33, AU-34)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.clinical.prep_pack import (
    NON_CLINICAL_DISCLAIMER,
    compile_clinical_prep_pack,
    compile_execution_plan,
    generate_and_persist_prep_pack,
    synthesize_doctor_questions,
)
from carefold.config import settings
from carefold.db.models import Appointment, Job, Note, Profile, ProfileAccess, User
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.tool_exec import ToolContext
from carefold.main import app
from carefold.schemas.plan import ExecutionPlan
from carefold.tools.prep_pack import execute_generate_prep_pack


def run_async(coro):
    return asyncio.run(coro)


# ============================================================================
# Section 1: ExecutionPlan Template Compilation Tests (AU-33)
# ============================================================================


def test_compile_execution_plan_visit_prep():
    """Verifies visit_prep compiles to 4 structured steps with proper parameters."""
    params = {
        "appointment_id": "appt-123",
        "specialty": "Cardiology",
        "reason": "Chest tightness and palpitations",
        "doctor_questions": ["What caused the spike?"],
    }
    plan = compile_execution_plan("visit_prep", params)

    assert isinstance(plan, ExecutionPlan)
    assert plan.intent == "visit_prep"
    assert plan["intent"] == "visit_prep"
    assert plan["status"] == "compiled"
    assert "steps" in plan
    steps = plan["steps"]
    assert len(steps) == 4

    tools = [s["tool"] for s in steps]
    assert tools == [
        "search_records",
        "calculate_trends",
        "draft_questions",
        "generate_prep_pack",
    ]


def test_compile_execution_plan_log_vitals():
    """Verifies log_vitals compiles to 3 steps."""
    params = {
        "systolic": 138,
        "diastolic": 88,
    }
    plan = compile_execution_plan("log_vitals", params)

    assert isinstance(plan, ExecutionPlan)
    assert plan["intent"] == "log_vitals"
    assert len(plan["steps"]) == 3
    tools = [s["tool"] for s in plan["steps"]]
    assert tools == ["parse_observation", "check_red_flags", "record_vitals"]


def test_compile_execution_plan_remind_me():
    """Verifies remind_me compiles to 2 steps."""
    params = {
        "title": "Take Lisinopril 10mg",
        "time": "08:00",
    }
    plan = compile_execution_plan("remind_me", params)

    assert isinstance(plan, ExecutionPlan)
    assert plan["intent"] == "remind_me"
    assert len(plan["steps"]) == 2
    tools = [s["tool"] for s in plan["steps"]]
    assert tools == ["parse_rrule", "create_reminder"]


def test_compile_execution_plan_unknown_intent():
    """Verifies unknown intent raises ValueError fail-closed."""
    with pytest.raises(ValueError, match="Unknown ExecutionPlan intent"):
        compile_execution_plan("unknown_workflow", {"key": "val"})


def test_execution_plan_dict_subscripting_and_methods():
    """Verifies backward compatibility dict operations on ExecutionPlan."""
    plan = compile_execution_plan("visit_prep", {"appointment_id": "appt-xyz"})

    # Subscript access
    assert plan["intent"] == "visit_prep"
    assert plan["status"] == "compiled"
    assert isinstance(plan["steps"], list)
    assert isinstance(plan["id"], str)

    # In operator
    assert "intent" in plan
    assert "steps" in plan
    assert "non_existent_key" not in plan

    # Get method
    assert plan.get("intent") == "visit_prep"
    assert plan.get("non_existent_key", "default_val") == "default_val"
    assert plan.get("non_existent_key") is None

    # KeyError on invalid subscript
    with pytest.raises(KeyError):
        _ = plan["non_existent_field"]


# ============================================================================
# Section 2: Doctor Questions Synthesis Tests (AU-34)
# ============================================================================


def test_synthesize_doctor_questions_user_questions_priority():
    """Verifies explicit patient questions take top priority."""
    user_qs = [
        "Can I switch from amlodipine to something else?",
        "Why is my resting pulse higher at night?",
    ]
    qs = synthesize_doctor_questions(
        specialty="Cardiology",
        custom_questions=user_qs,
    )
    assert len(qs) >= 2
    assert qs[0] == user_qs[0]
    assert qs[1] == user_qs[1]
    assert len(qs) <= 5


def test_synthesize_doctor_questions_specialty_prompts():
    """Verifies specialty-specific questions are injected when space permits."""
    # Cardiology
    cardio_qs = synthesize_doctor_questions(specialty="Cardiology")
    assert any("blood pressure" in q.lower() or "monitoring" in q.lower() for q in cardio_qs)

    # Endocrinology
    endo_qs = synthesize_doctor_questions(specialty="Endocrinology")
    assert any("glucose" in q.lower() or "a1c" in q.lower() for q in endo_qs)

    # Pulmonology
    pulm_qs = synthesize_doctor_questions(specialty="Pulmonology")
    assert any("inhaler" in q.lower() or "symptom" in q.lower() for q in pulm_qs)


def test_synthesize_doctor_questions_vitals_triggers():
    """Verifies vitals abnormalities trigger targeted questions."""
    trends = {
        "30_day": {
            "am": {"systolic": 140.0, "diastolic": 90.0, "classification": "Stage 2"},
            "pm": {"systolic": 142.0, "diastolic": 92.0, "classification": "Stage 2"},
        }
    }
    qs = synthesize_doctor_questions(
        specialty="General",
        vitals_trends=trends,
        custom_questions=["How is my diet?"],
    )
    assert len(qs) <= 5
    assert qs[0] == "How is my diet?"
    assert any("elevated" in q.lower() or "blood pressure" in q.lower() for q in qs)


def test_synthesize_doctor_questions_clamped_to_five():
    """Verifies that the synthesized questions never exceed 5."""
    user_qs = [f"Patient Question {i}" for i in range(1, 10)]
    qs = synthesize_doctor_questions(specialty="Cardiology", custom_questions=user_qs)
    assert len(qs) == 5
    assert qs == user_qs[:5]


# ============================================================================
# Section 3: Clinical Prep Pack Compiler Tests (AU-34)
# ============================================================================


def test_compile_clinical_prep_pack_full_data():
    """Verifies prep pack markdown formatting with all sections and metadata."""
    trends = {
        "30_day": {
            "am": {"systolic": 134.2, "diastolic": 86.1, "classification": "Stage 1"},
            "pm": {"systolic": 136.0, "diastolic": 88.0, "classification": "Stage 1"},
        }
    }
    res = compile_clinical_prep_pack(
        reason_for_visit="Hypertension follow-up and palpitations",
        specialty="Cardiology",
        appointment_date="2026-10-20",
        symptoms=[
            "Mild fluttering sensation in chest after coffee",
            "Lightheadedness upon standing",
        ],
        vitals_trends=trends,
        medications=["Lisinopril 10mg daily", "Metoprolol Succinate 25mg daily"],
        allergies=["Penicillin (hives)"],
        doctor_questions=[
            "Should we adjust the Lisinopril dosage given the higher evening readings?",
            "Is the palpitations episode related to my medication timing?",
        ],
        search_excerpts=[
            "Echocardiogram 2025-04: Normal left ventricular ejection fraction 60-65%."
        ],
    )

    assert res["title"] == "Prep Pack: Hypertension follow-up and palpitations"
    assert res["questions_count"] == 2
    assert res["has_vitals_summary"] is True
    assert res["printable_html_ready"] is True

    md = res["markdown"]
    assert "# Clinical Visit Preparation Dossier" in md
    assert "Cardiology" in md
    assert "## 1. Recent Symptoms Timeline" in md
    assert "Mild fluttering sensation in chest" in md
    assert "## 2. Vitals Trends Summary" in md
    assert "134.2/86.1 mmHg (Stage 1)" in md
    assert "## 3. Active Medications & Allergies" in md
    assert "Lisinopril 10mg daily" in md
    assert "Penicillin (hives)" in md
    assert "## 4. Prioritized Doctor Questions" in md
    assert "Should we adjust the Lisinopril dosage" in md
    assert "## 5. Relevant History from Prior Records" in md
    assert "Normal left ventricular ejection fraction" in md
    assert NON_CLINICAL_DISCLAIMER in md


def test_compile_clinical_prep_pack_empty_fallbacks():
    """Verifies that empty fields render polite fallbacks without crashing."""
    res = compile_clinical_prep_pack(
        reason_for_visit="General Health Check",
        specialty=None,
        appointment_date=None,
        symptoms=[],
        vitals_trends={},
        medications=[],
        allergies=[],
        doctor_questions=[],
        search_excerpts=[],
    )

    assert res["title"] == "Prep Pack: General Health Check"
    assert res["has_vitals_summary"] is False
    assert res["questions_count"] == 0

    md = res["markdown"]
    assert "No recent acute symptoms reported." in md
    assert "No recent vitals recorded." in md
    assert "Medications**: None reported" in md
    assert "Allergies**: No known drug allergies" in md
    assert NON_CLINICAL_DISCLAIMER in md


# ============================================================================
# Section 4: Persistence and Job Enqueueing Tests (AU-34)
# ============================================================================


@pytest.fixture
def prep_pack_test_db(monkeypatch):
    """Sets up an isolated SQLite DB for persistence testing."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    run_async(init_db(engine))
    session_factory = get_session_factory(engine)
    monkeypatch.setattr("carefold.tools.prep_pack.get_session_factory", lambda: session_factory)

    user_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    appt_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async def _init_data():
        async with session_factory() as session:
            # Create user to satisfy FK
            user = User(
                id=user_id,
                email="jordan@test.local",
                username="jordan_test",
                hashed_password="pbkdf2_sha256$placeholder",
                role="member",
                auth_provider="local",
                created_at=now,
                updated_at=now,
            )
            session.add(user)

            prof = Profile(
                id=profile_id,
                user_id=user_id,
                name="Jordan Lee",
                relationship="self",
                role="self",
                created_at=now,
                updated_at=now,
            )
            session.add(prof)

            appt = Appointment(
                id=appt_id,
                profile_id=profile_id,
                title="Cardiology Visit",
                start_time=now + timedelta(days=2),
                end_time=now + timedelta(days=2, hours=1),
                specialty="Cardiology",
                status="confirmed",
                reason="Palpitations",
                created_at=now,
                updated_at=now,
            )
            session.add(appt)
            await session.commit()

    run_async(_init_data())
    return {
        "session_factory": session_factory,
        "profile_id": profile_id,
        "appointment_id": appt_id,
        "user_id": user_id,
    }


def test_generate_and_persist_prep_pack_creates_note_and_job(prep_pack_test_db):
    """Verifies prep pack is persisted as visit Note and enqueues index_doc job."""
    factory = prep_pack_test_db["session_factory"]
    prof_id = prep_pack_test_db["profile_id"]
    appt_id = prep_pack_test_db["appointment_id"]
    u_id = prep_pack_test_db["user_id"]

    async def _test():
        async with factory() as session:
            res = await generate_and_persist_prep_pack(
                session=session,
                profile_id=prof_id,
                appointment_id=appt_id,
                specialty="Cardiology",
                visit_reason="Palpitations follow-up",
                doctor_questions=["Is caffeine the cause?"],
                user_id=u_id,
            )
            assert res["profile_id"] == prof_id
            assert res["appointment_id"] == appt_id
            assert res["note_id"] is not None
            assert "Clinical Visit Preparation Dossier" in res["markdown"]

            # Verify Note persisted in DB
            note_stmt = select(Note).where(Note.id == res["note_id"])
            note_res = await session.execute(note_stmt)
            note = note_res.scalar_one_or_none()
            assert note is not None
            assert note.type == "visit"
            assert note.linked_appointment_id == appt_id
            assert note.profile_id == prof_id
            assert "Is caffeine the cause?" in note.content

            # Verify index_doc Job enqueued
            job_stmt = select(Job).where(Job.profile_id == prof_id, Job.kind == "index_doc")
            job_res = await session.execute(job_stmt)
            job = job_res.scalar_one_or_none()
            assert job is not None
            payload = json.loads(job.payload)
            assert payload["document_id"] == res["note_id"]
            assert payload["doc_type"] == "note"

    run_async(_test())


def test_generate_and_persist_prep_pack_cross_profile_rejection(prep_pack_test_db):
    """Verifies linking an appointment belonging to another profile fails."""
    factory = prep_pack_test_db["session_factory"]
    other_prof_id = str(uuid.uuid4())
    appt_id = prep_pack_test_db["appointment_id"]

    async def _test():
        async with factory() as session:
            # Create other profile
            other_prof = Profile(
                id=other_prof_id,
                name="Other User",
                relationship="self",
                role="self",
            )
            session.add(other_prof)
            await session.commit()

            with pytest.raises(ValueError, match="not found for profile"):
                await generate_and_persist_prep_pack(
                    session=session,
                    profile_id=other_prof_id,
                    appointment_id=appt_id,
                )

    run_async(_test())


# ============================================================================
# Section 5: ToolSpec Execution Tests (AU-34)
# ============================================================================


def test_execute_generate_prep_pack_tool_success(prep_pack_test_db):
    """Verifies execute_generate_prep_pack Tool executes successfully."""
    prof_id = prep_pack_test_db["profile_id"]
    appt_id = prep_pack_test_db["appointment_id"]
    u_id = prep_pack_test_db["user_id"]
    ctx = ToolContext(profile_id=prof_id, user_id=u_id)

    args = {
        "appointment_id": appt_id,
        "specialty": "Cardiology",
        "visit_reason": "Palpitations evaluation",
        "doctor_questions": ["What is my target resting HR?"],
    }

    result = run_async(execute_generate_prep_pack(args, ctx))
    assert result.success is True
    assert result.error is None
    assert result.output["profile_id"] == prof_id
    assert result.output["appointment_id"] == appt_id
    assert result.output["note_id"] is not None
    assert result.output["undo_reference"] == f"note:{result.output['note_id']}"


def test_execute_generate_prep_pack_tool_missing_profile_security_error():
    """Verifies tool rejects invocation without profile_id in ToolContext."""
    result = run_async(execute_generate_prep_pack({}, None))
    assert result.success is False
    assert "Security violation" in result.error


# ============================================================================
# Section 6: REST API Endpoint Tests (AU-33, AU-34)
# ============================================================================


@pytest.fixture
def prep_pack_api_env(monkeypatch):
    """Sets up FastAPI test environment with authenticated users and profiles."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    run_async(init_db(engine))
    session_factory = get_session_factory(engine)
    auth_adapter = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr("carefold.tools.prep_pack.get_session_factory", lambda: session_factory)
    set_auth_port(auth_adapter)

    async def _setup():
        # Alice: Profile owner
        alice = await auth_adapter.register_user(
            email="alice_prep@test.local",
            username="alice_prep",
            password="Password123!",
            full_name="Alice Patient",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # Bob: Manage access
        bob = await auth_adapter.register_user(
            email="bob_prep@test.local",
            username="bob_prep",
            password="Password123!",
            full_name="Bob Manager",
            role="member",
            auth_provider="local",
        )
        bob_session = await auth_adapter.create_session(bob.id)

        # Charlie: Clinical view access
        charlie = await auth_adapter.register_user(
            email="charlie_prep@test.local",
            username="charlie_prep",
            password="Password123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # Dan: Paperwork view only
        dan = await auth_adapter.register_user(
            email="dan_prep@test.local",
            username="dan_prep",
            password="Password123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # Eve: Unauthorized
        eve = await auth_adapter.register_user(
            email="eve_prep@test.local",
            username="eve_prep",
            password="Password123!",
            full_name="Eve Stranger",
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

            appt = Appointment(
                id=str(uuid.uuid4()),
                profile_id=alice_profile.id,
                title="Cardiology Consultation",
                start_time=now + timedelta(days=3),
                end_time=now + timedelta(days=3, hours=1),
                specialty="Cardiology",
                status="confirmed",
                reason="Chest tightness",
                created_at=now,
                updated_at=now,
            )
            session.add(appt)

            # Permissions grants
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
                "appointment_id": appt.id,
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


def test_prep_pack_rest_api_lifecycle(prep_pack_api_env):
    """End-to-end REST test of POST and GET prep pack with RBAC."""
    client = TestClient(app)
    prof_id = prep_pack_api_env["profile_id"]
    appt_id = prep_pack_api_env["appointment_id"]

    alice_headers = {"Authorization": f"Bearer {prep_pack_api_env['alice_token']}"}
    charlie_headers = {"Authorization": f"Bearer {prep_pack_api_env['charlie_token']}"}
    dan_headers = {"Authorization": f"Bearer {prep_pack_api_env['dan_token']}"}
    eve_headers = {"Authorization": f"Bearer {prep_pack_api_env['eve_token']}"}

    # 1. Paperwork-only user cannot generate prep pack (403)
    post_payload = {
        "appointment_id": appt_id,
        "specialty": "Cardiology",
        "visit_reason": "Chest tightness",
        "doctor_questions": ["What tests are indicated?"],
    }
    res_dan = client.post(f"/api/profiles/{prof_id}/prep-pack", json=post_payload, headers=dan_headers)
    assert res_dan.status_code == 403

    # 2. Unauthorized user cannot generate prep pack (403)
    res_eve = client.post(f"/api/profiles/{prof_id}/prep-pack", json=post_payload, headers=eve_headers)
    assert res_eve.status_code == 403

    # 3. Owner creates prep pack successfully (201)
    res_create = client.post(f"/api/profiles/{prof_id}/prep-pack", json=post_payload, headers=alice_headers)
    assert res_create.status_code == 201
    pack_data = res_create.json()
    assert pack_data["profile_id"] == prof_id
    assert pack_data["appointment_id"] == appt_id
    assert pack_data["note_id"] is not None
    assert pack_data["printable_html_ready"] is True
    assert "Clinical Visit Preparation Dossier" in pack_data["markdown"]

    # 4. Clinical viewer can retrieve prep pack (200)
    res_get = client.get(f"/api/profiles/{prof_id}/prep-pack/{appt_id}", headers=charlie_headers)
    assert res_get.status_code == 200
    get_data = res_get.json()
    assert get_data["note_id"] == pack_data["note_id"]
    assert get_data["appointment_id"] == appt_id

    # 5. Paperwork user cannot view prep pack (403)
    res_get_dan = client.get(f"/api/profiles/{prof_id}/prep-pack/{appt_id}", headers=dan_headers)
    assert res_get_dan.status_code == 403

    # 6. Non-existent appointment returns 404
    bogus_appt = str(uuid.uuid4())
    res_not_found = client.get(f"/api/profiles/{prof_id}/prep-pack/{bogus_appt}", headers=alice_headers)
    assert res_not_found.status_code == 404
