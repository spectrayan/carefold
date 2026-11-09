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

"""Clinical terminology normalizer and curated UCUM unit conversion engine (#283).

Design & Conformance Notes:
1. **License-Safe Terminology Normalization (No Bundled Licensed Tables)**:
   - Carefold does **not** ship licensed terminology distributions (no bundled SNOMED CT release,
     no full LOINC table, no CPT/ICD distribution files).
   - This module normalizes legacy HL7 OIDs (`urn:oid:2.16.840.1.113883.6.1`, `.6.96`, `.6.88`,
     `.6.90`, `.12.292`, `.6.12`, `.6.285`, `.6.69`, `.6.8`, etc.) and HL7v2 table mnemonics to
     canonical HL7 FHIR R4 CodeSystem URIs, backed by a small, license-safe curated reference map
     of common US Core vital sign, outpatient lab, immunization, condition, medication, and
     allergy codes.
   - Code mappings are **never** invented or guessed. Unknown codes or unrecognized code systems
     pass through untouched with a PHI-safe `FhirDiagnostic`.
2. **Curated Unit Conversion via Pint (NOT General UCUM Validation)**:
   - Uses `pint` (`BSD-3-Clause`) for deterministic numeric conversion across an explicit curated
     allowlist of clinical/UCUM unit codes (`[lb_av]`/`lbs` <-> `kg`, `[oz_av]`/`oz` -> `kg`,
     `[degF]`/`°F` <-> `Cel`, `[in_i]`/`in` <-> `cm`, `[ft_i]`/`ft` -> `cm`, and analyte-specific
     `mmol/L` <-> `mg/dL` or `umol/L` <-> `mg/dL` only where the analyte LOINC code and molecular
     weight are explicitly listed in `CURATED_ANALYTE_MOLECULAR_WEIGHTS`).
   - Pint unit conversion is **not** general UCUM grammar or syntax validation.
   - Unknown, unmapped, or ambiguous units are kept as-is and flagged with a PHI-safe diagnostic,
     never guessed.
   - Whenever a quantity is converted, the original reported `value`, `unit`, `code`, and `system`
     are preserved on `Quantity.extension` using the standard HL7 FHIR extension
     `http://hl7.org/fhir/StructureDefinition/iso21090-PQ-translation` as well as in
     `_carefold_provenance["original_quantities"]`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import math
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import pint

from carefold.fhir.registry import FhirDiagnostic, extract_codings

# ============================================================================
# Section 1: Canonical FHIR R4 CodeSystem URIs & Capability Metadata
# ============================================================================

LOINC_SYSTEM: str = "http://loinc.org"
SNOMED_CT_SYSTEM: str = "http://snomed.info/sct"
RXNORM_SYSTEM: str = "http://www.nlm.nih.gov/research/umls/rxnorm"
ICD10_CM_SYSTEM: str = "http://hl7.org/fhir/sid/icd-10-cm"
ICD10_WHO_SYSTEM: str = "http://hl7.org/fhir/sid/icd-10"
CVX_SYSTEM: str = "http://hl7.org/fhir/sid/cvx"
CPT_SYSTEM: str = "http://www.ama-assn.org/go/cpt"
HCPCS_SYSTEM: str = "https://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets"
NDC_SYSTEM: str = "http://hl7.org/fhir/sid/ndc"
UCUM_SYSTEM: str = "http://unitsofmeasure.org"
UNII_SYSTEM: str = "http://fdasis.nlm.nih.gov"
V3_ACT_CODE_SYSTEM: str = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
CONDITION_CLINICAL_SYSTEM: str = "http://terminology.hl7.org/CodeSystem/condition-clinical"
CONDITION_VER_STATUS_SYSTEM: str = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
ALLERGY_CLINICAL_SYSTEM: str = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"
ALLERGY_VER_STATUS_SYSTEM: str = "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification"
OBSERVATION_CATEGORY_SYSTEM: str = "http://terminology.hl7.org/CodeSystem/observation-category"

ORIGINAL_QUANTITY_EXTENSION_URL: str = (
    "http://hl7.org/fhir/StructureDefinition/iso21090-PQ-translation"
)

CANONICAL_CODE_SYSTEM_URIS: FrozenSet[str] = frozenset({
    LOINC_SYSTEM,
    SNOMED_CT_SYSTEM,
    RXNORM_SYSTEM,
    ICD10_CM_SYSTEM,
    ICD10_WHO_SYSTEM,
    CVX_SYSTEM,
    CPT_SYSTEM,
    HCPCS_SYSTEM,
    NDC_SYSTEM,
    UCUM_SYSTEM,
    UNII_SYSTEM,
    V3_ACT_CODE_SYSTEM,
    CONDITION_CLINICAL_SYSTEM,
    CONDITION_VER_STATUS_SYSTEM,
    ALLERGY_CLINICAL_SYSTEM,
    ALLERGY_VER_STATUS_SYSTEM,
    OBSERVATION_CATEGORY_SYSTEM,
})

TERMINOLOGY_CAPABILITIES: Dict[str, Any] = {
    "bundled_licensed_releases": False,
    "canonical_oid_and_alias_normalization": True,
    "curated_license_safe_subset": True,
    "unknown_codes_passthrough_with_diagnostic": True,
    "invents_code_mappings": False,
}

UNIT_CONVERSION_CAPABILITIES: Dict[str, Any] = {
    "engine": "pint",
    "ucum_syntax_validation": False,
    "curated_ucum_unit_conversion": True,
    "unknown_units_kept_and_flagged": True,
    "preserves_original_quantity_extension": True,
    "original_quantity_extension_url": ORIGINAL_QUANTITY_EXTENSION_URL,
}

# Legacy HL7 OIDs (with or without `urn:oid:` prefix) -> canonical FHIR R4 CodeSystem URI
OID_TO_CANONICAL_SYSTEM_URI: Dict[str, str] = {
    "2.16.840.1.113883.6.1": LOINC_SYSTEM,
    "2.16.840.1.113883.6.96": SNOMED_CT_SYSTEM,
    "2.16.840.1.113883.6.88": RXNORM_SYSTEM,
    "2.16.840.1.113883.6.90": ICD10_CM_SYSTEM,
    "2.16.840.1.113883.6.3": ICD10_WHO_SYSTEM,
    "2.16.840.1.113883.12.292": CVX_SYSTEM,
    "2.16.840.1.113883.6.59": CVX_SYSTEM,
    "2.16.840.1.113883.6.12": CPT_SYSTEM,
    "2.16.840.1.113883.6.285": HCPCS_SYSTEM,
    "2.16.840.1.113883.6.69": NDC_SYSTEM,
    "2.16.840.1.113883.6.8": UCUM_SYSTEM,
    "2.16.840.1.113883.4.9": UNII_SYSTEM,
    "2.16.840.1.113883.5.4": V3_ACT_CODE_SYSTEM,
}

# Case-insensitive aliases, HL7v2 table mnemonics, and HTTP/HTTPS variants -> canonical URI
ALIAS_TO_CANONICAL_SYSTEM_URI: Dict[str, str] = {
    "loinc": LOINC_SYSTEM,
    "ln": LOINC_SYSTEM,
    "http://loinc.org": LOINC_SYSTEM,
    "https://loinc.org": LOINC_SYSTEM,
    "snomed": SNOMED_CT_SYSTEM,
    "snomed ct": SNOMED_CT_SYSTEM,
    "snomed-ct": SNOMED_CT_SYSTEM,
    "snomedct": SNOMED_CT_SYSTEM,
    "sct": SNOMED_CT_SYSTEM,
    "http://snomed.info/sct": SNOMED_CT_SYSTEM,
    "https://snomed.info/sct": SNOMED_CT_SYSTEM,
    "rxnorm": RXNORM_SYSTEM,
    "http://www.nlm.nih.gov/research/umls/rxnorm": RXNORM_SYSTEM,
    "https://www.nlm.nih.gov/research/umls/rxnorm": RXNORM_SYSTEM,
    "icd-10-cm": ICD10_CM_SYSTEM,
    "icd10cm": ICD10_CM_SYSTEM,
    "icd-10": ICD10_CM_SYSTEM,
    "icd10": ICD10_CM_SYSTEM,
    "i10": ICD10_CM_SYSTEM,
    "http://hl7.org/fhir/sid/icd-10-cm": ICD10_CM_SYSTEM,
    "https://hl7.org/fhir/sid/icd-10-cm": ICD10_CM_SYSTEM,
    "http://hl7.org/fhir/sid/icd-10": ICD10_WHO_SYSTEM,
    "https://hl7.org/fhir/sid/icd-10": ICD10_WHO_SYSTEM,
    "cvx": CVX_SYSTEM,
    "http://hl7.org/fhir/sid/cvx": CVX_SYSTEM,
    "https://hl7.org/fhir/sid/cvx": CVX_SYSTEM,
    "cpt": CPT_SYSTEM,
    "cpt-4": CPT_SYSTEM,
    "cpt4": CPT_SYSTEM,
    "http://www.ama-assn.org/go/cpt": CPT_SYSTEM,
    "https://www.ama-assn.org/go/cpt": CPT_SYSTEM,
    "hcpcs": HCPCS_SYSTEM,
    "http://www.cms.gov/medicare/coding/hcpcsreleasecodesets": HCPCS_SYSTEM,
    "https://www.cms.gov/medicare/coding/hcpcsreleasecodesets": HCPCS_SYSTEM,
    "ndc": NDC_SYSTEM,
    "http://hl7.org/fhir/sid/ndc": NDC_SYSTEM,
    "https://hl7.org/fhir/sid/ndc": NDC_SYSTEM,
    "ucum": UCUM_SYSTEM,
    "http://unitsofmeasure.org": UCUM_SYSTEM,
    "https://unitsofmeasure.org": UCUM_SYSTEM,
    "unii": UNII_SYSTEM,
    "http://fdasis.nlm.nih.gov": UNII_SYSTEM,
    "https://fdasis.nlm.nih.gov": UNII_SYSTEM,
    "actcode": V3_ACT_CODE_SYSTEM,
    "v3-actcode": V3_ACT_CODE_SYSTEM,
    "http://terminology.hl7.org/codesystem/v3-actcode": V3_ACT_CODE_SYSTEM,
    "https://terminology.hl7.org/codesystem/v3-actcode": V3_ACT_CODE_SYSTEM,
}


# ============================================================================
# Section 2: Small, License-Safe Curated Clinical Code Reference Table
# ============================================================================

@dataclass(frozen=True)
class CuratedCodeEntry:
    """Metadata for a single code in Carefold's small, license-safe curated reference subset."""

    system: str
    code: str
    display: str
    category: str
    canonical_unit: Optional[str] = None
    display_unit: Optional[str] = None
    concept_group: Optional[str] = None


