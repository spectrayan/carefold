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

"""Comprehensive tests for clinical terminology normalization, curated Pint unit conversion, and conservative cross-portal deduplication (#283)."""

from __future__ import annotations

import json
import math
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yarvelle_core.config import settings
from yarvelle_core.db.base import Base
from yarvelle_core.db.models import Profile, User
from carefold.fhir.dedup import (
    compute_clinical_dedup_fingerprint,
    evaluate_staged_records_dedup_preview,
    find_dedup_matches_in_repository,
    merge_fhir_resource_payloads,
    reverse_dedup_merge,
)
from carefold.fhir.repository import (
    get_outbound_references,
    get_resource_version_history,
    search_resources_by_coding,
    upsert_fhir_resource_with_history,
)
from carefold.fhir.terminology import (
    CURATED_CLINICAL_CODES,
    ORIGINAL_QUANTITY_EXTENSION_URL,
    convert_curated_ucum_quantity,
    extract_original_quantity_from_extension,
    get_curated_concept_group,
    normalize_code_system_uri,
    normalize_fhir_terminology_and_units,
)
from carefold.importers import (
    commit_import_batch,
    parse_apple_health_export,
    parse_ccda_xml,
    parse_fhir_bundle,
    stage_import,
)
from carefold.models import (
    HealthResource,
    HealthResourceCoding,
    HealthResourceReference,
    HealthResourceVersion,
)
from carefold.scope.context import ScopeViolationError, scope_context


@pytest.fixture
async def dedup_db_env(tmp_path, monkeypatch):
    """Creates an isolated in-memory SQLite database with two profiles for terminology and deduplication tests."""
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
            email="steward@example.com",
            username="steward_283",
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
            role="dependent",
            date_of_birth="1986-04-12",
            is_primary=False,
        )
        session.add_all([user, profile_a, profile_b])
        await session.commit()

    yield {
        "engine": engine,
        "factory": factory,
        "user_id": user_id,
        "profile_a_id": profile_a_id,
        "profile_b_id": profile_b_id,
    }
    await engine.dispose()


# =============================================================================
# 1. Clinical Terminology CodeSystem URI & Curated Code Normalization Tests
# =============================================================================


@pytest.mark.parametrize(
    ("raw_system", "expected_canonical", "expected_changed"),
    [
        # LOINC
        ("http://loinc.org", "http://loinc.org", False),
        ("https://loinc.org/", "http://loinc.org", True),
        ("urn:oid:2.16.840.1.113883.6.1", "http://loinc.org", True),
        ("2.16.840.1.113883.6.1", "http://loinc.org", True),
        ("LOINC", "http://loinc.org", True),
        # SNOMED CT
        ("http://snomed.info/sct", "http://snomed.info/sct", False),
        ("https://snomed.info/sct", "http://snomed.info/sct", True),
        ("urn:oid:2.16.840.1.113883.6.96", "http://snomed.info/sct", True),
        ("2.16.840.1.113883.6.96", "http://snomed.info/sct", True),
        ("SNOMED-CT", "http://snomed.info/sct", True),
        ("SCT", "http://snomed.info/sct", True),
        # RxNorm
        ("http://www.nlm.nih.gov/research/umls/rxnorm", "http://www.nlm.nih.gov/research/umls/rxnorm", False),
        ("urn:oid:2.16.840.1.113883.6.88", "http://www.nlm.nih.gov/research/umls/rxnorm", True),
        ("2.16.840.1.113883.6.88", "http://www.nlm.nih.gov/research/umls/rxnorm", True),
        ("RxNorm", "http://www.nlm.nih.gov/research/umls/rxnorm", True),
        # ICD-10-CM & ICD-10
        ("http://hl7.org/fhir/sid/icd-10-cm", "http://hl7.org/fhir/sid/icd-10-cm", False),
        ("urn:oid:2.16.840.1.113883.6.90", "http://hl7.org/fhir/sid/icd-10-cm", True),
        ("2.16.840.1.113883.6.90", "http://hl7.org/fhir/sid/icd-10-cm", True),
        ("ICD-10-CM", "http://hl7.org/fhir/sid/icd-10-cm", True),
        ("ICD10CM", "http://hl7.org/fhir/sid/icd-10-cm", True),
        ("urn:oid:2.16.840.1.113883.6.3", "http://hl7.org/fhir/sid/icd-10", True),
        # CVX
        ("http://hl7.org/fhir/sid/cvx", "http://hl7.org/fhir/sid/cvx", False),
        ("urn:oid:2.16.840.1.113883.12.292", "http://hl7.org/fhir/sid/cvx", True),
        ("2.16.840.1.113883.12.292", "http://hl7.org/fhir/sid/cvx", True),
        ("CVX", "http://hl7.org/fhir/sid/cvx", True),
        # UCUM, CPT, HCPCS, NDC, UNII, v3-ActCode
        ("urn:oid:2.16.840.1.113883.6.8", "http://unitsofmeasure.org", True),
        ("UCUM", "http://unitsofmeasure.org", True),
        ("urn:oid:2.16.840.1.113883.6.12", "http://www.ama-assn.org/go/cpt", True),
        ("CPT", "http://www.ama-assn.org/go/cpt", True),
        ("urn:oid:2.16.840.1.113883.6.285", "https://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets", True),
        ("urn:oid:2.16.840.1.113883.6.69", "http://hl7.org/fhir/sid/ndc", True),
        ("urn:oid:2.16.840.1.113883.4.9", "http://fdasis.nlm.nih.gov", True),
        ("urn:oid:2.16.840.1.113883.5.4", "http://terminology.hl7.org/CodeSystem/v3-ActCode", True),
    ],
)
def test_normalize_code_system_uri_canonical_mappings(
    raw_system: str,
    expected_canonical: str,
    expected_changed: bool,
):
    """Verifies OIDs, short names, and HTTPS variants normalize to canonical FHIR R4 CodeSystem URIs."""
    outcome = normalize_code_system_uri(raw_system)
    assert outcome.canonical_system == expected_canonical
    assert outcome.was_normalized is expected_changed
    assert outcome.is_known_system is True


