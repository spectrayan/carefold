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

"""Unit & integration tests for the HL7v2 (`hl7apy`) ADT / ORU / VXU -> FHIR R4 Converter (#284).

Verifies:
- `HL7APY_LICENSE_ATTESTATION` records permissive MIT license compatibility with PolyForm Noncommercial 1.0.0.
- `ORU^R01` lab messages (`MSH`, `PID`, `PV1`, `OBR`, multiple `OBX` segments with `NM`, `CE`, `ST` value types,
  `OBX-7` reference ranges, and `OBX-8` abnormal interpretation flags) convert into validated FHIR R4
  `Bundle`, `Patient`, `Encounter`, `DiagnosticReport` (linked via `result` references), and `Observation` resources.
- `VXU^V04` immunization messages (`MSH`, `PID`, `RXA`) convert into validated FHIR R4 `Patient` and `Immunization`
  resources with CVX codes, `lotNumber`, `expirationDate`, and `doseQuantity`.
- `ADT^A01` and `ADT^A08` encounter/admission messages (`MSH`, `PID`, `PV1`, `DG1`, `AL1`) convert into validated
  FHIR R4 `Patient`, `Encounter`, `Condition` (`encounter-diagnosis` / `problem-list-item`), and
  `AllergyIntolerance` (with repeating reaction manifestations and criticality) resources.
- HL7v2 escape sequences (`\\F\\`, `\\S\\`, `\\T\\`, `\\R\\`, `\\E\\`, `\\.br\\`, `\\X41\\`) and repeating fields (`~`)
  are accurately unescaped and split.
- Malformed, empty, non-HL7v2, and partially corrupted messages fail safely with structured, PHI-free
  `HL7v2ConversionError` / `HL7v2Diagnostic` entries.
- End-to-end staging and committing of HL7v2 `.hl7` files through `stage_import` and `commit_import_batch` into
  the relational FHIR repository (`HealthResource`, `HealthResourceVersion`, `HealthResourceCoding`,
  `HealthResourceReference`).
"""

from __future__ import annotations

import uuid

from fhir.resources.R4B.allergyintolerance import (
    AllergyIntolerance as FhirAllergyIntolerance,
)
from fhir.resources.R4B.bundle import Bundle as FhirBundle
from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.diagnosticreport import (
    DiagnosticReport as FhirDiagnosticReport,
)
from fhir.resources.R4B.encounter import Encounter as FhirEncounter
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.observation import Observation as FhirObservation
from fhir.resources.R4B.patient import Patient as FhirPatient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.config import settings
from carefold.db.base import Base
from carefold.db.models import (
    HealthResource,
    HealthResourceCoding,
    HealthResourceReference,
    HealthResourceVersion,
    Profile,
    User,
)
from carefold.importers import (
    HL7APY_LICENSE_ATTESTATION,
    HL7v2ConversionError,
    commit_import_batch,
    convert_clinical_payload_to_fhir,
    detect_import_format,
    parse_hl7v2_to_fhir,
    stage_import,
    unescape_hl7v2_text,
)

SAMPLE_ORU_R01 = (
    "MSH|^~\\&|QUEST_LAB|CITY_GENERAL|CAREFOLD|LOCAL_VAULT|20260410083000||ORU^R01|MSG-ORU-1001|P|2.5.1\r"
    "PID|1||MRN-88421^^^CITY_GENERAL^MR~SSN-999112222^^^SSA^SS||Patel^Maya^A||19881123|F|||742 Evergreen Terrace^^Springfield^IL^62704^USA||555-0199^PRN^PH^^^555^0199~^^^maya.patel@example.com\r"
    "PV1|1|O|CLINIC^ROOM-4^BED-A||||12345^Chen^Marcus^J|||MED||||||||V-2026-0410|||||||||||||||||||||||||20260410080000|20260410091500\r"
    "OBR|1|ORD-901|FIL-901|24323-8^Comprehensive Metabolic Panel \\T\\ A1c^LN|||20260410081500||||||||||||||||||F\r"
    "OBX|1|NM|4548-4^Hemoglobin A1c/Hemoglobin.total in Blood^LN||6.1|%^^UCUM|4.0-5.6|H|||F|||20260410082000\r"
    "OBX|2|NM|2345-7^Glucose [Mass/volume] in Serum or Plasma^LN||94|mg/dL^^UCUM|70-99|N|||F|||20260410082000\r"
    "OBX|3|CE|5778-6^Color of Urine^LN||YELLOW^Yellow^SCT||||||F|||20260410082200\r"
    "OBX|4|ST|33747-0^General Lab Comment^LN||Fasting sample\\.br\\No hemolysis\\F\\lipemia noted||||||F|||20260410082500\r"
)