CURATED_CLINICAL_CODES: Dict[Tuple[str, str], CuratedCodeEntry] = {
    # --- LOINC Vital Signs & Anthropometrics ---
    (LOINC_SYSTEM, "85353-1"): CuratedCodeEntry(
        LOINC_SYSTEM, "85353-1", "Vital signs, weight, height, head circumference, oxygen saturation and BMI panel", "vital-signs"
    ),
    (LOINC_SYSTEM, "85354-9"): CuratedCodeEntry(
        LOINC_SYSTEM, "85354-9", "Blood pressure panel with all children optional", "vital-signs", "mm[Hg]", "mmHg", "vital:bp_panel"
    ),
    (LOINC_SYSTEM, "8480-6"): CuratedCodeEntry(
        LOINC_SYSTEM, "8480-6", "Systolic blood pressure", "vital-signs", "mm[Hg]", "mmHg", "vital:bp_systolic"
    ),
    (LOINC_SYSTEM, "8462-4"): CuratedCodeEntry(
        LOINC_SYSTEM, "8462-4", "Diastolic blood pressure", "vital-signs", "mm[Hg]", "mmHg", "vital:bp_diastolic"
    ),
    (LOINC_SYSTEM, "8867-4"): CuratedCodeEntry(
        LOINC_SYSTEM, "8867-4", "Heart rate", "vital-signs", "/min", "/min", "vital:heart_rate"
    ),
    (LOINC_SYSTEM, "9279-1"): CuratedCodeEntry(
        LOINC_SYSTEM, "9279-1", "Respiratory rate", "vital-signs", "/min", "/min", "vital:respiratory_rate"
    ),
    (LOINC_SYSTEM, "8310-5"): CuratedCodeEntry(
        LOINC_SYSTEM, "8310-5", "Body temperature", "vital-signs", "Cel", "Cel", "vital:body_temp"
    ),
    (LOINC_SYSTEM, "29463-7"): CuratedCodeEntry(
        LOINC_SYSTEM, "29463-7", "Body weight", "vital-signs", "kg", "kg", "vital:body_weight"
    ),
    (LOINC_SYSTEM, "8302-2"): CuratedCodeEntry(
        LOINC_SYSTEM, "8302-2", "Body height", "vital-signs", "cm", "cm", "vital:body_height"
    ),
    (LOINC_SYSTEM, "39156-5"): CuratedCodeEntry(
        LOINC_SYSTEM, "39156-5", "Body mass index (BMI) [Ratio]", "vital-signs", "kg/m2", "kg/m2", "vital:bmi"
    ),
    (LOINC_SYSTEM, "59408-5"): CuratedCodeEntry(
        LOINC_SYSTEM, "59408-5", "Oxygen saturation in Arterial blood by Pulse oximetry", "vital-signs", "%", "%", "vital:spo2"
    ),
    (LOINC_SYSTEM, "2708-6"): CuratedCodeEntry(
        LOINC_SYSTEM, "2708-6", "Oxygen saturation in Arterial blood", "vital-signs", "%", "%", "vital:spo2"
    ),
    (LOINC_SYSTEM, "41950-7"): CuratedCodeEntry(
        LOINC_SYSTEM, "41950-7", "Number of steps in 24 hour Measured", "activity"
    ),
    (LOINC_SYSTEM, "41979-6"): CuratedCodeEntry(
        LOINC_SYSTEM, "41979-6", "Calories burned in 24 hour Calculated", "activity", "kcal", "kcal"
    ),
    (LOINC_SYSTEM, "93832-4"): CuratedCodeEntry(
        LOINC_SYSTEM, "93832-4", "Sleep duration", "activity", "h", "h"
    ),
    # --- LOINC Common Outpatient Labs ---
    (LOINC_SYSTEM, "4548-4"): CuratedCodeEntry(
        LOINC_SYSTEM, "4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "laboratory", "%", "%", "lab:hba1c"
    ),
    (LOINC_SYSTEM, "2339-0"): CuratedCodeEntry(
        LOINC_SYSTEM, "2339-0", "Glucose [Mass/volume] in Blood", "laboratory", "mg/dL", "mg/dL", "lab:glucose"
    ),
    (LOINC_SYSTEM, "2345-7"): CuratedCodeEntry(
        LOINC_SYSTEM, "2345-7", "Glucose [Mass/volume] in Serum or Plasma", "laboratory", "mg/dL", "mg/dL", "lab:glucose"
    ),
    (LOINC_SYSTEM, "15074-8"): CuratedCodeEntry(
        LOINC_SYSTEM, "15074-8", "Glucose [Moles/volume] in Blood", "laboratory", "mg/dL", "mg/dL", "lab:glucose"
    ),
    (LOINC_SYSTEM, "2093-3"): CuratedCodeEntry(
        LOINC_SYSTEM, "2093-3", "Cholesterol [Mass/volume] in Serum or Plasma", "laboratory", "mg/dL", "mg/dL", "lab:cholesterol_total"
    ),
    (LOINC_SYSTEM, "2085-9"): CuratedCodeEntry(
        LOINC_SYSTEM, "2085-9", "Cholesterol in HDL [Mass/volume] in Serum or Plasma", "laboratory", "mg/dL", "mg/dL", "lab:hdl"
    ),
    (LOINC_SYSTEM, "13457-7"): CuratedCodeEntry(
        LOINC_SYSTEM, "13457-7", "Cholesterol in LDL [Mass/volume] in Serum or Plasma by calculation", "laboratory", "mg/dL", "mg/dL", "lab:ldl"
    ),
    (LOINC_SYSTEM, "2089-1"): CuratedCodeEntry(
        LOINC_SYSTEM, "2089-1", "Cholesterol in LDL [Mass/volume] in Serum or Plasma", "laboratory", "mg/dL", "mg/dL", "lab:ldl"
    ),
    (LOINC_SYSTEM, "2571-8"): CuratedCodeEntry(
        LOINC_SYSTEM, "2571-8", "Triglyceride [Mass/volume] in Serum or Plasma", "laboratory", "mg/dL", "mg/dL", "lab:triglycerides"
    ),
    (LOINC_SYSTEM, "2160-0"): CuratedCodeEntry(
        LOINC_SYSTEM, "2160-0", "Creatinine [Mass/volume] in Serum or Plasma", "laboratory", "mg/dL", "mg/dL", "lab:creatinine"
    ),
    (LOINC_SYSTEM, "33914-3"): CuratedCodeEntry(
        LOINC_SYSTEM, "33914-3", "Glomerular filtration rate/1.73 sq M.predicted", "laboratory", "mL/min/{1.73_m2}", "mL/min/1.73m2", "lab:egfr"
    ),
    (LOINC_SYSTEM, "62238-1"): CuratedCodeEntry(
        LOINC_SYSTEM, "62238-1", "Glomerular filtration rate/1.73 sq M.predicted by CKD-EPI", "laboratory", "mL/min/{1.73_m2}", "mL/min/1.73m2", "lab:egfr"
    ),
    (LOINC_SYSTEM, "3016-3"): CuratedCodeEntry(
        LOINC_SYSTEM, "3016-3", "Thyrotropin [Units/volume] in Serum or Plasma", "laboratory", "u[IU]/mL", "uIU/mL", "lab:tsh"
    ),
    (LOINC_SYSTEM, "718-7"): CuratedCodeEntry(
        LOINC_SYSTEM, "718-7", "Hemoglobin [Mass/volume] in Blood", "laboratory", "g/dL", "g/dL", "lab:hemoglobin"
    ),
    (LOINC_SYSTEM, "6690-2"): CuratedCodeEntry(
        LOINC_SYSTEM, "6690-2", "Leukocytes [#/volume] in Blood by Automated count", "laboratory", "10*3/uL", "10*3/uL", "lab:wbc"
    ),
    (LOINC_SYSTEM, "777-3"): CuratedCodeEntry(
        LOINC_SYSTEM, "777-3", "Platelets [#/volume] in Blood by Automated count", "laboratory", "10*3/uL", "10*3/uL", "lab:platelets"
    ),
    (LOINC_SYSTEM, "2951-2"): CuratedCodeEntry(
        LOINC_SYSTEM, "2951-2", "Sodium [Moles/volume] in Serum or Plasma", "laboratory", "mmol/L", "mmol/L", "lab:sodium"
    ),
    (LOINC_SYSTEM, "2823-3"): CuratedCodeEntry(
        LOINC_SYSTEM, "2823-3", "Potassium [Moles/volume] in Serum or Plasma", "laboratory", "mmol/L", "mmol/L", "lab:potassium"
    ),
    (LOINC_SYSTEM, "24323-8"): CuratedCodeEntry(
        LOINC_SYSTEM, "24323-8", "Comprehensive metabolic panel", "laboratory"
    ),
    (LOINC_SYSTEM, "58410-2"): CuratedCodeEntry(
        LOINC_SYSTEM, "58410-2", "Complete blood count (hemogram) panel", "laboratory"
    ),
    (LOINC_SYSTEM, "57698-3"): CuratedCodeEntry(
        LOINC_SYSTEM, "57698-3", "Lipid panel with direct LDL", "laboratory"
    ),
    # --- SNOMED CT Small Curated Subset ---
    (SNOMED_CT_SYSTEM, "44054006"): CuratedCodeEntry(
        SNOMED_CT_SYSTEM, "44054006", "Type 2 diabetes mellitus", "condition", concept_group="cond:t2dm"
    ),
    (SNOMED_CT_SYSTEM, "38341003"): CuratedCodeEntry(
        SNOMED_CT_SYSTEM, "38341003", "Hypertensive disorder, systemic arterial", "condition", concept_group="cond:htn"
    ),
    (SNOMED_CT_SYSTEM, "59621000"): CuratedCodeEntry(
        SNOMED_CT_SYSTEM, "59621000", "Essential hypertension", "condition", concept_group="cond:htn"
    ),
    (SNOMED_CT_SYSTEM, "195967001"): CuratedCodeEntry(
        SNOMED_CT_SYSTEM, "195967001", "Asthma", "condition", concept_group="cond:asthma"
    ),
    (SNOMED_CT_SYSTEM, "13645005"): CuratedCodeEntry(
        SNOMED_CT_SYSTEM, "13645005", "Chronic obstructive lung disease", "condition", concept_group="cond:copd"
    ),
    (SNOMED_CT_SYSTEM, "91936005"): CuratedCodeEntry(
        SNOMED_CT_SYSTEM, "91936005", "Allergy to penicillin", "allergy", concept_group="allergy:penicillin"
    ),
    (SNOMED_CT_SYSTEM, "764146007"): CuratedCodeEntry(
        SNOMED_CT_SYSTEM, "764146007", "Penicillin", "allergy", concept_group="allergy:penicillin"
    ),
    (SNOMED_CT_SYSTEM, "91935009"): CuratedCodeEntry(
        SNOMED_CT_SYSTEM, "91935009", "Allergy to peanut", "allergy", concept_group="allergy:peanut"
    ),
    # --- ICD-10-CM Small Curated Subset ---
    (ICD10_CM_SYSTEM, "I10"): CuratedCodeEntry(
        ICD10_CM_SYSTEM, "I10", "Essential (primary) hypertension", "condition", concept_group="cond:htn"
    ),
    (ICD10_CM_SYSTEM, "E11.9"): CuratedCodeEntry(
        ICD10_CM_SYSTEM, "E11.9", "Type 2 diabetes mellitus without complications", "condition", concept_group="cond:t2dm"
    ),
    (ICD10_CM_SYSTEM, "E11.65"): CuratedCodeEntry(
        ICD10_CM_SYSTEM, "E11.65", "Type 2 diabetes mellitus with hyperglycemia", "condition", concept_group="cond:t2dm"
    ),
    (ICD10_CM_SYSTEM, "J45.909"): CuratedCodeEntry(
        ICD10_CM_SYSTEM, "J45.909", "Unspecified asthma, uncomplicated", "condition", concept_group="cond:asthma"
    ),
    (ICD10_CM_SYSTEM, "E78.5"): CuratedCodeEntry(
        ICD10_CM_SYSTEM, "E78.5", "Hyperlipidemia, unspecified", "condition", concept_group="cond:hyperlipidemia"
    ),
    # --- RxNorm Small Curated Subset ---
    (RXNORM_SYSTEM, "860975"): CuratedCodeEntry(
        RXNORM_SYSTEM, "860975", "Metformin hydrochloride 500 MG Oral Tablet", "medication", concept_group="med:metformin_500"
    ),
    (RXNORM_SYSTEM, "861004"): CuratedCodeEntry(
        RXNORM_SYSTEM, "861004", "Metformin hydrochloride 1000 MG Oral Tablet", "medication", concept_group="med:metformin_1000"
    ),
    (RXNORM_SYSTEM, "314076"): CuratedCodeEntry(
        RXNORM_SYSTEM, "314076", "Lisinopril 10 MG Oral Tablet", "medication", concept_group="med:lisinopril_10"
    ),
    (RXNORM_SYSTEM, "197361"): CuratedCodeEntry(
        RXNORM_SYSTEM, "197361", "Amlodipine 5 MG Oral Tablet", "medication", concept_group="med:amlodipine_5"
    ),
    (RXNORM_SYSTEM, "617312"): CuratedCodeEntry(
        RXNORM_SYSTEM, "617312", "Atorvastatin 20 MG Oral Tablet", "medication", concept_group="med:atorvastatin_20"
    ),
    (RXNORM_SYSTEM, "7980"): CuratedCodeEntry(
        RXNORM_SYSTEM, "7980", "Penicillin G", "allergy", concept_group="allergy:penicillin"
    ),
    (RXNORM_SYSTEM, "723"): CuratedCodeEntry(
        RXNORM_SYSTEM, "723", "Amoxicillin", "medication", concept_group="med:amoxicillin"
    ),
    # --- CVX Vaccine Subset ---
    (CVX_SYSTEM, "03"): CuratedCodeEntry(CVX_SYSTEM, "03", "MMR", "immunization", concept_group="vax:mmr"),
    (CVX_SYSTEM, "08"): CuratedCodeEntry(CVX_SYSTEM, "08", "HepB pediatric/adolescent", "immunization", concept_group="vax:hepb"),
    (CVX_SYSTEM, "10"): CuratedCodeEntry(CVX_SYSTEM, "10", "IPV", "immunization", concept_group="vax:ipv"),
    (CVX_SYSTEM, "17"): CuratedCodeEntry(CVX_SYSTEM, "17", "Hib", "immunization", concept_group="vax:hib"),
    (CVX_SYSTEM, "20"): CuratedCodeEntry(CVX_SYSTEM, "20", "DTaP", "immunization", concept_group="vax:dtap"),
    (CVX_SYSTEM, "21"): CuratedCodeEntry(CVX_SYSTEM, "21", "Varicella", "immunization", concept_group="vax:varicella"),
    (CVX_SYSTEM, "83"): CuratedCodeEntry(CVX_SYSTEM, "83", "HepA", "immunization", concept_group="vax:hepa"),
    (CVX_SYSTEM, "114"): CuratedCodeEntry(CVX_SYSTEM, "114", "MenACWY", "immunization", concept_group="vax:menacwy"),
    (CVX_SYSTEM, "115"): CuratedCodeEntry(CVX_SYSTEM, "115", "Tdap", "immunization", concept_group="vax:tdap"),
    (CVX_SYSTEM, "116"): CuratedCodeEntry(CVX_SYSTEM, "116", "Rotavirus pentavalent", "immunization", concept_group="vax:rotavirus"),
    (CVX_SYSTEM, "133"): CuratedCodeEntry(CVX_SYSTEM, "133", "PCV13", "immunization", concept_group="vax:pcv13"),
    (CVX_SYSTEM, "140"): CuratedCodeEntry(CVX_SYSTEM, "140", "Influenza, seasonal, injectable, preservative free", "immunization", concept_group="vax:flu"),
    (CVX_SYSTEM, "141"): CuratedCodeEntry(CVX_SYSTEM, "141", "Influenza, seasonal, injectable", "immunization", concept_group="vax:flu"),
    (CVX_SYSTEM, "165"): CuratedCodeEntry(CVX_SYSTEM, "165", "HPV9", "immunization", concept_group="vax:hpv9"),
    (CVX_SYSTEM, "207"): CuratedCodeEntry(CVX_SYSTEM, "207", "COVID-19, mRNA, LNP-S, PF, 100 mcg/0.5mL dose", "immunization", concept_group="vax:covid19"),
    (CVX_SYSTEM, "208"): CuratedCodeEntry(CVX_SYSTEM, "208", "COVID-19, mRNA, LNP-S, PF, 30 mcg/0.3mL dose", "immunization", concept_group="vax:covid19"),
    (CVX_SYSTEM, "213"): CuratedCodeEntry(CVX_SYSTEM, "213", "SARS-COV-2 (COVID-19) vaccine, UNSPECIFIED", "immunization", concept_group="vax:covid19"),
    (CVX_SYSTEM, "215"): CuratedCodeEntry(CVX_SYSTEM, "215", "PCV15", "immunization", concept_group="vax:pcv15"),
    # --- CPT / HCPCS / NDC Small Curated Subset ---
    (CPT_SYSTEM, "99213"): CuratedCodeEntry(CPT_SYSTEM, "99213", "Office or other outpatient visit, established patient, 20-29 minutes", "procedure"),
    (CPT_SYSTEM, "99214"): CuratedCodeEntry(CPT_SYSTEM, "99214", "Office or other outpatient visit, established patient, 30-39 minutes", "procedure"),
    (CPT_SYSTEM, "80053"): CuratedCodeEntry(CPT_SYSTEM, "80053", "Comprehensive metabolic panel", "procedure"),
    (CPT_SYSTEM, "83036"): CuratedCodeEntry(CPT_SYSTEM, "83036", "Hemoglobin; glycosylated (A1C)", "procedure"),
    (HCPCS_SYSTEM, "G0439"): CuratedCodeEntry(HCPCS_SYSTEM, "G0439", "Annual wellness visit; includes a personalized prevention plan of service (pps), subsequent visit", "procedure"),
    (HCPCS_SYSTEM, "J3420"): CuratedCodeEntry(HCPCS_SYSTEM, "J3420", "Injection, vitamin b-12 cyanocobalamin, up to 1000 mcg", "procedure"),
    (NDC_SYSTEM, "00093-1048-01"): CuratedCodeEntry(NDC_SYSTEM, "00093-1048-01", "Metformin Hydrochloride 500mg Tablet", "medication", concept_group="med:metformin_500"),
}

