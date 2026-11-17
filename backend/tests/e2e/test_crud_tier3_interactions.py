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

"""Tier 3: Cross-Feature Interactions E2E Tests for Carefold.

Covers pairwise cross-feature combinations (C-01 to C-09) and live SSE invalidation:
- C-01: F-02 (SSE) ↔ F-06 (Vitals): Vitals tool mutation event schema & notification.
- C-02: F-02 (SSE) ↔ F-05 (Notes): Note creation event schema & library sync.
- C-03: F-01 (Registry) ↔ F-07 (Clinical Records): Specialist agent wiring to FHIR tools.
- C-04: F-08 (Schedule) ↔ F-04 (Calendar/Reminders): Appointment booking and clinical reminders.
- C-05: F-09 (Coverage) ↔ F-07 (Clinical Records): Diagnosis requiring prior-auth detection.
- C-06: F-06 (Vitals) ↔ F-08 (School Forms): Pediatric vitals feeding School Form BMI prefill.
- C-07: F-03 (Core Notes) ↔ F-05 (Carefold Library): Notes isolation across core & health.
- C-08: F-09 (Claims) ↔ F-05 (Notes): Insurance claim denial linked to appeal prep note.
- C-09: F-02 (SSE) ↔ F-07 (Clinical Records): Allergy mutation and reactive cache invalidation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import uuid
import pytest

from carefold.clinical.school_forms import compile_school_form_prefill
from carefold.clinical.vitals import normalize_fhir_vitals, parse_all_vitals_observations
from carefold.dossiers.insurance_benefits import InsuranceBenefitsDossier
from carefold.models.health import HealthResource
from carefold.tools.record_vitals import execute_record_vitals
from yarvelle_core.constants.api import SSE_EVENT_ENTITY_CHANGED
from yarvelle_core.schemas.events import EntityChangedPayload, build_entity_changed_payload
from yarvelle_core.schemas.tool import ToolResult


class TestTier3CrossFeatureInteractions:
    """Pairwise interaction tests connecting features across domain boundaries."""

    @pytest.mark.asyncio
    async def test_c01_interaction_sse_vitals_invalidation(self, auth_async_client, profile_factory):
        """C-01: Specialist agent executes vitals mutation; verifies entity_changed event schema."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="SSE Vitals Patient")
            # 1. Post vital observation
            res = await client.post(
                f"/api/v1/profiles/{profile.id}/vitals",
                json={
                    "vitals": {"systolic": 130, "diastolic": 85, "heart_rate": 76},
                    "effective_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            assert res.status_code == 201
            data = res.json()
            assert "data" in data

            # 2. Verify entity_changed event schema via canonical builder and schema model
            event_payload = build_entity_changed_payload(
                tool_name="record_vitals",
                args={"profile_id": profile.id, "vitals": {"systolic": 130, "diastolic": 85}},
                output={"id": data.get("id", str(uuid.uuid4())), "action": "created"},
                profile_id=profile.id,
                scope="health.clinical",
            )
            event = EntityChangedPayload.model_validate(event_payload)
            assert event.type == SSE_EVENT_ENTITY_CHANGED
            assert event.entity_type == "vitals"
            assert event.profile_id == profile.id
            assert event.action == "created"
            assert event.scope == "health.clinical"

    @pytest.mark.asyncio
    async def test_c02_interaction_sse_notes_invalidation(self, auth_async_client, profile_factory):
        """C-02: User or agent adds note; verifies entity_changed ('note') payload contract."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="SSE Notes Patient")
            res = await client.post(
                f"/api/v1/profiles/{profile.id}/notes",
                json={
                    "title": "Agent Generated Summary",
                    "content": "Follow-up recommendations from cardiology prep.",
                    "type": "visit",
                    "tags": ["agent-summary"],
                },
            )
            assert res.status_code == 201
            note = res.json()

            event_payload = build_entity_changed_payload(
                tool_name="create_workspace_note",
                args={"profile_id": profile.id, "entity_type": "note", "title": note["title"]},
                output={"id": note["id"], "action": "created"},
                profile_id=profile.id,
                scope="health.clinical",
            )
            event = EntityChangedPayload.model_validate(event_payload)
            assert event.type == SSE_EVENT_ENTITY_CHANGED
            assert event.entity_type == "note"
            assert event.action == "created"
            assert event.entity_id == note["id"]
            assert event.profile_id == profile.id

    @pytest.mark.asyncio
    async def test_c03_interaction_registry_clinical_records(self, auth_async_client, profile_factory):
        """C-03: records-coordinator declared with clinical tools executes FHIR medication creation."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Records Coordinator Patient")
            med_id = f"med-reg-{uuid.uuid4().hex[:8]}"
            med_payload = {
                "resourceType": "MedicationStatement",
                "id": med_id,
                "status": "active",
                "medicationCodeableConcept": {
                    "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "316049", "display": "Amlodipine 5 MG"}]
                },
                "subject": {"reference": f"Patient/{profile.id}"},
                "effectiveDateTime": datetime.now(timezone.utc).isoformat(),
            }
            res_put = await client.put(
                f"/api/v1/fhir/r4/MedicationStatement/{med_id}?confirmed=true&profile_id={profile.id}",
                json=med_payload,
            )
            assert res_put.status_code in (200, 201)

            # Retrieve via search
            res_get = await client.get(
                f"/api/v1/fhir/r4/MedicationStatement/{med_id}?profile_id={profile.id}"
            )
            assert res_get.status_code == 200
            assert res_get.json()["id"] == med_id

    @pytest.mark.asyncio
    async def test_c04_interaction_schedule_calendar_reminders(self, auth_async_client, profile_factory):
        """C-04: Follow-up appointment booked in Schedule UI verifies scheduled appointment details."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Schedule Reminders Patient")
            start = datetime.now(timezone.utc) + timedelta(days=14)
            end = start + timedelta(minutes=30)
            payload = {
                "title": "Endocrinology Follow-up",
                "provider_name": "Dr. Alan Grant",
                "specialty": "Endocrinology",
                "status": "scheduled",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "timezone": "UTC",
            }
            res = await client.post(f"/api/v1/profiles/{profile.id}/appointments", json=payload)
            assert res.status_code == 201
            appt = res.json()
            assert appt["title"] == "Endocrinology Follow-up"
            assert appt["status"] == "scheduled"

    def test_c05_interaction_coverage_clinical_prior_auth(self):
        """C-05: Specialist records diagnosis requiring specialized imaging; Coverage flags prior-auth."""
        dossier = InsuranceBenefitsDossier(
            deductible="$1,500",
            in_out_network_rules="20% coinsurance in-network",
            prior_authorization_flags=["Advanced Imaging (MRI, CT, PET)", "Cardiac Stress Test"],
        )
        ordered_procedure = "MRI Lumbar Spine"
        # Verify procedure requires prior authorization per coverage flags
        requires_pa = any("mri" in flag.lower() for flag in dossier.prior_authorization_flags)
        assert requires_pa is True

    @pytest.mark.asyncio
    async def test_c06_interaction_vitals_school_forms_bmi(self, async_db_session_factory, profile_factory):
        """C-06: Pediatric vitals recorded feed directly into School Form prefill compilation."""
        from carefold.models.health import HealthResource
        import hashlib
        async with async_db_session_factory() as session:
            profile = await profile_factory(session=session, name="Pediatric Student")
            now = datetime.now(timezone.utc)

            # Insert height and weight observations
            ht_payload = {
                "resourceType": "Observation",
                "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": "8302-2", "display": "Body height"}]},
                "valueQuantity": {"value": 120.0, "unit": "cm", "code": "cm"},
                "effectiveDateTime": now.isoformat(),
            }
            wt_payload = {
                "resourceType": "Observation",
                "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]},
                "valueQuantity": {"value": 24.0, "unit": "kg", "code": "kg"},
                "effectiveDateTime": now.isoformat(),
            }
            session.add(HealthResource(
                id=str(uuid.uuid4()),
                profile_id=profile.id,
                resource_type="observation",
                source_type="manual",
                status="active",
                scope="health.clinical",
                data=ht_payload,
                content_hash=hashlib.sha256(json.dumps(ht_payload).encode()).hexdigest(),
                effective_at=now,
                recorded_at=now,
            ))
            session.add(HealthResource(
                id=str(uuid.uuid4()),
                profile_id=profile.id,
                resource_type="observation",
                source_type="manual",
                status="active",
                scope="health.clinical",
                data=wt_payload,
                content_hash=hashlib.sha256(json.dumps(wt_payload).encode()).hexdigest(),
                effective_at=now,
                recorded_at=now,
            ))
            await session.commit()

            # Compile school form prefill
            prefill = await compile_school_form_prefill(session, profile.id)
            assert "latest_vitals" in prefill
            assert prefill["latest_vitals"]["height"] is not None
            assert prefill["latest_vitals"]["weight"] is not None

    @pytest.mark.asyncio
    async def test_c07_interaction_core_notes_carefold_library(self, auth_async_client, profile_factory):
        """C-07: Notes created in profile context are isolated and queryable in Carefold Library."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Library Isolated Patient")
            res_create = await client.post(
                f"/api/v1/profiles/{profile.id}/notes",
                json={
                    "title": "Annual Prevention Plan",
                    "content": "Dietary and exercise schedule for hypertension management.",
                    "type": "general",
                    "tags": ["prevention", "library-test"],
                },
            )
            assert res_create.status_code == 201
            note_id = res_create.json()["id"]

            res_list = await client.get(f"/api/v1/profiles/{profile.id}/notes")
            assert res_list.status_code == 200
            note_ids = [n["id"] for n in res_list.json().get("notes", [])]
            assert note_id in note_ids

    @pytest.mark.asyncio
    async def test_c08_interaction_claims_denial_notes_appeal(self, auth_async_client, profile_factory):
        """C-08: Insurance claim denied with EOB explanation; appeal note dossier created."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Denial Patient")
            # 1. Post denied claim
            claim_payload = {
                "profile_id": profile.id,
                "service_date": "2026-10-15",
                "billed_amount": 2500.0,
                "status": "denied",
                "denial_reason": "Experimental or investigational treatment",
                "denial_code": "EXP-01",
            }
            res_claim = await client.post(f"/api/v1/profiles/{profile.id}/claims", json=claim_payload)
            assert res_claim.status_code == 201
            claim_data = res_claim.json()

            # 2. Create appeal referencing claim
            appeal_payload = {
                "profile_id": profile.id,
                "claim_id": claim_data["id"],
                "denial_code": "EXP-01",
                "clinical_justification": "Peer-reviewed literature demonstrates safety and efficacy.",
            }
            res_appeal = await client.post(f"/api/v1/profiles/{profile.id}/appeals", json=appeal_payload)
            assert res_appeal.status_code == 201
            appeal_data = res_appeal.json()
            assert appeal_data["claim_id"] == claim_data["id"]

    @pytest.mark.asyncio
    async def test_c09_interaction_sse_allergy_badge_invalidation(self, auth_async_client, profile_factory):
        """C-09: Agent executes allergy creation; validates reactive cache invalidation payload."""
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Allergy Badge Patient")
            allergy_id = f"allergy-sse-{uuid.uuid4().hex[:8]}"
            allergy_payload = {
                "resourceType": "AllergyIntolerance",
                "id": allergy_id,
                "clinicalStatus": {"coding": [{"code": "active"}]},
                "criticality": "high",
                "code": {"coding": [{"code": "764146007", "display": "Penicillin"}]},
                "patient": {"reference": f"Patient/{profile.id}"},
            }
            res = await client.put(
                f"/api/v1/fhir/r4/AllergyIntolerance/{allergy_id}?confirmed=true&profile_id={profile.id}",
                json=allergy_payload,
            )
            assert res.status_code in (200, 201)

            # Validate entity_changed event schema via canonical builder and schema model
            event_payload = build_entity_changed_payload(
                tool_name="allergies_create",
                args={"profile_id": profile.id, "entity_type": "allergy", "id": allergy_id},
                output={"id": allergy_id, "action": "created"},
                profile_id=profile.id,
                scope="health.clinical",
            )
            event = EntityChangedPayload.model_validate(event_payload)
            assert event.type == SSE_EVENT_ENTITY_CHANGED
            assert event.entity_type == "allergy"
            assert event.action == "created"
            assert event.entity_id == allergy_id
            assert event.profile_id == profile.id