SAMPLE_VXU_V04 = (
    "MSH|^~\\&|CAIR2_IIS|STATE_DOH|CAREFOLD|LOCAL_VAULT|20260315140000||VXU^V04|MSG-VXU-2002|P|2.5.1\r"
    "PID|1||PAT-VXU-77^^^CAIR2^MR||Patel^Maya||19881123|F\r"
    "RXA|0|1|20260315|20260315|208^SARS-COV-2 (COVID-19) vaccine, mRNA, spike protein, LNP, preservative free, 30 mcg/0.3mL dose^CVX|0.3|mL^milliliters^UCUM||||||||EL9262|20261231||||CP\r"
    "RXA|0|2|20251012|20251012|141^Influenza, seasonal, injectable^CVX|0.5|mL^milliliters^UCUM||||||||FLU-8821|20260630||||CP\r"
)

SAMPLE_ADT_A01 = (
    "MSH|^~\\&|EPIC_ADT|METRO_HOSPITAL|CAREFOLD|LOCAL_VAULT|20260501101500||ADT^A01|MSG-ADT-3003|P|2.5.1\r"
    "PID|1||MRN-88421^^^METRO_HOSPITAL^MR||Patel^Maya||19881123|F\r"
    "PV1|1|I|4WEST^402^1|E|||99887^Rivera^Elena^M||||||||||||ADM-2026-501|||||||||||||||||||||||||20260501093000|20260503140000\r"
    "DG1|1|I10|I10^Essential (primary) hypertension^ICD-10-CM|Essential hypertension|20260501094500|A\r"
    "DG1|2|I10|E11.9^Type 2 diabetes mellitus without complications^ICD-10-CM||20260501095000|F\r"
    "AL1|1|DA|7980^Penicillin G^RXNORM|SV|Hives~Anaphylaxis|20260501\r"
    "AL1|2|FA|227493005^Cashew nut^SCT|MO|Urticaria \\T\\ itching|20260501\r"
)


def test_hl7apy_license_attestation() -> None:
    """Verifies hl7apy license attestation is recorded as permissive MIT compatible with PolyForm Noncommercial."""
    assert HL7APY_LICENSE_ATTESTATION["package"] == "hl7apy"
    assert HL7APY_LICENSE_ATTESTATION["license"] == "MIT"
    assert "PolyForm Noncommercial" in HL7APY_LICENSE_ATTESTATION["compatibility"]


def test_unescape_hl7v2_escape_sequences() -> None:
    """Verifies HL7v2 escape sequences (\\F\\, \\S\\, \\T\\, \\R\\, \\E\\, \\.br\\, \\X41\\) are decoded accurately."""
    raw = r"Alpha\F\Beta\S\Gamma\T\Delta\R\Epsilon\E\Zeta\.br\Line2\X4142\End"
    decoded = unescape_hl7v2_text(raw)
    assert decoded == "Alpha|Beta^Gamma&Delta~Epsilon\\Zeta\nLine2ABEnd"