# Unambiguous fallback index for curated codes when an imported C-CDA entry omits `codeSystem`
_CURATED_CODE_BY_RESOURCE_AND_CODE: Dict[Tuple[str, str], CuratedCodeEntry] = {}
for (_sys, _code), _entry in CURATED_CLINICAL_CODES.items():
    if _entry.category in ("vital-signs", "laboratory", "activity"):
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("Observation", _code)] = _entry
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("DiagnosticReport", _code)] = _entry
    elif _entry.category == "condition":
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("Condition", _code)] = _entry
    elif _entry.category == "medication":
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("MedicationStatement", _code)] = _entry
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("MedicationRequest", _code)] = _entry
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("MedicationDispense", _code)] = _entry
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("Medication", _code)] = _entry
    elif _entry.category == "allergy":
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("AllergyIntolerance", _code)] = _entry
    elif _entry.category == "immunization":
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("Immunization", _code)] = _entry
    elif _entry.category == "procedure":
        _CURATED_CODE_BY_RESOURCE_AND_CODE[("Procedure", _code)] = _entry


# ============================================================================
# Section 3: Curated Pint Unit Conversion Engine (NOT UCUM Validation)
# ============================================================================

_UREG = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)

# Analyte molecular weights (g/mol) for explicit molar <-> mass concentration conversion
CURATED_ANALYTE_MOLECULAR_WEIGHTS: Dict[str, float] = {
    "2339-0": 180.156,   # Glucose [Mass/volume] in Blood
    "2345-7": 180.156,   # Glucose [Mass/volume] in Serum or Plasma
    "15074-8": 180.156,  # Glucose [Moles/volume] in Blood
    "2093-3": 386.654,   # Cholesterol total
    "2085-9": 386.654,   # Cholesterol in HDL
    "13457-7": 386.654,  # Cholesterol in LDL (calculated)
    "2089-1": 386.654,   # Cholesterol in LDL
    "2571-8": 885.45,    # Triglyceride
    "2160-0": 113.12,    # Creatinine
}


