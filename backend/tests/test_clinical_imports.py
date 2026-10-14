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

"""Unit and integration tests for Clinical & Wearable File Imports (AU-38 / E10.1, E10.2, E10.7, E8.0)."""

from __future__ import annotations

import json
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.api.deps import get_current_user, get_db
from carefold.api.imports import router as imports_router
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.db.base import Base
from carefold.db.models import (
    Attachment,
    AuditEventRecord,
    HealthResource,
    ImportBatch,
    Job,
    Profile,
    User,
)
from carefold.engine.tool_exec import TaintFlag, ToolContext
from carefold.importers import (
    commit_import_batch,
    discard_import_batch,
    parse_apple_health_export,
    parse_ccda_xml,
    parse_fhir_bundle,
    stage_import,
)
from carefold.tools.imports import (
    execute_commit_clinical_import,
    execute_stage_clinical_import,
)

SAMPLE_FHIR_BUNDLE = json.dumps({
    "resourceType": "Bundle",
    "id": "bundle-demo-001",
    "type": "collection",
    "entry": [
        {
            "resource": {
                "resourceType": "Observation",
                "id": "obs-hba1c-1",
                "status": "final",
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}],
                    "text": "Hemoglobin A1c",
                },
                "effectiveDateTime": "2026-03-10T09:15:00Z",
                "valueQuantity": {"value": 5.8, "unit": "%"},
            }
        },
        {
            "resource": {
                "resourceType": "Condition",
                "id": "cond-htn-1",
                "code": {
                    "coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10", "display": "Essential hypertension"}],
                    "text": "Essential hypertension",
                },
                "recordedDate": "2026-02-14",
            }
        },
        {
            "resource": {
                "resourceType": "MedicationStatement",
                "id": "med-lis-1",
                "status": "active",
                "medicationCodeableConcept": {"text": "Lisinopril 10 MG Oral Tablet"},
                "effectiveDateTime": "2026-02-14",
            }
        },
        {
            "resource": {
                "resourceType": "AllergyIntolerance",
                "id": "allergy-pen-1",
                "code": {"text": "Penicillin"},
                "recordedDate": "2025-11-01",
            }
        },
        {
            "resource": {
                "resourceType": "Immunization",
                "id": "imm-flu-1",
                "status": "completed",
                "vaccineCode": {"text": "Influenza, seasonal, injectable"},
                "occurrenceDateTime": "2025-10-15",
            }
        },
    ],
})

SAMPLE_CCDA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3">
  <effectiveTime value="20260320103000"/>
  <component>
    <structuredBody>
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.5.1"/>
          <code code="11450-4" codeSystem="2.16.840.1.113883.6.1" displayName="Problem List"/>
          <title>Problems</title>
          <entry>
            <act classCode="ACT" moodCode="EVN">
              <entryRelationship typeCode="SUBJ">
                <observation classCode="OBS" moodCode="EVN">
                  <id root="1.2.3.4" extension="prob-1"/>
                  <code code="55607006" displayName="Problem"/>
                  <effectiveTime><low value="20260115"/></effectiveTime>
                  <value code="44054006" displayName="Type 2 diabetes mellitus"/>
                </observation>
              </entryRelationship>
            </act>
          </entry>
        </section>
      </component>
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.1.1"/>
          <title>Medications</title>
          <entry>
            <substanceAdministration classCode="SBADM" moodCode="EVN">
              <id root="1.2.3.4" extension="med-1"/>
              <effectiveTime value="20260120"/>
              <consumable>
                <manufacturedProduct>
                  <manufacturedMaterial>
                    <code code="860975" displayName="Metformin hydrochloride 500 MG Oral Tablet"/>
                  </manufacturedMaterial>
                </manufacturedProduct>
              </consumable>
            </substanceAdministration>
          </entry>
        </section>
      </component>
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.6.1"/>
          <title>Allergies</title>
          <entry>
            <act classCode="ACT" moodCode="EVN">
              <entryRelationship typeCode="SUBJ">
                <observation classCode="OBS" moodCode="EVN">
                  <id root="1.2.3.4" extension="allergy-1"/>
                  <effectiveTime><low value="20250601"/></effectiveTime>
                  <value code="91936005" displayName="Allergy to penicillin"/>
                </observation>
              </entryRelationship>
            </act>
          </entry>
        </section>
      </component>
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.3.1"/>
          <title>Results</title>
          <entry>
            <organizer classCode="BATTERY" moodCode="EVN">
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <id root="1.2.3.4" extension="lab-ldl-1"/>
                  <code code="13457-7" displayName="Cholesterol in LDL"/>
                  <effectiveTime value="20260318"/>
                  <value value="92" unit="mg/dL"/>
                </observation>
              </component>
            </organizer>
          </entry>
        </section>
      </component>
    </structuredBody>
  </component>
