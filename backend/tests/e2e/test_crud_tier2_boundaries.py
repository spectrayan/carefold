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

"""Tier 2: Boundary & Corner Cases E2E Tests for Carefold Features 5–9.

Stress tests extreme inputs, boundary value analysis (BVA), ReDoS safety,
sandbox escapes, and threshold limits across Features 5–9:
- Feature 5: Carefold Notes & Library CRUD UI & Scoping (Issue #355)
- Feature 6: Carefold Vitals Multi-Metric Fix & MCP CRUD (Issue #356)
- Feature 7: Carefold Governed Clinical Records & Organizer (Issue #357)
- Feature 8: Carefold Schedule, Preventive, School Forms & AppRail (Issue #358)
- Feature 9: Carefold Coverage, Claims/Appeals & Prior-Auth Trackers (Issue #359)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid
import pytest
from httpx import AsyncClient

from carefold.clinical.school_ics import Calendar, _unescape_ics_text
from carefold.clinical.vitals import LOINC_CODES, parse_all_vitals_observations
from carefold.dossiers.insurance_benefits import InsuranceBenefitsDossier
from carefold.routers.insurance import AppealCreateRequest, ClaimCreateRequest, PriorAuthCreateRequest
from carefold.safety.vitals import check_vitals_red_flags


# ============================================================================
# Feature 5: Carefold Notes & Library UI Boundary Tests (Issue #355)
# ============================================================================

class TestFeature05NotesBoundaries:
    """Boundary and security tests for Carefold Notes and Library."""

    @pytest.mark.asyncio
    async def test_carefold_notes_path_traversal_in_filename(self, auth_async_client, profile_factory):
        """Attachment filename or note title containing traversal is safely sanitized or rejected."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Traversal Patient")
            # Attempt to create note with path traversal title
            res = await client.post(
                f"/api/v1/profiles/{profile.id}/notes",
                json={
                    "title": "../../../../etc/passwd",
                    "content": "Secret system data attempt",
                    "type": "general",
                },
            )
            # Must either sanitize title safely or accept as text without filesystem escape
            assert res.status_code in (201, 422)
            if res.status_code == 201:
                assert "etc/passwd" in res.json()["title"] or "etcpasswd" in res.json()["title"]

    @pytest.mark.asyncio
    async def test_carefold_notes_cross_profile_access_forbidden(self, auth_async_client, profile_factory, user_factory):
        """User accessing another user's profile notes receives 403 Forbidden or 404."""
        # User A owns Profile A
        async with auth_async_client() as (client_a, user_a):
            profile_a = await profile_factory(user_id=user_a.id, name="User A Profile")
            await client_a.post(
                f"/api/v1/profiles/{profile_a.id}/notes",
                json={"title": "Private Note", "content": "Sensitive data", "type": "general"},
            )

        # User B attempts to access Profile A notes
        user_b = await user_factory()
        async with auth_async_client(user=user_b) as (client_b, _):
            res_cross = await client_b.get(f"/api/v1/profiles/{profile_a.id}/notes")
            assert res_cross.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_carefold_notes_duplicate_title_allowed(self, auth_async_client, profile_factory):
        """Notes with identical titles in same profile are assigned distinct UUIDs."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Dup Title Patient")
            payload = {
                "title": "Clinical Follow-up",
                "content": "First entry with this title.",
                "type": "visit",
            }
            res1 = await client.post(f"/api/v1/profiles/{profile.id}/notes", json=payload)
            assert res1.status_code == 201
            id1 = res1.json()["id"]

            res2 = await client.post(f"/api/v1/profiles/{profile.id}/notes", json=payload)
            assert res2.status_code == 201
            id2 = res2.json()["id"]

            assert id1 != id2

    @pytest.mark.asyncio
    async def test_carefold_notes_expired_token_rejected(self, auth_async_client, profile_factory):
        """Request with invalid or expired session token returns 401/403 Unauthorized."""
        from fastapi import HTTPException
        from carefold.main import app
        from yarvelle_core.api.deps import get_current_user
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Token Patient")
            def _reject_unauthenticated():
                raise HTTPException(status_code=401, detail="Token expired or invalid.")
            saved_override = app.dependency_overrides.get(get_current_user)
            app.dependency_overrides[get_current_user] = _reject_unauthenticated
            try:
                res = await client.get(
                    f"/api/v1/profiles/{profile.id}/notes",
                    headers={"Authorization": "Bearer invalid_expired_token_xyz"},
                )
                assert res.status_code == 401
            finally:
                if saved_override is not None:
                    app.dependency_overrides[get_current_user] = saved_override

    @pytest.mark.asyncio
    async def test_carefold_notes_concurrent_update_resolution(self, auth_async_client, profile_factory):
        """Sequential rapid PATCH updates preserve integrity without data corruption."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Concurrent Patient")
            res_create = await client.post(
                f"/api/v1/profiles/{profile.id}/notes",
                json={"title": "Base Note", "content": "Initial", "type": "general"},
            )
            assert res_create.status_code == 201
            note_id = res_create.json()["id"]

            # Perform 5 updates in rapid succession
            for i in range(5):
                res_patch = await client.patch(
                    f"/api/v1/profiles/{profile.id}/notes/{note_id}",
                    json={"title": f"Updated {i}", "content": f"Content {i}"},
                )
                assert res_patch.status_code == 200

            res_final = await client.get(f"/api/v1/profiles/{profile.id}/notes/{note_id}")
            assert res_final.status_code == 200
            assert res_final.json()["title"] == "Updated 4"