@dataclass(frozen=True)
class CuratedUnitSpec:
    """Specification for a curated clinical/UCUM unit recognized by Carefold."""

    canonical_ucum_code: str
    display_unit: str
    dimension: str
    pint_unit: Optional[str]
    default_target_ucum_code: str
    default_target_display: str


# Curated lookup of input unit strings (case-folded or exact) -> CuratedUnitSpec
_CURATED_UNIT_SPECS_BY_TOKEN: Dict[str, CuratedUnitSpec] = {}


def _register_unit_spec(aliases: Sequence[str], spec: CuratedUnitSpec) -> None:
    for alias in aliases:
        _CURATED_UNIT_SPECS_BY_TOKEN[alias.strip()] = spec
        _CURATED_UNIT_SPECS_BY_TOKEN[alias.strip().lower()] = spec


# 1. Mass / Body weight ([lb_av]/lbs <-> kg, [oz_av]/oz -> kg, g <-> kg)
_register_unit_spec(
    ("[lb_av]", "lb_av", "lb", "lbs", "pound", "pounds", "[lb_av]/lbs"),
    CuratedUnitSpec(
        canonical_ucum_code="[lb_av]",
        display_unit="lb",
        dimension="mass",
        pint_unit="pound",
        default_target_ucum_code="kg",
        default_target_display="kg",
    ),
)
_register_unit_spec(
    ("[oz_av]", "oz_av", "oz", "ounce", "ounces"),
    CuratedUnitSpec(
        canonical_ucum_code="[oz_av]",
        display_unit="oz",
        dimension="mass",
        pint_unit="ounce",
        default_target_ucum_code="kg",
        default_target_display="kg",
    ),
)
_register_unit_spec(
    ("kg", "kilogram", "kilograms"),
    CuratedUnitSpec(
        canonical_ucum_code="kg",
        display_unit="kg",
        dimension="mass",
        pint_unit="kilogram",
        default_target_ucum_code="kg",
        default_target_display="kg",
    ),
)
_register_unit_spec(
    ("g", "gram", "grams"),
    CuratedUnitSpec(
        canonical_ucum_code="g",
        display_unit="g",
        dimension="mass",
        pint_unit="gram",
        default_target_ucum_code="g",
        default_target_display="g",
    ),
)

# 2. Temperature ([degF]/°F <-> Cel/°C)
_register_unit_spec(
    ("[degF]", "[degf]", "degF", "degf", "°F", "°f", "fahrenheit"),
    CuratedUnitSpec(
        canonical_ucum_code="[degF]",
        display_unit="degF",
        dimension="temperature",
        pint_unit="degF",
        default_target_ucum_code="Cel",
        default_target_display="Cel",
    ),
)
_register_unit_spec(
    ("Cel", "cel", "degC", "degc", "°C", "°c", "celsius"),
    CuratedUnitSpec(
        canonical_ucum_code="Cel",
        display_unit="Cel",
        dimension="temperature",
        pint_unit="degC",
        default_target_ucum_code="Cel",
        default_target_display="Cel",
    ),
)

# 3. Length / Body height ([in_i]/in <-> cm, [ft_i]/ft -> cm, m <-> cm)
_register_unit_spec(
    ("[in_i]", "in_i", "in", "inch", "inches"),
    CuratedUnitSpec(
        canonical_ucum_code="[in_i]",
        display_unit="in",
        dimension="length",
        pint_unit="inch",
        default_target_ucum_code="cm",
        default_target_display="cm",
    ),
)
_register_unit_spec(
    ("[ft_i]", "ft_i", "ft", "foot", "feet"),
    CuratedUnitSpec(
        canonical_ucum_code="[ft_i]",
        display_unit="ft",
        dimension="length",
        pint_unit="foot",
        default_target_ucum_code="cm",
        default_target_display="cm",
    ),
)
_register_unit_spec(
    ("cm", "centimeter", "centimeters"),
    CuratedUnitSpec(
        canonical_ucum_code="cm",
        display_unit="cm",
        dimension="length",
        pint_unit="centimeter",
        default_target_ucum_code="cm",
        default_target_display="cm",
    ),
)
_register_unit_spec(
    ("m", "meter", "meters"),
    CuratedUnitSpec(
        canonical_ucum_code="m",
        display_unit="m",
        dimension="length",
        pint_unit="meter",
        default_target_ucum_code="m",
        default_target_display="m",
    ),
)
_register_unit_spec(
    ("mm", "millimeter", "millimeters"),
    CuratedUnitSpec(
        canonical_ucum_code="mm",
        display_unit="mm",
        dimension="length",
        pint_unit="millimeter",
        default_target_ucum_code="mm",
        default_target_display="mm",
    ),
)