def test_unknown_code_systems_and_codes_are_preserved_and_flagged_without_guessing():
    """Verifies unknown CodeSystems or codes are never silently guessed and emit PHI-safe diagnostics."""
    unknown_oid = normalize_code_system_uri("urn:oid:1.2.840.999999.1")
    assert unknown_oid.canonical_system == "urn:oid:1.2.840.999999.1"
    assert unknown_oid.was_normalized is False
    assert unknown_oid.is_known_system is False

    obs = {
        "resourceType": "Observation",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://hospital.example.org/local-lab-codes",
                    "code": "LOCAL-GLU-99",
                    "display": "Hospital Local Glucose",
                },
                {
                    "system": "http://loinc.org",
                    "code": "99999-1",
                    "display": "Uncurated LOINC Test",
                },
            ],
            "text": "Hospital Local Glucose",
        },
        "effectiveDateTime": "2026-03-15T10:00:00Z",
    }
    res = normalize_fhir_terminology_and_units(obs, rtype="Observation")
    codings = res.normalized["code"]["coding"]
    assert codings[0]["system"] == "http://hospital.example.org/local-lab-codes"
    assert codings[0]["code"] == "LOCAL-GLU-99"
    assert codings[1]["system"] == "http://loinc.org"
    assert codings[1]["code"] == "99999-1"

    diag_codes = {d.code for d in res.diagnostics}
    assert "unknown_or_unmapped_code_system" in diag_codes
    assert "unrecognized_curated_code" in diag_codes
    assert res.has_unknown_codes is True


def test_curated_display_enrichment_preserves_existing_display():
    """Verifies curated codes enrich missing display names without overwriting existing portal display labels."""
    assert ("http://loinc.org", "4548-4") in CURATED_CLINICAL_CODES
    assert ("http://snomed.info/sct", "44054006") in CURATED_CLINICAL_CODES
    assert ("http://www.nlm.nih.gov/research/umls/rxnorm", "860975") in CURATED_CLINICAL_CODES
    assert ("http://hl7.org/fhir/sid/icd-10-cm", "I10") in CURATED_CLINICAL_CODES
    assert ("http://hl7.org/fhir/sid/cvx", "208") in CURATED_CLINICAL_CODES

    cond = {
        "resourceType": "Condition",
        "code": {
            "coding": [
                {"system": "urn:oid:2.16.840.1.113883.6.96", "code": "44054006"},
                {"system": "ICD-10-CM", "code": "E11.9", "display": "Custom Portal T2DM Label"},
            ]
        },
    }
    res = normalize_fhir_terminology_and_units(cond, rtype="Condition")
    c0, c1 = res.normalized["code"]["coding"]
    assert c0["system"] == "http://snomed.info/sct"
    assert c0["display"] == "Type 2 diabetes mellitus"
    assert c1["system"] == "http://hl7.org/fhir/sid/icd-10-cm"
    assert c1["display"] == "Custom Portal T2DM Label"


# =============================================================================
# 2. Curated Pint Unit Conversion & Original Quantity Preservation Tests
# =============================================================================


