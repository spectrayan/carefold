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

"""Declarative HL7 FHIR R4 (4.0.1) resource registry, validation wrapper, and element extractor (#281).

Standards & Library Compatibility Notes:
- Carefold targets **HL7 FHIR R4 (`4.0.1`)** across an explicit allowlist of 33 clinical,
  diagnostic, care-plan, demographic, and administrative/payer resource types.
- Carefold uses `fhir.resources` (`v8.3.0`, Pydantic v2 `fhir-core`), which ships
  `fhir.resources.R4B` (`__fhir_version__ == "4.3.0"`) as its 4.x model package
  (`fhir.resources` 6.x targeted `4.0.1` on Pydantic v1 and is incompatible with Pydantic v2).
- Across the 33 allowlisted resource types in `SUPPORTED_FHIR_RESOURCE_TYPES`, HL7 FHIR R4B
  (`4.3.0`) preserves structural and wire compatibility with HL7 FHIR R4 (`4.0.1`).
- This module enforces an explicit R4 (`4.0.1`) allowlist, rejects R4B-only resource types
  (e.g., `Citation`, `EvidenceReport`, `SubscriptionStatus`, `AdministrableProductDefinition`)
  and R4B-only `CodeableReference` shapes, and documents that Pydantic model validation
  establishes **base FHIR structural and datatype validity only**—it does **not** perform
  HL7 US Core IG or HL7 International Patient Summary (IPS) StructureDefinition, slicing,
  ValueSet binding, or MustSupport profile validation.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse

from fhir.resources.R4B import (
    __fhir_version__ as _R4B_LIBRARY_VERSION,
    get_fhir_model_class as _get_r4b_model_class,
)
from pydantic import ValidationError

try:
    import fhirpathpy as _fhirpathpy  # type: ignore[import-not-found]
except ImportError:
    _fhirpathpy = None


# ============================================================================
# Section 1: FHIR R4 (4.0.1) Target & Conformance Metadata
# ============================================================================

TARGET_FHIR_RELEASE: str = "R4"
TARGET_FHIR_VERSION: str = "4.0.1"
MODEL_LIBRARY_PACKAGE: str = "fhir.resources.R4B"
MODEL_LIBRARY_FHIR_VERSION: str = str(_R4B_LIBRARY_VERSION)

FHIR_VALIDATION_CAPABILITIES: Dict[str, Any] = {
    "target_fhir_release": TARGET_FHIR_RELEASE,
    "target_fhir_version": TARGET_FHIR_VERSION,
    "model_library_package": MODEL_LIBRARY_PACKAGE,
    "model_library_fhir_version": MODEL_LIBRARY_FHIR_VERSION,
    "validation_scope": "base_structural_and_datatype_only",
    "us_core_profile_validation": False,
    "ips_profile_validation": False,
    "terminology_valueset_expansion": False,
    "notes": (
        "Validates allowlisted FHIR R4 (4.0.1) resource structures using Pydantic v2 models from "
        "fhir.resources.R4B (4.3.0) with explicit R4 allowlist and R4B-only exclusion guards. "
        "Does not establish HL7 US Core IG or HL7 IPS StructureDefinition profile conformance."
    ),
}


# ============================================================================
# Section 2: Explicit FHIR R4 Resource Allowlist & Scope Routing
# ============================================================================

DEMOGRAPHIC_AND_CARE_TEAM_RESOURCE_TYPES: FrozenSet[str] = frozenset({
    "Patient",
    "RelatedPerson",
    "Practitioner",
    "PractitionerRole",
    "Organization",
    "CareTeam",
    "Location",
})

CLINICAL_CORE_RESOURCE_TYPES: FrozenSet[str] = frozenset({
    "Condition",
    "AllergyIntolerance",
    "MedicationRequest",
    "MedicationStatement",
    "MedicationDispense",
    "Medication",
    "Immunization",
    "Procedure",
    "FamilyMemberHistory",
    "Device",
})

DIAGNOSTIC_AND_VITALS_RESOURCE_TYPES: FrozenSet[str] = frozenset({
    "Observation",
    "DiagnosticReport",
    "ImagingStudy",
    "Specimen",
    "DocumentReference",
    "Media",
})

CARE_PLAN_AND_ADMIN_RESOURCE_TYPES: FrozenSet[str] = frozenset({
    "Encounter",
    "CarePlan",
    "Goal",
    "ServiceRequest",
    "QuestionnaireResponse",
    "Coverage",
    "ExplanationOfBenefit",
    "Consent",
    "Provenance",
    "Composition",
})

SUPPORTED_FHIR_RESOURCE_TYPES: FrozenSet[str] = (
    DEMOGRAPHIC_AND_CARE_TEAM_RESOURCE_TYPES
    | CLINICAL_CORE_RESOURCE_TYPES
    | DIAGNOSTIC_AND_VITALS_RESOURCE_TYPES
    | CARE_PLAN_AND_ADMIN_RESOURCE_TYPES
)

# Resource types introduced or restructured in FHIR R4B (4.3.0) that are NOT part of FHIR R4 (4.0.1)
R4B_ONLY_RESOURCE_TYPES: FrozenSet[str] = frozenset({
    "AdministrableProductDefinition",
    "Citation",
    "ClinicalUseDefinition",
    "EvidenceReport",
    "Ingredient",
    "ManufacturedItemDefinition",
    "MedicinalProductDefinition",
    "PackagedProductDefinition",
    "RegulatedAuthorization",
    "SubscriptionStatus",
    "SubscriptionTopic",
    "SubstanceDefinition",
})

# Financial/insurance/payer FHIR R4 resources route to health.paperwork; clinical/demographic route to health.clinical
PAPERWORK_FHIR_RESOURCE_TYPES: FrozenSet[str] = frozenset({
    "Coverage",
    "ExplanationOfBenefit",
})

CLINICAL_FHIR_RESOURCE_TYPES: FrozenSet[str] = SUPPORTED_FHIR_RESOURCE_TYPES - PAPERWORK_FHIR_RESOURCE_TYPES

INFRASTRUCTURE_AND_ACTOR_RESOURCE_TYPES: FrozenSet[str] = frozenset({
    "Practitioner",
    "PractitionerRole",
    "Organization",
    "Location",
    "Medication",
    "Provenance",
})

PATIENT_SUBJECT_RESOURCE_TYPES: FrozenSet[str] = (
    SUPPORTED_FHIR_RESOURCE_TYPES
    - INFRASTRUCTURE_AND_ACTOR_RESOURCE_TYPES
    - frozenset({"Patient"})
)

# Maps each resource type to the element path(s) holding its primary patient/subject reference
RESOURCE_PATIENT_SUBJECT_PATHS: Dict[str, Tuple[str, ...]] = {
    "Patient": (),
    "RelatedPerson": ("patient",),
    "CareTeam": ("subject",),
    "Condition": ("subject",),
    "AllergyIntolerance": ("patient",),
    "MedicationRequest": ("subject",),
    "MedicationStatement": ("subject",),
    "MedicationDispense": ("subject",),
    "Immunization": ("patient",),
    "Procedure": ("subject",),
    "FamilyMemberHistory": ("patient",),
    "Device": ("patient",),
    "Observation": ("subject",),
    "DiagnosticReport": ("subject",),
    "ImagingStudy": ("subject",),
    "Specimen": ("subject",),
    "DocumentReference": ("subject",),
    "Media": ("subject",),
    "Encounter": ("subject",),
    "CarePlan": ("subject",),
    "Goal": ("subject",),
    "ServiceRequest": ("subject",),
    "QuestionnaireResponse": ("subject",),
    "Coverage": ("beneficiary", "subscriber"),
    "ExplanationOfBenefit": ("patient",),
    "Consent": ("patient",),
    "Composition": ("subject",),
}


def resolve_resource_scope(resource_type: str, resource: Optional[Dict[str, Any]] = None) -> str:
    """Routes a FHIR R4 resource type to its Carefold ScopeContext ('health.clinical' or 'health.paperwork')."""
    clean_type = (resource_type or "").strip()
    if clean_type in PAPERWORK_FHIR_RESOURCE_TYPES:
        return "health.paperwork"
    return "health.clinical"


def get_r4_model_class(resource_type: str) -> Optional[Any]:
    """Returns the Pydantic v2 FHIR model class for an allowlisted FHIR R4 resource type."""
    clean_type = (resource_type or "").strip()
    if not clean_type or clean_type not in SUPPORTED_FHIR_RESOURCE_TYPES:
        return None
    try:
        return _get_r4b_model_class(clean_type)
    except Exception:
        return None


# ============================================================================
# Section 3: Declarative FHIRPath Evaluator & Extraction Expressions
# ============================================================================

# Declarative FHIRPath expressions for primary and secondary CodeableConcept.coding / Coding tuples
DECLARATIVE_CODING_EXPRESSIONS: Dict[str, Tuple[str, ...]] = {
    "*": (
        "code.coding",
        "category.coding",
        "type.coding",
        "clinicalStatus.coding",
        "verificationStatus.coding",
        "severity.coding",
        "bodySite.coding",
        "valueCodeableConcept.coding",
        "interpretation.coding",
        "method.coding",
        "reasonCode.coding",
        "statusReason.coding",
        "statusReasonCodeableConcept.coding",
        "priority.coding",
        "outcome.coding",
    ),
    "Observation": (
        "code.coding",
        "category.coding",
        "valueCodeableConcept.coding",
        "interpretation.coding",
        "bodySite.coding",
        "method.coding",
        "dataAbsentReason.coding",
        "component.code.coding",
        "component.valueCodeableConcept.coding",
        "component.interpretation.coding",
        "component.dataAbsentReason.coding",
    ),
    "Condition": (
        "code.coding",
        "category.coding",
        "clinicalStatus.coding",
        "verificationStatus.coding",
        "severity.coding",
        "bodySite.coding",
        "stage.summary.coding",
        "stage.type.coding",
        "evidence.code.coding",
    ),
    "AllergyIntolerance": (
        "code.coding",
        "clinicalStatus.coding",
        "verificationStatus.coding",
        "reaction.substance.coding",
        "reaction.manifestation.coding",
        "reaction.exposureRoute.coding",
    ),
    "MedicationRequest": (
        "medicationCodeableConcept.coding",
        "category.coding",
        "statusReason.coding",
        "reasonCode.coding",
        "courseOfTherapyType.coding",
        "dosageInstruction.route.coding",
        "dosageInstruction.method.coding",
        "dosageInstruction.site.coding",
        "dosageInstruction.asNeededCodeableConcept.coding",
    ),
    "MedicationStatement": (
        "medicationCodeableConcept.coding",
        "category.coding",
        "statusReason.coding",
        "reasonCode.coding",
        "dosage.route.coding",
        "dosage.method.coding",
        "dosage.site.coding",
    ),
    "MedicationDispense": (
        "medicationCodeableConcept.coding",
        "category.coding",
        "type.coding",
        "statusReasonCodeableConcept.coding",
        "dosageInstruction.route.coding",
    ),
    "Medication": (
        "code.coding",
        "form.coding",
        "ingredient.itemCodeableConcept.coding",
    ),
    "Immunization": (
        "vaccineCode.coding",
        "statusReason.coding",
        "site.coding",
        "route.coding",
        "reasonCode.coding",
        "subpotentReason.coding",
        "ReportOrigin.coding",
        "reportOrigin.coding",
    ),
    "Procedure": (
        "code.coding",
        "category.coding",
        "statusReason.coding",
        "bodySite.coding",
        "outcome.coding",
        "reasonCode.coding",
        "complication.coding",
        "usedCode.coding",
        "focalDevice.action.coding",
    ),
    "DiagnosticReport": (
        "code.coding",
        "category.coding",
        "conclusionCode.coding",
    ),
    "Encounter": (
        "type.coding",
        "serviceType.coding",
        "priority.coding",
        "reasonCode.coding",
        "class",
        "hospitalization.admitSource.coding",
        "hospitalization.dischargeDisposition.coding",
        "participant.type.coding",
    ),
    "DocumentReference": (
        "type.coding",
        "category.coding",
        "securityLabel.coding",
        "context.event.coding",
        "context.facilityType.coding",
        "context.practiceSetting.coding",
        "content.format",
    ),
    "CarePlan": (
        "category.coding",
        "activity.detail.code.coding",
        "activity.detail.ReasonCode.coding",
        "activity.detail.reasonCode.coding",
    ),
    "CareTeam": (
        "category.coding",
        "reasonCode.coding",
        "participant.role.coding",
    ),
    "Goal": (
        "description.coding",
        "category.coding",
        "priority.coding",
        "achievementStatus.coding",
        "startCodeableConcept.coding",
        "statusReason.coding",
        "outcomeCode.coding",
        "target.measure.coding",
        "target.detailCodeableConcept.coding",
    ),
    "ServiceRequest": (
        "code.coding",
        "category.coding",
        "orderDetail.coding",
        "reasonCode.coding",
        "bodySite.coding",
        "asNeededCodeableConcept.coding",
    ),
    "Coverage": (
        "type.coding",
        "relationship.coding",
        "class.type.coding",
    ),
    "ExplanationOfBenefit": (
        "type.coding",
        "subType.coding",
        "diagnosis.diagnosisCodeableConcept.coding",
        "diagnosis.type.coding",
        "procedure.procedureCodeableConcept.coding",
        "item.productOrService.coding",
        "item.category.coding",
        "item.revenue.coding",
    ),
    "FamilyMemberHistory": (
        "relationship.coding",
        "sex.coding",
        "dataAbsentReason.coding",
        "reasonCode.coding",
        "condition.code.coding",
        "condition.outcome.coding",
    ),
    "Specimen": (
        "type.coding",
        "collection.method.coding",
        "collection.bodySite.coding",
        "condition.coding",
    ),
    "ImagingStudy": (
        "modality",
        "reasonCode.coding",
        "procedureCode.coding",
        "series.modality",
        "series.bodySite",
    ),
    "Media": (
        "type.coding",
        "modality.coding",
        "view.coding",
        "reasonCode.coding",
        "bodySite.coding",
    ),
    "PractitionerRole": (
        "code.coding",
        "specialty.coding",
    ),
    "Practitioner": (
        "qualification.code.coding",
    ),
    "Organization": (
        "type.coding",
    ),
    "Location": (
        "type.coding",
        "physicalType.coding",
        "operationalStatus",
    ),
    "RelatedPerson": (
        "relationship.coding",
    ),
    "Device": (
        "type.coding",
        "statusReason.coding",
    ),
    "Composition": (
        "type.coding",
        "category.coding",
        "section.code.coding",
    ),
    "Consent": (
        "scope.coding",
        "category.coding",
        "policyRule.coding",
        "provision.code.coding",
        "provision.class",
        "provision.purpose",
    ),
    "Provenance": (
        "activity.coding",
        "reason.coding",
        "agent.type.coding",
        "agent.role.coding",
    ),
    "QuestionnaireResponse": (
        "item.answer.valueCoding",
    ),
}

# Declarative FHIRPath expressions for effective/clinical dates in priority order
DECLARATIVE_EFFECTIVE_DATE_EXPRESSIONS: Tuple[str, ...] = (
    "effectiveDateTime",
    "effectivePeriod.start",
    "effectiveInstant",
    "onsetDateTime",
    "onsetPeriod.start",
    "performedDateTime",
    "performedPeriod.start",
    "occurrenceDateTime",
    "occurrencePeriod.start",
    "recordedDate",
    "authoredOn",
    "date",
    "dateAsserted",
    "whenHandedOver",
    "whenPrepared",
    "started",
    "createdDateTime",
    "createdPeriod.start",
    "created",
    "issued",
    "period.start",
    "billablePeriod.start",
    "dateTime",
    "recorded",
    "startDate",
    "meta.lastUpdated",
)

# Declarative FHIRPath expressions for outbound Reference fields
DECLARATIVE_REFERENCE_EXPRESSIONS: Tuple[str, ...] = (
    "subject",
    "patient",
    "beneficiary",
    "subscriber",
    "encounter",
    "context.encounter",
    "context.sourcePatientInfo",
    "context.related",
    "performer",
    "performer.actor",
    "performer.onBehalfOf",
    "requester",
    "recorder",
    "asserter",
    "author",
    "enterer",
    "practitioner",
    "organization",
    "managingOrganization",
    "serviceProvider",
    "location",
    "location.location",
    "payor",
    "insurer",
    "provider",
    "facility",
    "prescription",
    "medicationReference",
    "reasonReference",
    "basedOn",
    "partOf",
    "result",
    "resultsInterpreter",
    "specimen",
    "imagingStudy",
    "media.link",
    "careTeam",
    "addresses",
    "supportingInfo",
    "supportingInformation",
    "goal",
    "custodian",
    "sourceReference",
    "target",
    "agent.who",
    "agent.onBehalfOf",
    "section.entry",
    "section.author",
    "participant.member",
    "participant.individual",
    "participant.actor",
    "insurance.coverage",
    "item.encounter",
    "diagnosis.diagnosisReference",
    "procedure.procedureReference",
    "activity.reference",
    "activity.detail.location",
    "activity.detail.performer",
    "activity.detail.productReference",
    "hasMember",
    "derivedFrom",
    "focus",
    "device",
    "parent",
    "endpoint",
    "healthcareService",
)


_WHERE_RE = re.compile(r"^([A-Za-z0-9_]+)\.where\(\s*([A-Za-z0-9_]+)\s*=\s*['\"]([^'\"]*)['\"]\s*\)$")
_INDEX_RE = re.compile(r"^([A-Za-z0-9_]+)\[(\d+)\]$")


def _evaluate_single_fhirpath(resource: Dict[str, Any], expr: str) -> List[Any]:
    """Evaluates a single deterministic FHIRPath navigation expression over a FHIR resource dict."""
    if not isinstance(resource, dict):
        return []
    clean_expr = (expr or "").strip()
    if not clean_expr:
        return []

    tokens = [t.strip() for t in clean_expr.split(".") if t.strip()]
    if not tokens:
        return []

    # Rejoin `.where(...)` tokens if split on internal dots
    merged_tokens: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("where(") and merged_tokens:
            merged_tokens[-1] = f"{merged_tokens[-1]}.{tok}"
        else:
            merged_tokens.append(tok)
        i += 1
    tokens = merged_tokens

    rtype = str(resource.get("resourceType") or "").strip()
    if tokens[0] == rtype:
        tokens = tokens[1:]
    elif tokens[0][:1].isupper() and tokens[0] in SUPPORTED_FHIR_RESOURCE_TYPES and tokens[0] != rtype:
        return []

    current: List[Any] = [resource]
    for tok in tokens:
        if tok in ("first()", "first"):
            current = current[:1]
            continue

        where_match = _WHERE_RE.match(tok)
        if where_match:
            field_name, pred_key, pred_val = where_match.groups()
            next_items: List[Any] = []
            for item in current:
                if isinstance(item, dict) and field_name in item:
                    val = item[field_name]
                    candidates = val if isinstance(val, list) else [val]
                    for cand in candidates:
                        if isinstance(cand, dict) and str(cand.get(pred_key, "")) == pred_val:
                            next_items.append(cand)
            current = next_items
            continue

        idx_match = _INDEX_RE.match(tok)
        if idx_match:
            field_name, idx_str = idx_match.groups()
            idx_num = int(idx_str)
            next_items = []
            for item in current:
                if isinstance(item, dict) and field_name in item:
                    val = item[field_name]
                    seq = val if isinstance(val, list) else [val]
                    if 0 <= idx_num < len(seq) and seq[idx_num] is not None:
                        next_items.append(seq[idx_num])
            current = next_items
            continue

        next_items = []
        for item in current:
            if isinstance(item, dict) and tok in item:
                val = item[tok]
                if isinstance(val, list):
                    next_items.extend(v for v in val if v is not None)
                elif val is not None:
                    next_items.append(val)
        current = next_items
        if not current:
            break

    return current


def evaluate_fhirpath(resource: Dict[str, Any], expression: str) -> List[Any]:
    """Evaluates a declarative HL7 FHIRPath expression (supporting union `|`, dotted paths, `.where()`, `.first()`).

    Uses `fhirpathpy` if installed in the environment and falls back to the built-in deterministic
    evaluator so Carefold operates with zero `uv.lock` churn.
    """
    if not isinstance(resource, dict) or not expression or not isinstance(expression, str):
        return []

    if _fhirpathpy is not None:
        try:
            res = _fhirpathpy.evaluate(resource, expression)
            if isinstance(res, list):
                return res
        except Exception:
            pass

    results: List[Any] = []
    for branch in expression.split("|"):
        branch_clean = branch.strip()
        if branch_clean:
            results.extend(_evaluate_single_fhirpath(resource, branch_clean))
    return results


# ============================================================================
# Section 4: Declarative Coding, Effective Date & Reference Extraction
# ============================================================================

def _normalize_coding_dict(
    coding: Dict[str, Any],
    element_path: str,
) -> Optional[Dict[str, Optional[str]]]:
    """Normalizes a single FHIR `Coding` dictionary into an indexable tuple dict."""
    if not isinstance(coding, dict):
        return None
    raw_code = coding.get("code")
    if raw_code is None or not str(raw_code).strip():
        return None
    code_str = str(raw_code).strip()
    raw_system = coding.get("system")
    system_str = str(raw_system).strip() if raw_system and str(raw_system).strip() else None
    raw_display = coding.get("display")
    display_str = str(raw_display).strip()[:255] if raw_display and str(raw_display).strip() else None
    return {
        "element_path": element_path,
        "system": system_str,
        "code": code_str,
        "display": display_str,
    }


def extract_codings(
    resource: Dict[str, Any],
    rtype: Optional[str] = None,
) -> List[Dict[str, Optional[str]]]:
    """Declaratively extracts all `(element_path, system, code, display)` codings from a FHIR R4 resource.

    Note: Extracts structured `Coding` entries (`system`, `code`, `display`) only. Free-text
    `CodeableConcept.text` and narrative `text.div` are intentionally excluded from coding index
    tuples to prevent free-text PHI/PII leakage into terminology indexes.
    """
    if not isinstance(resource, dict):
        return []
    resolved_type = (rtype or str(resource.get("resourceType") or "")).strip()

    expressions: List[str] = []
    seen_exprs: Set[str] = set()
    for exp in DECLARATIVE_CODING_EXPRESSIONS.get(resolved_type, ()) + DECLARATIVE_CODING_EXPRESSIONS.get("*", ()):
        if exp not in seen_exprs:
            seen_exprs.add(exp)
            expressions.append(exp)

    extracted: List[Dict[str, Optional[str]]] = []
    seen_keys: Set[Tuple[str, str, str]] = set()

    for expr in expressions:
        matches = evaluate_fhirpath(resource, expr)
        element_path = expr[:-7] if expr.endswith(".coding") else expr
        for match in matches:
            if isinstance(match, dict):
                norm = _normalize_coding_dict(match, element_path=element_path)
                if norm is not None:
                    dedup_key = (norm["element_path"] or "", norm["system"] or "", norm["code"] or "")
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        extracted.append(norm)

    # Also traverse any remaining nested CodeableConcept.coding dictionaries not in the static list
    def _walk_extra_codings(node: Any, path_prefix: str) -> None:
        if isinstance(node, dict):
            if "coding" in node and isinstance(node["coding"], list):
                for c_item in node["coding"]:
                    if isinstance(c_item, dict):
                        norm = _normalize_coding_dict(c_item, element_path=path_prefix or "code")
                        if norm is not None:
                            dedup_key = (norm["element_path"] or "", norm["system"] or "", norm["code"] or "")
                            if dedup_key not in seen_keys:
                                seen_keys.add(dedup_key)
                                extracted.append(norm)
            for k, v in node.items():
                if k in ("contained", "_carefold_provenance", "text", "meta"):
                    continue
                child_path = f"{path_prefix}.{k}" if path_prefix else k
                _walk_extra_codings(v, child_path)
        elif isinstance(node, list):
            for elem in node:
                _walk_extra_codings(elem, path_prefix)

    _walk_extra_codings(resource, "")
    return extracted


def extract_primary_coding_and_display(
    resource: Dict[str, Any],
    rtype: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """Extracts the primary clinical code and human-readable display label for a FHIR R4 resource."""
    if not isinstance(resource, dict):
        return None, "Resource"

    resolved_type = (rtype or str(resource.get("resourceType") or "Resource")).strip()
    codings = extract_codings(resource, resolved_type)
    primary_code: Optional[str] = codings[0]["code"] if codings else None
    primary_coding_display: Optional[str] = codings[0]["display"] if codings else None

    # Check primary CodeableConcept.text for human display narrative on the resource itself
    concept_candidates = evaluate_fhirpath(
        resource,
        "code | medicationCodeableConcept | vaccineCode | type | description | category | clinicalStatus",
    )
    concept_text: Optional[str] = None
    for cand in concept_candidates:
        if isinstance(cand, dict):
            txt = cand.get("text")
            if isinstance(txt, str) and txt.strip():
                concept_text = txt.strip()
                break
            c_list = cand.get("coding")
            if isinstance(c_list, list) and c_list and isinstance(c_list[0], dict):
                if not primary_code and c_list[0].get("code"):
                    primary_code = str(c_list[0]["code"]).strip()
                if not concept_text and c_list[0].get("display"):
                    concept_text = str(c_list[0]["display"]).strip()
                    break
        elif isinstance(cand, str) and cand.strip():
            concept_text = cand.strip()
            break

    display_val: Optional[str] = concept_text or primary_coding_display

    # Resource-specific human display fallbacks for administrative/demographic/care-team types
    if not display_val:
        if resolved_type in ("Patient", "Practitioner", "RelatedPerson"):
            names = resource.get("name")
            if isinstance(names, list) and names and isinstance(names[0], dict):
                n0 = names[0]
                if isinstance(n0.get("text"), str) and n0["text"].strip():
                    display_val = n0["text"].strip()
                else:
                    given = " ".join(str(g) for g in (n0.get("given") or []) if g)
                    family = str(n0.get("family") or "").strip()
                    full = f"{given} {family}".strip()
                    if full:
                        display_val = f"{resolved_type}: {full}"
            elif isinstance(names, str) and names.strip():
                display_val = f"{resolved_type}: {names.strip()}"
        elif resolved_type in ("Organization", "Location", "CareTeam"):
            name_str = resource.get("name")
            if isinstance(name_str, str) and name_str.strip():
                display_val = f"{resolved_type}: {name_str.strip()}"
        elif resolved_type == "Device":
            dev_names = resource.get("deviceName")
            if isinstance(dev_names, list) and dev_names and isinstance(dev_names[0], dict):
                dn = dev_names[0].get("name")
                if isinstance(dn, str) and dn.strip():
                    display_val = f"Device: {dn.strip()}"

    if not display_val:
        for attr in ("title", "description", "conclusion"):
            val = resource.get(attr)
            if isinstance(val, str) and val.strip():
                display_val = val.strip()
                break

    if not display_val:
        display_val = f"{resolved_type} ({primary_code or resource.get('id') or 'record'})"

    # Append Observation value summary if present
    if resolved_type == "Observation":
        vq = resource.get("valueQuantity")
        if isinstance(vq, dict) and vq.get("value") is not None:
            unit = vq.get("unit") or vq.get("code") or ""
            display_val = f"{display_val}: {vq['value']} {unit}".strip()
        elif isinstance(resource.get("valueString"), str) and resource["valueString"].strip():
            display_val = f"{display_val}: {resource['valueString'].strip()}".strip()
        elif isinstance(resource.get("valueCodeableConcept"), dict):
            vcc = resource["valueCodeableConcept"]
            vcc_text = vcc.get("text") or (
                vcc["coding"][0].get("display")
                if isinstance(vcc.get("coding"), list) and vcc["coding"] and isinstance(vcc["coding"][0], dict)
                else None
            )
            if isinstance(vcc_text, str) and vcc_text.strip():
                display_val = f"{display_val}: {vcc_text.strip()}".strip()

    return primary_code, str(display_val)


_ISO_DATE_PREFIX_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")


def extract_effective_iso(
    resource: Dict[str, Any],
    rtype: Optional[str] = None,
) -> Tuple[str, str]:
    """Declaratively extracts `(iso_timestamp, yyyy_mm_dd)` from a FHIR R4 resource."""
    if isinstance(resource, dict):
        for expr in DECLARATIVE_EFFECTIVE_DATE_EXPRESSIONS:
            matches = evaluate_fhirpath(resource, expr)
            for raw in matches:
                if raw and isinstance(raw, str) and raw.strip():
                    clean = raw.strip()
                    m = _ISO_DATE_PREFIX_RE.match(clean)
                    if not m:
                        continue
                    yyyy, mm, dd = m.groups()
                    mm = mm or "01"
                    dd = dd or "01"
                    date_part = f"{yyyy}-{mm}-{dd}"
                    if "T" not in clean:
                        return f"{date_part}T00:00:00+00:00", date_part
                    return clean, date_part

    now = datetime.now(timezone.utc)
    return now.isoformat(), now.strftime("%Y-%m-%d")


# ============================================================================
# Section 5: Reference Classification, Malicious URI Guard & Extraction
# ============================================================================

_FORBIDDEN_SCHEMES: FrozenSet[str] = frozenset({
    "javascript",
    "data",
    "file",
    "ftp",
    "gopher",
    "jar",
    "vbscript",
    "ws",
    "wss",
    "ldap",
    "ldaps",
})

_SSRF_FORBIDDEN_HOSTS: FrozenSet[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "[::1]",
    "169.254.169.254",
    "metadata.google.internal",
})

_RELATIVE_REF_RE = re.compile(
    r"^([A-Z][A-Za-z0-9]+)/([A-Za-z0-9\-\.]{1,64})(?:/_history/[A-Za-z0-9\-\.]{1,64})?$"
)
_URN_UUID_RE = re.compile(r"^urn:uuid:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[A-Za-z0-9\-\.]{1,64})$")
_URN_OID_RE = re.compile(r"^urn:oid:([0-2](\.(0|[1-9][0-9]*))+)$")
_CONTAINED_REF_RE = re.compile(r"^#([A-Za-z0-9\-\._]{1,64})$")


def classify_fhir_reference(ref_str: str) -> Dict[str, Any]:
    """Classifies a FHIR Reference string and detects malicious/traversal/SSRF reference payloads.

    Returns a dictionary with:
    - `raw_reference`: original string
    - `kind`: `'contained'`, `'urn_uuid'`, `'urn_oid'`, `'relative'`, `'absolute'`, or `'invalid'`
    - `target_type`: resolved FHIR resourceType if determinable, else None
    - `target_id`: resolved resource ID or UUID if determinable, else None
    - `is_external`: True if pointing to an external URL or unresolved URN
    - `is_malicious`: True if scheme/path/host violates reference security policy
    - `diagnostic_code`: diagnostic code string if invalid or malicious, else None
    """
    if not isinstance(ref_str, str) or not ref_str.strip():
        return {
            "raw_reference": "",
            "kind": "invalid",
            "target_type": None,
            "target_id": None,
            "is_external": False,
            "is_malicious": False,
            "diagnostic_code": "empty_reference",
        }

    raw = ref_str.strip()

    # 1. Check control chars, null bytes, CRLF, or path traversal sequences
    if any(ch in raw for ch in ("\x00", "\r", "\n", "\\")) or ".." in raw or "%2e%2e" in raw.lower():
        return {
            "raw_reference": raw[:128],
            "kind": "invalid",
            "target_type": None,
            "target_id": None,
            "is_external": False,
            "is_malicious": True,
            "diagnostic_code": "malicious_reference_traversal_or_control_char",
        }

    # 2. Contained reference (#id)
    contained_m = _CONTAINED_REF_RE.match(raw)
    if contained_m:
        return {
            "raw_reference": raw,
            "kind": "contained",
            "target_type": None,
            "target_id": contained_m.group(1),
            "is_external": False,
            "is_malicious": False,
            "diagnostic_code": None,
        }

    # 3. urn:uuid:<uuid>
    uuid_m = _URN_UUID_RE.match(raw)
    if uuid_m:
        return {
            "raw_reference": raw,
            "kind": "urn_uuid",
            "target_type": None,
            "target_id": uuid_m.group(1),
            "is_external": False,
            "is_malicious": False,
            "diagnostic_code": None,
        }

    # 4. urn:oid:<oid>
    oid_m = _URN_OID_RE.match(raw)
    if oid_m:
        return {
            "raw_reference": raw,
            "kind": "urn_oid",
            "target_type": None,
            "target_id": oid_m.group(1),
            "is_external": True,
            "is_malicious": False,
            "diagnostic_code": None,
        }

    # 5. Relative ResourceType/id
    rel_m = _RELATIVE_REF_RE.match(raw)
    if rel_m:
        r_type, r_id = rel_m.group(1), rel_m.group(2)
        return {
            "raw_reference": raw,
            "kind": "relative",
            "target_type": r_type,
            "target_id": r_id,
            "is_external": False,
            "is_malicious": False,
            "diagnostic_code": None,
        }

    # 6. Check URI scheme
    if ":" in raw:
        scheme = raw.split(":", 1)[0].lower().strip()
        if scheme in _FORBIDDEN_SCHEMES:
            return {
                "raw_reference": f"{scheme}:[redacted]",
                "kind": "invalid",
                "target_type": None,
                "target_id": None,
                "is_external": True,
                "is_malicious": True,
                "diagnostic_code": f"malicious_reference_scheme_{scheme}",
            }
        if scheme in ("http", "https"):
            parsed = urlparse(raw)
            host = (parsed.hostname or "").lower().strip()
            if not host or host in _SSRF_FORBIDDEN_HOSTS or host.startswith("127.") or host.startswith("169.254."):
                return {
                    "raw_reference": raw[:128],
                    "kind": "invalid",
                    "target_type": None,
                    "target_id": None,
                    "is_external": True,
                    "is_malicious": True,
                    "diagnostic_code": "malicious_reference_ssrf_host",
                }
            if parsed.query or parsed.fragment:
                return {
                    "raw_reference": raw[:128],
                    "kind": "invalid",
                    "target_type": None,
                    "target_id": None,
                    "is_external": True,
                    "is_malicious": True,
                    "diagnostic_code": "malicious_reference_query_or_fragment",
                }
            # Extract trailing /ResourceType/id if present on the FHIR server URL path
            path_parts = [p for p in (parsed.path or "").split("/") if p]
            if len(path_parts) >= 4 and path_parts[-2] == "_history":
                cand_type, cand_id = path_parts[-4], path_parts[-3]
            elif len(path_parts) >= 2:
                cand_type, cand_id = path_parts[-2], path_parts[-1]
            else:
                cand_type, cand_id = None, None

            if cand_type and cand_id and _RELATIVE_REF_RE.match(f"{cand_type}/{cand_id}"):
                return {
                    "raw_reference": raw,
                    "kind": "absolute",
                    "target_type": cand_type,
                    "target_id": cand_id,
                    "is_external": True,
                    "is_malicious": False,
                    "diagnostic_code": None,
                }
            return {
                "raw_reference": raw,
                "kind": "absolute",
                "target_type": None,
                "target_id": None,
                "is_external": True,
                "is_malicious": False,
                "diagnostic_code": "unparseable_absolute_fhir_reference",
            }

    return {
        "raw_reference": raw[:128],
        "kind": "invalid",
        "target_type": None,
        "target_id": None,
        "is_external": False,
        "is_malicious": False,
        "diagnostic_code": "invalid_reference_format",
    }


def extract_references(
    resource: Dict[str, Any],
    rtype: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Declaratively extracts all outbound FHIR `Reference` edges from a resource dict.

    Note: Intentionally excludes `Reference.display` from extracted graph edges so free-text
    patient or clinician names are never copied into reference index rows.
    """
    if not isinstance(resource, dict):
        return []
    resolved_type = (rtype or str(resource.get("resourceType") or "")).strip()
    subject_paths = set(RESOURCE_PATIENT_SUBJECT_PATHS.get(resolved_type, ()))
    synthesized_defaults = set(
        ((resource.get("_carefold_provenance") or {}).get("synthesized_defaults") or [])
        if isinstance(resource.get("_carefold_provenance"), dict)
        else []
    )

    extracted: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()

    def _process_ref_obj(ref_obj: Dict[str, Any], field_path: str) -> None:
        if not isinstance(ref_obj, dict):
            return
        if field_path in synthesized_defaults and "reference" not in ref_obj:
            return
        raw_ref = ref_obj.get("reference")
        explicit_type = ref_obj.get("type")
        if isinstance(raw_ref, str) and raw_ref.strip():
            key = (field_path, raw_ref.strip())
            if key in seen:
                return
            seen.add(key)
            classified = classify_fhir_reference(raw_ref)
            if not classified["target_type"] and isinstance(explicit_type, str) and explicit_type.strip():
                classified["target_type"] = explicit_type.strip()
            classified["field"] = field_path
            classified["is_patient_subject"] = (
                field_path in subject_paths or classified.get("target_type") == "Patient"
            )
            extracted.append(classified)
        elif isinstance(ref_obj.get("identifier"), dict) and isinstance(explicit_type, str) and explicit_type.strip():
            ident = ref_obj["identifier"]
            sys_val = str(ident.get("system") or "").strip()
            val_str = str(ident.get("value") or "").strip()
            if val_str:
                logical_key = f"logical:{explicit_type.strip()}:{sys_val}"
                key = (field_path, logical_key)
                if key not in seen:
                    seen.add(key)
                    extracted.append({
                        "field": field_path,
                        "raw_reference": logical_key,
                        "kind": "logical",
                        "target_type": explicit_type.strip(),
                        "target_id": None,
                        "is_external": True,
                        "is_malicious": False,
                        "is_patient_subject": field_path in subject_paths or explicit_type.strip() == "Patient",
                        "diagnostic_code": None,
                    })

    for expr in DECLARATIVE_REFERENCE_EXPRESSIONS:
        matches = evaluate_fhirpath(resource, expr)
        for m in matches:
            if isinstance(m, dict):
                _process_ref_obj(m, expr)

    # Also walk any remaining nested dicts that have a `reference` string field
    def _walk_extra_refs(node: Any, path_prefix: str) -> None:
        if isinstance(node, dict):
            if "reference" in node and isinstance(node["reference"], str) and path_prefix:
                _process_ref_obj(node, path_prefix)
            for k, v in node.items():
                if k in ("contained", "_carefold_provenance", "text", "meta", "coding"):
                    continue
                child_path = f"{path_prefix}.{k}" if path_prefix else k
                _walk_extra_refs(v, child_path)
        elif isinstance(node, list):
            for elem in node:
                _walk_extra_refs(elem, path_prefix)

    _walk_extra_refs(resource, "")
    return extracted