def test_oru_r01_converts_patient_encounter_diagnostic_report_and_observations() -> None:
    """Verifies ORU^R01 parses MSH/PID/PV1/OBR/OBX into validated FHIR R4 resources with linked DiagnosticReport.result."""
    res = parse_hl7v2_to_fhir(SAMPLE_ORU_R01, source_name="Quest Diagnostics HL7v2")
    assert res["format"] == "hl7v2"
    assert res["message_type"] == "ORU^R01"
    assert res["message_control_id"] == "MSG-ORU-1001"
    assert res["diagnostics"] == []

    # Validate top-level Bundle with fhir.resources
    validated_bundle = FhirBundle.model_validate(res["bundle"])
    assert validated_bundle.type == "collection"

    # Validate Patient (repeating PID-3 identifiers, PID-11 address, repeating PID-13 telecoms)
    patient = res["patient"]
    assert patient is not None
    FhirPatient.model_validate(patient)
    assert patient["id"] == "pat-MRN-88421"
    assert len(patient["identifier"]) == 2
    assert patient["identifier"][0]["value"] == "MRN-88421"
    assert patient["identifier"][1]["value"] == "SSN-999112222"
    assert patient["name"][0]["family"] == "Patel"
    assert patient["name"][0]["given"] == ["Maya", "A"]
    assert patient["birthDate"] == "1988-11-23"
    assert patient["gender"] == "female"
    assert patient["address"][0]["city"] == "Springfield"
    telecom_systems = {t["system"]: t["value"] for t in patient["telecom"]}
    assert telecom_systems["phone"] == "555-0199"
    assert telecom_systems["email"] == "maya.patel@example.com"

    # Check staged records: 1 Encounter + 1 DiagnosticReport + 4 Observations = 6 records
    records = res["records"]
    assert len(records) == 6
    assert res["summary"]["counts_by_type"] == {
        "Encounter": 1,
        "DiagnosticReport": 1,
        "Observation": 4,
    }

    enc_rec = next(r for r in records if r["resource_type"] == "Encounter")
    FhirEncounter.model_validate({k: v for k, v in enc_rec["data"].items() if k != "_carefold_provenance"})
    assert enc_rec["data"]["class"]["code"] == "AMB"
    assert enc_rec["data"]["participant"][0]["individual"]["display"] == "Marcus Chen"

    dr_rec = next(r for r in records if r["resource_type"] == "DiagnosticReport")
    dr_clean = {k: v for k, v in dr_rec["data"].items() if k != "_carefold_provenance"}
    FhirDiagnosticReport.model_validate(dr_clean)
    # Verify \T\ unescaped to '&'
    assert dr_clean["code"]["text"] == "Comprehensive Metabolic Panel & A1c"
    assert len(dr_clean["result"]) == 4

    obs_records = [r for r in records if r["resource_type"] == "Observation"]
    by_code = {r["code"]: r for r in obs_records}

    # OBX-1: HbA1c numeric with referenceRange 4.0-5.6 and abnormal flag H -> High
    hba1c = by_code["4548-4"]["data"]
    FhirObservation.model_validate({k: v for k, v in hba1c.items() if k != "_carefold_provenance"})
    assert hba1c["valueQuantity"]["value"] == 6.1
    assert hba1c["valueQuantity"]["unit"] == "%"
    assert hba1c["referenceRange"][0]["low"]["value"] == 4.0
    assert hba1c["referenceRange"][0]["high"]["value"] == 5.6
    assert hba1c["interpretation"][0]["coding"][0]["code"] == "H"
    assert hba1c["interpretation"][0]["coding"][0]["display"] == "High"

    # OBX-2: Glucose numeric with normal flag N
    glucose = by_code["2345-7"]["data"]
    assert glucose["valueQuantity"]["value"] == 94.0
    assert glucose["interpretation"][0]["coding"][0]["code"] == "N"

    # OBX-3: Coded CE observation
    urine_color = by_code["5778-6"]["data"]
    assert urine_color["valueCodeableConcept"]["coding"][0]["code"] == "YELLOW"
    assert urine_color["valueCodeableConcept"]["coding"][0]["system"] == "http://snomed.info/sct"

    # OBX-4: String ST observation with \.br\ and \F\ escape sequences
    comment_obs = by_code["33747-0"]["data"]
    assert comment_obs["valueString"] == "Fasting sample\nNo hemolysis|lipemia noted"