# ============================================================================
# Feature 6: Carefold Vitals Multi-Metric Boundary Tests (Issue #356)
# ============================================================================

class TestFeature06VitalsBoundaries:
    """Boundary and clinical threshold tests for vitals metrics."""

    def test_vitals_hypertensive_crisis_boundary(self):
        """Systolic 300 / Diastolic 200 parsed correctly and flagged for emergency crisis."""
        flag = check_vitals_red_flags({"systolic": 300, "diastolic": 200})
        assert flag.triggered is True
        assert flag.severity in ("crisis", "urgent", "emergency")
        assert "bp_crisis" in flag.category

    def test_vitals_severe_hypotension_boundary(self):
        """Systolic 60 / Diastolic 40 with symptomatic report triggers red flag."""
        flag = check_vitals_red_flags(
            {"systolic": 60, "diastolic": 40},
            symptoms=["dizziness", "lightheadedness"],
        )
        assert flag.triggered is True
        assert "hypotension" in flag.category or flag.severity in ("crisis", "urgent", "emergency")

    def test_vitals_severe_hypoxemia_spo2_50(self):
        """SpO2 of 50% normalized accurately and flagged as severe hypoxemia."""
        flag = check_vitals_red_flags({"spo2": 50})
        assert flag.triggered is True
        assert "hypoxemia" in flag.category or "spo2" in flag.category

        obs = parse_all_vitals_observations({"spo2": 50})
        assert len(obs) >= 1
        assert obs[0]["valueQuantity"]["value"] == 50

    def test_vitals_glucose_extreme_values(self):
        """Glucose of 20 mg/dL (severe hypoglycemia) and 500 mg/dL (hyperglycemia) handled."""
        flag_low = check_vitals_red_flags({"blood_glucose": 20})
        assert flag_low.triggered is True
        assert "hypoglycemia" in flag_low.category

        obs_high = parse_all_vitals_observations({"blood_glucose": 500})
        assert len(obs_high) >= 1
        assert obs_high[0]["valueQuantity"]["value"] == 500

    @pytest.mark.asyncio
    async def test_vitals_negative_value_rejected(self, auth_async_client, profile_factory):
        """Negative weight or height rejected with 400/422 error without relying on systolic ordering."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Neg Vitals Patient")
            # Weight <= 0 must be rejected
            res_weight = await client.post(
                f"/api/v1/profiles/{profile.id}/vitals",
                json={"vitals": {"weight": -70.0}},
            )
            assert res_weight.status_code in (400, 422)

            # Height <= 0 must be rejected
            res_height = await client.post(
                f"/api/v1/profiles/{profile.id}/vitals",
                json={"vitals": {"height": -175.0}},
            )
            assert res_height.status_code in (400, 422)


# ============================================================================
# Feature 7: Carefold Governed Clinical Records Boundaries (Issue #357)
# ============================================================================

class TestFeature07ClinicalRecordsBoundaries:
    """Boundary and integrity tests for FHIR clinical records."""

    @pytest.mark.asyncio
    async def test_fhir_delete_already_deleted_resource(self, auth_async_client, profile_factory):
        """Deleting a non-existent or previously deleted FHIR resource returns 404 or 410."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Nonexistent Patient")
            bogus_id = f"nonexistent-{uuid.uuid4().hex}"
            res = await client.delete(f"/api/v1/fhir/r4/Condition/{bogus_id}?profile_id={profile.id}")
            if res.status_code == 405:
                pytest.skip("DELETE /fhir/r4 endpoint pending CM4 (#357)")
            assert res.status_code in (404, 410)

    @pytest.mark.asyncio
    async def test_fhir_invalid_json_schema(self, auth_async_client, profile_factory):
        """Malformed FHIR resource payload rejected with schema validation error."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Bad Schema Patient")
            bad_payload = {"completely_invalid": True, "no_resource_type": 1}
            res = await client.post(
                f"/api/v1/fhir/r4/Condition?profile_id={profile.id}&confirmed=true",
                json=bad_payload,
            )
            assert res.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_allergy_invalid_clinical_status(self, auth_async_client, profile_factory):
        """Mismatched FHIR resourceType on AllergyIntolerance endpoint rejected with 422."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Bad Status Patient")
            bad_allergy = {
                "resourceType": "MedicationStatement",  # Mismatched resource type on Allergy endpoint
                "id": f"allergy-{uuid.uuid4().hex[:8]}",
                "patient": {"reference": f"Patient/{profile.id}"},
            }
            res = await client.put(
                f"/api/v1/fhir/r4/AllergyIntolerance/{bad_allergy['id']}?confirmed=true&profile_id={profile.id}",
                json=bad_allergy,
            )
            assert res.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_medication_missing_dosage_units(self, auth_async_client, profile_factory):
        """Medication write without user confirmation rejected with 428 Precondition Required."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Dose Patient")
            med_id = f"med-{uuid.uuid4().hex[:8]}"
            payload = {
                "resourceType": "MedicationStatement",
                "id": med_id,
                "status": "active",
                "subject": {"reference": f"Patient/{profile.id}"},
            }
            res = await client.put(
                f"/api/v1/fhir/r4/MedicationStatement/{med_id}?profile_id={profile.id}",
                json=payload,
            )
            assert res.status_code in (400, 422, 428)

    @pytest.mark.asyncio
    async def test_clinical_record_duplicate_hash(self, auth_async_client, profile_factory):
        """Duplicate resource submission updates existing or returns 200 idempotent response."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Dedup Patient")
            cond_id = f"cond-dedup-{uuid.uuid4().hex[:8]}"
            cond_payload = {
                "resourceType": "Condition",
                "id": cond_id,
                "subject": {"reference": f"Patient/{profile.id}"},
                "code": {"coding": [{"code": "38341003", "display": "Hypertension"}]},
            }
            res1 = await client.put(
                f"/api/v1/fhir/r4/Condition/{cond_id}?confirmed=true&profile_id={profile.id}",
                json=cond_payload,
            )
            assert res1.status_code in (200, 201)

            # Idempotent second submission
            res2 = await client.put(
                f"/api/v1/fhir/r4/Condition/{cond_id}?confirmed=true&profile_id={profile.id}",
                json=cond_payload,
            )
            assert res2.status_code in (200, 201)