def extract_patient_subject_references(
    resource: Dict[str, Any],
    rtype: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extracts the primary patient/subject references declared on a FHIR resource."""
    if not isinstance(resource, dict):
        return []
    resolved_type = (rtype or str(resource.get("resourceType") or "")).strip()
    subject_paths = set(RESOURCE_PATIENT_SUBJECT_PATHS.get(resolved_type, ()))
    all_refs = extract_references(resource, resolved_type)
    return [
        r for r in all_refs
        if r["field"] in subject_paths or r.get("target_type") == "Patient"
    ]


# ============================================================================
# Section 6: PHI-Safe Diagnostics & Structural FHIR R4 Validation
# ============================================================================

@dataclass(frozen=True)
class FhirDiagnostic:
    """PHI-safe diagnostic emitted for unsupported, malformed, or quarantined FHIR inputs."""

    code: str
    severity: str
    message: str
    entry_index: Optional[int] = None
    resource_type: Optional[str] = None
    source_id: Optional[str] = None
    field_paths: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "entry_index": self.entry_index,
            "resource_type": self.resource_type,
            "source_id": self.source_id,
            "field_paths": list(self.field_paths),
        }


@dataclass
class FhirValidationResult:
    """Result of validating and normalizing a single FHIR R4 resource dict."""

    is_valid: bool
    resource_type: str
    normalized: Dict[str, Any]
    raw_resource: Dict[str, Any]
    synthesized_defaults: List[str] = field(default_factory=list)
    diagnostics: List[FhirDiagnostic] = field(default_factory=list)


# Minimal R4 required boilerplate defaults applied ONLY when omitted on partial clinical inputs
_MINIMAL_R4_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "Observation": {
        "status": "final",
        "code": {"text": "Clinical Observation"},
    },
    "Condition": {
        "subject": {"display": "Patient"},
    },
    "AllergyIntolerance": {
        "patient": {"display": "Patient"},
    },
    "MedicationStatement": {
        "status": "active",
        "subject": {"display": "Patient"},
    },
    "MedicationRequest": {
        "status": "active",
        "intent": "order",
        "subject": {"display": "Patient"},
    },
    "MedicationDispense": {
        "status": "completed",
    },
    "Immunization": {
        "status": "completed",
        "vaccineCode": {"text": "Immunization"},
        "patient": {"display": "Patient"},
    },
    "Procedure": {
        "status": "completed",
        "subject": {"display": "Patient"},
    },
    "FamilyMemberHistory": {
        "status": "completed",
        "patient": {"display": "Patient"},
        "relationship": {"text": "Relative"},
    },
    "DiagnosticReport": {
        "status": "final",
        "code": {"text": "Diagnostic Report"},
    },
    "ImagingStudy": {
        "status": "available",
        "subject": {"display": "Patient"},
    },
    "DocumentReference": {
        "status": "current",
        "content": [{"attachment": {"contentType": "text/plain"}}],
    },
    "Media": {
        "status": "completed",
        "content": {"contentType": "image/png"},
    },
    "Encounter": {
        "status": "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
    },
    "CarePlan": {
        "status": "active",
        "intent": "plan",
        "subject": {"display": "Patient"},
    },
    "Goal": {
        "lifecycleStatus": "active",
        "description": {"text": "Care Goal"},
        "subject": {"display": "Patient"},
    },
    "ServiceRequest": {
        "status": "active",
        "intent": "order",
        "subject": {"display": "Patient"},
    },
    "QuestionnaireResponse": {
        "status": "completed",
    },
    "Coverage": {
        "status": "active",
        "beneficiary": {"display": "Patient"},
        "payor": [{"display": "Insurance Payor"}],
    },
    "ExplanationOfBenefit": {
        "status": "active",
        "type": {"text": "Claim"},
        "use": "claim",
        "patient": {"display": "Patient"},
        "created": "2026-01-01T00:00:00+00:00",
        "insurer": {"display": "Insurer"},
        "provider": {"display": "Provider"},
        "outcome": "complete",
        "insurance": [{"focal": True, "coverage": {"display": "Coverage"}}],
    },
    "Consent": {
        "status": "active",
        "scope": {"text": "patient-privacy"},
        "category": [{"text": "Consent"}],
    },
    "Composition": {
        "status": "final",
        "type": {"text": "Clinical Summary"},
        "date": "2026-01-01T00:00:00+00:00",
        "author": [{"display": "Author"}],
        "title": "Clinical Summary",
    },
    "RelatedPerson": {
        "patient": {"display": "Patient"},
    },
    "Provenance": {
        "recorded": "2026-01-01T00:00:00+00:00",
        "target": [{"display": "Record"}],
        "agent": [{"who": {"display": "Source"}}],
    },
}


def _find_r4b_incompatible_paths(node: Any, prefix: str = "") -> List[str]:
    """Detects R4B-only `CodeableReference` shapes (`{'concept': ..., 'reference': ...}`) in R4 payloads."""
    bad_paths: List[str] = []
    if isinstance(node, dict):
        if "concept" in node and ("reference" in node or isinstance(node.get("concept"), dict)):
            # In FHIR R4 (4.0.1), CodeableReference did not exist; fields used CodeableConcept or Reference
            if set(node.keys()).issubset({"id", "extension", "concept", "reference"}):
                bad_paths.append(prefix or "root")
        for k, v in node.items():
            if k == "_carefold_provenance":
                continue
            child = f"{prefix}.{k}" if prefix else k
            bad_paths.extend(_find_r4b_incompatible_paths(v, child))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            child = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
            bad_paths.extend(_find_r4b_incompatible_paths(item, child))
    return bad_paths


def validate_and_normalize_fhir_resource(
    resource: Dict[str, Any],
    rtype: Optional[str] = None,
    entry_index: Optional[int] = None,
    source_id: Optional[str] = None,
) -> FhirValidationResult:
    """Validates and normalizes a FHIR R4 resource dict while preserving original JSON and emitting safe diagnostics."""
    if not isinstance(resource, dict):
        return FhirValidationResult(
            is_valid=False,
            resource_type=str(rtype or ""),
            normalized={},
            raw_resource={},
            diagnostics=[
                FhirDiagnostic(
                    code="malformed_resource_not_object",
                    severity="error",
                    message="FHIR resource must be a JSON object.",
                    entry_index=entry_index,
                    resource_type=rtype,
                    source_id=source_id,
                )
            ],
        )

    raw_copy = copy.deepcopy(resource)
    resolved_type = (rtype or str(resource.get("resourceType") or "")).strip()

    if not resolved_type:
        return FhirValidationResult(
            is_valid=False,
            resource_type="",
            normalized=raw_copy,
            raw_resource=raw_copy,
            diagnostics=[
                FhirDiagnostic(
                    code="missing_resource_type",
                    severity="error",
                    message="FHIR resource is missing required 'resourceType' property.",
                    entry_index=entry_index,
                    source_id=source_id,
                    field_paths=("resourceType",),
                )
            ],
        )

    if resolved_type in R4B_ONLY_RESOURCE_TYPES:
        return FhirValidationResult(
            is_valid=False,
            resource_type=resolved_type,
            normalized=raw_copy,
            raw_resource=raw_copy,
            diagnostics=[
                FhirDiagnostic(
                    code="r4b_only_resource_type",
                    severity="error",
                    message=(
                        f"Resource type '{resolved_type}' was introduced in FHIR R4B (4.3.0) and is not supported "
                        f"by Carefold's FHIR R4 (4.0.1) allowlist."
                    ),
                    entry_index=entry_index,
                    resource_type=resolved_type,
                    source_id=source_id,
                    field_paths=("resourceType",),
                )
            ],
        )

    if resolved_type not in SUPPORTED_FHIR_RESOURCE_TYPES:
        return FhirValidationResult(
            is_valid=False,
            resource_type=resolved_type,
            normalized=raw_copy,
            raw_resource=raw_copy,
            diagnostics=[
                FhirDiagnostic(
                    code="unsupported_resource_type",
                    severity="error",
                    message=f"Resource type '{resolved_type}' is not in Carefold's supported FHIR R4 allowlist.",
                    entry_index=entry_index,
                    resource_type=resolved_type,
                    source_id=source_id,
                    field_paths=("resourceType",),
                )
            ],
        )

    r4b_paths = _find_r4b_incompatible_paths(resource)
    if r4b_paths:
        return FhirValidationResult(
            is_valid=False,
            resource_type=resolved_type,
            normalized=raw_copy,
            raw_resource=raw_copy,
            diagnostics=[
                FhirDiagnostic(
                    code="r4b_only_element_structure",
                    severity="error",
                    message="Resource contains R4B-only CodeableReference structure not valid in FHIR R4 (4.0.1).",
                    entry_index=entry_index,
                    resource_type=resolved_type,
                    source_id=source_id,
                    field_paths=tuple(r4b_paths),
                )
            ],
        )

    model_cls = get_r4_model_class(resolved_type)
    if model_cls is None:
        return FhirValidationResult(
            is_valid=False,
            resource_type=resolved_type,
            normalized=raw_copy,
            raw_resource=raw_copy,
            diagnostics=[
                FhirDiagnostic(
                    code="model_class_unavailable",
                    severity="error",
                    message=f"No FHIR model class available for '{resolved_type}'.",
                    entry_index=entry_index,
                    resource_type=resolved_type,
                    source_id=source_id,
                )
            ],
        )

    candidate = copy.deepcopy(resource)
    candidate.pop("_carefold_provenance", None)
    synthesized_defaults: List[str] = []

    defaults_for_type = _MINIMAL_R4_DEFAULTS.get(resolved_type, {})
    for field_name, default_val in defaults_for_type.items():
        if field_name not in candidate:
            # For MedicationRequest / MedicationStatement / MedicationDispense, do not inject code if medication[x] exists
            candidate[field_name] = copy.deepcopy(default_val)
            synthesized_defaults.append(field_name)

    if resolved_type in ("MedicationRequest", "MedicationStatement", "MedicationDispense"):
        if "medicationCodeableConcept" not in candidate and "medicationReference" not in candidate:
            candidate["medicationCodeableConcept"] = {"text": resolved_type}
            synthesized_defaults.append("medicationCodeableConcept")

    try:
        validated = model_cls.model_validate(candidate)
        normalized = validated.model_dump(mode="json", exclude_none=True)
        # Preserve original fields alongside validated canonical fields
        merged = copy.deepcopy(resource)
        merged.update(normalized)
        return FhirValidationResult(
            is_valid=True,
            resource_type=resolved_type,
            normalized=merged,
            raw_resource=raw_copy,
            synthesized_defaults=synthesized_defaults,
            diagnostics=[],
        )
    except ValidationError as exc:
        field_paths: List[str] = []
        for err in exc.errors():
            loc = err.get("loc") or ()
            loc_str = ".".join(str(part) for part in loc if part is not None)
            if loc_str and loc_str not in field_paths:
                field_paths.append(loc_str)
        return FhirValidationResult(
            is_valid=False,
            resource_type=resolved_type,
            normalized=raw_copy,
            raw_resource=raw_copy,
            synthesized_defaults=synthesized_defaults,
            diagnostics=[
                FhirDiagnostic(
                    code="validation_error",
                    severity="error",
                    message=(
                        f"FHIR R4 structural validation failed for '{resolved_type}' on "
                        f"{len(field_paths) or 1} field(s)."
                    ),
                    entry_index=entry_index,
                    resource_type=resolved_type,
                    source_id=source_id,
                    field_paths=tuple(field_paths) if field_paths else (resolved_type,),
                )
            ],
        )
    except Exception:
        return FhirValidationResult(
            is_valid=False,
            resource_type=resolved_type,
            normalized=raw_copy,
            raw_resource=raw_copy,
            synthesized_defaults=synthesized_defaults,
            diagnostics=[
                FhirDiagnostic(
                    code="validation_error",
                    severity="error",
                    message=f"FHIR R4 structural validation failed for '{resolved_type}'.",
                    entry_index=entry_index,
                    resource_type=resolved_type,
                    source_id=source_id,
                    field_paths=(resolved_type,),
                )
            ],
        )


__all__ = [
    "CARE_PLAN_AND_ADMIN_RESOURCE_TYPES",
    "CLINICAL_CORE_RESOURCE_TYPES",
    "CLINICAL_FHIR_RESOURCE_TYPES",
    "DECLARATIVE_CODING_EXPRESSIONS",
    "DECLARATIVE_EFFECTIVE_DATE_EXPRESSIONS",
    "DECLARATIVE_REFERENCE_EXPRESSIONS",
    "DEMOGRAPHIC_AND_CARE_TEAM_RESOURCE_TYPES",
    "DIAGNOSTIC_AND_VITALS_RESOURCE_TYPES",
    "FHIR_VALIDATION_CAPABILITIES",
    "INFRASTRUCTURE_AND_ACTOR_RESOURCE_TYPES",
    "MODEL_LIBRARY_FHIR_VERSION",
    "MODEL_LIBRARY_PACKAGE",
    "PAPERWORK_FHIR_RESOURCE_TYPES",
    "PATIENT_SUBJECT_RESOURCE_TYPES",
    "R4B_ONLY_RESOURCE_TYPES",
    "RESOURCE_PATIENT_SUBJECT_PATHS",
    "SUPPORTED_FHIR_RESOURCE_TYPES",
    "TARGET_FHIR_RELEASE",
    "TARGET_FHIR_VERSION",
    "FhirDiagnostic",
    "FhirValidationResult",
    "classify_fhir_reference",
    "evaluate_fhirpath",
    "extract_codings",
    "extract_effective_iso",
    "extract_patient_subject_references",
    "extract_primary_coding_and_display",
    "extract_references",
    "get_r4_model_class",
    "resolve_resource_scope",
    "validate_and_normalize_fhir_resource",
]