</ClinicalDocument>
"""

SAMPLE_APPLE_HEALTH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!ELEMENT HealthData (Record*)>
]>
<HealthData locale="en_US">
  <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="1200" startDate="2026-03-15 08:15:00 -0500" endDate="2026-03-15 08:30:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="3400" startDate="2026-03-15 12:15:00 -0500" endDate="2026-03-15 12:45:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="2100" startDate="2026-03-15 18:00:00 -0500" endDate="2026-03-15 18:30:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="62" startDate="2026-03-15 07:00:00 -0500" endDate="2026-03-15 07:01:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="78" startDate="2026-03-15 13:00:00 -0500" endDate="2026-03-15 13:01:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="110" startDate="2026-03-15 17:30:00 -0500" endDate="2026-03-15 17:31:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" unit="kcal" value="145.5" startDate="2026-03-15 09:00:00 -0500" endDate="2026-03-15 10:00:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" unit="kcal" value="204.5" startDate="2026-03-15 17:00:00 -0500" endDate="2026-03-15 18:00:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierBloodPressureSystolic" unit="mmHg" value="124" startDate="2026-03-15 09:00:00 -0500" endDate="2026-03-15 09:00:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierBloodPressureDiastolic" unit="mmHg" value="78" startDate="2026-03-15 09:00:00 -0500" endDate="2026-03-15 09:00:00 -0500"/>
  <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg" value="72.4" startDate="2026-03-15 07:30:00 -0500" endDate="2026-03-15 07:30:00 -0500"/>
</HealthData>
"""


@pytest.fixture
async def import_db_env(tmp_path, monkeypatch):
    """Sets up an isolated SQLite DB and CAS home directory for clinical import tests."""
    monkeypatch.setattr(settings, "home_dir", tmp_path)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    user_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    async with factory() as session:
        user = User(
            id=user_id,
            email="patient@example.com",
            username="patient_one",
            hashed_password="hashed_password",
            role="steward",
        )
        profile = Profile(
            id=profile_id,
            user_id=user_id,
            name="Maya Patel",
            relationship="self",
            role="self",
            date_of_birth="1988-11-23",
            is_primary=True,
        )
        session.add_all([user, profile])
        await session.commit()

    yield {
        "engine": engine,
        "factory": factory,
        "user_id": user_id,
        "profile_id": profile_id,
    }
    await engine.dispose()


def test_parse_fhir_bundle_extracts_resources_and_provenance():
    """Verifies FHIR R4 Bundle parser extracts clinical entries, provenance, and untrusted tags."""
    parsed = parse_fhir_bundle(SAMPLE_FHIR_BUNDLE, source_name="City General FHIR")
    assert parsed["format"] == "fhir_r4"
    records = parsed["records"]
    # 5 clinical resources + 1 synthesized Provenance record
    assert len(records) == 6
    types = {r["resource_type"] for r in records}
    assert {
        "Observation",
        "Condition",
        "MedicationStatement",
        "AllergyIntolerance",
        "Immunization",
        "Provenance",
    }.issubset(types)

    for rec in records:
        assert rec["trust"] == "untrusted"
        assert rec["source_display"].startswith("From City General FHIR, ")


def test_parse_ccda_xml_extracts_sections_and_blocks_xxe():
    """Verifies C-CDA parser extracts Problems, Medications, Allergies, Results and blocks XXE."""
    parsed = parse_ccda_xml(SAMPLE_CCDA_XML, source_name="Epic Care Everywhere")
    assert parsed["format"] == "ccda"
    records = parsed["records"]
    assert len(records) == 4
    types = [r["resource_type"] for r in records]
    assert "Condition" in types
    assert "MedicationStatement" in types
    assert "AllergyIntolerance" in types
    assert "Observation" in types
    for rec in records:
        assert rec["trust"] == "untrusted"
        assert "From Epic Care Everywhere," in rec["source_display"]

    xxe_xml = """<?xml version="1.0"?>
    <!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
    <ClinicalDocument>&xxe;</ClinicalDocument>
    """
    with pytest.raises(ValueError, match="XXE"):
        parse_ccda_xml(xxe_xml)


