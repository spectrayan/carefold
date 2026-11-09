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

"""Unit and isolation tests for read-only, scope-isolated FHIR R4 chart query tools (#287)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.engine.tool_exec import TaintFlag, UntrustedResult
from carefold.fhir.repository import (
    delete_fhir_resource_with_history,
    upsert_fhir_resource_with_history,
)
from carefold.scope.context import scope_context
from carefold.tools.fhir_tools import (
    NON_CLINICAL_FHIR_TOOL_DISCLAIMER,
    SPEC_GET_OBSERVATION_TRENDS,
    SPEC_GET_PATIENT_SUMMARY,
    SPEC_SEARCH_RESOURCES,
    execute_fhir_get_observation_trends,
    execute_fhir_get_patient_summary,
    execute_fhir_search_resources,
    fhir_get_observation_trends,
    fhir_get_patient_summary,
    fhir_search_resources,
)
from yarvelle_core.config import settings
from yarvelle_core.db.base import Base
from yarvelle_core.db.models import Profile, User


@dataclass
class DummyToolContext:
    """Minimal ToolContext test double carrying profile_id, session_factory, scopes, and taint."""

    profile_id: Optional[str] = None
    user_id: Optional[str] = None
    session_factory: Any = None
    scopes: Optional[Set[str]] = None
    taint: TaintFlag = field(default_factory=lambda: TaintFlag(False))


@pytest.fixture
async def fhir_tools_env(tmp_path, monkeypatch):
    """Creates an isolated in-memory SQLite database with two patient profiles for FHIR tool tests."""
    monkeypatch.setattr(settings, "home_dir", tmp_path)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    user_id = str(uuid.uuid4())
    profile_a_id = str(uuid.uuid4())
    profile_b_id = str(uuid.uuid4())

    async with factory() as session:
        user = User(
            id=user_id,
            email="coordinator-test@example.com",
            username="coord_tester_287",
            hashed_password="hashed_password",
            role="steward",
        )
        profile_a = Profile(
            id=profile_a_id,
            user_id=user_id,
            name="Maya Patel",
            relationship="self",
            role="self",
            date_of_birth="1988-11-23",
            is_primary=True,
        )
        profile_b = Profile(
            id=profile_b_id,
            user_id=user_id,
            name="Arjun Patel",
            relationship="spouse",
            role="adult_household",
            date_of_birth="1986-04-12",
            is_primary=False,
        )
        session.add_all([user, profile_a, profile_b])
        await session.commit()

    yield {
        "factory": factory,
        "user_id": user_id,
        "profile_a": profile_a_id,
        "profile_b": profile_b_id,
    }
    await engine.dispose()


def test_fhir_tool_specs_are_read_only_and_clinical_scoped():
    """Verifies all 3 FHIR chart tools are strictly read-only, zero-egress, and scoped to health.clinical."""
    for spec in (SPEC_SEARCH_RESOURCES, SPEC_GET_PATIENT_SUMMARY, SPEC_GET_OBSERVATION_TRENDS):
        assert spec.risk_tier == "read"
        assert spec.scopes == {"health.clinical"}
        assert spec.data_flows.allowed_hosts == ()
        assert spec.data_flows.data_sensitivity == "phi"
        assert callable(spec.executor)


@pytest.mark.asyncio
async def test_empty_chart_handling_across_all_three_tools(fhir_tools_env):
    """Verifies clean empty-chart responses, non-clinical disclaimers, and untainted state when no records exist."""
    ctx_a = DummyToolContext(
        profile_id=fhir_tools_env["profile_a"],
        user_id=fhir_tools_env["user_id"],
        session_factory=fhir_tools_env["factory"],
    )

    search_res = await execute_fhir_search_resources({"resource_type": "Condition"}, ctx_a)
    assert search_res.success is True
    assert search_res["count"] == 0
    assert search_res["records"] == []
    assert search_res.taint is False
    assert search_res.trust == "trusted"
    assert search_res["disclaimer"] == NON_CLINICAL_FHIR_TOOL_DISCLAIMER

    summary_res = await execute_fhir_get_patient_summary({}, ctx_a)
    assert summary_res.success is True
    assert summary_res["empty_chart"] is True
    assert summary_res["total_records"] == 0
    assert summary_res["active_conditions"] == []
    assert summary_res["active_medications"] == []
    assert summary_res["allergies"] == []
    assert summary_res["recent_labs_and_vitals"] == []
    assert summary_res["immunizations"] == []
    assert summary_res.taint is False
    assert summary_res["disclaimer"] == NON_CLINICAL_FHIR_TOOL_DISCLAIMER

    trends_res = await execute_fhir_get_observation_trends({"loinc_or_code": "4548-4"}, ctx_a)
    assert trends_res.success is True
    assert trends_res["count"] == 0
    assert trends_res["data_points"] == []
    assert trends_res["summary"]["latest_value"] is None
    assert trends_res.taint is False
    assert ctx_a.taint.is_tainted is False


@pytest.mark.asyncio
async def test_fhir_search_resources_filters_provenance_and_taint(fhir_tools_env):
    """Verifies code/system|code, category, date_from, limit filters, provenance citations, and UntrustedResult taint."""
    factory = fhir_tools_env["factory"]
    profile_a = fhir_tools_env["profile_a"]

    async with factory() as session:
        # 1. Lab Observation (HbA1c 4548-4) from Epic MyChart (untrusted portal import)
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Observation",
            source_type="connector",
            source_ref="Epic MyChart",
            source_id="obs-hba1c-1",
            fhir_data={
                "resourceType": "Observation",
                "id": "obs-hba1c-1",
                "status": "final",
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "laboratory",
                                "display": "Laboratory",
                            }
                        ]
                    }
                ],
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "4548-4",
                            "display": "Hemoglobin A1c/Hemoglobin.total in Blood",
                        }
                    ]
                },
                "subject": {"reference": f"Patient/{profile_a}"},
                "effectiveDateTime": "2026-09-15T09:30:00Z",
                "valueQuantity": {"value": 6.8, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"},
                "meta": {"trust": "untrusted"},
                "_carefold_provenance": {"source_name": "Epic MyChart", "trust": "untrusted"},
            },
        )
        # 2. Vital Sign Observation (Heart rate 8867-4) from Manual Entry (trusted)
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Observation",
            source_type="manual",
            source_ref="Patient Manual Entry",
            source_id="obs-hr-1",
            fhir_data={
                "resourceType": "Observation",
                "id": "obs-hr-1",
                "status": "final",
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "vital-signs",
                                "display": "Vital Signs",
                            }
                        ]
                    }
                ],
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8867-4",
                            "display": "Heart rate",
                        }
                    ]
                },
                "subject": {"reference": f"Patient/{profile_a}"},
                "effectiveDateTime": "2026-03-10T08:00:00Z",
                "valueQuantity": {"value": 72, "unit": "/min", "system": "http://unitsofmeasure.org", "code": "/min"},
            },
        )
        await session.commit()

    # Query 1: Search by system|code for HbA1c (untrusted)
    ctx_portal = DummyToolContext(profile_id=profile_a, session_factory=factory)
    res_hba1c = await fhir_search_resources(
        "Observation",
        code="http://loinc.org|4548-4",
        category="laboratory",
        date_from="2026-06-01",
        ctx=ctx_portal,
    )
    assert res_hba1c.success is True
    assert res_hba1c["count"] == 1
    rec = res_hba1c["records"][0]
    assert rec["resource_type"] == "Observation"
    assert rec["value"] == "6.8 %"
    assert rec["provenance_citation"] == "From Epic MyChart, 2026-09-15"
    assert rec["trust"] == "untrusted"
    assert res_hba1c.taint is True
    assert res_hba1c.trust == "untrusted"
    assert isinstance(res_hba1c.untrusted_result, UntrustedResult)
    assert res_hba1c.untrusted_result.taint is True
    assert ctx_portal.taint.is_tainted is True

    # Query 2: Search only vital-signs (manual trusted entry)
    ctx_manual = DummyToolContext(profile_id=profile_a, session_factory=factory)
    res_vitals = await fhir_search_resources(
        "observation",
        category="vital-signs",
        ctx=ctx_manual,
    )
    assert res_vitals.success is True
    assert res_vitals["count"] == 1
    v_rec = res_vitals["records"][0]
    assert v_rec["display"] == "Heart rate"
    assert v_rec["provenance_citation"] == "From Patient Manual Entry, 2026-03-10"
    assert v_rec["trust"] == "trusted"
    assert res_vitals.taint is False
    assert ctx_manual.taint.is_tainted is False


@pytest.mark.asyncio
async def test_fhir_get_patient_summary_ips_sections_and_active_filtering(fhir_tools_env):
    """Verifies IPS patient summary populates active conditions, medications, allergies, labs/vitals, and immunizations while excluding resolved/stopped/tombstoned records."""
    factory = fhir_tools_env["factory"]
    profile_a = fhir_tools_env["profile_a"]

    async with factory() as session:
        # Active Condition
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Condition",
            source_type="file",
            source_ref="Mercy Hospital C-CDA",
            source_id="cond-active-htn",
            fhir_data={
                "resourceType": "Condition",
                "id": "cond-active-htn",
                "clinicalStatus": {
                    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]
                },
                "code": {
                    "coding": [{"system": "http://snomed.info/sct", "code": "38341003", "display": "Hypertensive disorder"}]
                },
                "subject": {"reference": f"Patient/{profile_a}"},
                "recordedDate": "2026-08-01T10:00:00Z",
                "_carefold_provenance": {"source_name": "Mercy Hospital C-CDA", "trust": "untrusted"},
            },
        )
        # Resolved Condition (should be excluded from active_conditions)
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Condition",
            source_type="file",
            source_ref="Mercy Hospital C-CDA",
            source_id="cond-resolved-sprain",
            fhir_data={
                "resourceType": "Condition",
                "id": "cond-resolved-sprain",
                "clinicalStatus": {
                    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "resolved"}]
                },
                "code": {"text": "Ankle sprain"},
                "subject": {"reference": f"Patient/{profile_a}"},
                "recordedDate": "2024-05-01T10:00:00Z",
            },
        )
        # Active MedicationRequest
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="MedicationRequest",
            source_type="connector",
            source_ref="Epic MyChart",
            source_id="med-lisinopril",
            fhir_data={
                "resourceType": "MedicationRequest",
                "id": "med-lisinopril",
                "status": "active",
                "intent": "order",
                "medicationCodeableConcept": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "314076",
                            "display": "Lisinopril 10 MG Oral Tablet",
                        }
                    ]
                },
                "subject": {"reference": f"Patient/{profile_a}"},
                "authoredOn": "2026-08-15T12:00:00Z",
                "dosageInstruction": [{"text": "Take 1 tablet by mouth daily"}],
                "_carefold_provenance": {"source_name": "Epic MyChart", "trust": "untrusted"},
            },
        )
        # Stopped MedicationRequest (should be excluded from active_medications)
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="MedicationRequest",
            source_type="connector",
            source_ref="Epic MyChart",
            source_id="med-stopped",
            fhir_data={
                "resourceType": "MedicationRequest",
                "id": "med-stopped",
                "status": "stopped",
                "intent": "order",
                "medicationCodeableConcept": {"text": "Old Antibiotic"},
                "subject": {"reference": f"Patient/{profile_a}"},
                "authoredOn": "2023-01-10T12:00:00Z",
            },
        )
        # Active AllergyIntolerance
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="AllergyIntolerance",
            source_type="connector",
            source_ref="Epic MyChart",
            source_id="allergy-penicillin",
            fhir_data={
                "resourceType": "AllergyIntolerance",
                "id": "allergy-penicillin",
                "clinicalStatus": {
                    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]
                },
                "criticality": "high",
                "code": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "7980",
                            "display": "Penicillin G",
                        }
                    ]
                },
                "patient": {"reference": f"Patient/{profile_a}"},
                "recordedDate": "2025-04-20T00:00:00Z",
                "reaction": [{"manifestation": [{"text": "Hives and rash"}]}],
            },
        )
        # Immunization
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Immunization",
            source_type="file",
            source_ref="State Immunization Registry",
            source_id="imm-flu-2026",
            fhir_data={
                "resourceType": "Immunization",
                "id": "imm-flu-2026",
                "status": "completed",
                "vaccineCode": {
                    "coding": [{"system": "http://hl7.org/fhir/sid/cvx", "code": "140", "display": "Influenza, seasonal, injectable, preservative free"}]
                },
                "patient": {"reference": f"Patient/{profile_a}"},
                "occurrenceDateTime": "2026-10-01T14:00:00Z",
            },
        )
        # Tombstoned Condition (must never appear)
        tomb_hr, _, _ = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Condition",
            source_type="manual",
            source_id="cond-tombstoned",
            fhir_data={
                "resourceType": "Condition",
                "id": "cond-tombstoned",
                "clinicalStatus": {"coding": [{"code": "active"}]},
                "code": {"text": "Mistaken entry"},
                "subject": {"reference": f"Patient/{profile_a}"},
            },
        )
        await delete_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_id=tomb_hr.id,
        )
        await session.commit()

    ctx_a = DummyToolContext(profile_id=profile_a, session_factory=factory)
    summary = await fhir_get_patient_summary(ctx=ctx_a)
    assert summary.success is True
    assert summary["empty_chart"] is False
    assert summary["total_records"] == 4
    assert summary.taint is True

    assert len(summary["active_conditions"]) == 1
    assert summary["active_conditions"][0]["display"] == "Hypertensive disorder"
    assert summary["active_conditions"][0]["provenance_citation"] == "From Mercy Hospital C-CDA, 2026-08-01"

    assert len(summary["active_medications"]) == 1
    assert summary["active_medications"][0]["display"] == "Lisinopril 10 MG Oral Tablet"
    assert summary["active_medications"][0]["dosage_text"] == "Take 1 tablet by mouth daily"
    assert summary["active_medications"][0]["provenance_citation"] == "From Epic MyChart, 2026-08-15"

    assert len(summary["allergies"]) == 1
    assert summary["allergies"][0]["display"] == "Penicillin G"
    assert summary["allergies"][0]["criticality"] == "high"
    assert summary["allergies"][0]["manifestations"] == ["Hives and rash"]

    assert len(summary["immunizations"]) == 1
    assert "Influenza" in summary["immunizations"][0]["display"]


@pytest.mark.asyncio
async def test_fhir_get_observation_trends_chronological_stats_and_unit_translation(fhir_tools_env):
    """Verifies chronological ordering, reference range flag derivation, original unit preservation, and BP component queries."""
    factory = fhir_tools_env["factory"]
    profile_a = fhir_tools_env["profile_a"]

    async with factory() as session:
        # Three HbA1c readings over time (out of chronological insertion order)
        for idx, (dt_str, val) in enumerate(
            [
                ("2026-09-01T08:00:00Z", 6.2),
                ("2026-03-01T08:00:00Z", 7.4),
                ("2026-06-01T08:00:00Z", 6.8),
            ],
            start=1,
        ):
            await upsert_fhir_resource_with_history(
                session,
                profile_id=profile_a,
                resource_type="Observation",
                source_type="connector",
                source_ref="Quest Diagnostics",
                source_id=f"hba1c-{idx}",
                fhir_data={
                    "resourceType": "Observation",
                    "id": f"hba1c-{idx}",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}]
                    },
                    "subject": {"reference": f"Patient/{profile_a}"},
                    "effectiveDateTime": dt_str,
                    "valueQuantity": {"value": val, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"},
                    "referenceRange": [
                        {
                            "low": {"value": 4.0, "unit": "%"},
                            "high": {"value": 5.6, "unit": "%"},
                            "text": "4.0 - 5.6 %",
                        }
                    ],
                },
            )

        # Body weight in lbs (automatically normalized to kg by #283 with original quantity extension)
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Observation",
            source_type="device",
            source_ref="Withings Scale",
            source_id="wt-lbs-1",
            fhir_data={
                "resourceType": "Observation",
                "id": "wt-lbs-1",
                "status": "final",
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]
                },
                "subject": {"reference": f"Patient/{profile_a}"},
                "effectiveDateTime": "2026-10-05T07:00:00Z",
                "valueQuantity": {
                    "value": 154.324,
                    "unit": "lbs",
                    "system": "http://unitsofmeasure.org",
                    "code": "[lb_av]",
                },
            },
        )

        # Blood pressure panel (85354-9) with systolic (8480-6) and diastolic (8462-4) components
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Observation",
            source_type="manual",
            source_ref="Patient Manual Entry",
            source_id="bp-panel-1",
            fhir_data={
                "resourceType": "Observation",
                "id": "bp-panel-1",
                "status": "final",
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": "85354-9", "display": "Blood pressure panel"}]
                },
                "subject": {"reference": f"Patient/{profile_a}"},
                "effectiveDateTime": "2026-10-10T08:00:00Z",
                "component": [
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]},
                        "valueQuantity": {"value": 128, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]},
                        "valueQuantity": {"value": 82, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
                    },
                ],
            },
        )
        await session.commit()

    ctx_a = DummyToolContext(profile_id=profile_a, session_factory=factory)

    # 1. Trend HbA1c (4548-4) -> chronological order: 7.4 (2026-03-01), 6.8 (2026-06-01), 6.2 (2026-09-01)
    hba1c_trends = await fhir_get_observation_trends("4548-4", ctx=ctx_a)
    assert hba1c_trends.success is True
    assert hba1c_trends["count"] == 3
    pts = hba1c_trends["data_points"]
    assert [p["date"] for p in pts] == ["2026-03-01", "2026-06-01", "2026-09-01"]
    assert [p["value"] for p in pts] == [7.4, 6.8, 6.2]
    assert all(p["interpretation"] == "H" for p in pts)
    assert all(p["provenance_citation"].startswith("From Quest Diagnostics, ") for p in pts)
    assert hba1c_trends["summary"]["min_value"] == 6.2
    assert hba1c_trends["summary"]["max_value"] == 7.4
    assert hba1c_trends["summary"]["latest_value"] == 6.2
    assert hba1c_trends["summary"]["delta_from_first"] == pytest.approx(-1.2)

    # 2. Trend Body weight (29463-7) -> normalized to ~70 kg with original_quantity preserved
    wt_trends = await fhir_get_observation_trends("http://loinc.org|29463-7", ctx=ctx_a)
    assert wt_trends.success is True
    assert wt_trends["count"] == 1
    wt_pt = wt_trends["data_points"][0]
    assert wt_pt["unit"] == "kg"
    assert wt_pt["value"] == pytest.approx(70.0, rel=1e-2)
    assert wt_pt["original_quantity"] is not None
    assert wt_pt["original_quantity"]["value"] == pytest.approx(154.324)

    # 3. Trend component code 8480-6 (Systolic BP inside 85354-9 BP panel)
    sys_trends = await fhir_get_observation_trends("8480-6", ctx=ctx_a)
    assert sys_trends.success is True
    assert sys_trends["count"] == 1
    assert sys_trends["data_points"][0]["value"] == 128
    assert sys_trends["data_points"][0]["unit"] == "mmHg"


@pytest.mark.asyncio
async def test_strict_profile_and_scope_isolation(fhir_tools_env):
    """Verifies fail-closed profile_id enforcement, cross-profile isolation, and health.clinical vs health.paperwork scope isolation."""
    factory = fhir_tools_env["factory"]
    profile_a = fhir_tools_env["profile_a"]
    profile_b = fhir_tools_env["profile_b"]

    async with factory() as session:
        # Profile B clinical Condition (must never leak to Profile A)
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_b,
            resource_type="Condition",
            source_type="connector",
            source_ref="Arjun Portal",
            source_id="b-cond-1",
            fhir_data={
                "resourceType": "Condition",
                "id": "b-cond-1",
                "clinicalStatus": {"coding": [{"code": "active"}]},
                "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Type 2 diabetes mellitus"}]},
                "subject": {"reference": f"Patient/{profile_b}"},
                "recordedDate": "2026-07-01T00:00:00Z",
            },
        )
        # Profile B HbA1c Observation (must never leak to Profile A)
        await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_b,
            resource_type="Observation",
            source_type="connector",
            source_ref="Arjun Portal",
            source_id="b-obs-1",
            fhir_data={
                "resourceType": "Observation",
                "id": "b-obs-1",
                "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}]},
                "subject": {"reference": f"Patient/{profile_b}"},
                "effectiveDateTime": "2026-07-01T00:00:00Z",
                "valueQuantity": {"value": 8.9, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"},
            },
        )
        # Profile A paperwork Coverage resource (routes to health.paperwork, must not be exposed via clinical chart tools)
        with scope_context(
            scope="health.paperwork",
            active_scopes=frozenset({"health.paperwork", "health.clinical"}),
            granted_scopes=frozenset({"health.paperwork", "health.clinical"}),
        ):
            await upsert_fhir_resource_with_history(
                session,
                profile_id=profile_a,
                resource_type="Coverage",
                source_type="file",
                source_ref="Insurance Card",
                source_id="a-cov-1",
                scope="health.paperwork",
                fhir_data={
                    "resourceType": "Coverage",
                    "id": "a-cov-1",
                    "status": "active",
                    "beneficiary": {"reference": f"Patient/{profile_a}"},
                    "payor": [{"display": "Acme Health Plan"}],
                },
            )
        await session.commit()

    # 1. Missing profile_id fails closed
    no_prof_ctx = DummyToolContext(profile_id=None, session_factory=factory)
    r_missing_1 = await execute_fhir_search_resources({"resource_type": "Condition"}, no_prof_ctx)
    r_missing_2 = await execute_fhir_get_patient_summary({}, no_prof_ctx)
    r_missing_3 = await execute_fhir_get_observation_trends({"loinc_or_code": "4548-4"}, no_prof_ctx)
    assert r_missing_1.success is False and "Security violation" in (r_missing_1.error or "")
    assert r_missing_2.success is False and "Security violation" in (r_missing_2.error or "")
    assert r_missing_3.success is False and "Security violation" in (r_missing_3.error or "")

    # 2. Cross-profile override attempt in args fails closed
    ctx_a = DummyToolContext(profile_id=profile_a, session_factory=factory)
    r_cross = await execute_fhir_search_resources(
        {"resource_type": "Condition", "profile_id": profile_b},
        ctx_a,
    )
    assert r_cross.success is False
    assert "cross-profile access denied" in (r_cross.error or "")

    # 3. Profile A queries return zero records from Profile B
    res_a_cond = await execute_fhir_search_resources({"resource_type": "Condition"}, ctx_a)
    assert res_a_cond.success is True
    assert res_a_cond["count"] == 0

    res_a_sum = await execute_fhir_get_patient_summary({}, ctx_a)
    assert res_a_sum.success is True
    assert res_a_sum["total_records"] == 0

    res_a_trend = await execute_fhir_get_observation_trends({"loinc_or_code": "4548-4"}, ctx_a)
    assert res_a_trend.success is True
    assert res_a_trend["count"] == 0

    # 4. Querying a health.paperwork resource type (Coverage) via clinical tool fails closed
    res_cov = await execute_fhir_search_resources({"resource_type": "Coverage"}, ctx_a)
    assert res_cov.success is False
    assert "health.paperwork" in (res_cov.error or "")

    # 5. Executing clinical tools inside a health.paperwork-only ScopeContext fails closed
    with scope_context(
        scope="health.paperwork",
        active_scopes=frozenset({"health.paperwork"}),
        granted_scopes=frozenset({"health.paperwork"}),
    ):
        r_scope_1 = await execute_fhir_search_resources({"resource_type": "Condition"}, ctx_a)
        r_scope_2 = await execute_fhir_get_patient_summary({}, ctx_a)
        r_scope_3 = await execute_fhir_get_observation_trends({"loinc_or_code": "4548-4"}, ctx_a)
        assert r_scope_1.success is False and "Scope violation" in (r_scope_1.error or "")
        assert r_scope_2.success is False and "Scope violation" in (r_scope_2.error or "")
        assert r_scope_3.success is False and "Scope violation" in (r_scope_3.error or "")

    # 6. Executing with a ToolContext restricted to health.paperwork fails closed
    paperwork_ctx = DummyToolContext(
        profile_id=profile_a,
        session_factory=factory,
        scopes={"health.paperwork"},
    )
    r_ctx_scope = await execute_fhir_get_patient_summary({}, paperwork_ctx)
    assert r_ctx_scope.success is False
    assert "Scope violation" in (r_ctx_scope.error or "")