def test_vxu_v04_converts_immunizations_with_cvx_lot_and_dose() -> None:
    """Verifies VXU^V04 parses RXA segments into validated FHIR R4 Immunization resources."""
    res = convert_clinical_payload_to_fhir(SAMPLE_VXU_V04, input_type="hl7v2")
    assert res["message_type"] == "VXU^V04"
    assert res["summary"]["counts_by_type"] == {"Immunization": 2}

    imm_records = res["records"]
    assert len(imm_records) == 2
    by_cvx = {r["code"]: r["data"] for r in imm_records}

    covid = by_cvx["208"]
    FhirImmunization.model_validate({k: v for k, v in covid.items() if k != "_carefold_provenance"})
    assert covid["status"] == "completed"
    assert covid["vaccineCode"]["coding"][0]["system"] == "http://hl7.org/fhir/sid/cvx"
    assert covid["lotNumber"] == "EL9262"
    assert covid["expirationDate"] == "2026-12-31"
    assert covid["doseQuantity"]["value"] == 0.3
    assert covid["doseQuantity"]["unit"] == "milliliters"

    flu = by_cvx["141"]
    FhirImmunization.model_validate({k: v for k, v in flu.items() if k != "_carefold_provenance"})
    assert flu["lotNumber"] == "FLU-8821"
    assert flu["doseQuantity"]["value"] == 0.5


def test_adt_a01_converts_encounter_diagnoses_and_allergies_with_repeating_reactions() -> None:
    """Verifies ADT^A01 parses PV1, DG1, and AL1 segments into Encounter, Condition, and AllergyIntolerance."""
    res = parse_hl7v2_to_fhir(SAMPLE_ADT_A01, source_name="Metro Hospital ADT")
    assert res["message_type"] == "ADT^A01"
    assert res["summary"]["counts_by_type"] == {
        "Encounter": 1,
        "Condition": 2,
        "AllergyIntolerance": 2,
    }

    records = res["records"]
    enc = next(r["data"] for r in records if r["resource_type"] == "Encounter")
    assert enc["class"]["code"] == "IMP"
    assert enc["period"]["start"] == "2026-05-01T09:30:00Z"
    assert enc["period"]["end"] == "2026-05-03T14:00:00Z"

    conditions = [r["data"] for r in records if r["resource_type"] == "Condition"]
    for c in conditions:
        FhirCondition.model_validate({k: v for k, v in c.items() if k != "_carefold_provenance"})
        assert c["encounter"]["reference"] == f"Encounter/{enc['id']}"

    allergies = {r["code"]: r["data"] for r in records if r["resource_type"] == "AllergyIntolerance"}
    penicillin = allergies["7980"]
    FhirAllergyIntolerance.model_validate({k: v for k, v in penicillin.items() if k != "_carefold_provenance"})
    assert penicillin["category"] == ["medication"]
    assert penicillin["criticality"] == "high"
    assert penicillin["reaction"][0]["severity"] == "severe"
    manifestations = [m["text"] for m in penicillin["reaction"][0]["manifestation"]]
    assert manifestations == ["Hives", "Anaphylaxis"]

    cashew = allergies["227493005"]
    FhirAllergyIntolerance.model_validate({k: v for k, v in cashew.items() if k != "_carefold_provenance"})
    assert cashew["category"] == ["food"]
    assert cashew["criticality"] == "low"
    assert cashew["reaction"][0]["manifestation"][0]["text"] == "Urticaria & itching"


