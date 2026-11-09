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

"""Carefold HL7 FHIR R4 (4.0.1) structural model registry, declarative extractor, and reference utilities."""

from carefold.fhir.registry import (
    CARE_PLAN_AND_ADMIN_RESOURCE_TYPES,
    CLINICAL_CORE_RESOURCE_TYPES,
    CLINICAL_FHIR_RESOURCE_TYPES,
    DECLARATIVE_CODING_EXPRESSIONS,
    DECLARATIVE_EFFECTIVE_DATE_EXPRESSIONS,
    DECLARATIVE_REFERENCE_EXPRESSIONS,
    DEMOGRAPHIC_AND_CARE_TEAM_RESOURCE_TYPES,
    DIAGNOSTIC_AND_VITALS_RESOURCE_TYPES,
    FHIR_VALIDATION_CAPABILITIES,
    INFRASTRUCTURE_AND_ACTOR_RESOURCE_TYPES,
    MODEL_LIBRARY_FHIR_VERSION,
    MODEL_LIBRARY_PACKAGE,
    PAPERWORK_FHIR_RESOURCE_TYPES,
    PATIENT_SUBJECT_RESOURCE_TYPES,
    R4B_ONLY_RESOURCE_TYPES,
    RESOURCE_PATIENT_SUBJECT_PATHS,
    SUPPORTED_FHIR_RESOURCE_TYPES,
    TARGET_FHIR_RELEASE,
    TARGET_FHIR_VERSION,
    FhirDiagnostic,
    FhirValidationResult,
    classify_fhir_reference,
    evaluate_fhirpath,
    extract_codings,
    extract_effective_iso,
    extract_patient_subject_references,
    extract_primary_coding_and_display,
    extract_references,
    get_r4_model_class,
    resolve_resource_scope,
    validate_and_normalize_fhir_resource,
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
