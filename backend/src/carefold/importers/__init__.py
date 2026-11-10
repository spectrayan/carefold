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

"""Clinical and wearable file importers package (AU-38 / E10.1, E10.2, E10.7, E8.0)."""

from carefold.importers.apple_health import (
    HIGH_FREQUENCY_HK_TYPES,
    LOW_FREQUENCY_CLINICAL_HK_TYPES,
    parse_apple_health_export,
)
from carefold.importers.ccda import parse_ccda_xml
from carefold.importers.fhir_bundle import (
    CLINICAL_FHIR_RESOURCE_TYPES,
    PAPERWORK_FHIR_RESOURCE_TYPES,
    SUPPORTED_FHIR_RESOURCE_TYPES,
    parse_fhir_bundle,
)
from carefold.importers.fhir_converter import (
    HL7APY_LICENSE_ATTESTATION,
    HL7v2ConversionError,
    HL7v2Diagnostic,
    convert_clinical_payload_to_fhir,
    parse_hl7v2_to_fhir,
    unescape_hl7v2_text,
)
from carefold.importers.iis_pdf import (
    SUPPORTED_IIS_VACCINES,
    parse_iis_immunisation_text,
)
from carefold.importers.service import (
    SUPPORTED_IMPORT_FORMATS,
    commit_import_batch,
    compute_canonical_fhir_content_hash,
    confirm_batch,
    delete_fhir_resource_with_history,
    detect_import_format,
    discard_import_batch,
    ensure_canonical_patient_resource,
    evaluate_staged_records_dedup_preview,
    get_import_batch,
    get_inbound_references,
    get_outbound_references,
    get_resource_version_history,
    list_import_batches,
    reverse_dedup_merge,
    search_resources_by_coding,
    stage_import,
    upsert_fhir_resource_with_history,
)
from carefold.importers.smart_health_card import (
    create_signed_shc_jws,
    decode_shc_qr_uri,
    encode_shc_qr_uri,
    export_public_jwk,
    verify_and_parse_smart_health_card,
)

__all__ = [
    "CLINICAL_FHIR_RESOURCE_TYPES",
    "HIGH_FREQUENCY_HK_TYPES",
    "HL7APY_LICENSE_ATTESTATION",
    "HL7v2ConversionError",
    "HL7v2Diagnostic",
    "LOW_FREQUENCY_CLINICAL_HK_TYPES",
    "PAPERWORK_FHIR_RESOURCE_TYPES",
    "SUPPORTED_FHIR_RESOURCE_TYPES",
    "SUPPORTED_IIS_VACCINES",
    "SUPPORTED_IMPORT_FORMATS",
    "commit_import_batch",
    "compute_canonical_fhir_content_hash",
    "confirm_batch",
    "convert_clinical_payload_to_fhir",
    "create_signed_shc_jws",
    "decode_shc_qr_uri",
    "delete_fhir_resource_with_history",
    "detect_import_format",
    "discard_import_batch",
    "encode_shc_qr_uri",
    "ensure_canonical_patient_resource",
    "evaluate_staged_records_dedup_preview",
    "export_public_jwk",
    "get_import_batch",
    "get_inbound_references",
    "get_outbound_references",
    "get_resource_version_history",
    "list_import_batches",
    "parse_apple_health_export",
    "parse_ccda_xml",
    "parse_fhir_bundle",
    "parse_hl7v2_to_fhir",
    "parse_iis_immunisation_text",
    "reverse_dedup_merge",
    "search_resources_by_coding",
    "stage_import",
    "unescape_hl7v2_text",
    "upsert_fhir_resource_with_history",
    "verify_and_parse_smart_health_card",
]