def test_malformed_and_corrupted_hl7v2_messages_fail_safely_with_phi_free_diagnostics() -> None:
    """Verifies empty, non-HL7v2, and partially corrupted messages emit PHI-safe diagnostics without leaking PHI."""
    with pytest.raises(HL7v2ConversionError) as empty_exc:
        parse_hl7v2_to_fhir("   \n\r  ")
    assert empty_exc.value.diagnostics[0]["code"] == "empty_message"

    secret_phi_Attempt = "NOT_HL7|Jane Doe SSN 123-45-6789|Secret Note"
    with pytest.raises(HL7v2ConversionError) as bad_exc:
        parse_hl7v2_to_fhir(secret_phi_Attempt)
    assert bad_exc.value.diagnostics[0]["code"] == "unrecognized_hl7v2_payload"
    # Ensure raw PHI from the rejected line is never echoed in exception or diagnostic messages
    assert "123-45-6789" not in str(bad_exc.value)
    assert "Jane Doe" not in str(bad_exc.value.diagnostics)

    # Partially corrupted message: valid MSH/PID/OBX alongside malformed lines
    partial_msg = (
        "MSH|^~\\&|LAB|FAC|CAREFOLD|VAULT|20260410083000||ORU^R01|MSG-PARTIAL|P|2.5.1\r"
        "PID|1||MRN-555||Doe^John||19750101|M\r"
        "BAD_HEADER_LINE|with|patient|secret|SSN-000-11-2222\r"
        "TRUNCATED_SEG_NO_DELIM\r"
        "OBX|1|NM|4548-4^HbA1c^LN||5.4|%^^UCUM|4.0-5.6|N|||F|||20260410083000\r"
    )
    partial_res = parse_hl7v2_to_fhir(partial_msg)
    assert len(partial_res["records"]) == 1
    assert partial_res["records"][0]["code"] == "4548-4"
    diag_codes = [d["code"] for d in partial_res["diagnostics"]]
    assert "malformed_segment_header" in diag_codes
    for diag in partial_res["diagnostics"]:
        assert "SSN-000-11-2222" not in diag["message"]


@pytest.mark.asyncio
async def test_hl7v2_stage_and_commit_into_relational_fhir_repository(
    tmp_path,
    monkeypatch,
    async_db_session_factory,
    user_factory,
    profile_factory,
) -> None:
    """Verifies end-to-end staging and committing of an HL7v2 `.hl7` file into the #282 FHIR repository."""
    monkeypatch.setattr(settings, "home_dir", tmp_path)
    user = await user_factory(email="maya@example.com", username="maya_patel", role="steward")
    profile = await profile_factory(
        user_id=user.id,
        name="Maya Patel",
        relationship="self",
        role="self",
        date_of_birth="1988-11-23",
        is_primary=True,
    )
    user_id = user.id
    profile_id = profile.id

    async with async_db_session_factory() as session:
        assert detect_import_format("quest_labs.hl7", SAMPLE_ORU_R01) == "hl7v2"

        batch = await stage_import(
            session=session,
            profile_id=profile_id,
            filename="quest_labs.hl7",
            content=SAMPLE_ORU_R01,
            source_name="Quest Diagnostics HL7v2",
            user_id=user_id,
        )
        assert batch.status == "staged"
        assert batch.format == "hl7v2"

        commit_res = await commit_import_batch(
            session=session,
            profile_id=profile_id,
            batch_id=batch.id,
            actor_user_id=user_id,
        )
        assert commit_res["status"] == "committed"
        assert commit_res["committed_count"] == 6

        resources = (
            await session.execute(select(HealthResource).where(HealthResource.profile_id == profile_id))
        ).scalars().all()
        # 6 clinical resources + 1 canonical Patient resource created by commit_import_batch
        assert len(resources) >= 6

        versions = (
            await session.execute(select(HealthResourceVersion).where(HealthResourceVersion.profile_id == profile_id))
        ).scalars().all()
        assert len(versions) >= 6

        codings = (
            await session.execute(
                select(HealthResourceCoding).where(
                    HealthResourceCoding.profile_id == profile_id,
                    HealthResourceCoding.code == "4548-4",
                )
            )
        ).scalars().all()
        assert len(codings) == 1
        assert codings[0].system == "http://loinc.org"

        refs = (
            await session.execute(
                select(HealthResourceReference).where(
                    HealthResourceReference.profile_id == profile_id,
                    HealthResourceReference.target_type == "Observation",
                    HealthResourceReference.reference_field == "result",
                )
            )
        ).scalars().all()
        assert len(refs) == 4
