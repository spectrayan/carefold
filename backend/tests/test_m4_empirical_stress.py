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

"""Empirical adversarial stress harness for Milestone 4 (AU-35):
Extraction Engine citations, OTC vs prescription differentiation, typed notes categories,
cross-profile appointment security, and multi-tenant RBAC permissions.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.clinical.notes import (
    NON_CLINICAL_DISCLAIMER,
    NoteType,
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
# Section 1: Extraction Engine Citations & Line Parsing Stress
# ============================================================================


class TestExtractionEngineCitationsStress:
    """Stress tests verifying 1-indexed [Note Line X] physical line citations."""

    def test_citations_with_interleaved_blank_lines(self):
        """Verifies physical line numbering across interleaved and multiple consecutive blank lines."""
        note = (
            "\n"                                                           # Line 1: blank
            "Diagnosis: Paroxysmal atrial fibrillation\n"                  # Line 2
            "\n"                                                           # Line 3: blank
            "\n"                                                           # Line 4: blank
            "Prescribed Apixaban 5mg tablet twice daily\n"                 # Line 5
            "   \n"                                                        # Line 6: whitespace-only line
            "Ordered echocardiogram and 14-day holter monitor\n"           # Line 7
            "\n"                                                           # Line 8: blank
            "Follow-up in 4 weeks with electrophysiologist\n"             # Line 9
            "\n"                                                           # Line 10: blank
            "Reminder: monitor pulse twice daily\n"                        # Line 11
        )
        res = extract_after_visit_summary(note)

        assert len(res["diagnoses"]) == 1
        assert res["diagnoses"][0]["citation"] == "[Note Line 2]"
        assert "atrial fibrillation" in res["diagnoses"][0]["text"].lower()

        assert len(res["medication_adjustments"]) == 1
        assert res["medication_adjustments"][0]["citation"] == "[Note Line 5]"
        assert "Apixaban 5mg" in res["medication_adjustments"][0]["text"]

        assert len(res["ordered_tests"]) == 1
        assert res["ordered_tests"][0]["citation"] == "[Note Line 7]"
        assert "echocardiogram" in res["ordered_tests"][0]["text"].lower()

        assert len(res["follow_up_timeline"]) == 1
        assert res["follow_up_timeline"][0]["citation"] == "[Note Line 9]"
        assert "4 weeks" in res["follow_up_timeline"][0]["text"].lower()

        assert len(res["recommended_reminders"]) == 1
        assert res["recommended_reminders"][0]["citation"] == "[Note Line 11]"
        assert "pulse" in res["recommended_reminders"][0]["text"].lower()

        assert res["extracted_items_count"] == 5
        assert res["disclaimer"] == NON_CLINICAL_DISCLAIMER

    def test_citations_with_markdown_headers_and_leading_blanks(self):
        """Verifies citations when markdown headers (#, ##, ###) and clinical text are interleaved."""
        note = (
            "# Visit Summary - Cardiology Consult\n"                       # Line 1
            "Patient: Taylor S.\n"                                         # Line 2
            "## Clinical Impression\n"                                     # Line 3
            "Assessment: Stage 1 essential hypertension\n"                 # Line 4
            "### Plan & Medication Changes\n"                              # Line 5
            "Started on Losartan 50mg daily by mouth\n"                    # Line 6
            "### Laboratory and Diagnostic Orders\n"                       # Line 7
            "Ordered blood work including comprehensive metabolic panel\n" # Line 8
            "### Next Steps\n"                                             # Line 9
            "Return in 3 months for blood pressure recheck\n"              # Line 10
        )
        res = extract_after_visit_summary(note)

        assert len(res["diagnoses"]) == 1
        assert res["diagnoses"][0]["citation"] == "[Note Line 4]"
        assert "essential hypertension" in res["diagnoses"][0]["text"].lower()

        assert len(res["medication_adjustments"]) == 1
        assert res["medication_adjustments"][0]["citation"] == "[Note Line 6]"
        assert "Losartan 50mg" in res["medication_adjustments"][0]["text"]

        assert len(res["ordered_tests"]) == 1
        assert res["ordered_tests"][0]["citation"] == "[Note Line 8]"

        assert len(res["follow_up_timeline"]) == 1
        assert res["follow_up_timeline"][0]["citation"] == "[Note Line 10]"

    def test_single_sentence_and_multi_sentence_lines(self):
        """Verifies multi-sentence lines capture the whole line and assign the correct citation."""
        note = (
            "Line 1 introductory remark.\n"
            "Evaluated for recurrent migraine headaches with aura. Patient reports frequent severe nausea.\n"
            "Start taking Sumatriptan 50mg tablets at onset of headache. Maximum 200mg daily.\n"
        )
        res = extract_after_visit_summary(note)

        assert len(res["diagnoses"]) == 1
        assert res["diagnoses"][0]["citation"] == "[Note Line 2]"
        assert "recurrent migraine" in res["diagnoses"][0]["text"].lower()

        assert len(res["medication_adjustments"]) == 1
        assert res["medication_adjustments"][0]["citation"] == "[Note Line 3]"
        assert "Sumatriptan 50mg" in res["medication_adjustments"][0]["text"]

    def test_exact_disclaimer_invariance(self):
        """Verifies the mandatory disclaimer is exactly preserved under all conditions."""
        cases = [
            "",
            "   \n  \n  ",
            "Single line note without clinical entities.",
            "Diagnosis: asthma\nPrescribed Albuterol 90mcg",
        ]
        expected_disclaimer = "Extracted from your notes, not formal medical advice."
        for text in cases:
            res = extract_after_visit_summary(text)
            assert res["disclaimer"] == expected_disclaimer


# ============================================================================
# Section 2: OTC vs Prescription Medication Distinction Stress
# ============================================================================


class TestOtcVsPrescriptionStress:
    """Stress tests verifying OTC advice exclusion vs prescription medication extraction."""

    def test_otc_explicit_exclusion_with_dosages_and_units(self):
        """Verifies lines containing 'over-the-counter' or 'otc' are strictly excluded from medication_adjustments."""
        otc_notes = (
            "Clinical notes on self-care:\n"                                           # Line 1
            "Advised to take over-the-counter Cetirizine 10mg daily for rhinitis.\n"    # Line 2: OTC
            "Patient should purchase OTC omeprazole 20mg capsules each morning.\n"     # Line 3: OTC
            "Stop taking generic over-the-counter decongestants.\n"                     # Line 4: OTC
            "Discontinue otc cold remedies and cough syrup.\n"                          # Line 5: OTC
            "Prescribed over-the-counter hydrocortisone 1% cream.\n"                   # Line 6: contains prescribed but also OTC
            "Take over-the-counter acetaminophen 500mg tablets as needed.\n"           # Line 7: OTC
        )
        res = extract_after_visit_summary(otc_notes)
        assert len(res["medication_adjustments"]) == 0

    def test_prescription_medications_captured_across_dosage_formats(self):
        """Verifies prescription medications across diverse dosage units and instructions."""
        rx_notes = (
            "Prescribed Atorvastatin 40mg daily at bedtime.\n"                         # Line 1: mg
            "Start taking Levothyroxine 75mcg every morning before food.\n"            # Line 2: mcg
            "Increased Gabapentin to 300mg capsules three times daily.\n"              # Line 3: capsules
            "Decreased Prednisone to 5mg tablets daily.\n"                             # Line 4: tablets
            "Titrated Insulin Glargine to 20 units nightly.\n"                         # Line 5: units
            "Dose: Amoxicillin 250mg per 5ml oral suspension.\n"                       # Line 6: ml
            "Discontinue Lisinopril 20mg daily due to cough.\n"                        # Line 7: discontinue with mg
            "Wean off Lorazepam 0.5mg tablets over 2 weeks.\n"                         # Line 8: wean off with mg
        )
        res = extract_after_visit_summary(rx_notes)
        meds = res["medication_adjustments"]
        assert len(meds) == 8
        citations = [m["citation"] for m in meds]
        assert citations == [f"[Note Line {i}]" for i in range(1, 9)]

    def test_mixed_note_prescription_captured_while_otc_excluded(self):
        """Verifies notes containing BOTH prescription changes and OTC advice properly separate them."""
        mixed_note = (
            "Encounter debrief:\n"                                                     # Line 1
            "Diagnosis: Type 2 diabetes mellitus without complications.\n"             # Line 2
            "Prescribed Metformin 500mg twice daily with meals.\n"                     # Line 3: RX -> captured
            "Recommend over-the-counter artificial tears 2 drops daily.\n"             # Line 4: OTC -> excluded
            "Discontinue otc herbal supplements.\n"                                    # Line 5: OTC -> excluded
            "Titrated Semaglutide to 0.5mg weekly subcutaneous injection.\n"           # Line 6: RX -> captured
            "Ordered blood work: Hemoglobin A1c and fasting lipids.\n"                 # Line 7
            "Follow-up in 3 months for glycemic control review.\n"                     # Line 8
        )
        res = extract_after_visit_summary(mixed_note)

        assert len(res["diagnoses"]) == 1
        assert "diabetes" in res["diagnoses"][0]["text"].lower()

        assert len(res["medication_adjustments"]) == 2
        med_texts = [m["text"] for m in res["medication_adjustments"]]
        assert any("Metformin 500mg" in t for t in med_texts)
        assert any("Semaglutide" in t for t in med_texts)
        assert not any("artificial tears" in t for t in med_texts)
        assert not any("herbal" in t for t in med_texts)

        assert len(res["ordered_tests"]) == 1
        assert len(res["follow_up_timeline"]) == 1


# ============================================================================
# Section 3: Note Categories & Type Validation Stress
# ============================================================================


class TestNoteCategoriesAndValidationStress:
    """Stress tests verifying 7 canonical note categories, edge cases, and legacy mappings."""

    def test_all_7_canonical_categories_exact_and_normalized(self):
        """Verifies each of the 7 canonical categories is accepted and normalized."""
        expected = ["visit", "symptom", "question", "after_visit", "school", "scratchpad", "general"]
        for cat in expected:
            assert validate_note_type(cat) == cat
            assert validate_note_type(cat.upper()) == cat
            assert validate_note_type(f"  {cat} \t") == cat
            assert cat in VALID_NOTE_TYPES

    def test_invalid_categories_rejected_with_value_error(self):
        """Verifies invalid, blank, non-string, and hallucinated categories fail-closed."""
        bad_categories = [
            "soap", "soap_note", "clinical", "summary", "progress",
            "discharge", "billing", "chart", "lab_result", "order",
            "", "   ", "\t\n", None, 123, False,
        ]
        for bad in bad_categories:
            with pytest.raises(ValueError):
                validate_note_type(bad, allow_legacy=False)

    def test_legacy_category_mapping_boundary(self):
        """Verifies allow_legacy maps only known legacy types, and rejects when allow_legacy=False."""
        assert validate_note_type("clinical_prep", allow_legacy=True) == "question"
        assert validate_note_type("visit_summary", allow_legacy=True) == "after_visit"

        with pytest.raises(ValueError):
            validate_note_type("clinical_prep", allow_legacy=False)
        with pytest.raises(ValueError):
            validate_note_type("visit_summary", allow_legacy=False)


# ============================================================================
# Section 4: Cross-Profile Appointment Security & Multi-Tenant RBAC Stress
# ============================================================================


@pytest.fixture
def m4_stress_env(monkeypatch):
    """Sets up an isolated database with 2 distinct profiles and 4 RBAC user tiers."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    run_async(init_db(engine))
    session_factory = get_session_factory(engine)
    auth_adapter = SqlAuthAdapter(session_factory=session_factory)

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr("carefold.tools.notes.get_session_factory", lambda: session_factory)
    set_auth_port(auth_adapter)

    async def _setup():
        # Alice: Profile A Owner (manage)
        alice = await auth_adapter.register_user(
            email="alice_stress@test.local",
            username="alice_stress",
            password="Password123!",
            full_name="Alice Owner",
            role="member",
            auth_provider="local",
        )
        alice_session = await auth_adapter.create_session(alice.id)

        # Charlie: Clinical viewer on Profile A (view_clinical)
        charlie = await auth_adapter.register_user(
            email="charlie_stress@test.local",
            username="charlie_stress",
            password="Password123!",
            full_name="Charlie Clinician",
            role="member",
            auth_provider="local",
        )
        charlie_session = await auth_adapter.create_session(charlie.id)

        # Dan: Paperwork viewer on Profile A (view_paperwork)
        dan = await auth_adapter.register_user(
            email="dan_stress@test.local",
            username="dan_stress",
            password="Password123!",
            full_name="Dan Paperwork",
            role="member",
            auth_provider="local",
        )
        dan_session = await auth_adapter.create_session(dan.id)

        # Eve: Unrelated user with zero permissions on Profile A
        eve = await auth_adapter.register_user(
            email="eve_stress@test.local",
            username="eve_stress",
            password="Password123!",
            full_name="Eve Stranger",
            role="member",
            auth_provider="local",
        )
        eve_session = await auth_adapter.create_session(eve.id)

        # Bob: Owner of Profile B
        bob = await auth_adapter.register_user(
            email="bob_stress@test.local",
            username="bob_stress",
            password="Password123!",
            full_name="Bob Other",
            role="member",
            auth_provider="local",
        )
        bob_session = await auth_adapter.create_session(bob.id)

        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            # Profile A (Alice)
            profile_a = Profile(
                id=str(uuid.uuid4()),
                user_id=alice.id,
                name="Alice Primary Profile",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
            session.add(profile_a)

            # Appointment A on Profile A
            appt_a = Appointment(
                id=str(uuid.uuid4()),
                profile_id=profile_a.id,
                title="Profile A Cardiology Visit",
                start_time=now + timedelta(days=3),
                end_time=now + timedelta(days=3, hours=1),
                specialty="Cardiology",
                status="confirmed",
                created_at=now,
                updated_at=now,
            )
            session.add(appt_a)

            # Profile B (Bob)
            profile_b = Profile(
                id=str(uuid.uuid4()),
                user_id=bob.id,
                name="Bob Distinct Profile",
                relationship="self",
                role="self",
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
            session.add(profile_b)

            # Appointment B on Profile B
            appt_b = Appointment(
                id=str(uuid.uuid4()),
                profile_id=profile_b.id,
                title="Profile B Dermatology Visit",
                start_time=now + timedelta(days=5),
                end_time=now + timedelta(days=5, hours=1),
                specialty="Dermatology",
                status="confirmed",
                created_at=now,
                updated_at=now,
            )
            session.add(appt_b)

            # Grant permissions on Profile A
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=profile_a.id,
                user_id=charlie.id,
                access_level="view_clinical",
                granted_by=alice.id,
                granted_at=now,
            ))
            session.add(ProfileAccess(
                id=str(uuid.uuid4()),
                profile_id=profile_a.id,
                user_id=dan.id,
                access_level="view_paperwork",
                granted_by=alice.id,
                granted_at=now,
            ))

            await session.commit()

            return {
                "session_factory": session_factory,
                "profile_a_id": profile_a.id,
                "profile_b_id": profile_b.id,
                "appointment_a_id": appt_a.id,
                "appointment_b_id": appt_b.id,
                "alice_token": alice_session.token,
                "charlie_token": charlie_session.token,
                "dan_token": dan_session.token,
                "eve_token": eve_session.token,
                "bob_token": bob_session.token,
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


class TestCrossProfileAppointmentSecurityStress:
    """Stress tests verifying appointment FK cross-profile boundary enforcement."""

    def test_create_note_rejects_foreign_profile_appointment(self, m4_stress_env):
        """Verifies attempting to link an appointment belonging to Profile B from Profile A fails with HTTP 400."""
        client = TestClient(app)
        pid_a = m4_stress_env["profile_a_id"]
        appt_b = m4_stress_env["appointment_b_id"]
        headers = {"Authorization": f"Bearer {m4_stress_env['alice_token']}"}

        payload = {
            "title": "Cross-Profile Note Attack",
            "content": "Attempting to link Bob's appointment to Alice's profile.",
            "type": "visit",
            "linked_appointment_id": appt_b,
        }
        res = client.post(f"/api/profiles/{pid_a}/notes", json=payload, headers=headers)
        assert res.status_code == 400
        assert "Security violation" in res.json()["detail"]
        assert "Linked appointment does not exist or does not belong to profile" in res.json()["detail"]

    def test_patch_note_rejects_foreign_profile_appointment(self, m4_stress_env):
        """Verifies patching an existing note with an appointment from another profile fails with HTTP 400."""
        client = TestClient(app)
        pid_a = m4_stress_env["profile_a_id"]
        appt_a = m4_stress_env["appointment_a_id"]
        appt_b = m4_stress_env["appointment_b_id"]
        headers = {"Authorization": f"Bearer {m4_stress_env['alice_token']}"}

        # Create note with valid appointment
        create_res = client.post(
            f"/api/profiles/{pid_a}/notes",
            json={"title": "Legit Note", "content": "Clean note", "type": "visit", "linked_appointment_id": appt_a},
            headers=headers,
        )
        assert create_res.status_code == 201
        note_id = create_res.json()["id"]

        # Attempt to patch with Bob's appointment
        patch_res = client.patch(
            f"/api/profiles/{pid_a}/notes/{note_id}",
            json={"linked_appointment_id": appt_b},
            headers=headers,
        )
        assert patch_res.status_code == 400
        assert "Security violation" in patch_res.json()["detail"]

    def test_tool_execute_create_typed_note_rejects_foreign_appointment(self, m4_stress_env):
        """Verifies the closed execute_create_typed_note tool also enforces cross-profile appointment security."""
        pid_a = m4_stress_env["profile_a_id"]
        appt_b = m4_stress_env["appointment_b_id"]

        ctx = ToolContext(profile_id=pid_a, user_id="alice-user")
        args = {
            "title": "Tool Attack Note",
            "content": "Trying to link Bob's appointment via tool",
            "type": "visit",
            "linked_appointment_id": appt_b,
        }
        result = run_async(execute_create_typed_note(args, ctx))
        assert result.success is False
        assert "Security violation" in result.error
        assert "Linked appointment does not exist or does not belong to profile" in result.error


class TestRbacPermissionsStress:
    """Stress tests verifying RBAC permission tiers across all notes endpoints:
    manage vs view_clinical vs view_paperwork vs unauthenticated.
    """

    def test_unauthenticated_requests_return_401(self, m4_stress_env):
        """Verifies unauthenticated calls across endpoints return HTTP 401 Unauthorized."""
        client = TestClient(app)
        pid = m4_stress_env["profile_a_id"]

        # No auth header
        res_list = client.get(f"/api/profiles/{pid}/notes")
        assert res_list.status_code == 401

        res_post = client.post(f"/api/profiles/{pid}/notes", json={"title": "T", "content": "C", "type": "visit"})
        assert res_post.status_code == 401

        res_adhoc = client.post(f"/api/profiles/{pid}/notes/extract", json={"content": "C"})
        assert res_adhoc.status_code == 401

    def test_paperwork_view_permissions_rejected_with_403(self, m4_stress_env):
        """Verifies view_paperwork user cannot read, list, create, or extract clinical notes (HTTP 403)."""
        client = TestClient(app)
        pid = m4_stress_env["profile_a_id"]
        dan_headers = {"Authorization": f"Bearer {m4_stress_env['dan_token']}"}

        # 1. List notes
        res_list = client.get(f"/api/profiles/{pid}/notes", headers=dan_headers)
        assert res_list.status_code == 403
        assert "clinical view permissions required" in res_list.json()["detail"].lower()

        # 2. Create note
        res_post = client.post(
            f"/api/profiles/{pid}/notes",
            json={"title": "Paperwork note", "content": "Content", "type": "general"},
            headers=dan_headers,
        )
        assert res_post.status_code == 403

        # 3. Adhoc extract
        res_extract = client.post(
            f"/api/profiles/{pid}/notes/extract",
            json={"content": "Content"},
            headers=dan_headers,
        )
        assert res_extract.status_code == 403

    def test_view_clinical_can_read_but_cannot_modify_or_extract(self, m4_stress_env):
        """Verifies view_clinical user can list and read detail, but cannot create, patch, delete, or extract."""
        client = TestClient(app)
        pid = m4_stress_env["profile_a_id"]
        alice_headers = {"Authorization": f"Bearer {m4_stress_env['alice_token']}"}
        charlie_headers = {"Authorization": f"Bearer {m4_stress_env['charlie_token']}"}

        # Setup: Alice creates a note
        create_res = client.post(
            f"/api/profiles/{pid}/notes",
            json={"title": "Cardiology Note", "content": "Diagnosis: CAD", "type": "visit"},
            headers=alice_headers,
        )
        assert create_res.status_code == 201
        note_id = create_res.json()["id"]

        # Charlie CAN list notes (200)
        list_res = client.get(f"/api/profiles/{pid}/notes", headers=charlie_headers)
        assert list_res.status_code == 200
        assert list_res.json()["total"] >= 1

        # Charlie CAN get note detail (200)
        detail_res = client.get(f"/api/profiles/{pid}/notes/{note_id}", headers=charlie_headers)
        assert detail_res.status_code == 200
        assert detail_res.json()["title"] == "Cardiology Note"

        # Charlie CANNOT create note (403)
        post_res = client.post(
            f"/api/profiles/{pid}/notes",
            json={"title": "Charlie Note", "content": "Content", "type": "visit"},
            headers=charlie_headers,
        )
        assert post_res.status_code == 403
        assert "management permissions required" in post_res.json()["detail"].lower()

        # Charlie CANNOT patch note (403)
        patch_res = client.patch(
            f"/api/profiles/{pid}/notes/{note_id}",
            json={"title": "Hacked Title"},
            headers=charlie_headers,
        )
        assert patch_res.status_code == 403

        # Charlie CANNOT delete note (403)
        del_res = client.delete(f"/api/profiles/{pid}/notes/{note_id}", headers=charlie_headers)
        assert del_res.status_code == 403

        # Charlie CANNOT extract note (403 - requires manage)
        extract_res = client.post(f"/api/profiles/{pid}/notes/{note_id}/extract", headers=charlie_headers)
        assert extract_res.status_code == 403

    def test_unrelated_stranger_rejected_with_403(self, m4_stress_env):
        """Verifies user with no permissions on the profile receives HTTP 403 across all actions."""
        client = TestClient(app)
        pid = m4_stress_env["profile_a_id"]
        eve_headers = {"Authorization": f"Bearer {m4_stress_env['eve_token']}"}

        res = client.get(f"/api/profiles/{pid}/notes", headers=eve_headers)
        assert res.status_code == 403
        assert "access denied" in res.json()["detail"].lower()

    def test_api_notes_legacy_endpoint_rejects_invalid_type_with_400(self, m4_stress_env):
        """Verifies POST /api/notes endpoint explicitly returns HTTP 400 when given an invalid note type."""
        client = TestClient(app)
        pid = m4_stress_env["profile_a_id"]
        alice_headers = {"Authorization": f"Bearer {m4_stress_env['alice_token']}"}

        bad_payload = {
            "title": "Bad Type Note",
            "content": "Some text",
            "profile_id": pid,
            "type": "invalid_soap_note",
        }
        res = client.post("/api/notes", json=bad_payload, headers=alice_headers)
        assert res.status_code == 400
        assert "Invalid note type" in res.json()["detail"]