def test_parse_apple_health_aggregates_high_frequency_per_day():
    """Verifies Titan S4 / E8.0: high-frequency wearable samples are aggregated daily, never raw."""
    parsed = parse_apple_health_export(SAMPLE_APPLE_HEALTH_XML, source_name="Apple Watch HealthKit")
    assert parsed["format"] == "apple_health"
    summary = parsed["summary"]
    assert summary["raw_sample_count"] == 11
    assert summary["aggregated_raw_sample_count"] == 8

    records = parsed["records"]
    # Expected: 1 daily steps + 1 daily HR + 1 daily energy + 1 paired BP panel + 1 body weight = 5 records
    assert len(records) == 5

    by_code = {r["code"]: r for r in records}
    # Steps (LOINC 41950-7): 1200 + 3400 + 2100 = 6700 across 3 samples
    steps_rec = by_code["41950-7"]
    assert steps_rec["aggregation"]["sum"] == 6700
    assert steps_rec["aggregation"]["sample_count"] == 3
    assert steps_rec["trust"] == "untrusted"

    # Heart Rate (LOINC 8867-4): min=62, max=110, avg=83.3 across 3 samples
    hr_rec = by_code["8867-4"]
    assert hr_rec["aggregation"]["min"] == 62.0
    assert hr_rec["aggregation"]["max"] == 110.0
    assert hr_rec["aggregation"]["avg"] == 83.3
    assert hr_rec["aggregation"]["sample_count"] == 3

    # Active Energy (LOINC 41979-6): 145.5 + 204.5 = 350.0 kcal across 2 samples
    energy_rec = by_code["41979-6"]
    assert energy_rec["aggregation"]["sum"] == 350.0
    assert energy_rec["aggregation"]["sample_count"] == 2

    # Paired Blood Pressure panel (LOINC 85354-9): 124/78 mmHg
    bp_rec = by_code["85354-9"]
    assert "124/78" in bp_rec["display"]

    # Body Mass (LOINC 29463-7): 72.4 kg
    wt_rec = by_code["29463-7"]
    assert wt_rec["data"]["valueQuantity"]["value"] == 72.4