# 4. Curated Lab Concentration & Clinical Units
_register_unit_spec(
    ("mg/dL", "mg/dl"),
    CuratedUnitSpec(
        canonical_ucum_code="mg/dL",
        display_unit="mg/dL",
        dimension="mass_concentration",
        pint_unit="milligram / deciliter",
        default_target_ucum_code="mg/dL",
        default_target_display="mg/dL",
    ),
)
_register_unit_spec(
    ("g/dL", "g/dl"),
    CuratedUnitSpec(
        canonical_ucum_code="g/dL",
        display_unit="g/dL",
        dimension="mass_concentration",
        pint_unit="gram / deciliter",
        default_target_ucum_code="g/dL",
        default_target_display="g/dL",
    ),
)
_register_unit_spec(
    ("mmol/L", "mmol/l"),
    CuratedUnitSpec(
        canonical_ucum_code="mmol/L",
        display_unit="mmol/L",
        dimension="molar_concentration",
        pint_unit="millimole / liter",
        default_target_ucum_code="mmol/L",
        default_target_display="mmol/L",
    ),
)
_register_unit_spec(
    ("umol/L", "umol/l", "µmol/L", "µmol/l", "mcmol/L"),
    CuratedUnitSpec(
        canonical_ucum_code="umol/L",
        display_unit="umol/L",
        dimension="molar_concentration",
        pint_unit="micromole / liter",
        default_target_ucum_code="umol/L",
        default_target_display="umol/L",
    ),
)
_register_unit_spec(
    ("mm[Hg]", "mm[hg]", "mmHg", "mmhg", "mm Hg"),
    CuratedUnitSpec(
        canonical_ucum_code="mm[Hg]",
        display_unit="mmHg",
        dimension="pressure",
        pint_unit="mmHg",
        default_target_ucum_code="mm[Hg]",
        default_target_display="mmHg",
    ),
)
_register_unit_spec(
    ("%", "percent"),
    CuratedUnitSpec(
        canonical_ucum_code="%",
        display_unit="%",
        dimension="percent",
        pint_unit=None,
        default_target_ucum_code="%",
        default_target_display="%",
    ),
)
_register_unit_spec(
    ("/min", "{beats}/min", "beats/min", "bpm", "count/min", "{breaths}/min", "breaths/min"),
    CuratedUnitSpec(
        canonical_ucum_code="/min",
        display_unit="/min",
        dimension="rate",
        pint_unit="1 / minute",
        default_target_ucum_code="/min",
        default_target_display="/min",
    ),
)
_register_unit_spec(
    ("kg/m2", "kg/m^2"),
    CuratedUnitSpec(
        canonical_ucum_code="kg/m2",
        display_unit="kg/m2",
        dimension="bmi",
        pint_unit="kilogram / meter ** 2",
        default_target_ucum_code="kg/m2",
        default_target_display="kg/m2",
    ),
)
_register_unit_spec(
    ("kcal", "Cal"),
    CuratedUnitSpec(
        canonical_ucum_code="kcal",
        display_unit="kcal",
        dimension="energy",
        pint_unit="kilocalorie",
        default_target_ucum_code="kcal",
        default_target_display="kcal",
    ),
)
_register_unit_spec(
    ("h", "hr", "hrs", "hour", "hours"),
    CuratedUnitSpec(
        canonical_ucum_code="h",
        display_unit="h",
        dimension="time",
        pint_unit="hour",
        default_target_ucum_code="h",
        default_target_display="h",
    ),
)
_register_unit_spec(
    ("steps", "count", "{steps}", "{count}"),
    CuratedUnitSpec(
        canonical_ucum_code="{count}",
        display_unit="steps",
        dimension="count",
        pint_unit=None,
        default_target_ucum_code="{count}",
        default_target_display="steps",
    ),
)
_register_unit_spec(
    ("mL/min/{1.73_m2}", "mL/min/1.73m2", "ml/min/1.73m2"),
    CuratedUnitSpec(
        canonical_ucum_code="mL/min/{1.73_m2}",
        display_unit="mL/min/1.73m2",
        dimension="filtration_rate",
        pint_unit=None,
        default_target_ucum_code="mL/min/{1.73_m2}",
        default_target_display="mL/min/1.73m2",
    ),
)
_register_unit_spec(
    ("u[IU]/mL", "uIU/mL", "mIU/L", "miu/l"),
    CuratedUnitSpec(
        canonical_ucum_code="u[IU]/mL",
        display_unit="uIU/mL",
        dimension="arbitrary_concentration",
        pint_unit=None,
        default_target_ucum_code="u[IU]/mL",
        default_target_display="uIU/mL",
    ),
)
_register_unit_spec(
    ("10*3/uL", "10*3/ul", "K/uL", "k/ul"),
    CuratedUnitSpec(
        canonical_ucum_code="10*3/uL",
        display_unit="10*3/uL",
        dimension="cell_concentration",
        pint_unit=None,
        default_target_ucum_code="10*3/uL",
        default_target_display="10*3/uL",
    ),
)


def _lookup_curated_unit_spec(raw_unit: Optional[str]) -> Optional[CuratedUnitSpec]:
    if not raw_unit or not isinstance(raw_unit, str):
        return None
    clean = raw_unit.strip()
    if not clean:
        return None
    return _CURATED_UNIT_SPECS_BY_TOKEN.get(clean) or _CURATED_UNIT_SPECS_BY_TOKEN.get(clean.lower())


@dataclass
class CuratedUnitConversionResult:
    """Outcome of converting or inspecting a quantity against Carefold's curated UCUM unit table."""

    status: str  # 'converted', 'already_canonical', 'kept_as_is_unknown_unit', 'kept_as_is_unconvertible', 'invalid_value'
    value: Any
    unit: Optional[str]
    code: Optional[str]
    system: Optional[str]
    original_value: Any
    original_unit: Optional[str]
    original_code: Optional[str]
    original_system: Optional[str]
    converted: bool = False
    flagged: bool = False
    diagnostic: Optional[FhirDiagnostic] = None

    def to_metadata_dict(self, field_path: str = "valueQuantity") -> Dict[str, Any]:
        return {
            "field_path": field_path,
            "status": self.status,
            "converted": self.converted,
            "flagged": self.flagged,
            "original_value": self.original_value,
            "original_unit": self.original_unit,
            "original_code": self.original_code,
            "normalized_value": self.value,
            "normalized_unit": self.unit,
            "normalized_code": self.code,
        }