def test_curated_pint_unit_conversions_and_roundtrip_extension():
    """Verifies Pint conversions across weight, height, temperature, and analyte-aware molar labs."""
    # 1. Body weight: [lb_av] -> kg (154.3236 lb -> 70.0 kg)
    wt_conv = convert_curated_ucum_quantity(154.3236, "[lb_av]", loinc_code="29463-7")
    assert wt_conv.converted is True
    assert wt_conv.flagged is False
    assert wt_conv.code == "kg"
    assert wt_conv.value == pytest.approx(70.0, abs=1e-2)

    # 2. Body weight: ounces [oz_av] -> kg (35.274 oz -> 1.0 kg)
    oz_conv = convert_curated_ucum_quantity(35.27396, "[oz_av]", loinc_code="29463-7")
    assert oz_conv.converted is True
    assert oz_conv.code == "kg"
    assert oz_conv.value == pytest.approx(1.0, abs=1e-2)

    # 3. Body temperature: [degF] -> Cel (98.6 °F -> 37.0 °C, 100.4 °F -> 38.0 °C)
    temp_conv = convert_curated_ucum_quantity(98.6, "[degF]", loinc_code="8310-5")
    assert temp_conv.converted is True
    assert temp_conv.code == "Cel"
    assert temp_conv.value == pytest.approx(37.0, abs=1e-2)

    fever_conv = convert_curated_ucum_quantity(100.4, "°F", loinc_code="8310-5")
    assert fever_conv.converted is True
    assert fever_conv.code == "Cel"
    assert fever_conv.value == pytest.approx(38.0, abs=1e-2)

    # 4. Body height: [in_i] -> cm (70 in -> 177.8 cm) and [ft_i] -> cm (6 ft -> 182.88 cm)
    ht_conv = convert_curated_ucum_quantity(70.0, "[in_i]", loinc_code="8302-2")
    assert ht_conv.converted is True
    assert ht_conv.code == "cm"
    assert ht_conv.value == pytest.approx(177.8, abs=1e-2)

    ft_conv = convert_curated_ucum_quantity(6.0, "[ft_i]", loinc_code="8302-2")
    assert ft_conv.converted is True
    assert ft_conv.code == "cm"
    assert ft_conv.value == pytest.approx(182.88, abs=1e-2)

    # 5. Analyte-aware glucose: mmol/L -> mg/dL (5.5 mmol/L -> ~99.09 mg/dL)
    glu_conv = convert_curated_ucum_quantity(5.5, "mmol/L", loinc_code="2339-0")
    assert glu_conv.converted is True
    assert glu_conv.code == "mg/dL"
    assert glu_conv.value == pytest.approx(99.09, abs=1e-2)

    # 6. Analyte-aware cholesterol: mmol/L -> mg/dL (5.0 mmol/L -> ~193.33 mg/dL)
    chol_conv = convert_curated_ucum_quantity(5.0, "mmol/L", loinc_code="2093-3")
    assert chol_conv.converted is True
    assert chol_conv.code == "mg/dL"
    assert chol_conv.value == pytest.approx(193.33, abs=1e-2)

    # 7. Analyte-aware creatinine: umol/L -> mg/dL (88.4 umol/L -> ~1.0 mg/dL)
    creat_conv = convert_curated_ucum_quantity(88.4, "umol/L", loinc_code="2160-0")
    assert creat_conv.converted is True
    assert creat_conv.code == "mg/dL"
    assert creat_conv.value == pytest.approx(1.0, abs=1e-2)

    # 8. Observation normalization preserves original value/unit in iso21090-PQ-translation extension
    obs_lb = {
        "resourceType": "Observation",
        "status": "final",
        "code": {
            "coding": [{"system": "urn:oid:2.16.840.1.113883.6.1", "code": "29463-7", "display": "Body weight"}]
        },
        "effectiveDateTime": "2026-03-15T08:30:00Z",
        "valueQuantity": {
            "value": 154.3236,
            "unit": "lbs",
            "system": "http://unitsofmeasure.org",
            "code": "[lb_av]",
        },
    }
    norm_res = normalize_fhir_terminology_and_units(obs_lb, rtype="Observation")
    vq = norm_res.normalized["valueQuantity"]
    assert vq["value"] == pytest.approx(70.0, abs=1e-2)
    assert vq["unit"] == "kg"
    assert vq["code"] == "kg"
    assert vq["system"] == "http://unitsofmeasure.org"

    ext_orig = extract_original_quantity_from_extension(vq)
    assert ext_orig is not None
    assert ext_orig["value"] == pytest.approx(154.3236)
    assert ext_orig["unit"] == "lbs"
    assert ext_orig["code"] == "[lb_av]"
    assert vq["extension"][0]["url"] == ORIGINAL_QUANTITY_EXTENSION_URL