@pytest.mark.asyncio
async def test_stage_commit_idempotency_and_discard_workflow(import_db_env):
    """Verifies review-before-save staging, idempotent commit, job/audit creation, and discard."""
    factory = import_db_env["factory"]
    profile_id = import_db_env["profile_id"]
    user_id = import_db_env["user_id"]

    async with factory() as session:
        # 1. Stage import: zero HealthResource rows exist prior to commit
        batch = await stage_import(
            session=session,
            profile_id=profile_id,
            filename="visit_bundle.json",
            content=SAMPLE_FHIR_BUNDLE,
            source_name="Mercy Portal",
            user_id=user_id,
        )
        assert batch.status == "staged"
        assert batch.attachment_id is not None

        hr_before = (
            await session.execute(select(HealthResource).where(HealthResource.profile_id == profile_id))
        ).scalars().all()
        assert len(hr_before) == 0

        att_row = (
            await session.execute(select(Attachment).where(Attachment.id == batch.attachment_id))
        ).scalar_one()
        assert att_row.source == "import"

        # 2. Commit staged batch
        commit_res = await commit_import_batch(
            session=session,
            profile_id=profile_id,
            batch_id=batch.id,
            actor_user_id=user_id,
        )
        assert commit_res["status"] == "committed"
        assert commit_res["committed_count"] == 6
        assert commit_res["created_count"] == 6

        hr_after = (
            await session.execute(select(HealthResource).where(HealthResource.profile_id == profile_id))
        ).scalars().all()
        assert len(hr_after) == 6

        # Verify index_doc Job and AuditEventRecord were written
        jobs = (
            await session.execute(select(Job).where(Job.profile_id == profile_id, Job.kind == "index_doc"))
        ).scalars().all()
        assert len(jobs) >= 1

        audits = (
            await session.execute(
                select(AuditEventRecord).where(
                    AuditEventRecord.profile_id == profile_id,
                    AuditEventRecord.tool == "commit_clinical_import",
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].external_ref == f"import_batch:{batch.id}"

        # 3. Re-import identical bundle and commit -> idempotent upsert (no duplicate HealthResources)
        import_set2 = await stage_import(
            session=session,
            profile_id=profile_id,
            filename="visit_bundle.json",
            content=SAMPLE_FHIR_BUNDLE,
            source_name="Mercy Portal",
            user_id=user_id,
        )
        commit_res2 = await commit_import_batch(
            session=session,
            profile_id=profile_id,
            batch_id=import_set2.id,
            actor_user_id=user_id,
        )
        assert commit_res2["updated_count"] == 6
        assert commit_res2["created_count"] == 0

        hr_reimport = (
            await session.execute(select(HealthResource).where(HealthResource.profile_id == profile_id))
        ).scalars().all()
        assert len(hr_reimport) == 6

        # 4. Stage and discard a batch -> status becomes 'discarded', no new HealthResources
        import_set3 = await stage_import(
            session=session,
            profile_id=profile_id,
            filename="summary.xml",
            content=SAMPLE_CCDA_XML,
            user_id=user_id,
        )
        discarded = await discard_import_batch(session, profile_id=profile_id, batch_id=import_set3.id)
        assert discarded is True

        refreshed_b3 = (
            await session.execute(select(ImportBatch).where(ImportBatch.id == import_set3.id))
        ).scalar_one()
        assert refreshed_b3.status == "discarded"


@pytest.mark.asyncio
async def test_import_tools_and_rest_api_endpoints(import_db_env):
    """Verifies tool executors and FastAPI /profiles/{profile_id}/imports/* endpoints."""
    factory = import_db_env["factory"]
    profile_id = import_db_env["profile_id"]
    user_id = import_db_env["user_id"]

    ctx = ToolContext(
        user_id=user_id,
        profile_id=profile_id,
        taint=TaintFlag(False),
        extra={"session_factory": factory},
    )

    staged_out = await execute_stage_clinical_import(
        {
            "filename": "apple_export.xml",
            "content": SAMPLE_APPLE_HEALTH_XML,
            "source_name": "Apple Health",
        },
        ctx=ctx,
    )
    assert staged_out["status"] == "staged"
    assert staged_out["format"] == "apple_health"
    assert bool(ctx.taint) is True

    # Commit only the first 2 records selectively via tool
    commit_out = await execute_commit_clinical_import(
        {
            "batch_id": staged_out["batch_id"],
            "selected_indices": [0, 1],
        },
        ctx=ctx,
    )
    assert commit_out["status"] == "committed"
    assert commit_out["committed_count"] == 2

    # Verify FastAPI endpoints
    app = FastAPI()
    app.include_router(imports_router)

    async def _override_get_db():
        async with factory() as session:
            yield session

    async def _override_user():
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return UserProfile(
            id=user_id,
            email="patient@example.com",
            username="patient_one",
            role="steward",
            status="active",
            created_at=now,
            updated_at=now,
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # POST /stage
        stage_resp = await client.post(
            f"/profiles/{profile_id}/imports/stage",
            json={
                "filename": "ccda_summary.xml",
                "content": SAMPLE_CCDA_XML,
                "source_name": "Clinic C-CDA",
            },
        )
        assert stage_resp.status_code == 201
        staged_batch = stage_resp.json()
        batch_id = staged_batch["id"]
        assert staged_batch["status"] == "staged"
        assert len(staged_batch["staged_records"]) == 4

        # GET /imports
        list_resp = await client.get(f"/profiles/{profile_id}/imports")
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] >= 2

        # GET /imports/{batch_id}
        detail_resp = await client.get(f"/profiles/{profile_id}/imports/{batch_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["id"] == batch_id

        # POST /imports/{batch_id}/commit
        commit_resp = await client.post(
            f"/profiles/{profile_id}/imports/{batch_id}/commit",
            json={"selected_indices": [0, 1, 2]},
        )
        assert commit_resp.status_code == 200
        assert commit_resp.json()["committed_count"] == 3

        # Stage another and DELETE /imports/{batch_id}
        stage2_resp = await client.post(
            f"/profiles/{profile_id}/imports/stage",
            json={
                "filename": "extra_ccda.xml",
                "content": SAMPLE_CCDA_XML,
            },
        )
        b2_id = stage2_resp.json()["id"]
        del_resp = await client.delete(f"/profiles/{profile_id}/imports/{b2_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "discarded"