def convert_curated_ucum_quantity(
    value: Any,
    from_unit: Optional[str],
    *,
    to_unit: Optional[str] = None,
    loinc_code: Optional[str] = None,
    from_code: Optional[str] = None,
    from_system: Optional[str] = None,
    field_path: str = "valueQuantity",
    entry_index: Optional[int] = None,
    resource_type: str = "Observation",
    source_id: Optional[str] = None,
    precision: int = 2,
) -> CuratedUnitConversionResult:
    """Converts a numeric clinical measurement between curated UCUM units via `pint`.

    Note: This function performs numeric unit conversion for a curated allowlist of UCUM/clinical
    units. It is NOT a general UCUM syntax validator. Unknown or unmapped units are kept as-is
    and flagged with a PHI-safe diagnostic, never guessed.
    """
    raw_unit_token = (from_code or from_unit or "").strip() or (from_unit or "").strip()
    orig_unit_str = str(from_unit).strip() if from_unit is not None and str(from_unit).strip() else None
    orig_code_str = str(from_code).strip() if from_code is not None and str(from_code).strip() else None
    orig_sys_str = str(from_system).strip() if from_system is not None and str(from_system).strip() else None

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            num_val = float(value)
        except (ValueError, TypeError):
            diag = FhirDiagnostic(
                code="invalid_numeric_quantity_value",
                severity="warning",
                message="Quantity value is not a finite number; kept as-is without unit conversion.",
                entry_index=entry_index,
                resource_type=resource_type,
                source_id=source_id,
                field_paths=(field_path,),
            )
            return CuratedUnitConversionResult(
                status="invalid_value",
                value=value,
                unit=orig_unit_str,
                code=orig_code_str,
                system=orig_sys_str,
                original_value=value,
                original_unit=orig_unit_str,
                original_code=orig_code_str,
                original_system=orig_sys_str,
                converted=False,
                flagged=True,
                diagnostic=diag,
            )
    else:
        num_val = float(value)

    if not math.isfinite(num_val):
        diag = FhirDiagnostic(
            code="non_finite_quantity_value",
            severity="warning",
            message="Quantity value is NaN or infinite; kept as-is and flagged.",
            entry_index=entry_index,
            resource_type=resource_type,
            source_id=source_id,
            field_paths=(field_path,),
        )
        return CuratedUnitConversionResult(
            status="invalid_value",
            value=value,
            unit=orig_unit_str,
            code=orig_code_str,
            system=orig_sys_str,
            original_value=value,
            original_unit=orig_unit_str,
            original_code=orig_code_str,
            original_system=orig_sys_str,
            converted=False,
            flagged=True,
            diagnostic=diag,
        )

    source_spec = _lookup_curated_unit_spec(raw_unit_token) or _lookup_curated_unit_spec(orig_unit_str)
    if source_spec is None:
        diag = FhirDiagnostic(
            code="unknown_or_unmapped_unit",
            severity="warning",
            message="Quantity unit is not in Carefold's curated UCUM unit conversion table; kept as-is.",
            entry_index=entry_index,
            resource_type=resource_type,
            source_id=source_id,
            field_paths=(field_path,),
        )
        return CuratedUnitConversionResult(
            status="kept_as_is_unknown_unit",
            value=value,
            unit=orig_unit_str,
            code=orig_code_str,
            system=orig_sys_str,
            original_value=value,
            original_unit=orig_unit_str,
            original_code=orig_code_str,
            original_system=orig_sys_str,
            converted=False,
            flagged=True,
            diagnostic=diag,
        )

    clean_loinc = (loinc_code or "").strip()
    curated_loinc_entry = CURATED_CLINICAL_CODES.get((LOINC_SYSTEM, clean_loinc)) if clean_loinc else None

    # Determine target unit specification
    target_spec: Optional[CuratedUnitSpec] = None
    if to_unit and str(to_unit).strip():
        target_spec = _lookup_curated_unit_spec(str(to_unit).strip())
        if target_spec is None:
            diag = FhirDiagnostic(
                code="unknown_target_unit",
                severity="warning",
                message="Requested target unit is not in Carefold's curated UCUM unit conversion table; kept as-is.",
                entry_index=entry_index,
                resource_type=resource_type,
                source_id=source_id,
                field_paths=(field_path,),
            )
            return CuratedUnitConversionResult(
                status="kept_as_is_unknown_unit",
                value=value,
                unit=orig_unit_str,
                code=orig_code_str,
                system=orig_sys_str,
                original_value=value,
                original_unit=orig_unit_str,
                original_code=orig_code_str,
                original_system=orig_sys_str,
                converted=False,
                flagged=True,
                diagnostic=diag,
            )
    elif curated_loinc_entry and curated_loinc_entry.canonical_unit:
        target_spec = _lookup_curated_unit_spec(curated_loinc_entry.canonical_unit)
    else:
        target_spec = _lookup_curated_unit_spec(source_spec.default_target_ucum_code)

    if target_spec is None:
        target_spec = source_spec

    # Check if already in canonical target unit
    if source_spec.canonical_ucum_code == target_spec.canonical_ucum_code:
        # Preserve original display string if it is a standard human-readable synonym (e.g. 'bpm', 'steps', 'mmHg')
        final_unit = orig_unit_str or target_spec.display_unit
        if target_spec.canonical_ucum_code in ("kg", "cm", "Cel", "mg/dL", "g/dL", "mmol/L", "%"):
            final_unit = target_spec.display_unit
        return CuratedUnitConversionResult(
            status="already_canonical",
            value=value,
            unit=final_unit,
            code=target_spec.canonical_ucum_code,
            system=UCUM_SYSTEM,
            original_value=value,
            original_unit=orig_unit_str,
            original_code=orig_code_str,
            original_system=orig_sys_str,
            converted=False,
            flagged=False,
            diagnostic=None,
        )

    # Check if conversion requires molar <-> mass concentration with analyte molecular weight
    if {source_spec.dimension, target_spec.dimension} == {"molar_concentration", "mass_concentration"}:
        mw_g_mol = CURATED_ANALYTE_MOLECULAR_WEIGHTS.get(clean_loinc)
        if mw_g_mol is None or not source_spec.pint_unit or not target_spec.pint_unit:
            diag = FhirDiagnostic(
                code="unconvertible_molar_mass_without_analyte",
                severity="warning",
                message=(
                    "Cannot convert between molar and mass concentration without a curated analyte "
                    "LOINC code and molecular weight; quantity kept as-is."
                ),
                entry_index=entry_index,
                resource_type=resource_type,
                source_id=source_id,
                field_paths=(field_path,),
            )
            return CuratedUnitConversionResult(
                status="kept_as_is_unconvertible",
                value=value,
                unit=orig_unit_str,
                code=orig_code_str,
                system=orig_sys_str,
                original_value=value,
                original_unit=orig_unit_str,
                original_code=orig_code_str,
                original_system=orig_sys_str,
                converted=False,
                flagged=True,
                diagnostic=diag,
            )

        ctx = pint.Context()
        mw_quantity = mw_g_mol * _UREG("gram / mole")
        ctx.add_transformation(
            "[substance] / [volume]",
            "[mass] / [volume]",
            lambda _u, x: x * mw_quantity,
        )
        ctx.add_transformation(
            "[mass] / [volume]",
            "[substance] / [volume]",
            lambda _u, x: x / mw_quantity,
        )
        converted_mag = float(
            _UREG.Quantity(num_val, source_spec.pint_unit).to(target_spec.pint_unit, ctx).magnitude
        )
        rounded_val = round(converted_mag, precision)
        return CuratedUnitConversionResult(
            status="converted",
            value=rounded_val,
            unit=target_spec.display_unit,
            code=target_spec.canonical_ucum_code,
            system=UCUM_SYSTEM,
            original_value=value,
            original_unit=orig_unit_str or source_spec.canonical_ucum_code,
            original_code=orig_code_str or source_spec.canonical_ucum_code,
            original_system=orig_sys_str or UCUM_SYSTEM,
            converted=True,
            flagged=False,
            diagnostic=None,
        )

    # Same-dimension physical unit conversion via Pint (mass, temperature, length)
    if source_spec.dimension != target_spec.dimension or not source_spec.pint_unit or not target_spec.pint_unit:
        diag = FhirDiagnostic(
            code="incompatible_unit_dimensions",
            severity="warning",
            message="Quantity unit dimension is incompatible with the expected target unit; kept as-is.",
            entry_index=entry_index,
            resource_type=resource_type,
            source_id=source_id,
            field_paths=(field_path,),
        )
        return CuratedUnitConversionResult(
            status="kept_as_is_unconvertible",
            value=value,
            unit=orig_unit_str,
            code=orig_code_str,
            system=orig_sys_str,
            original_value=value,
            original_unit=orig_unit_str,
            original_code=orig_code_str,
            original_system=orig_sys_str,
            converted=False,
            flagged=True,
            diagnostic=diag,
        )

    converted_mag = float(
        _UREG.Quantity(num_val, source_spec.pint_unit).to(target_spec.pint_unit).magnitude
    )
    rounded_val = round(converted_mag, precision)
    return CuratedUnitConversionResult(
        status="converted",
        value=rounded_val,
        unit=target_spec.display_unit,
        code=target_spec.canonical_ucum_code,
        system=UCUM_SYSTEM,
        original_value=value,
        original_unit=orig_unit_str or source_spec.canonical_ucum_code,
        original_code=orig_code_str or source_spec.canonical_ucum_code,
        original_system=orig_sys_str or UCUM_SYSTEM,
        converted=True,
        flagged=False,
        diagnostic=None,
    )


# ============================================================================
# Section 4: CodeSystem URI & Resource Terminology Normalization
# ============================================================================

@dataclass(frozen=True)
class SystemNormalizationOutcome:
    """Result of normalizing a raw CodeSystem OID, mnemonic, or URI."""

    canonical_system: Optional[str]
    original_system: Optional[str]
    was_normalized: bool
    is_known_system: bool