def test_unit_conversion_edge_cases_unknown_and_incompatible_units():
    """Verifies unknown, analyte-ambiguous, or dimensionally incompatible units are kept as-is and flagged."""
    # 1. mmol/L on an analyte that stays in mmol/L (Sodium 2951-2) -> canonical_unit is mmol/L, not converted to mg/dL
    na_conv = convert_curated_ucum_quantity(140.0, "mmol/L", loinc_code="2951-2")
    assert na_conv.converted is False
    assert na_conv.flagged is False
    assert na_conv.code == "mmol/L"
    assert na_conv.value == 140.0

    # 2. mmol/L with to_unit="mg/dL" but no known analyte molar mass -> refused with diagnostic
    ambig_conv = convert_curated_ucum_quantity(5.0, "mmol/L", loinc_code="99999-9", to_unit="mg/dL")
    assert ambig_conv.converted is False
    assert ambig_conv.flagged is True
    assert ambig_conv.diagnostic is not None
    assert ambig_conv.diagnostic.code == "unconvertible_molar_mass_without_analyte"

    # 3. Unknown unit string -> preserved verbatim and flagged with unknown_or_unmapped_unit
    unk_conv = convert_curated_ucum_quantity(42.0, "custom_home_units", loinc_code="29463-7")
    assert unk_conv.converted is False
    assert unk_conv.flagged is True
    assert unk_conv.value == 42.0
    assert unk_conv.unit == "custom_home_units"
    assert unk_conv.diagnostic is not None
    assert unk_conv.diagnostic.code == "unknown_or_unmapped_unit"

    # 4. Dimensionally incompatible curated unit (e.g. temperature degF on a Body Weight LOINC 29463-7 expecting kg)
    dim_conv = convert_curated_ucum_quantity(98.6, "[degF]", loinc_code="29463-7")
    assert dim_conv.converted is False
    assert dim_conv.flagged is True
    assert dim_conv.value == 98.6
    assert dim_conv.diagnostic is not None
    assert dim_conv.diagnostic.code == "incompatible_unit_dimensions"

    # 5. Non-finite float (NaN / Inf) -> rejected cleanly with non_finite_quantity_value diagnostic
    nan_conv = convert_curated_ucum_quantity(math.nan, "kg", loinc_code="29463-7")
    assert nan_conv.converted is False
    assert nan_conv.flagged is True
    assert nan_conv.diagnostic is not None
    assert nan_conv.diagnostic.code == "non_finite_quantity_value"


# =============================================================================
# 3. Cross-Portal Deduplication True Positives & Provenance Merging Tests
# =============================================================================


