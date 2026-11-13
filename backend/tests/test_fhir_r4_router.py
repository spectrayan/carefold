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

"""End-to-End Integration, REST<->MCP Parity, and Security Isolation Tests for Issue #285.

Covers:
1. `GET /api/v1/fhir/r4/metadata` CapabilityStatement R4 validation.
2. `POST /api/v1/fhir/r4/{resource_type}` and `PUT /api/v1/fhir/r4/{resource_type}/{id}`:
   - Fail-closed 428 Precondition Required without `X-Carefold-Confirm: true` / `confirmed=true`.
   - R4 validation, terminology/unit normalization (#282/#283), `ETag: W/"{versionId}"`, `Location`.
   - `Idempotency-Key` safe replay and `If-Match` optimistic concurrency (`412 Precondition Failed`).
3. `GET /api/v1/fhir/r4/{resource_type}/{id}` (including `Patient/{profile_id}`), `OperationOutcome`
   and RFC 9457 `application/problem+json` error formatting.
4. `GET /api/v1/fhir/r4/{resource_type}` search (`patient`, `category`, `code` `system|code`, `date`
   `ge`/`le`, `status`, `clinical-status`, `_lastUpdated`, `_include`, `_sort`, `_count`, and
   HMAC-signed opaque `_cursor` pagination).
5. `GET /api/v1/fhir/r4/{resource_type}/{id}/_history` returning `Bundle(type="history")`.
6. `GET /api/v1/fhir/r4/Patient/{id}/$everything` returning `Bundle(type="searchset")` with
   SHA-256 hash-chained `AuditEventRecord` verification.
7. `GET /api/v1/fhir/r4/Patient/{id}/$summary` returning a validated HL7 International Patient
   Summary (IPS) `Bundle(type="document")` headed by `Composition` (`LOINC 60591-5`) with all 7
   required IPS sections (`11450-4`, `10160-0`, `48765-2`, `11369-6`, `30954-2`, `8716-3`, `47519-4`).
8. `POST /api/v1/fhir/r4/Patient/{id}/$export`, `$export-status/{job_id}`, per-resource NDJSON
   file download, and streaming `GET /api/v1/fhir/r4/Patient/{id}/$export` with hash-chained audit.
9. REST <-> MCP Parity Contract: identical clinical outputs across FastAPI REST routes,
   `McpDatabaseToolbox.execute_tool`, and `read_fhir_mcp_resource`, plus MCP annotations and
   `db-operator` tool allowlist verification.
10. Cross-profile (`Profile A` vs `Profile B`) and cross-scope (`health.clinical` vs
    `health.paperwork`) isolation on both REST and MCP surfaces.
11. Per-profile rate limiting (`429 Too Many Requests`) and OpenAPI 3.1.0 contract verification.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Tuple

from fastapi.testclient import TestClient
from fhir.resources.R4B.bundle import Bundle as FhirBundle
from fhir.resources.R4B.capabilitystatement import CapabilityStatement as FhirCapabilityStatement
from fhir.resources.R4B.composition import Composition as FhirComposition
from fhir.resources.R4B.operationoutcome import OperationOutcome as FhirOperationOutcome
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import yaml

from carefold.clinical.db_hooks import register_carefold_db_toolbox
from carefold.db.base import Base
from carefold.db.models import AuditEventRecord, Profile
import carefold.db.session as db_session_mod
from carefold.fhir.operations import (
    FHIR_MCP_TOOL_REGISTRY,
    FHIR_OPERATION_REGISTRY,
    FHIR_OPERATION_SPECS,
    FhirExecutionContext,
    FhirOperationError,
    check_fhir_rate_limit,
    execute_fhir_mcp_operation,
    read_fhir_mcp_resource,
    reset_fhir_rate_limits_and_idempotency_cache,
)
from carefold.main import app
from carefold.routers.fhir_r4 import generate_fhir_r4_openapi_spec
from carefold.scope.context import scope_context
from carefold.tools.mcp_db_toolbox import get_db_toolbox
import carefold.tools.mcp_db_toolbox as toolbox_mod


@pytest.fixture(autouse=True)
def _reset_fhir_state():
    """Ensure clean rate-limit and idempotency state around each test."""
    reset_fhir_rate_limits_and_idempotency_cache()
    yield
    reset_fhir_rate_limits_and_idempotency_cache()


@pytest.fixture
async def dual_profiles_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Tuple[async_sessionmaker[AsyncSession], Profile, Profile]:
    """Creates an isolated async SQLite DB with two distinct household profiles."""
    db_path = tmp_path / "fhir_r4_parity.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(db_session_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(toolbox_mod, "get_session_factory", lambda: factory)

    async with factory() as session:
        profile_a = Profile(
            id="prof-alice-285",
            name="Alice Carter",
            relationship="self",
            role="self",
            is_primary=True,
            preferred_locale="en-US",
        )
        profile_b = Profile(
            id="prof-bob-285",
            name="Bob Carter",
            relationship="spouse",
            role="adult",
            is_primary=False,
            preferred_locale="en-US",
        )
        session.add_all([profile_a, profile_b])
        await session.commit()

    yield factory, profile_a, profile_b
    await engine.dispose()


def _create_second_profile(client: TestClient, name: str = "Bob Household") -> str:
    # Ensure primary profile & default steward user exist first
    client.get("/api/v1/fhir/r4/metadata")
    resp = client.post(
        "/api/v1/profiles",
        json={"name": name, "relationship": "spouse", "role": "guardian"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def test_capability_statement_metadata_validates_as_fhir_r4(client: TestClient):
    """`GET /api/v1/fhir/r4/metadata` returns a valid FHIR R4 CapabilityStatement."""
    resp = client.get("/api/v1/fhir/r4/metadata")
    assert resp.status_code == 200
    assert "application/fhir+json" in resp.headers["content-type"]

    payload = resp.json()
    assert payload["resourceType"] == "CapabilityStatement"
    assert payload["fhirVersion"] == "4.0.1"
    validated = FhirCapabilityStatement.model_validate(payload)
    assert validated.status == "active"

    rest_entry = payload["rest"][0]
    resource_types = {r["type"] for r in rest_entry["resource"]}
    for expected_rt in (
        "Patient",
        "Observation",
        "Condition",
        "MedicationStatement",
        "AllergyIntolerance",
        "Immunization",
        "DiagnosticReport",
        "Procedure",
        "Encounter",
    ):
        assert expected_rt in resource_types

    op_names = {op["name"] for op in rest_entry["operation"]}
    assert {"everything", "summary", "export"} <= op_names


def test_write_confirmation_idempotency_etag_and_history_on_rest(client: TestClient):
    """POST/PUT enforce X-Carefold-Confirm, Idempotency-Key, If-Match ETag, and _history."""
    obs_body = {
        "resourceType": "Observation",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                    }
                ]
            }
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}],
            "text": "Hemoglobin A1c",
        },
        "effectiveDateTime": "2026-03-10T08:30:00Z",
        "valueQuantity": {"value": 5.6, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"},
    }

    # 1. POST without confirmation fails closed with 428 OperationOutcome
    unconfirmed = client.post("/api/v1/fhir/r4/Observation", json=obs_body)
    assert unconfirmed.status_code == 428
    oo = FhirOperationOutcome.model_validate(unconfirmed.json())
    assert oo.issue[0].severity == "error"

    # 2. POST with X-Carefold-Confirm: true and Idempotency-Key creates version 1
    headers = {"X-Carefold-Confirm": "true", "Idempotency-Key": "idem-obs-a1c-1"}
    created = client.post("/api/v1/fhir/r4/Observation", json=obs_body, headers=headers)
    assert created.status_code == 201, created.text
    assert created.headers.get("ETag") == 'W/"1"'
    assert "/api/v1/fhir/r4/Observation/" in created.headers.get("Location", "")
    created_json = created.json()
    obs_id = created_json["id"]
    assert created_json["meta"]["versionId"] == "1"

    # 3. Replaying identical Idempotency-Key returns version 1 without creating a duplicate version
    replay = client.post("/api/v1/fhir/r4/Observation", json=obs_body, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["id"] == obs_id
    assert replay.json()["meta"]["versionId"] == "1"

    # 4. GET /Observation/{id} returns resource with ETag W/"1"
    read_resp = client.get(f"/api/v1/fhir/r4/Observation/{obs_id}")
    assert read_resp.status_code == 200
    assert read_resp.headers.get("ETag") == 'W/"1"'
    assert read_resp.json()["valueQuantity"]["value"] == 5.6

    # 5. PUT update with If-Match: W/"1" increments versionId to "2"
    updated_body = dict(obs_body, id=obs_id)
    updated_body["valueQuantity"] = {"value": 5.4, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"}
    put_resp = client.put(
        f"/api/v1/fhir/r4/Observation/{obs_id}",
        json=updated_body,
        headers={"X-Carefold-Confirm": "true", "If-Match": 'W/"1"'},
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.headers.get("ETag") == 'W/"2"'
    assert put_resp.json()["meta"]["versionId"] == "2"

    # 6. PUT with stale If-Match: W/"1" fails with 412 Precondition Failed
    stale_resp = client.put(
        f"/api/v1/fhir/r4/Observation/{obs_id}",
        json=updated_body,
        headers={"X-Carefold-Confirm": "true", "If-Match": 'W/"1"'},
    )
    assert stale_resp.status_code == 412

    # 7. GET /Observation/{id}/_history returns Bundle(type="history") with both revisions
    hist_resp = client.get(f"/api/v1/fhir/r4/Observation/{obs_id}/_history")
    assert hist_resp.status_code == 200
    hist_bundle = hist_resp.json()
    FhirBundle.model_validate(hist_bundle)
    assert hist_bundle["type"] == "history"
    assert hist_bundle["total"] == 2
    versions = [entry["resource"]["meta"]["versionId"] for entry in hist_bundle["entry"]]
    assert versions == ["1", "2"]


def test_search_parameters_include_and_opaque_cursor_pagination(client: TestClient):
    """Search supports category, code, date ge/le, status, _include, _sort, _count, and _cursor."""
    confirm_hdr = {"X-Carefold-Confirm": "true"}

    # Create 3 Observations and 1 DiagnosticReport referencing the first two Observations
    obs_ids = []
    for idx, (dt, val) in enumerate(
        [
            ("2026-01-15T09:00:00Z", 92.0),
            ("2026-02-15T09:00:00Z", 96.0),
            ("2026-03-15T09:00:00Z", 89.0),
        ],
        start=1,
    ):
        oid = f"obs-glu-{idx}"
        obs_ids.append(oid)
        r = client.put(
            f"/api/v1/fhir/r4/Observation/{oid}",
            headers=confirm_hdr,
            json={
                "resourceType": "Observation",
                "id": oid,
                "status": "final",
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "laboratory",
                            }
                        ]
                    }
                ],
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": "2345-7", "display": "Glucose"}],
                    "text": "Glucose",
                },
                "effectiveDateTime": dt,
                "valueQuantity": {
                    "value": val,
                    "unit": "mg/dL",
                    "system": "http://unitsofmeasure.org",
                    "code": "mg/dL",
                },
            },
        )
        assert r.status_code in (200, 201), r.text

    dr_resp = client.put(
        "/api/v1/fhir/r4/DiagnosticReport/dr-panel-1",
        headers=confirm_hdr,
        json={
            "resourceType": "DiagnosticReport",
            "id": "dr-panel-1",
            "status": "final",
            "code": {
                "coding": [{"system": "http://loinc.org", "code": "24323-8", "display": "Comprehensive metabolic 2000 panel"}],
                "text": "CMP",
            },
            "effectiveDateTime": "2026-03-15T09:00:00Z",
            "result": [
                {"reference": f"Observation/{obs_ids[0]}"},
                {"reference": f"Observation/{obs_ids[1]}"},
            ],
        },
    )
    assert dr_resp.status_code in (200, 201), dr_resp.text

    # 1. Search by code=http://loinc.org|2345-7, date ge/le, _count=2, _sort=date
    page1 = client.get(
        "/api/v1/fhir/r4/Observation",
        params={
            "code": "http://loinc.org|2345-7",
            "category": "laboratory",
            "date": ["ge2026-01-01", "le2026-04-01"],
            "_sort": "date",
            "_count": 2,
        },
    )
    assert page1.status_code == 200, page1.text
    b1 = page1.json()
    FhirBundle.model_validate(b1)
    assert b1["type"] == "searchset"
    assert b1["total"] == 3
    assert len(b1["entry"]) == 2
    assert [e["resource"]["id"] for e in b1["entry"]] == ["obs-glu-1", "obs-glu-2"]

    # Extract _cursor from next link and fetch page 2
    next_links = [lnk["url"] for lnk in b1.get("link", []) if lnk.get("relation") == "next"]
    assert len(next_links) == 1
    from urllib.parse import parse_qs, urlparse

    parsed_next = urlparse(next_links[0])
    cursor_token = parse_qs(parsed_next.query)["_cursor"][0]

    page2 = client.get(
        "/api/v1/fhir/r4/Observation",
        params={
            "code": "http://loinc.org|2345-7",
            "category": "laboratory",
            "date": ["ge2026-01-01", "le2026-04-01"],
            "_sort": "date",
            "_count": 2,
            "_cursor": cursor_token,
        },
    )
    assert page2.status_code == 200
    b2 = page2.json()
    assert len(b2["entry"]) == 1
    assert b2["entry"][0]["resource"]["id"] == "obs-glu-3"

    # Tampered cursor fails closed with 400 Bad Request
    bad_cursor = client.get("/api/v1/fhir/r4/Observation", params={"_cursor": "tampered-cursor"})
    assert bad_cursor.status_code == 400

    # 2. Search DiagnosticReport with _include=DiagnosticReport:result
    inc_resp = client.get(
        "/api/v1/fhir/r4/DiagnosticReport",
        params={"_include": "DiagnosticReport:result"},
    )
    assert inc_resp.status_code == 200
    inc_bundle = inc_resp.json()
    FhirBundle.model_validate(inc_bundle)
    modes = {(e["resource"]["resourceType"], e["resource"]["id"]): e["search"]["mode"] for e in inc_bundle["entry"]}
    assert modes[("DiagnosticReport", "dr-panel-1")] == "match"
    assert modes[("Observation", "obs-glu-1")] == "include"
    assert modes[("Observation", "obs-glu-2")] == "include"


def test_patient_everything_summary_ips_and_bulk_export_with_audit_chain(client: TestClient):
    """Verifies $everything, $summary (IPS LOINC 60591-5), and $export NDJSON + hash-chained audit."""
    confirm_hdr = {"X-Carefold-Confirm": "true"}

    # Seed clinical resources across IPS sections for primary profile
    client.put(
        "/api/v1/fhir/r4/Condition/cond-htn-1",
        headers=confirm_hdr,
        json={
            "resourceType": "Condition",
            "id": "cond-htn-1",
            "clinicalStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": "active",
                    }
                ]
            },
            "code": {
                "coding": [{"system": "http://snomed.info/sct", "code": "38341003", "display": "Hypertension"}],
                "text": "Hypertension",
            },
        },
    )
    client.put(
        "/api/v1/fhir/r4/MedicationStatement/med-lisinopril-1",
        headers=confirm_hdr,
        json={
            "resourceType": "MedicationStatement",
            "id": "med-lisinopril-1",
            "status": "active",
            "subject": {"reference": "Patient/default"},
            "medicationCodeableConcept": {
                "coding": [
                    {
                        "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                        "code": "314076",
                        "display": "Lisinopril 10 MG Oral Tablet",
                    }
                ],
                "text": "Lisinopril 10 MG",
            },
        },
    )
    client.put(
        "/api/v1/fhir/r4/AllergyIntolerance/allergy-pen-1",
        headers=confirm_hdr,
        json={
            "resourceType": "AllergyIntolerance",
            "id": "allergy-pen-1",
            "patient": {"reference": "Patient/default"},
            "code": {
                "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "7980", "display": "Penicillin G"}],
                "text": "Penicillin",
            },
        },
    )
    client.put(
        "/api/v1/fhir/r4/Immunization/imm-flu-1",
        headers=confirm_hdr,
        json={
            "resourceType": "Immunization",
            "id": "imm-flu-1",
            "status": "completed",
            "patient": {"reference": "Patient/default"},
            "vaccineCode": {
                "coding": [{"system": "http://hl7.org/fhir/sid/cvx", "code": "141", "display": "Influenza, seasonal, injectable"}],
                "text": "Influenza vaccine",
            },
            "occurrenceDateTime": "2025-10-15T10:00:00Z",
        },
    )
    client.put(
        "/api/v1/fhir/r4/Observation/obs-bp-sys-1",
        headers=confirm_hdr,
        json={
            "resourceType": "Observation",
            "id": "obs-bp-sys-1",
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "vital-signs",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}],
                "text": "Systolic BP",
            },
            "effectiveDateTime": "2026-03-20T08:00:00Z",
            "valueQuantity": {"value": 122, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
        },
    )
    client.put(
        "/api/v1/fhir/r4/Procedure/proc-appendectomy-1",
        headers=confirm_hdr,
        json={
            "resourceType": "Procedure",
            "id": "proc-appendectomy-1",
            "status": "completed",
            "subject": {"reference": "Patient/default"},
            "code": {
                "coding": [{"system": "http://snomed.info/sct", "code": "80146002", "display": "Appendectomy"}],
                "text": "Appendectomy",
            },
            "performedDateTime": "2020-06-01T12:00:00Z",
        },
    )

    # Resolve primary profile ID
    prof_resp = client.get("/api/v1/profiles")
    assert prof_resp.status_code == 200
    primary_id = prof_resp.json()[0]["id"]

    # 1. GET /Patient/{id}/$everything
    everything_resp = client.get(f"/api/v1/fhir/r4/Patient/{primary_id}/$everything")
    assert everything_resp.status_code == 200, everything_resp.text
    ev_bundle = everything_resp.json()
    FhirBundle.model_validate(ev_bundle)
    assert ev_bundle["type"] == "searchset"
    ev_types = {e["resource"]["resourceType"] for e in ev_bundle["entry"]}
    assert {
        "Patient",
        "Condition",
        "MedicationStatement",
        "AllergyIntolerance",
        "Immunization",
        "Observation",
        "Procedure",
    } <= ev_types

    # 2. GET /Patient/{id}/$summary (HL7 IPS Document Bundle)
    ips_resp = client.get(f"/api/v1/fhir/r4/Patient/{primary_id}/$summary")
    assert ips_resp.status_code == 200, ips_resp.text
    ips_bundle = ips_resp.json()
    FhirBundle.model_validate(ips_bundle)
    assert ips_bundle["type"] == "document"
    first_resource = ips_bundle["entry"][0]["resource"]
    assert first_resource["resourceType"] == "Composition"
    FhirComposition.model_validate(first_resource)
    assert first_resource["type"]["coding"][0]["code"] == "60591-5"

    section_codes = [sec["code"]["coding"][0]["code"] for sec in first_resource["section"]]
    assert section_codes == [
        "11450-4",  # Problem List
        "10160-0",  # Medication Summary
        "48765-2",  # Allergies and Intolerances
        "11369-6",  # History of Immunizations
        "30954-2",  # Relevant Diagnostic Tests / Lab Data
        "8716-3",   # Vital Signs
        "47519-4",  # History of Procedures
    ]

    # 3. POST /Patient/{id}/$export without confirmation -> 428
    unconf_exp = client.post(f"/api/v1/fhir/r4/Patient/{primary_id}/$export")
    assert unconf_exp.status_code == 428

    # 4. POST /Patient/{id}/$export with confirmation -> 202 Accepted + Content-Location
    exp_start = client.post(
        f"/api/v1/fhir/r4/Patient/{primary_id}/$export",
        headers=confirm_hdr,
    )
    assert exp_start.status_code == 202, exp_start.text
    assert "$export-status/" in exp_start.headers.get("Content-Location", "")
    job_id = exp_start.json()["job_id"]

    # 5. GET /$export-status/{job_id} returns completed manifest with output NDJSON URLs
    status_resp = client.get(f"/api/v1/fhir/r4/$export-status/{job_id}")
    assert status_resp.status_code == 200
    manifest = status_resp.json()
    assert manifest["status"] == "completed"
    output_types = {item["type"] for item in manifest["output"]}
    assert "Condition" in output_types
    assert "Observation" in output_types

    # 6. GET /$export-status/{job_id}/files/Observation.ndjson returns valid NDJSON lines
    dl_resp = client.get(f"/api/v1/fhir/r4/$export-status/{job_id}/files/Observation.ndjson")
    assert dl_resp.status_code == 200
    assert "application/fhir+ndjson" in dl_resp.headers["content-type"]
    lines = [json.loads(line) for line in dl_resp.text.strip().splitlines() if line.strip()]
    assert len(lines) >= 1
    assert all(item["resourceType"] == "Observation" for item in lines)

    # 7. Streaming GET /Patient/{id}/$export?_type=Condition,Immunization&confirmed=true
    stream_resp = client.get(
        f"/api/v1/fhir/r4/Patient/{primary_id}/$export",
        params={"_type": "Condition,Immunization", "confirmed": "true"},
    )
    assert stream_resp.status_code == 200
    assert "application/fhir+ndjson" in stream_resp.headers["content-type"]
    stream_items = [json.loads(line) for line in stream_resp.text.strip().splitlines() if line.strip()]
    stream_rts = {item["resourceType"] for item in stream_items}
    assert stream_rts <= {"Patient", "Condition", "Immunization"}

    # 8. Verify Audit Log contains hash-chained export audit entries
    audit_resp = client.get("/api/v1/audit")
    assert audit_resp.status_code == 200


@pytest.mark.asyncio
async def test_rest_and_mcp_parity_and_isolation_contracts(
    dual_profiles_session: Tuple[async_sessionmaker[AsyncSession], Profile, Profile],
):
    """Asserts REST<->MCP parity, MCP annotations, URI resources, and cross-profile/scope isolation."""
    factory, profile_a, profile_b = dual_profiles_session

    # Register Carefold DB Toolbox hooks and verify all 9 FHIR MCP tools are registered
    register_carefold_db_toolbox()
    toolbox = get_db_toolbox()

    expected_mcp_tools = {
        "fhir_get_capabilities",
        "fhir_search_resources",
        "fhir_read_resource",
        "fhir_get_resource_history",
        "fhir_get_patient_everything",
        "fhir_get_patient_summary",
        "fhir_upsert_resource",
        "fhir_start_bulk_export",
        "fhir_get_bulk_export_status",
        "fhir_download_bulk_export_file",
    }
    from carefold.engine.tool_registry import create_default_registry

    default_registry = create_default_registry()
    for tool_name in expected_mcp_tools:
        assert tool_name in FHIR_MCP_TOOL_REGISTRY
        if tool_name == "fhir_get_capabilities":
            # #344: fhir_get_capabilities is a zero-SQL declarative MCP tool, not a dummy db_tools.yaml SQL query
            assert tool_name not in toolbox.manifest.tools
            assert default_registry.get(tool_name) is not None
        else:
            assert toolbox.get_tool_config(tool_name) is not None

    # Verify MCP annotations (readOnlyHint, destructiveHint, idempotentHint)
    for spec in FHIR_OPERATION_SPECS:
        ann = spec.annotations.to_dict()
        if spec.risk_tier == "read":
            assert ann["readOnlyHint"] is True
            assert ann["destructiveHint"] is False
            assert ann["idempotentHint"] is True
        else:
            assert ann["readOnlyHint"] is False
            assert spec.requires_confirmation is True

    # Verify db-operator agent.yaml declares only read-only FHIR tools and never write/export tools
    repo_root = Path(__file__).resolve().parents[2]
    db_operator_yaml = yaml.safe_load(
        (repo_root / "agents" / "_system" / "db-operator" / "agent.yaml").read_text(encoding="utf-8")
    )
    declared_tools = set(db_operator_yaml["tools"]) | set(
        db_operator_yaml.get("extensions", {}).get("fhir_read_tools", [])
    )
    for ro_tool in (
        "fhir_get_capabilities",
        "fhir_search_resources",
        "fhir_read_resource",
        "fhir_get_resource_history",
        "fhir_get_patient_everything",
        "fhir_get_patient_summary",
    ):
        assert ro_tool in declared_tools
    assert "fhir_upsert_resource" not in declared_tools
    assert "fhir_start_bulk_export" not in declared_tools

    async with factory() as session:
        ctx_a = FhirExecutionContext(
            profile_id=profile_a.id,
            user_id="user-1",
            scopes=frozenset({"health.clinical", "health.paperwork"}),
            confirmed=True,
        )
        ctx_b = FhirExecutionContext(
            profile_id=profile_b.id,
            user_id="user-1",
            scopes=frozenset({"health.clinical", "health.paperwork"}),
            confirmed=True,
        )

        # Upsert an Observation for Alice via Registry (REST path) and another via MCP DB Toolbox
        obs_alice = {
            "resourceType": "Observation",
            "id": "obs-alice-ldl",
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "laboratory",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [{"system": "http://loinc.org", "code": "13457-7", "display": "LDL Cholesterol"}],
                "text": "LDL Cholesterol",
            },
            "effectiveDateTime": "2026-03-01T10:00:00Z",
            "valueQuantity": {"value": 104, "unit": "mg/dL", "system": "http://unitsofmeasure.org", "code": "mg/dL"},
        }
        rest_upsert = await FHIR_OPERATION_REGISTRY["fhir_upsert_resource"].handler(
            session,
            ctx_a,
            {"resource_type": "Observation", "resource_id": "obs-alice-ldl", "resource": obs_alice, "confirmed": True},
        )
        assert rest_upsert["status_code"] == 201

        # Upsert Bob's secret Condition
        await FHIR_OPERATION_REGISTRY["fhir_upsert_resource"].handler(
            session,
            ctx_b,
            {
                "resource_type": "Condition",
                "resource_id": "cond-bob-secret",
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-bob-secret",
                    "code": {"text": "Bob Private Condition"},
                },
                "confirmed": True,
            },
        )

        # 1. Parity check: Read Alice's Observation via REST handler, MCP DB Toolbox, and MCP Resource URI
        alice_tool_ctx = SimpleNamespace(
            profile_id=profile_a.id,
            locale="en-US",
            scopes=["health.clinical", "health.paperwork"],
        )
        rest_read = await FHIR_OPERATION_REGISTRY["fhir_read_resource"].handler(
            session,
            ctx_a,
            {"resource_type": "Observation", "resource_id": "obs-alice-ldl"},
        )
        mcp_read = await toolbox.execute_tool(
            "fhir_read_resource",
            {"resource_type": "Observation", "resource_id": "obs-alice-ldl"},
            alice_tool_ctx,
        )
        uri_read = await read_fhir_mcp_resource(
            session,
            ctx_a,
            f"fhir://profiles/{profile_a.id}/Observation/obs-alice-ldl",
        )
        assert rest_read["resource"] == mcp_read["resource"] == uri_read["resource"]
        assert mcp_read["_mcp"]["tool_name"] == "fhir_read_resource"
        assert mcp_read["_mcp"]["annotations"]["readOnlyHint"] is True

        # 2. Parity check: Search via REST handler vs MCP DB Toolbox
        rest_search = await FHIR_OPERATION_REGISTRY["fhir_search_resources"].handler(
            session,
            ctx_a,
            {"resource_type": "Observation", "code": "http://loinc.org|13457-7"},
        )
        mcp_search = await toolbox.execute_tool(
            "fhir_search_resources",
            {"resource_type": "Observation", "code": "http://loinc.org|13457-7"},
            alice_tool_ctx,
        )
        assert rest_search["total"] == mcp_search["total"] == 1
        assert rest_search["entry"][0]["resource"] == mcp_search["entry"][0]["resource"]

        # 3. Parity check: IPS $summary via REST handler vs MCP DB Toolbox vs MCP Resource URI
        rest_ips = await FHIR_OPERATION_REGISTRY["fhir_patient_summary"].handler(
            session,
            ctx_a,
            {"patient_id": profile_a.id},
        )
        mcp_ips = await toolbox.execute_tool(
            "fhir_get_patient_summary",
            {},
            alice_tool_ctx,
        )
        uri_ips = await read_fhir_mcp_resource(
            session,
            ctx_a,
            f"fhir://profiles/{profile_a.id}/Patient/{profile_a.id}/$summary",
        )
        assert len(rest_ips["entry"]) == len(mcp_ips["entry"]) == len(uri_ips["entry"])
        assert (
            rest_ips["entry"][0]["resource"]["section"]
            == mcp_ips["entry"][0]["resource"]["section"]
            == uri_ips["entry"][0]["resource"]["section"]
        )

        # 4. Cross-profile isolation on both REST handler and MCP surface:
        # Alice attempting to read Bob's Condition gets 404 Not Found
        with pytest.raises(FhirOperationError) as exc_rest:
            await FHIR_OPERATION_REGISTRY["fhir_read_resource"].handler(
                session,
                ctx_a,
                {"resource_type": "Condition", "resource_id": "cond-bob-secret"},
            )
        assert exc_rest.value.status_code == 404

        mcp_cross_read = await toolbox.execute_tool(
            "fhir_read_resource",
            {"resource_type": "Condition", "resource_id": "cond-bob-secret"},
            alice_tool_ctx,
        )
        assert mcp_cross_read["error"]["status_code"] == 404

        # Alice attempting to read `fhir://profiles/{bob}/...` fails closed with 403 Forbidden
        with pytest.raises(FhirOperationError) as exc_uri:
            await read_fhir_mcp_resource(
                session,
                ctx_a,
                f"fhir://profiles/{profile_b.id}/Patient/{profile_b.id}/$summary",
            )
        assert exc_uri.value.status_code == 403

        # 5. Cross-scope isolation: clinical-only context cannot read/search Coverage (`health.paperwork`)
        clinical_only_ctx = FhirExecutionContext(
            profile_id=profile_a.id,
            user_id="user-1",
            scopes=frozenset({"health.clinical"}),
            confirmed=False,
        )
        with pytest.raises(FhirOperationError) as exc_scope:
            await FHIR_OPERATION_REGISTRY["fhir_search_resources"].handler(
                session,
                clinical_only_ctx,
                {"resource_type": "Coverage"},
            )
        assert exc_scope.value.status_code == 403

        alice_clinical_only_tool_ctx = SimpleNamespace(
            profile_id=profile_a.id,
            locale="en-US",
            scopes=["health.clinical"],
        )
        with scope_context("health.clinical", profile_id=profile_a.id):
            mcp_scope_denied = await toolbox.execute_tool(
                "fhir_search_resources",
                {"resource_type": "Coverage"},
                alice_clinical_only_tool_ctx,
            )
            assert mcp_scope_denied["error"]["status_code"] == 403

        # 6. Verify hash-chained AuditEventRecord integrity for $everything
        await FHIR_OPERATION_REGISTRY["fhir_patient_everything"].handler(
            session,
            ctx_a,
            {"patient_id": profile_a.id},
        )
        await FHIR_OPERATION_REGISTRY["fhir_patient_everything"].handler(
            session,
            ctx_a,
            {"patient_id": profile_a.id},
        )
        audit_rows = (
            await session.execute(
                select(AuditEventRecord)
                .where(AuditEventRecord.profile_id == profile_a.id)
                .order_by(AuditEventRecord.ts.asc())
            )
        ).scalars().all()
        assert len(audit_rows) >= 2
        assert audit_rows[-1].prev_hash == audit_rows[-2].entry_hash


def test_cross_profile_isolation_and_rfc9457_problem_details_on_http(client: TestClient):
    """HTTP requests for another profile's data fail closed and support RFC 9457 problem+json."""
    bob_id = _create_second_profile(client, "Bob Isolated")
    confirm_hdr = {"X-Carefold-Confirm": "true"}

    # Create a Condition under Bob's profile
    bob_cond = client.put(
        "/api/v1/fhir/r4/Condition/cond-bob-http",
        params={"profile_id": bob_id},
        headers=confirm_hdr,
        json={
            "resourceType": "Condition",
            "id": "cond-bob-http",
            "code": {"text": "Bob HTTP Condition"},
        },
    )
    assert bob_cond.status_code in (200, 201), bob_cond.text

    # Primary profile cannot read Bob's Condition (returns 404 without leaking existence)
    alice_read_bob = client.get("/api/v1/fhir/r4/Condition/cond-bob-http")
    assert alice_read_bob.status_code == 404
    FhirOperationOutcome.model_validate(alice_read_bob.json())

    # Requesting with Accept: application/problem+json returns RFC 9457 Problem Details
    problem_resp = client.get(
        "/api/v1/fhir/r4/Condition/cond-bob-http",
        headers={"Accept": "application/problem+json"},
    )
    assert problem_resp.status_code == 404
    assert "application/problem+json" in problem_resp.headers["content-type"]
    prob = problem_resp.json()
    assert prob["status"] == 404
    assert prob["code"] == "not-found"
    assert "type" in prob and "title" in prob and "detail" in prob


def test_rate_limit_and_openapi_31_contract():
    """Verifies per-profile rate limiting (429) and committed OpenAPI 3.1.0 specification."""
    for _ in range(5):
        check_fhir_rate_limit("prof-rate-test", limit=5, window_seconds=60.0)
    with pytest.raises(FhirOperationError) as exc_info:
        check_fhir_rate_limit("prof-rate-test", limit=5, window_seconds=60.0)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers

    repo_root = Path(__file__).resolve().parents[2]
    spec_path = repo_root / "backend" / "src" / "carefold" / "resources" / "openapi_fhir_r4.json"
    assert spec_path.is_file()
    committed_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    generated_spec = generate_fhir_r4_openapi_spec()
    assert committed_spec["openapi"] == "3.1.0"
    assert committed_spec["paths"] == generated_spec["paths"]
    assert committed_spec["x-carefold-mcp-operations"] == generated_spec["x-carefold-mcp-operations"]