def normalize_code_system_uri(
    raw_system: Optional[str],
    *,
    code: Optional[str] = None,
    resource_type: Optional[str] = None,
) -> SystemNormalizationOutcome:
    """Normalizes a legacy HL7 OID (`urn:oid:...`), HL7v2 mnemonic, or URI to its canonical FHIR R4 URI.

    Never invents a system mapping for unknown OIDs/URIs. When `raw_system` is missing or the
    internal C-CDA placeholder `'urn:oid:ccda'`, resolves the system ONLY if `(resource_type, code)`
    is explicitly present in `CURATED_CLINICAL_CODES`.
    """
    orig = str(raw_system).strip() if raw_system is not None and str(raw_system).strip() else None
    clean_code = str(code).strip() if code is not None and str(code).strip() else None
    clean_rtype = str(resource_type).strip() if resource_type is not None and str(resource_type).strip() else None

    if not orig or orig == "urn:oid:ccda":
        if clean_rtype and clean_code:
            curated = _CURATED_CODE_BY_RESOURCE_AND_CODE.get((clean_rtype, clean_code))
            if curated is not None:
                return SystemNormalizationOutcome(
                    canonical_system=curated.system,
                    original_system=orig,
                    was_normalized=True,
                    is_known_system=True,
                )
        return SystemNormalizationOutcome(
            canonical_system=orig,
            original_system=orig,
            was_normalized=False,
            is_known_system=False,
        )

    trimmed = orig.rstrip("/")
    lower = trimmed.lower()

    # 1. Check urn:oid:<oid> or bare OID
    if lower.startswith("urn:oid:"):
        oid_body = lower[len("urn:oid:") :].strip()
        if oid_body in OID_TO_CANONICAL_SYSTEM_URI:
            canonical = OID_TO_CANONICAL_SYSTEM_URI[oid_body]
            return SystemNormalizationOutcome(
                canonical_system=canonical,
                original_system=orig,
                was_normalized=(canonical != orig),
                is_known_system=True,
            )
    elif lower in OID_TO_CANONICAL_SYSTEM_URI:
        canonical = OID_TO_CANONICAL_SYSTEM_URI[lower]
        return SystemNormalizationOutcome(
            canonical_system=canonical,
            original_system=orig,
            was_normalized=(canonical != orig),
            is_known_system=True,
        )

    # 2. Check alias/mnemonic table
    if lower in ALIAS_TO_CANONICAL_SYSTEM_URI:
        canonical = ALIAS_TO_CANONICAL_SYSTEM_URI[lower]
        return SystemNormalizationOutcome(
            canonical_system=canonical,
            original_system=orig,
            was_normalized=(canonical != orig),
            is_known_system=True,
        )

    # 3. Check standard HL7 / FHIR terminology namespaces
    if (
        trimmed in CANONICAL_CODE_SYSTEM_URIS
        or lower.startswith("http://terminology.hl7.org/")
        or lower.startswith("http://hl7.org/fhir/")
    ):
        return SystemNormalizationOutcome(
            canonical_system=trimmed,
            original_system=orig,
            was_normalized=(trimmed != orig),
            is_known_system=True,
        )

    # Unknown system URI/OID: pass through untouched
    return SystemNormalizationOutcome(
        canonical_system=orig,
        original_system=orig,
        was_normalized=False,
        is_known_system=False,
    )


def _attach_original_quantity_extension(
    quantity_dict: Dict[str, Any],
    conv: CuratedUnitConversionResult,
) -> None:
    """Attaches the standard HL7 `iso21090-PQ-translation` extension preserving the pre-conversion quantity."""
    orig_vq: Dict[str, Any] = {"value": conv.original_value}
    if conv.original_unit:
        orig_vq["unit"] = conv.original_unit
    if conv.original_system:
        orig_vq["system"] = conv.original_system
    if conv.original_code:
        orig_vq["code"] = conv.original_code

    ext_entry = {
        "url": ORIGINAL_QUANTITY_EXTENSION_URL,
        "valueQuantity": orig_vq,
    }
    existing_exts = quantity_dict.get("extension")
    if not isinstance(existing_exts, list):
        quantity_dict["extension"] = [ext_entry]
        return

    # Avoid duplicating if already attached
    for ext in existing_exts:
        if isinstance(ext, dict) and ext.get("url") == ORIGINAL_QUANTITY_EXTENSION_URL:
            return
    existing_exts.append(ext_entry)