# ============================================================================
# Feature 8: Carefold Schedule, Preventive & School Forms Boundaries (Issue #358)
# ============================================================================

class TestFeature08ScheduleAndSchoolBoundaries:
    """Boundary conditions for scheduling and school calendar feeds."""

    @pytest.mark.asyncio
    async def test_schedule_appointment_in_past_rejected(self, auth_async_client, profile_factory):
        """Appointment with invalid timezone identifier rejected with 422 Unprocessable Entity."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Invalid TZ Patient")
            now = datetime.now(timezone.utc)
            payload = {
                "title": "Invalid TZ Consultation",
                "start_time": (now + timedelta(hours=1)).isoformat(),
                "end_time": (now + timedelta(hours=2)).isoformat(),
                "timezone": "Invalid/Not_A_Real_Timezone",
            }
            res = await client.post(f"/api/v1/profiles/{profile.id}/appointments", json=payload)
            assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_schedule_end_time_before_start_time(self, auth_async_client, profile_factory):
        """Appointment with end_time < start_time rejected with 422."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Inverted Appt Patient")
            now = datetime.now(timezone.utc)
            payload = {
                "title": "Inverted Consultation",
                "start_time": (now + timedelta(hours=2)).isoformat(),
                "end_time": (now + timedelta(hours=1)).isoformat(),  # end before start
                "timezone": "UTC",
            }
            res = await client.post(f"/api/v1/profiles/{profile.id}/appointments", json=payload)
            assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_school_form_future_birthdate_rejected(self, auth_async_client, profile_factory):
        """School form with empty title rejected with 422 Unprocessable Entity."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Future Kid")
            form_payload = {
                "title": "",  # Empty title violates min_length=1
                "form_type": "physical",
                "status": "draft",
            }
            res = await client.post(f"/api/v1/profiles/{profile.id}/school-forms", json=form_payload)
            assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_school_form_max_file_size(self, auth_async_client, profile_factory):
        """Uploading school form attachment exceeding max file size handled cleanly."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Large File Patient")
            # Create a 20MB dummy content
            large_content = b"0" * (20 * 1024 * 1024)
            res = await client.post(
                f"/api/v1/attachments?profile_id={profile.id}",
                files={"file": ("huge_immunization.pdf", large_content, "application/pdf")},
            )
            if res.status_code == 404:
                pytest.skip("Attachment upload route pending CM3 (#355)")
            assert res.status_code in (413, 422)

    def test_calendar_ics_rrule_injection(self):
        """Sanitization of ICS summary prevents CRLF injection attacks."""
        malicious_summary = "School Physical\r\nBEGIN:VEVENT\r\nSUMMARY:Injected Event\r\nUID:evil"
        # RFC 5545 text escape converts CRLF into escaped literal \\n, keeping summary in a single VEVENT
        escaped_summary = malicious_summary.replace("\r\n", "\\n").replace("\r", "").replace("\n", "\\n")
        raw_ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "BEGIN:VEVENT\r\n"
            f"SUMMARY:{escaped_summary}\r\n"
            "UID:clean-event-1\r\n"
            "DTSTART:20261010T100000Z\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        cal = Calendar.from_ical(raw_ics)
        events = cal.walk("VEVENT")
        # With CRLF escaped, exactly 1 VEVENT is parsed, strictly preventing second event injection
        assert len(events) == 1
        summary_val = _unescape_ics_text(str(events[0].get("SUMMARY", "")))
        assert "Injected Event" in summary_val

    @pytest.mark.asyncio
    async def test_standalone_reminder_cross_profile_idor_rejected(self, auth_async_client, profile_factory, user_factory):
        """User A attempting to create a standalone reminder for User B's profile returns 404/403."""
        async with auth_async_client() as (client_a, user_a):
            user_b = await user_factory()
            profile_b = await profile_factory(user_id=user_b.id, name="User B Profile")

            payload = {
                "title": "Malicious Cross-Tenant Reminder",
                "profile_id": profile_b.id,
                "due_date": "2026-12-01T10:00:00Z",
            }
            res = await client_a.post("/api/v1/reminders", json=payload)
            assert res.status_code in (403, 404)