@pytest.mark.asyncio
async def test_cross_portal_dedup_merges_ccda_fhir_and_apple_health_weight(dedup_db_env):
    """Verifies identical body weight across C-CDA (lbs), FHIR Bundle (kg), and Apple Health (lb) deduplicates into 1 row."""
    factory = dedup_db_env["factory"]
    profile_id = dedup_db_env["profile_a_id"]
    user_id = dedup_db_env["user_id"]

    # Portal 1: C-CDA XML with weight in [lb_av] and LOINC OID 2.16.840.1.113883.6.1 at 2026-03-15T08:30:00Z
    ccda_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <ClinicalDocument xmlns="urn:hl7-org:v3">
      <effectiveTime value="20260315083000"/>
      <component>
        <structuredBody>
          <component>
            <section>
              <templateId root="2.16.840.1.113883.10.20.22.2.4.1"/>
              <title>Vital Signs</title>
              <entry>
                <organizer classCode="CLUSTER" moodCode="EVN">
                  <component>
                    <observation classCode="OBS" moodCode="EVN">
                      <id root="1.2.3.4" extension="vitals-wt-ccda"/>
                      <code code="29463-7" codeSystem="2.16.840.1.113883.6.1" displayName="Body weight"/>
                      <effectiveTime value="20260315083000"/>
                      <value value="154.3236" unit="[lb_av]"/>
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

    # Portal 2: FHIR R4 Bundle with weight in kg (70.0 kg) at 2026-03-15T08:30:00+00:00
    fhir_bundle = json.dumps({
        "resourceType": "Bundle",
        "id": "bundle-portal-2",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "epic-wt-1",
                    "status": "final",
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "29463-7",
                                "display": "Body weight",
                            }
                        ],
                        "text": "Body weight",
                    },
                    "effectiveDateTime": "2026-03-15T08:30:00+00:00",
                    "valueQuantity": {
                        "value": 70.0,
                        "unit": "kg",
                        "system": "http://unitsofmeasure.org",
                        "code": "kg",
                    },
                }
            }
        ],
    })

    # Portal 3: Apple Health export with HKQuantityTypeIdentifierBodyMass in lb at 2026-03-15 08:30:00 +0000
    apple_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <HealthData locale="en_US">
      <Record type="HKQuantityTypeIdentifierBodyMass" unit="lb" value="154.3236" startDate="2026-03-15 08:30:00 +0000" endDate="2026-03-15 08:30:00 +0000"/>
    </HealthData>
    """

    async with factory() as session:
        # 1. Stage and commit C-CDA from Portal 1
        b1 = await stage_import(
            session,
            profile_id=profile_id,
            filename="portal1_ccda.xml",
            content=ccda_xml,
            source_name="Mercy C-CDA Portal",
            user_id=user_id,
        )
        c1 = await commit_import_batch(session, profile_id=profile_id, batch_id=b1.id, actor_user_id=user_id)
        assert c1["created_count"] == 1
        assert c1["merged_count"] == 0

        # 2. Stage FHIR Bundle from Portal 2 -> check dedup_preview before commit
        b2 = await stage_import(
            session,
            profile_id=profile_id,
            filename="portal2_fhir.json",
            content=fhir_bundle,
            source_name="City General FHIR",
            user_id=user_id,
        )
        b2_summary = json.loads(b2.summary_json)
        assert b2_summary["dedup_preview"]["exact_duplicate_count"] == 1

        c2 = await commit_import_batch(session, profile_id=profile_id, batch_id=b2.id, actor_user_id=user_id)
        assert c2["merged_count"] == 1

        # 3. Stage and commit Apple Health from Portal 3
        b3 = await stage_import(
            session,
            profile_id=profile_id,
            filename="apple_export.xml",
            content=apple_xml,
            source_name="Apple HealthKit",
            user_id=user_id,
        )
        c3 = await commit_import_batch(session, profile_id=profile_id, batch_id=b3.id, actor_user_id=user_id)
        assert c3["merged_count"] == 1

        # Verify only ONE Observation HealthResource row exists for LOINC 29463-7!
        obs_rows = await search_resources_by_coding(
            session,
            profile_id=profile_id,
            system="2.16.840.1.113883.6.1",  # OID query also normalizes to http://loinc.org
            code="29463-7",
        )
        assert len(obs_rows) == 1
        merged_hr = obs_rows[0]

        payload = merged_hr.data
        assert payload["meta"]["versionId"] == "3"
        assert payload["meta"]["trust"] == "untrusted"
        prov = payload["_carefold_provenance"]
        assert prov["trust"] == "untrusted"
        assert prov["dedup"]["merge_count"] == 2
        assert "Mercy C-CDA Portal" in prov["sources"]
        assert "City General FHIR" in prov["sources"]
        assert "Apple HealthKit" in prov["sources"]
        assert len(prov["merged_sources"]) == 2

        # Original quantity extension from the first lb conversion is preserved
        orig_q = extract_original_quantity_from_extension(payload["valueQuantity"])
        assert orig_q is not None
        assert orig_q["value"] == pytest.approx(154.3236)
        assert orig_q["unit"] == "[lb_av]"

        # Version history has 1 create + 2 merge versions
        versions = await get_resource_version_history(session, profile_id=profile_id, resource_id=merged_hr.id)
        assert [v.operation for v in versions] == ["create", "merge", "merge"]


@pytest.mark.asyncio
async def test_cross_portal_dedup_immunization_condition_medication_and_identifier(dedup_db_env):
    """Verifies conservative deduplication across Immunization, Condition, Medication, and business identifiers."""
    factory = dedup_db_env["factory"]
    profile_id = dedup_db_env["profile_a_id"]

    async with factory() as session:
        # 1. Condition: C-CDA SNOMED OID vs FHIR SNOMED URI on same onset date
        cond_ccda = {
            "resourceType": "Condition",
            "code": {
                "coding": [
                    {
                        "system": "urn:oid:2.16.840.1.113883.6.96",
                        "code": "44054006",
                        "display": "Type 2 diabetes mellitus",
                    }
                ]
            },
            "onsetDateTime": "2026-01-15T00:00:00+00:00",
            "_carefold_provenance": {"source_name": "Portal A", "trust": "untrusted"},
        }
        cond_fhir = {
            "resourceType": "Condition",
            "code": {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "44054006",
                        "display": "Type 2 diabetes mellitus",
                    },
                    {
                        "system": "http://hl7.org/fhir/sid/icd-10-cm",
                        "code": "E11.9",
                        "display": "Type 2 diabetes mellitus without complications",
                    },
                ]
            },
            "onsetDateTime": "2026-01-15",
            "_carefold_provenance": {"source_name": "Portal B", "trust": "untrusted"},
        }
        hr_c1, _, _ = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Condition",
            fhir_data=cond_ccda,
            source_id="ccda:cond:1",
            source_ref="batch-a",
        )
        hr_c2, v_c2, created_c2 = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Condition",
            fhir_data=cond_fhir,
            source_id="fhir:cond:2",
            source_ref="batch-b",
        )
        assert created_c2 is False
        assert hr_c2.id == hr_c1.id
        assert v_c2.operation == "merge"

        # Verify both SNOMED and ICD-10-CM codings are now indexed on the merged Condition!
        icd_matches = await search_resources_by_coding(
            session,
            profile_id=profile_id,
            system="ICD-10-CM",
            code="E11.9",
        )
        assert len(icd_matches) == 1
        assert icd_matches[0].id == hr_c1.id

        # 2. Immunization: CVX OID vs CVX URI on same occurrenceDateTime
        imm_1 = {
            "resourceType": "Immunization",
            "status": "completed",
            "vaccineCode": {
                "coding": [{"system": "2.16.840.1.113883.12.292", "code": "208"}]
            },
            "occurrenceDateTime": "2025-10-15T00:00:00Z",
            "_carefold_provenance": {"source_name": "State IIS PDF", "trust": "untrusted"},
        }
        imm_2 = {
            "resourceType": "Immunization",
            "status": "completed",
            "vaccineCode": {
                "coding": [{"system": "http://hl7.org/fhir/sid/cvx", "code": "208", "display": "COVID-19, mRNA, LNP-S, PF"}]
            },
            "occurrenceDateTime": "2025-10-15",
            "_carefold_provenance": {"source_name": "SMART Health Card", "trust": "untrusted"},
        }
        hr_i1, _, _ = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Immunization",
            fhir_data=imm_1,
            source_id="iis:imm:1",
        )
        hr_i2, v_i2, created_i2 = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Immunization",
            fhir_data=imm_2,
            source_id="shc:imm:2",
        )
        assert created_i2 is False
        assert hr_i2.id == hr_i1.id
        assert v_i2.operation == "merge"

        # 3. Business identifier exact match across two DiagnosticReports
        dr_1 = {
            "resourceType": "DiagnosticReport",
            "status": "final",
            "identifier": [{"system": "http://quest.example.com/accession", "value": "ACC-2026-8841"}],
            "code": {"coding": [{"system": "http://loinc.org", "code": "24323-8"}]},
            "effectiveDateTime": "2026-03-10T08:00:00Z",
            "_carefold_provenance": {"source_name": "Quest Direct", "trust": "untrusted"},
        }
        dr_2 = {
            "resourceType": "DiagnosticReport",
            "status": "final",
            "identifier": [{"system": "http://quest.example.com/accession", "value": "ACC-2026-8841"}],
            "code": {"coding": [{"system": "http://loinc.org", "code": "24323-8"}]},
            "effectiveDateTime": "2026-03-10T08:05:00Z",
            "_carefold_provenance": {"source_name": "Primary Care Portal", "trust": "untrusted"},
        }
        hr_d1, _, _ = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="DiagnosticReport",
            fhir_data=dr_1,
            source_id="quest:dr:1",
        )
        hr_d2, v_d2, created_d2 = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="DiagnosticReport",
            fhir_data=dr_2,
            source_id="pcp:dr:2",
        )
        assert created_d2 is False
        assert hr_d2.id == hr_d1.id
        assert v_d2.operation == "merge"


# =============================================================================
# 4. Deduplication False-Positive Prevention & Near-Duplicate Flagging Tests
# =============================================================================


@pytest.mark.asyncio
async def test_dedup_prevents_false_positives_and_flags_near_duplicates(dedup_db_env):
    """Verifies distinct same-day vitals, conflicting values, and cross-system conditions are NOT merged."""
    factory = dedup_db_env["factory"]
    profile_id = dedup_db_env["profile_a_id"]

    async with factory() as session:
        # Case A: Same LOINC code (2339-0 Blood glucose) at two different times on the same day (08:00 vs 18:00)
        glu_morning = {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "2339-0", "display": "Glucose"}]},
            "effectiveDateTime": "2026-03-16T08:00:00Z",
            "valueQuantity": {"value": 95.0, "unit": "mg/dL"},
            "_carefold_provenance": {"source_name": "Portal A", "trust": "untrusted"},
        }
        glu_evening = {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "2339-0", "display": "Glucose"}]},
            "effectiveDateTime": "2026-03-16T18:00:00Z",
            "valueQuantity": {"value": 132.0, "unit": "mg/dL"},
            "_carefold_provenance": {"source_name": "Portal B", "trust": "untrusted"},
        }
        hr_gm, _, created_gm = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Observation",
            fhir_data=glu_morning,
            source_id="portalA:glu:morning",
        )
        hr_ge, _, created_ge = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Observation",
            fhir_data=glu_evening,
            source_id="portalB:glu:evening",
        )
        assert created_gm is True
        assert created_ge is True
        assert hr_gm.id != hr_ge.id

        ge_dedup = hr_ge.data["_carefold_provenance"]["dedup"]
        assert ge_dedup["review_required"] is True
        assert hr_gm.id in ge_dedup["candidate_resource_ids"]
        assert ge_dedup["reason"] == "same_code_different_effective_time"

        # Verify HealthResourceReference graph edge with reference_field="near_duplicate_of"
        out_refs = await get_outbound_references(session, profile_id=profile_id, source_resource_id=hr_ge.id)
        near_edges = [r for r in out_refs if r.reference_field == "near_duplicate_of"]
        assert len(near_edges) == 1
        assert near_edges[0].target_resource_id == hr_gm.id

        # Case B: Same LOINC code at the EXACT same timestamp, but conflicting values (95 mg/dL vs 140 mg/dL)
        glu_conflict = {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "2339-0", "display": "Glucose"}]},
            "effectiveDateTime": "2026-03-16T08:00:00Z",
            "valueQuantity": {"value": 140.0, "unit": "mg/dL"},
            "_carefold_provenance": {"source_name": "Portal C", "trust": "untrusted"},
        }
        hr_gc, _, created_gc = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Observation",
            fhir_data=glu_conflict,
            source_id="portalC:glu:conflict",
        )
        assert created_gc is True
        assert hr_gc.id != hr_gm.id
        gc_dedup = hr_gc.data["_carefold_provenance"]["dedup"]
        assert gc_dedup["review_required"] is True
        assert gc_dedup["reason"] == "same_code_different_value"

        # Case C: Cross-system Condition on the same date (SNOMED-only vs ICD-10-CM-only)
        cond_snomed_only = {
            "resourceType": "Condition",
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "38341003", "display": "Hypertension"}]},
            "onsetDateTime": "2026-02-01",
            "_carefold_provenance": {"source_name": "Clinic A", "trust": "untrusted"},
        }
        cond_icd10_only = {
            "resourceType": "Condition",
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10", "display": "Essential hypertension"}]},
            "onsetDateTime": "2026-02-01",
            "_carefold_provenance": {"source_name": "Clinic B", "trust": "untrusted"},
        }
        hr_cs, _, _ = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Condition",
            fhir_data=cond_snomed_only,
            source_id="clinicA:htn",
        )
        hr_ci, _, created_ci = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Condition",
            fhir_data=cond_icd10_only,
            source_id="clinicB:htn",
        )
        # Never auto-merge SNOMED <-> ICD-10; must stay separate and flag near_duplicate_of
        assert created_ci is True
        assert hr_ci.id != hr_cs.id
        ci_dedup = hr_ci.data["_carefold_provenance"]["dedup"]
        assert ci_dedup["review_required"] is True
        assert ci_dedup["reason"] == "cross_code_system_concept_match"

        # Case D: Observations with unknown/unconvertible units must NEVER auto-merge
        unk_unit_1 = {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]},
            "effectiveDateTime": "2026-03-17T08:00:00Z",
            "valueQuantity": {"value": 100.0, "unit": "mystery_stones"},
        }
        unk_unit_2 = {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]},
            "effectiveDateTime": "2026-03-17T08:00:00Z",
            "valueQuantity": {"value": 100.0, "unit": "mystery_stones"},
        }
        hr_u1, _, created_u1 = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Observation",
            fhir_data=unk_unit_1,
            source_id="src1:unk:1",
        )
        hr_u2, _, created_u2 = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_id,
            resource_type="Observation",
            fhir_data=unk_unit_2,
            source_id="src2:unk:2",
        )
        assert created_u1 is True
        assert created_u2 is True
        assert hr_u1.id != hr_u2.id


# =============================================================================
# 5. Profile & Scope Isolation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_dedup_strict_profile_and_scope_isolation(dedup_db_env):
    """Verifies deduplication never merges or links resources across different profiles or different scopes."""
    factory = dedup_db_env["factory"]
    profile_a = dedup_db_env["profile_a_id"]
    profile_b = dedup_db_env["profile_b_id"]

    obs_payload = {
        "resourceType": "Observation",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}]},
        "effectiveDateTime": "2026-03-10T09:15:00Z",
        "valueQuantity": {"value": 5.7, "unit": "%"},
        "_carefold_provenance": {"source_name": "Quest Labs", "trust": "untrusted"},
    }

    async with factory() as session:
        hr_a, _, created_a = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Observation",
            fhir_data=obs_payload,
            source_id="quest:hba1c:1",
        )
        hr_b, _, created_b = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_b,
            resource_type="Observation",
            fhir_data=obs_payload,
            source_id="quest:hba1c:2",
        )
        assert created_a is True
        assert created_b is True
        assert hr_a.id != hr_b.id
        assert hr_a.profile_id == profile_a
        assert hr_b.profile_id == profile_b

        # Verify Scope isolation within the same profile (health.clinical vs health.paperwork)
        doc_clinical = {
            "resourceType": "DocumentReference",
            "status": "current",
            "identifier": [{"system": "http://portal.example.org/doc", "value": "DOC-100"}],
            "type": {"coding": [{"system": "http://loinc.org", "code": "34133-9", "display": "Summary of episode note"}]},
            "date": "2026-03-10T10:00:00Z",
        }
        hr_clin, _, _ = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="DocumentReference",
            fhir_data=doc_clinical,
            source_id="portal1:doc:100",
            scope="health.clinical",
        )
        hr_pw, _, created_pw = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="DocumentReference",
            fhir_data=doc_clinical,
            source_id="portal2:doc:100",
            scope="health.paperwork",
        )
        assert created_pw is True
        assert hr_pw.id != hr_clin.id
        assert hr_clin.scope == "health.clinical"
        assert hr_pw.scope == "health.paperwork"


# =============================================================================
# 6. Merge Reversibility (Undo / Split) Tests
# =============================================================================


@pytest.mark.asyncio
async def test_reverse_dedup_merge_restores_prior_version_and_splits_resource(dedup_db_env):
    """Verifies reverse_dedup_merge restores the pre-merge snapshot and splits the merged source into its own row."""
    factory = dedup_db_env["factory"]
    profile_a = dedup_db_env["profile_a_id"]
    profile_b = dedup_db_env["profile_b_id"]

    obs_portal_1 = {
        "resourceType": "Observation",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]},
        "effectiveDateTime": "2026-03-18T07:45:00Z",
        "valueQuantity": {"value": 68.0, "unit": "kg"},
        "_carefold_provenance": {"source_name": "Portal One", "trust": "untrusted"},
    }
    obs_portal_2 = {
        "resourceType": "Observation",
        "status": "final",
        "code": {"coding": [{"system": "2.16.840.1.113883.6.1", "code": "29463-7", "display": "Body weight"}]},
        "effectiveDateTime": "2026-03-18T07:45:00Z",
        "valueQuantity": {"value": 149.914, "unit": "[lb_av]"},
        "note": [{"text": "Measured at Portal Two clinic"}],
        "_carefold_provenance": {"source_name": "Portal Two", "trust": "untrusted"},
    }

    async with factory() as session:
        hr1, _, _ = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Observation",
            fhir_data=obs_portal_1,
            source_id="p1:wt:1",
            source_ref="batch-p1",
        )
        hr_merged, v_merge, is_created = await upsert_fhir_resource_with_history(
            session,
            profile_id=profile_a,
            resource_type="Observation",
            fhir_data=obs_portal_2,
            source_id="p2:wt:1",
            source_ref="batch-p2",
        )
        assert is_created is False
        assert hr_merged.id == hr1.id
        assert v_merge.version_id == 2
        assert v_merge.operation == "merge"

        # Wrong profile_id must be rejected
        with pytest.raises(ValueError, match="not found"):
            await reverse_dedup_merge(
                session,
                profile_id=profile_b,
                resource_id=hr1.id,
            )

        # Wrong ScopeContext (health.paperwork instead of health.clinical) must also be rejected
        with scope_context(
            scope="health.paperwork",
            granted_scopes=["health.paperwork"],
            active_scopes=["health.paperwork"],
        ):
            with pytest.raises((ValueError, ScopeViolationError)):
                await reverse_dedup_merge(
                    session,
                    profile_id=profile_a,
                    resource_id=hr1.id,
                )

        # Reverse the merge on profile_a
        revert_res = await reverse_dedup_merge(
            session,
            profile_id=profile_a,
            resource_id=hr1.id,
            actor_user_id=dedup_db_env["user_id"],
        )
        assert revert_res.target_resource_id == hr1.id
        assert revert_res.restored_from_version_id == 1
        assert revert_res.restored_version_id == 3
        split_id = revert_res.separated_resource_id
        assert split_id is not None
        assert split_id != hr1.id

        # Verify restored resource has version_id == 3 ("revert_merge") and original Portal One state
        versions = await get_resource_version_history(session, profile_id=profile_a, resource_id=hr1.id)
        assert [v.operation for v in versions] == ["create", "merge", "revert_merge"]

        restored_hr = (
            await session.execute(select(HealthResource).where(HealthResource.id == hr1.id))
        ).scalar_one()
        restored_payload = restored_hr.data
        assert "note" not in restored_payload
        assert restored_payload["_carefold_provenance"]["source_name"] == "Portal One"

        # Verify split resource is active in profile_a with Portal Two's payload
        split_hr = (
            await session.execute(select(HealthResource).where(HealthResource.id == split_id))
        ).scalar_one()
        assert split_hr.profile_id == profile_a
        assert split_hr.status == "active"
        split_payload = split_hr.data
        assert split_payload["note"][0]["text"] == "Measured at Portal Two clinic"
        assert split_payload["meta"]["trust"] == "untrusted"