def extract_original_quantity_from_extension(
    quantity_dict: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Extracts the preserved original `valueQuantity` from `Quantity.extension` if present."""
    if not isinstance(quantity_dict, dict):
        return None
    exts = quantity_dict.get("extension")
    if not isinstance(exts, list):
        return None
    for ext in exts:
        if isinstance(ext, dict) and ext.get("url") in (
            ORIGINAL_QUANTITY_EXTENSION_URL,
            "http://carefold.org/fhir/StructureDefinition/original-quantity",
        ):
            vq = ext.get("valueQuantity")
            if isinstance(vq, dict):
                return copy.deepcopy(vq)
    return None


@dataclass
class TerminologyNormalizationResult:
    """Result of normalizing terminology systems, curated codes, and curated UCUM units on a FHIR resource."""

    normalized: Dict[str, Any]
    codings: List[Dict[str, Optional[str]]] = field(default_factory=list)
    terminology_changes: List[Dict[str, Any]] = field(default_factory=list)
    unit_conversions: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: List[FhirDiagnostic] = field(default_factory=list)
    has_unknown_codes: bool = False
    has_unknown_units: bool = False


def normalize_fhir_terminology_and_units(
    resource: Dict[str, Any],
    *,
    rtype: Optional[str] = None,
    entry_index: Optional[int] = None,
    source_id: Optional[str] = None,
) -> TerminologyNormalizationResult:
    """Normalizes CodeSystem OIDs/URIs and curated Observation units on a FHIR R4 resource dict.

    Guarantees:
    - Legacy HL7 OIDs and aliases in `Coding.system` are normalized to canonical HL7 FHIR R4 URIs.
    - Codes in `CURATED_CLINICAL_CODES` enrich missing `display` fields without overwriting user/source text.
    - Codes not in `CURATED_CLINICAL_CODES` or with unknown systems are kept untouched and emit a
      PHI-safe `FhirDiagnostic`.
    - Curated `Observation` units (`[lb_av]`/`lbs` -> `kg`, `[degF]`/`°F` -> `Cel`, `[in_i]`/`in` -> `cm`,
      and curated analyte `mmol/L` -> `mg/dL`) are converted deterministically via `pint` with the
      original `valueQuantity` preserved in `valueQuantity.extension`.
    - Unknown or unconvertible units are kept as-is and flagged with a PHI-safe `FhirDiagnostic`.
    """
    if not isinstance(resource, dict):
        return TerminologyNormalizationResult(normalized={})

    normalized = copy.deepcopy(resource)
    resolved_type = (rtype or str(normalized.get("resourceType") or "")).strip()
    terminology_changes: List[Dict[str, Any]] = []
    unit_conversions: List[Dict[str, Any]] = []
    diagnostics: List[FhirDiagnostic] = []
    has_unknown_codes = False
    has_unknown_units = False

    # 1. Walk and normalize all Coding dictionaries across the resource
    def _walk_and_normalize_codings(node: Any, path_prefix: str) -> None:
        nonlocal has_unknown_codes
        if isinstance(node, dict):
            if "coding" in node and isinstance(node["coding"], list):
                for c_idx, c_item in enumerate(node["coding"]):
                    if not isinstance(c_item, dict):
                        continue
                    raw_code = c_item.get("code")
                    code_str = str(raw_code).strip() if raw_code is not None and str(raw_code).strip() else None
                    raw_sys = c_item.get("system")
                    field_loc = f"{path_prefix}.coding[{c_idx}]" if path_prefix else f"coding[{c_idx}]"

                    sys_outcome = normalize_code_system_uri(
                        raw_sys,
                        code=code_str,
                        resource_type=resolved_type,
                    )
                    if sys_outcome.was_normalized and sys_outcome.canonical_system:
                        c_item["system"] = sys_outcome.canonical_system
                        terminology_changes.append({
                            "field_path": field_loc,
                            "code": code_str,
                            "original_system": sys_outcome.original_system,
                            "canonical_system": sys_outcome.canonical_system,
                        })

                    eff_sys = c_item.get("system")
                    if not code_str or code_str.lower() == "unknown":
                        has_unknown_codes = True
                        diagnostics.append(
                            FhirDiagnostic(
                                code="missing_or_unknown_coding_code",
                                severity="warning",
                                message="Coding entry has a missing or 'unknown' code; passed through untouched.",
                                entry_index=entry_index,
                                resource_type=resolved_type or None,
                                source_id=source_id,
                                field_paths=(field_loc,),
                            )
                        )
                        continue

                    if not sys_outcome.is_known_system:
                        has_unknown_codes = True
                        diagnostics.append(
                            FhirDiagnostic(
                                code="unknown_or_unmapped_code_system",
                                severity="warning",
                                message="Coding system URI/OID is not in Carefold's canonical registry; passed through untouched.",
                                entry_index=entry_index,
                                resource_type=resolved_type or None,
                                source_id=source_id,
                                field_paths=(field_loc,),
                            )
                        )
                        continue

                    # Check curated lookup table for clinical code sistemas
                    if eff_sys in (
                        LOINC_SYSTEM,
                        SNOMED_CT_SYSTEM,
                        RXNORM_SYSTEM,
                        ICD10_CM_SYSTEM,
                        ICD10_WHO_SYSTEM,
                        CVX_SYSTEM,
                        CPT_SYSTEM,
                        HCPCS_SYSTEM,
                        NDC_SYSTEM,
                    ):
                        curated_entry = CURATED_CLINICAL_CODES.get(( str(eff_sys), code_str ))
                        if curated_entry is not None:
                            if not c_item.get("display"):
                                c_item["display"] = curated_entry.display
                        else:
                            has_unknown_codes = True
                            diagnostics.append(
                                FhirDiagnostic(
                                    code="unrecognized_curated_code",
                                    severity="info",
                                    message=(
                                        "Clinical code is not in Carefold's small license-safe curated subset; "
                                        "passed through untouched without invented mapping."
                                    ),
                                    entry_index=entry_index,
                                    resource_type=resolved_type or None,
                                    source_id=source_id,
                                    field_paths=(field_loc,),
                                )
                            )

            for k, v in node.items():
                if k in ("_carefold_provenance", "contained", "text", "meta", "extension"):
                    continue
                child_path = f"{path_prefix}.{k}" if path_prefix else k
                _walk_and_normalize_codings(v, child_path)
        elif isinstance(node, list):
            for elem in node:
                _walk_and_normalize_codings(elem, path_prefix)

    _walk_and_normalize_codings(normalized, "")

    # 2. Extract primary LOINC code on Observation for context-aware unit conversion
    primary_loinc_code: Optional[str] = None
    if resolved_type == "Observation":
        code_obj = normalized.get("code")
        if isinstance(code_obj, dict) and isinstance(code_obj.get("coding"), list):
            for c_entry in code_obj["coding"]:
                if isinstance(c_entry, dict) and c_entry.get("system") == LOINC_SYSTEM and c_entry.get("code"):
                    primary_loinc_code = str(c_entry["code"]).strip()
                    break
            if not primary_loinc_code and code_obj["coding"] and isinstance(code_obj["coding"][0], dict):
                primary_loinc_code = str(code_obj["coding"][0].get("code") or "").strip() or None

        # Normalize top-level valueQuantity if present
        vq = normalized.get("valueQuantity")
        if isinstance(vq, dict) and "value" in vq:
            # Normalize valueQuantity.system if it was a UCUM OID
            if vq.get("system"):
                vq_sys = normalize_code_system_uri(vq.get("system"))
                if vq_sys.canonical_system:
                    vq["system"] = vq_sys.canonical_system

            conv = convert_curated_ucum_quantity(
                vq.get("value"),
                vq.get("unit"),
                loinc_code=primary_loinc_code,
                from_code=vq.get("code"),
                from_system=vq.get("system"),
                field_path="valueQuantity",
                entry_index=entry_index,
                resource_type=resolved_type,
                source_id=source_id,
            )
            if conv.converted:
                _attach_original_quantity_extension(vq, conv)
                vq["value"] = conv.value
                vq["unit"] = conv.unit
                vq["code"] = conv.code
                vq["system"] = conv.system
                unit_conversions.append(conv.to_metadata_dict("valueQuantity"))
            elif conv.status == "already_canonical":
                if conv.system and not vq.get("system"):
                    vq["system"] = conv.system
                if conv.code and not vq.get("code"):
                    vq["code"] = conv.code
            elif conv.flagged:
                has_unknown_units = True
                unit_conversions.append(conv.to_metadata_dict("valueQuantity"))
                if conv.diagnostic is not None:
                    diagnostics.append(conv.diagnostic)

        # Normalize component[*].valueQuantity if present
        components = normalized.get("component")
        if isinstance(components, list):
            for comp_idx, comp in enumerate(components):
                if not isinstance(comp, dict):
                    continue
                comp_vq = comp.get("valueQuantity")
                if not isinstance(comp_vq, dict) or "value" not in comp_vq:
                    continue
                comp_loinc: Optional[str] = None
                comp_code_obj = comp.get("code")
                if isinstance(comp_code_obj, dict) and isinstance(comp_code_obj.get("coding"), list):
                    for cc in comp_code_obj["coding"]:
                        if isinstance(cc, dict) and cc.get("system") == LOINC_SYSTEM and cc.get("code"):
                            comp_loinc = str(cc["code"]).strip()
                            break
                comp_path = f"component[{comp_idx}].valueQuantity"
                comp_conv = convert_curated_ucum_quantity(
                    comp_vq.get("value"),
                    comp_vq.get("unit"),
                    loinc_code=comp_loinc or primary_loinc_code,
                    from_code=comp_vq.get("code"),
                    from_system=comp_vq.get("system"),
                    field_path=comp_path,
                    entry_index=entry_index,
                    resource_type=resolved_type,
                    source_id=source_id,
                )
                if comp_conv.converted:
                    _attach_original_quantity_extension(comp_vq, comp_conv)
                    comp_vq["value"] = comp_conv.value
                    comp_vq["unit"] = comp_conv.unit
                    comp_vq["code"] = comp_conv.code
                    comp_vq["system"] = comp_conv.system
                    unit_conversions.append(comp_conv.to_metadata_dict(comp_path))
                elif comp_conv.status == "already_canonical":
                    if comp_conv.system and not comp_vq.get("system"):
                        comp_vq["system"] = comp_conv.system
                    if comp_conv.code and not comp_vq.get("code"):
                        comp_vq["code"] = comp_conv.code
                elif comp_conv.flagged:
                    has_unknown_units = True
                    unit_conversions.append(comp_conv.to_metadata_dict(comp_path))
                    if comp_conv.diagnostic is not None:
                        diagnostics.append(comp_conv.diagnostic)

    # 3. Record normalization audit metadata in _carefold_provenance if present or when changes occurred
    if terminology_changes or unit_conversions or isinstance(normalized.get("_carefold_provenance"), dict):
        prov = (
            normalized.setdefault("_carefold_provenance", {})
            if isinstance(normalized.get("_carefold_provenance"), dict)
            else {}
        )
        if not isinstance(prov, dict):
            prov = {}
            normalized["_carefold_provenance"] = prov
        prov.setdefault("trust", "untrusted")
        if terminology_changes:
            prov["terminology_normalizations"] = terminology_changes
        if unit_conversions:
            prov["unit_conversions"] = unit_conversions
            converted_originals = [
                u for u in unit_conversions if u.get("converted")
            ]
            if converted_originals:
                prov["original_quantities"] = converted_originals

    codings = extract_codings(normalized, rtype=resolved_type)
    return TerminologyNormalizationResult(
        normalized=normalized,
        codings=codings,
        terminology_changes=terminology_changes,
        unit_conversions=unit_conversions,
        diagnostics=diagnostics,
        has_unknown_codes=has_unknown_codes,
        has_unknown_units=has_unknown_units,
    )


def get_curated_concept_group(system: Optional[str], code: Optional[str]) -> Optional[str]:
    """Returns the curated cross-system concept group tag for `(system, code)` if defined, else None."""
    if not system or not code:
        return None
    entry = CURATED_CLINICAL_CODES.get((str(system).strip(), str(code).strip()))
    return entry.concept_group if entry is not None else None


__all__ = [
    "ALIAS_TO_CANONICAL_SYSTEM_URI",
    "ALLERGY_CLINICAL_SYSTEM",
    "ALLERGY_VER_STATUS_SYSTEM",
    "CANONICAL_CODE_SYSTEM_URIS",
    "CONDITION_CLINICAL_SYSTEM",
    "CONDITION_VER_STATUS_SYSTEM",
    "CPT_SYSTEM",
    "CURATED_ANALYTE_MOLECULAR_WEIGHTS",
    "CURATED_CLINICAL_CODES",
    "CVX_SYSTEM",
    "HCPCS_SYSTEM",
    "ICD10_CM_SYSTEM",
    "ICD10_WHO_SYSTEM",
    "LOINC_SYSTEM",
    "NDC_SYSTEM",
    "OBSERVATION_CATEGORY_SYSTEM",
    "OID_TO_CANONICAL_SYSTEM_URI",
    "ORIGINAL_QUANTITY_EXTENSION_URL",
    "RXNORM_SYSTEM",
    "SNOMED_CT_SYSTEM",
    "TERMINOLOGY_CAPABILITIES",
    "UCUM_SYSTEM",
    "UNIT_CONVERSION_CAPABILITIES",
    "UNII_SYSTEM",
    "V3_ACT_CODE_SYSTEM",
    "CuratedCodeEntry",
    "CuratedUnitConversionResult",
    "CuratedUnitSpec",
    "SystemNormalizationOutcome",
    "TerminologyNormalizationResult",
    "convert_curated_ucum_quantity",
    "extract_original_quantity_from_extension",
    "get_curated_concept_group",
    "normalize_code_system_uri",
    "normalize_fhir_terminology_and_units",
]
