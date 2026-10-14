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

"""Unit, integration, and API test suite for Typed Notes & After-Visit Extraction (AU-35)."""

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
from carefold.clinical.notes import (
    NON_CLINICAL_DISCLAIMER,
    VALID_NOTE_TYPES,
    extract_after_visit_summary,
    validate_note_type,
)
from carefold.config import settings
from carefold.db.models import Appointment, Job, Note, Profile, ProfileAccess, User
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.engine.tool_exec import ToolContext
from carefold.main import app
from carefold.tools.notes import execute_create_typed_note


def run_async(coro):
    return asyncio.run(coro)


# ============================================================================
# Section 1: Note Categories & Type Validation Tests (AU-35)
# ============================================================================


def test_valid_note_types_canonical_set():
    """Verifies that VALID_NOTE_TYPES contains all 7 canonical categories."""
    expected = {"visit", "symptom", "question", "after_visit", "school", "scratchpad", "general"}
    assert VALID_NOTE_TYPES == expected
    assert len(VALID_NOTE_TYPES) == 7


def test_validate_note_type_success():
    """Verifies all 7 valid categories pass validation and normalize casing/whitespace."""
    for category in VALID_NOTE_TYPES:
        assert validate_note_type(category) == category
        assert validate_note_type(category.upper()) == category
        assert validate_note_type(f"  {category.capitalize()}  ") == category


def test_validate_note_type_invalid_raises():
    """Verifies invalid or unknown categories raise ValueError fail-closed."""
    invalid_categories = ["soap", "clinical_prep", "billing", "random_note", "", "   "]
    for bad in invalid_categories:
        with pytest.raises(ValueError):
            validate_note_type(bad, allow_legacy=False)


def test_validate_note_type_legacy_mapping():
    """Verifies legacy type mapping when allow_legacy=True."""
    assert validate_note_type("clinical_prep", allow_legacy=True) == "question"
    assert validate_note_type("visit_summary", allow_legacy=True) == "after_visit"


# ============================================================================
# Section 2: After-Visit Summary Extraction Tests (AU-35)
# ============================================================================


def test_after_visit_extraction_diagnoses_with_citations():
    """Verifies diagnoses are extracted with 1-indexed [Note Line X] citations."""
    note_text = (
        "Consultation with Dr. Emily Watson on 2026-10-12.\n"
        "Patient presents with intermittent palpitations.\n"
        "Diagnosis: mild essential hypertension and benign palpitations.\n"
        "Recommended lowering dietary sodium."
    )
    res = extract_after_visit_summary(note_text)
    assert len(res["diagnoses"]) >= 1
    diag = res["diagnoses"][0]
    assert "mild essential hypertension" in diag["text"].lower()
    assert diag["citation"] == "[Note Line 3]"


def test_after_visit_extraction_medications_with_dosage_and_citations():
    """Verifies medication adjustments parse dosage units and carry line citations."""
    note_text = (
        "Doctor's debrief notes:\n"
        "Continue current multivitamin.\n"
        "Prescribed Lisinopril 10mg daily by mouth.\n"
        "Follow-up in 4 weeks."
    )
    res = extract_after_visit_summary(note_text)
    assert len(res["medication_adjustments"]) == 1
    med = res["medication_adjustments"][0]
    assert "Lisinopril 10mg" in med["text"]
    assert med["citation"] == "[Note Line 3]"


def test_after_visit_extraction_excludes_generic_otc_advice():
    """Verifies generic over-the-counter advice is NOT classified as prescription medication."""
    note_text = (
        "Post-visit clinical guidance:\n"
        "Prescribed Metformin 500mg twice daily with meals.\n"
        "Stop taking generic over-the-counter decongestants.\n"
        "Discontinue otc cold remedies."
    )
    res = extract_after_visit_summary(note_text)
    meds = res["medication_adjustments"]
    assert len(meds) == 1
    assert "Metformin 500mg" in meds[0]["text"]
    assert not any("decongestants" in m["text"].lower() for m in meds)
    assert not any("cold remedies" in m["text"].lower() for m in meds)


def test_after_visit_extraction_ordered_tests_and_follow_up():
    """Verifies ordered tests and follow-up timeline extraction."""
    note_text = (
        "Clinic encounter:\n"
        "Ordered comprehensive metabolic panel and fasting lipid panel.\n"
        "Follow-up in 6 weeks for blood pressure recheck."
    )
    res = extract_after_visit_summary(note_text)
    assert len(res["ordered_tests"]) >= 1
    assert "lipid panel" in res["ordered_tests"][0]["text"].lower()
    assert res["ordered_tests"][0]["citation"] == "[Note Line 2]"

    assert len(res["follow_up_timeline"]) >= 1
    assert "6 weeks" in res["follow_up_timeline"][0]["text"].lower()
    assert res["follow_up_timeline"][0]["citation"] == "[Note Line 3]"


def test_after_visit_extraction_mandatory_disclaimer():
    """Verifies the mandatory non-clinical disclaimer is always present."""
    res = extract_after_visit_summary("Single line note without clinical entities.")
    assert res["disclaimer"] == NON_CLINICAL_DISCLAIMER
    assert "Extracted from your notes, not formal medical advice." in res["disclaimer"]