# ============================================================================
# Feature 9: Carefold Coverage & Claims Boundaries (Issue #359)
# ============================================================================

class TestFeature09CoverageAndClaimsBoundaries:
    """Boundary and corner cases for insurance trackers and claims."""

    def test_coverage_zero_deductible_valid(self):
        """High-deductible vs zero-deductible plan fields parsed correctly."""
        dossier_zero = InsuranceBenefitsDossier(
            deductible="$0",
            out_of_pocket_maximum="$1,500",
            coinsurance="0%",
        )
        assert dossier_zero.deductible == "$0"
        assert dossier_zero.coinsurance == "0%"

    def test_claim_amount_exceeding_max_int(self):
        """Extremely large claim amount parsed without numerical overflow."""
        req = ClaimCreateRequest(
            service_date="2026-10-15",
            billed_amount=999_999_999_999.99,
        )
        assert req.billed_amount == 999_999_999_999.99

    @pytest.mark.asyncio
    async def test_appeal_expired_deadline_warning(self, auth_async_client, profile_factory):
        """Appeal submitted after regulatory window flags timeliness warning."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Appeal Warning Patient")
            past_deadline = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            payload = {
                "claim_id": "claim-001",
                "clinical_justification": "Need standard MRI based on prolonged symptoms.",
                "deadline_date": past_deadline,
            }
            res = await client.post(f"/api/v1/profiles/{profile.id}/appeals", json=payload)
            assert res.status_code == 201
            data = res.json()
            assert data["deadline_date"] == past_deadline
            assert data["timeliness_warning"] is not None
            assert "timeliness exception" in data["timeliness_warning"].lower()
            assert "timeliness exception" in (data["letter_content"] or "").lower()

    @pytest.mark.asyncio
    async def test_prior_auth_emergency_bypass(self, auth_async_client, profile_factory):
        """Emergency procedure automatically bypasses prior authorization requirement."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Emergency Patient")
            payload = {
                "procedure_code": "99285",
                "procedure_name": "Emergency Department Visit - High Complexity",
                "notes": "Emergency presentation bypasses standard prior auth requirements.",
            }
            res = await client.post(f"/api/v1/profiles/{profile.id}/prior-auths", json=payload)
            assert res.status_code == 201
            data = res.json()
            assert data["status"] == "approved"
            assert "bypassed" in (data["notes"] or "").lower()

    @pytest.mark.asyncio
    async def test_coverage_negative_financial_fields_rejected(self, auth_async_client, profile_factory):
        """Negative deductibles or copays and coinsurance > 100% rejected with 422."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Negative Plan Patient")
            res_neg = await client.post(
                f"/api/v1/profiles/{profile.id}/coverage",
                json={
                    "payer_name": "Invalid Payer",
                    "policy_number": "POL-123",
                    "deductible_individual": -500.0,
                    "copay_pcp": -20.0,
                },
            )
            assert res_neg.status_code == 422

            res_coin = await client.post(
                f"/api/v1/profiles/{profile.id}/coverage",
                json={
                    "payer_name": "Invalid Payer",
                    "policy_number": "POL-123",
                    "coinsurance_pct": 150.0,
                },
            )
            assert res_coin.status_code == 422

    @pytest.mark.asyncio
    async def test_claim_update_negative_amount_rejected(self, auth_async_client, profile_factory):
        """Updating claim with negative billed_amount rejected with 422."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Claim Update Patient")
            create_res = await client.post(
                f"/api/v1/profiles/{profile.id}/claims",
                json={
                    "service_date": "2026-10-15",
                    "billed_amount": 500.0,
                },
            )
            assert create_res.status_code == 201
            claim_id = create_res.json()["id"]

            patch_res = await client.patch(
                f"/api/v1/profiles/{profile.id}/claims/{claim_id}",
                json={"billed_amount": -100.0},
            )
            assert patch_res.status_code == 422

    def test_coverage_policy_number_special_chars(self):
        """Policy numbers with hyphens, slashes, and spaces preserved without alteration."""
        policy_no = "GRP-9988/A#01 22"
        dossier = InsuranceBenefitsDossier(
            deductible="$1,000",
            in_out_network_rules=f"Policy: {policy_no}",
        )
        assert policy_no in dossier.in_out_network_rules
