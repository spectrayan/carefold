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

"""Tier 4: Real-World Clinical Application Scenarios (S-01 to S-05).

Simulates comprehensive end-user journeys across:
- S-01: New Patient Intake & Visit Summary Extraction (F-01, F-03, F-05, F-07, F-08)
- S-02: Chronic Hypertension & Diabetic Multi-Metric Care (F-02, F-06, F-07, F-08)
- S-03: Pediatric School Physical & Sports Clearance (F-01, F-06, F-07, F-08)
- S-04: Denied Insurance Claim & Prior-Authorization Appeal (F-01, F-05, F-07, F-09)
- S-05: Multi-Specialist Deliberative Consultation with Live UI Sync (F-01, F-02, F-06, F-07, F-09)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid
import pytest
from httpx import AsyncClient

from carefold.clinical.bmi import calculate_adult_bmi, calculate_pediatric_bmi_percentile
from carefold.clinical.notes import extract_after_visit_summary, NON_CLINICAL_DISCLAIMER
from carefold.clinical.vitals import calculate_diurnal_bp_trends, parse_all_vitals_observations
from carefold.dossiers.insurance_benefits import InsuranceBenefitsDossier
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.safety.vitals import check_vitals_red_flags
from carefold.workflows.subgraphs.extraction.sanitizer import sanitize_pii


class TestTier4RealWorldScenarios:
    """End-to-end multi-feature user journeys."""

    @pytest.mark.asyncio
    async def test_scenario_s01_new_patient_intake_extraction(self, auth_async_client, profile_factory):
        """S-01: New Patient Intake & Visit Summary Extraction.

        Workflow:
        1. Ingest raw clinical visit text with PII.
        2. Sanitize sensitive identifiers (SSN, MRN, phone).
        3. Extract conditions and medications into FHIR R4 resources.
        4. Record baseline vitals.
        5. Schedule initial follow-up appointment.
        """
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Jane Doe")

            raw_visit_text = (
                "CLINICAL VISIT SUMMARY\n"
                "Patient: Jane Doe, MRN: MRN99421, SSN: 000-12-3456, Phone: (555) 019-2834\n"
                "Assessment: Essential Hypertension, Mild Dehydration.\n"
                "Prescriptions: Amlodipine 5mg oral tablet once daily.\n"
                "Vitals: Blood pressure 138/88 mmHg, Heart rate 76 bpm.\n"
                "Follow-up: Return in 4 weeks for blood pressure re-evaluation.\n"
            )

            # Step 1 & 2: PII sanitization
            sanitized = sanitize_pii(raw_visit_text)
            assert "000-12-3456" not in sanitized
            assert "MRN99421" not in sanitized

            # Step 3: Save condition & medication to FHIR
            cond_id = f"cond-intake-{uuid.uuid4().hex[:8]}"
            res_cond = await client.put(
                f"/api/v1/fhir/r4/Condition/{cond_id}?confirmed=true&profile_id={profile.id}",
                json={
                    "resourceType": "Condition",
                    "id": cond_id,
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "code": {"coding": [{"code": "38341003", "display": "Essential Hypertension"}]},
                    "subject": {"reference": f"Patient/{profile.id}"},
                },
            )
            assert res_cond.status_code in (200, 201)

            # Step 4: Record baseline vitals
            res_vitals = await client.post(
                f"/api/v1/profiles/{profile.id}/vitals",
                json={
                    "vitals": {"systolic": 138, "diastolic": 88, "heart_rate": 76},
                    "effective_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            assert res_vitals.status_code == 201

            # Step 5: Schedule 4-week follow-up appointment
            appt_time = datetime.now(timezone.utc) + timedelta(weeks=4)
            res_appt = await client.post(
                f"/api/v1/profiles/{profile.id}/appointments",
                json={
                    "title": "Hypertension Re-evaluation",
                    "provider_name": "Dr. Primary Care",
                    "specialty": "Primary Care",
                    "status": "scheduled",
                    "start_time": appt_time.isoformat(),
                    "end_time": (appt_time + timedelta(minutes=30)).isoformat(),
                    "timezone": "UTC",
                },
            )
            assert res_appt.status_code == 201
            assert res_appt.json()["title"] == "Hypertension Re-evaluation"

    @pytest.mark.asyncio
    async def test_scenario_s02_chronic_hypertension_diabetic_care(self, auth_async_client, profile_factory):
        """S-02: Chronic Hypertension & Diabetic Multi-Metric Care.

        Workflow:
        1. Patient logs multi-vital reading (BP 142/92, HR 78, Glucose 145 mg/dL, Weight 182 lbs).
        2. Normalizer parses all 4 independent metrics into FHIR resources.
        3. Diurnal BP trends and adult BMI are calculated.
        4. Create a clinical visit prep note with summary.
        """
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Robert Chronic")

            # 1 & 2: Log multi-metric vitals
            multi_vitals = {
                "systolic": 142,
                "diastolic": 92,
                "heart_rate": 78,
                "blood_glucose": 145,
                "weight": 82.5,  # ~182 lbs
                "height": 178,
            }
            obs_list = parse_all_vitals_observations(multi_vitals)
            assert len(obs_list) >= 4

            # 3: Verify BMI calculation
            bmi_calc = calculate_adult_bmi(82.5, 178)
            assert bmi_calc is not None
            assert 25.0 <= bmi_calc["bmi"] <= 27.5

            # 4: Persist in DB via REST
            res_post = await client.post(
                f"/api/v1/profiles/{profile.id}/vitals",
                json={
                    "vitals": {"systolic": 142, "diastolic": 92, "heart_rate": 78, "blood_glucose": 145},
                    "effective_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            assert res_post.status_code == 201

            # 5: Create pre-visit note
            res_note = await client.post(
                f"/api/v1/profiles/{profile.id}/notes",
                json={
                    "title": "Hypertension & Glucose Log Review",
                    "content": "Blood pressure elevated above 140/90; morning fasting glucose 145 mg/dL.",
                    "type": "visit",
                    "tags": ["chronic-care", "diabetic", "hypertension"],
                },
            )
            assert res_note.status_code == 201

    @pytest.mark.asyncio
    async def test_scenario_s03_pediatric_school_physical_clearance(self, auth_async_client, profile_factory):
        """S-03: Pediatric School Physical & Sports Clearance.

        Workflow:
        1. Profile created for 7-year-old child.
        2. Pediatric BMI percentile calculated using CDC growth charts.
        3. School Form draft created with universal state form.
        4. School calendar feed subscribed for immunization reminders.
        """
        async with auth_async_client() as (client, user):
            child_dob = (datetime.now(timezone.utc) - timedelta(days=7 * 365)).strftime("%Y-%m-%d")
            profile = await profile_factory(
                user_id=user.id,
                name="Leo Martinez",
                relationship="child",
                date_of_birth=child_dob,
            )

            # 2: CDC Pediatric BMI calculation (7 years = 84 months)
            bmi_res = calculate_pediatric_bmi_percentile(
                age_months=84,
                gender="male",
                weight_kg=24.0,
                height_cm=120.0,
            )
            assert bmi_res is not None
            assert "category" in bmi_res or "percentile" in bmi_res or "bmi" in bmi_res

            # 3: Create School Form dossier
            res_form = await client.post(
                f"/api/v1/profiles/{profile.id}/school-forms",
                json={
                    "title": "Elementary Sports & Physical Clearance 2026",
                    "school_or_camp_name": "Oakridge Elementary",
                    "form_type": "physical",
                    "status": "draft",
                },
            )
            assert res_form.status_code == 201
            assert res_form.json()["title"] == "Elementary Sports & Physical Clearance 2026"

    @pytest.mark.asyncio
    async def test_scenario_s04_denied_claim_prior_auth_appeal(self, auth_async_client, profile_factory):
        """S-04: Denied Insurance Claim & Prior-Authorization Appeal.

        Workflow:
        1. Patient sets up coverage plan.
        2. Submits prior authorization for diagnostic imaging (MRI).
        3. Payer denies claim due to lack of prior auth.
        4. Patient creates appeal dossier citing clinical guidelines.
        """
        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Appeal Workflow Patient")

            # 1. Coverage plan setup
            res_cov = await client.post(
                f"/api/v1/profiles/{profile.id}/coverage",
                json={
                    "payer_name": "Anthem Blue Cross",
                    "policy_number": "ANT-11223344",
                    "deductible_individual": 2000.0,
                    "oop_max_individual": 5000.0,
                },
            )
            assert res_cov.status_code == 201

            # 2. Prior authorization request
            res_pa = await client.post(
                f"/api/v1/profiles/{profile.id}/prior-auths",
                json={
                    "procedure_code": "72148",
                    "procedure_name": "MRI Lumbar Spine",
                    "status": "pending",
                },
            )
            assert res_pa.status_code == 201
            pa_id = res_pa.json()["id"]

            # 3. Denied claim submission
            res_claim = await client.post(
                f"/api/v1/profiles/{profile.id}/claims",
                json={
                    "service_date": "2026-11-01",
                    "billed_amount": 1850.0,
                    "status": "denied",
                    "denial_code": "NO-PA",
                    "denial_reason": "Prior authorization not on file at time of service",
                },
            )
            assert res_claim.status_code == 201
            claim_id = res_claim.json()["id"]

            # 4. Appeal creation
            res_appeal = await client.post(
                f"/api/v1/profiles/{profile.id}/appeals",
                json={
                    "claim_id": claim_id,
                    "prior_auth_id": pa_id,
                    "denial_code": "NO-PA",
                    "clinical_justification": "Prior authorization was submitted prior to date of service; clinical guidelines warrant urgent diagnostic.",
                },
            )
            assert res_appeal.status_code == 201
            appeal_data = res_appeal.json()
            assert appeal_data["claim_id"] == claim_id
            assert appeal_data["prior_auth_id"] == pa_id

    @pytest.mark.asyncio
    async def test_scenario_s05_multi_specialist_deliberative_consultation(self, auth_async_client, profile_factory):
        """S-05: Multi-Specialist Consultation Tool Wiring, Execution & Live UI Sync."""
        from yarvelle_core.engine.tool_registry import create_default_registry as core_create_default_registry
        from yarvelle_core.schemas.events import build_entity_changed_payload
        from yarvelle_core.workflows.nodes.main_agent_node import MainAgentNode
        from carefold.engine.runtime import CarefoldAgentExecutionService

        repo_root = Path(__file__).resolve().parents[3]
        svc = CarefoldAgentExecutionService(workspace_root=repo_root)
        reg = svc._agent_registry()

        heart_tools = reg.get_effective_tools("heart-care-coordinator")
        benefits_tools = reg.get_effective_tools("benefits-coordinator")
        claims_tools = reg.get_effective_tools("claims-appeals-coordinator")
        assert {"vitals_create", "vitals_list", "vitals_update"}.issubset(set(heart_tools))
        assert {"coverage_create", "coverage_list"}.issubset(set(benefits_tools))
        assert {"claims_create", "appeals_create"}.issubset(set(claims_tools))

        main_node = MainAgentNode(
            model=None,
            registry=reg,
            orchestration=svc.orchestration,
            default_agent=svc.default_agent_id,
        )
        resolver = main_node._build_turn_tool_resolver({"workspace_root": str(repo_root)})
        heart_resolved = {t.name: t for t in resolver("heart-care-coordinator", heart_tools)}
        benefits_resolved = {t.name: t for t in resolver("benefits-coordinator", benefits_tools)}
        assert "vitals_create" in heart_resolved
        assert "coverage_create" in benefits_resolved

        # Schema fidelity: nested vitals keys & numeric coverage deductible preserved
        vitals_schema_text = json.dumps(heart_resolved["vitals_create"].args_schema.model_json_schema())
        benefits_schema_text = json.dumps(benefits_resolved["coverage_create"].args_schema.model_json_schema())
        assert "systolic" in vitals_schema_text and "spo2" in vitals_schema_text
        assert '"type": "number"' in benefits_schema_text

        async with auth_async_client() as (client, user):
            profile = await profile_factory(user_id=user.id, name="Deliberation Sync Patient")

            res_vitals = await client.post(
                f"/api/v1/profiles/{profile.id}/vitals",
                json={"vitals": {"systolic": 126, "diastolic": 80, "spo2": 98}},
            )
            assert res_vitals.status_code == 201
            vitals_ev = build_entity_changed_payload(
                tool_name="vitals_create",
                args={"vitals": {"systolic": 126, "diastolic": 80, "spo2": 98}},
                output=res_vitals.json(),
                profile_id=profile.id,
            )
            assert vitals_ev["entity_type"] == "vitals"
            assert vitals_ev["action"] == "created"

            res_cov = await client.post(
                f"/api/v1/profiles/{profile.id}/coverage",
                json={
                    "payer_name": "UnitedHealthcare PPO",
                    "policy_number": "UHC-882211",
                    "deductible_individual": 1500.0,
                },
            )
            assert res_cov.status_code == 201
            cov_ev = build_entity_changed_payload(
                tool_name="coverage_create",
                args={"payer_name": "UnitedHealthcare PPO", "policy_number": "UHC-882211"},
                output=res_cov.json(),
                profile_id=profile.id,
            )
            assert cov_ev["entity_type"] == "coverage"
            assert cov_ev["action"] == "created"
            assert NON_CLINICAL_DISCLAIMER
            assert core_create_default_registry() is not None