# ============================================================================
# Section 3: Relational Persistence and Indexing Tests (AU-35)
# ============================================================================


@pytest.fixture
def notes_test_db(monkeypatch):
    """Sets up an isolated SQLite DB with a patient profile, user, and appointment."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    run_async(init_db(engine))
    session_factory = get_session_factory(engine)
    monkeypatch.setattr("carefold.tools.notes.get_session_factory", lambda: session_factory)

    user_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    appt_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async def _init_data():
        async with session_factory() as session:
            user = User(
                id=user_id,
                email="taylor@test.local",
                username="taylor_test",
                hashed_password="pbkdf2_sha256$test",
                role="member",
                auth_provider="local",
                created_at=now,
                updated_at=now,
            )
            session.add(user)

            prof = Profile(
                id=profile_id,
                user_id=user_id,
                name="Taylor Swift",
                relationship="self",
                role="self",
                created_at=now,
                updated_at=now,
            )
            session.add(prof)

            appt = Appointment(
                id=appt_id,
                profile_id=profile_id,
                title="Pulmonology Consultation",
                start_time=now + timedelta(days=1),
                end_time=now + timedelta(days=1, hours=1),
                specialty="Pulmonology",
                status="confirmed",
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


def test_create_typed_note_tool_success_and_indexing(notes_test_db):
    """Verifies execute_create_typed_note persists Note and enqueues index_doc job."""
    prof_id = notes_test_db["profile_id"]
    appt_id = notes_test_db["appointment_id"]
    u_id = notes_test_db["user_id"]
    factory = notes_test_db["session_factory"]

    ctx = ToolContext(profile_id=prof_id, user_id=u_id)
    args = {
        "title": "Post-Visit Debrief",
        "content": "Doctor prescribed albuterol inhaler for exercise induced wheeze.",
        "type": "after_visit",
        "linked_appointment_id": appt_id,
        "tags": ["pulmonology", "inhaler"],
    }

    result = run_async(execute_create_typed_note(args, ctx))
    assert result.success is True
    assert result.error is None
    note_id = result.output["id"]
    assert result.output["type"] == "after_visit"
    assert result.output["linked_appointment_id"] == appt_id
    assert "pulmonology" in result.output["tags"]

    async def _verify_db():
        async with factory() as session:
            note_stmt = select(Note).where(Note.id == note_id)
            n_res = await session.execute(note_stmt)
            note = n_res.scalar_one_or_none()
            assert note is not None
            assert note.type == "after_visit"
            assert note.linked_appointment_id == appt_id

            job_stmt = select(Job).where(Job.profile_id == prof_id, Job.kind == "index_doc")
            j_res = await session.execute(job_stmt)
            job = j_res.scalar_one_or_none()
            assert job is not None
            payload = json.loads(job.payload)
            assert payload["document_id"] == note_id
            assert payload["doc_type"] == "note"

    run_async(_verify_db())


def test_create_typed_note_tool_cross_profile_appointment_rejection(notes_test_db):
    """Verifies linking an appointment from another profile is rejected fail-closed."""
    factory = notes_test_db["session_factory"]
    appt_id = notes_test_db["appointment_id"]
    other_prof_id = str(uuid.uuid4())

    async def _init_other():
        async with factory() as session:
            session.add(Profile(id=other_prof_id, name="Other", relationship="self", role="self"))
            await session.commit()

    run_async(_init_other())

    ctx = ToolContext(profile_id=other_prof_id, user_id="user-other")
    args = {
        "title": "Sneaky Note",
        "content": "Trying to link another profile's appointment",
        "type": "visit",
        "linked_appointment_id": appt_id,
    }

    result = run_async(execute_create_typed_note(args, ctx))
    assert result.success is False
    assert "Security violation" in result.error
    assert "Linked appointment does not exist or does not belong to profile" in result.error


def test_create_typed_note_tool_invalid_type_rejection(notes_test_db):
    """Verifies invalid note category is rejected fail-closed."""
    prof_id = notes_test_db["profile_id"]
    ctx = ToolContext(profile_id=prof_id, user_id="user-test")
    args = {
        "title": "Invalid Note",
        "content": "Valid content",
        "type": "invalid_category",
    }
    result = run_async(execute_create_typed_note(args, ctx))
    assert result.success is False
    assert "invalid_category" in result.error


# ============================================================================
# Section 4: REST API Endpoints Tests (AU-35)
# ============================================================================


@pytest.fixture
def notes_api_env(monkeypatch):
    """Sets up FastAPI test environment with authenticated users and profiles."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    run_async(init_db(engine))
    session_factory = get_session_factory(engine)
    auth_adapter = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr("carefold.tools.notes.get_session_factory", lambda: session_factory)
    set_auth_port(auth_adapter)

    async def _setup():
        # Alice: Owner
        alice = await auth_adapter.register_user(
            email="alice_note@test.local",
            username="alice_note",
            password="Password123!",
            full_name="Alice Patient",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # Charlie: Clinical view
        charlie = await auth_adapter.register_user(
            email="charlie_note@test.local",
            username="charlie_note",
            password="Password123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # Dan: Paperwork only
        dan = await auth_adapter.register_user(
            email="dan_note@test.local",
            username="dan_note",
            password="Password123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # Eve: Unauthorized
        eve = await auth_adapter.register_user(
            email="eve_note@test.local",
            username="eve_note",
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
                title="Cardiology Visit",
                start_time=now + timedelta(days=2),
                end_time=now + timedelta(days=2, hours=1),
                specialty="Cardiology",
                status="confirmed",
                created_at=now,
                updated_at=now,
            )
            session.add(appt)

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


def test_typed_notes_rest_api_crud_and_extract(notes_api_env):
    """End-to-end REST test of profile-scoped typed notes CRUD and extraction."""
    client = TestClient(app)
    prof_id = notes_api_env["profile_id"]
    appt_id = notes_api_env["appointment_id"]

    alice_headers = {"Authorization": f"Bearer {notes_api_env['alice_token']}"}
    charlie_headers = {"Authorization": f"Bearer {notes_api_env['charlie_token']}"}
    dan_headers = {"Authorization": f"Bearer {notes_api_env['dan_token']}"}
    eve_headers = {"Authorization": f"Bearer {notes_api_env['eve_token']}"}

    # 1. POST create note with invalid type returns 422
    bad_payload = {
        "title": "Bad Type Note",
        "content": "Content here",
        "type": "invalid_type_name",
    }
    res_bad = client.post(f"/api/profiles/{prof_id}/notes", json=bad_payload, headers=alice_headers)
    assert res_bad.status_code == 422

    # 2. POST create note with cross-profile appointment returns 400
    bogus_appt = str(uuid.uuid4())
    cross_payload = {
        "title": "Cross Appt Note",
        "content": "Content here",
        "type": "visit",
        "linked_appointment_id": bogus_appt,
    }
    res_cross = client.post(f"/api/profiles/{prof_id}/notes", json=cross_payload, headers=alice_headers)
    assert res_cross.status_code == 400

    # 3. Paperwork user cannot create note (403)
    valid_payload = {
        "title": "Clinic After-Visit Summary",
        "content": (
            "Visit with Dr. House.\n"
            "Diagnosed with mild hypertension.\n"
            "Prescribed Amlodipine 5mg daily.\n"
            "Follow-up in 30 days."
        ),
        "type": "after_visit",
        "linked_appointment_id": appt_id,
        "tags": ["hypertension", "followup"],
    }
    res_dan = client.post(f"/api/profiles/{prof_id}/notes", json=valid_payload, headers=dan_headers)
    assert res_dan.status_code == 403

    # 4. Owner creates note successfully (201)
    res_create = client.post(f"/api/profiles/{prof_id}/notes", json=valid_payload, headers=alice_headers)
    assert res_create.status_code == 201
    note_data = res_create.json()
    note_id = note_data["id"]
    assert note_data["type"] == "after_visit"
    assert note_data["linked_appointment_id"] == appt_id
    assert note_data["profile_id"] == prof_id

    # 5. Clinical viewer can list notes (200) and filter by type
    res_list = client.get(f"/api/profiles/{prof_id}/notes?type=after_visit", headers=charlie_headers)
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["total"] >= 1
    assert any(n["id"] == note_id for n in list_data["notes"])

    # 6. Clinical viewer can retrieve note detail (200)
    res_get = client.get(f"/api/profiles/{prof_id}/notes/{note_id}", headers=charlie_headers)
    assert res_get.status_code == 200
    assert res_get.json()["id"] == note_id

    # 7. Extract after-visit summary via endpoint
    res_extract = client.post(f"/api/profiles/{prof_id}/notes/{note_id}/extract", headers=alice_headers)
    assert res_extract.status_code == 200
    ext_data = res_extract.json()
    assert len(ext_data["diagnoses"]) >= 1
    assert ext_data["diagnoses"][0]["citation"] == "[Note Line 2]"
    assert len(ext_data["medication_adjustments"]) == 1
    assert "Amlodipine 5mg" in ext_data["medication_adjustments"][0]["text"]
    assert ext_data["medication_adjustments"][0]["citation"] == "[Note Line 3]"
    assert ext_data["disclaimer"] == NON_CLINICAL_DISCLAIMER

    # 8. Update note content
    patch_payload = {
        "title": "Updated Clinic Debrief",
        "tags": ["updated", "hypertension"],
    }
    res_patch = client.patch(f"/api/profiles/{prof_id}/notes/{note_id}", json=patch_payload, headers=alice_headers)
    assert res_patch.status_code == 200
    assert res_patch.json()["title"] == "Updated Clinic Debrief"

    # 9. Delete note
    res_del = client.delete(f"/api/profiles/{prof_id}/notes/{note_id}", headers=alice_headers)
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # 10. GET deleted note returns 404
    res_get_deleted = client.get(f"/api/profiles/{prof_id}/notes/{note_id}", headers=charlie_headers)
    assert res_get_deleted.status_code == 404
