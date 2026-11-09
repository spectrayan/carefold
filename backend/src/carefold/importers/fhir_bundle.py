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

"""FHIR R4 Bundle clinical & EHR record parser, reference resolver, and normalizer (#281).

Parses HL7 FHIR R4 (`4.0.1`) `Bundle` JSON documents across Carefold's 33 allowlisted
clinical, diagnostic, care-plan, demographic, and administrative/payer resource types:
- Validates resources against Pydantic v2 models via `carefold.fhir.registry`
- Extracts codings, effective dates, and outbound references declaratively
- Resolves bundle-internal `fullUrl` (`urn:uuid:...`), relative `ResourceType/id`,
  matching absolute `fullUrl` entries, and `#contained` resources
- Enforces patient/profile reference safety (never blindly rewriting references;
  quarantining wrong-patient, ambiguous multi-patient, and malicious references)
- Routes resources to `health.clinical` or `health.paperwork` scopes
- Preserves original source JSON, attaches untrusted provenance, and emits PHI-safe diagnostics
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
import uuid

from fhir.resources.R4B.provenance import Provenance as FhirProvenance

from carefold.fhir.registry import (
    CARE_PLAN_AND_ADMIN_RESOURCE_TYPES,
    CLINICAL_CORE_RESOURCE_TYPES,
    CLINICAL_FHIR_RESOURCE_TYPES,
    DEMOGRAPHIC_AND_CARE_TEAM_RESOURCE_TYPES,
    DIAGNOSTIC_AND_VITALS_RESOURCE_TYPES,
    FHIR_VALIDATION_CAPABILITIES,
    INFRASTRUCTURE_AND_ACTOR_RESOURCE_TYPES,
    PAPERWORK_FHIR_RESOURCE_TYPES,
    PATIENT_SUBJECT_RESOURCE_TYPES,
    R4B_ONLY_RESOURCE_TYPES,
    RESOURCE_PATIENT_SUBJECT_PATHS,
    SUPPORTED_FHIR_RESOURCE_TYPES,
    TARGET_FHIR_RELEASE,
    TARGET_FHIR_VERSION,
    FhirDiagnostic,
    classify_fhir_reference,
    extract_codings,
    extract_effective_iso,
    extract_primary_coding_and_display,
    extract_references,
    get_r4_model_class,
    resolve_resource_scope,
    validate_and_normalize_fhir_resource,
)

# Backward-compatible model registry mapping all 33 allowlisted FHIR R4 resource types
_FHIR_MODEL_REGISTRY: Dict[str, Any] = {
    rtype: get_r4_model_class(rtype) for rtype in sorted(SUPPORTED_FHIR_RESOURCE_TYPES)
}


def _validate_and_normalize_fhir_resource(resource: Dict[str, Any], rtype: str) -> Dict[str, Any]:
    """Backward-compatible wrapper around `carefold.fhir.registry.validate_and_normalize_fhir_resource`."""
    res = validate_and_normalize_fhir_resource(resource, rtype=rtype)
    return res.normalized


def _extract_coding_and_display(resource: Dict[str, Any], rtype: str) -> Tuple[Optional[str], str]:
    """Backward-compatible wrapper around `carefold.fhir.registry.extract_primary_coding_and_display`."""
    return extract_primary_coding_and_display(resource, rtype=rtype)


def _extract_effective_iso(resource: Dict[str, Any]) -> Tuple[str, str]:
    """Backward-compatible wrapper around `carefold.fhir.registry.extract_effective_iso`."""
    return extract_effective_iso(resource)


def _has_Unsafe_id_chars(raw_id: Any) -> bool:
    """Returns True if a resource ID contains path traversal, slash, or control characters."""
    if not isinstance(raw_id, str):
        return False
    s = raw_id.strip()
    return (
        not s
        or any(ch in s for ch in ("\x00", "\r", "\n", "\\", "/"))
        or ".." in s
        or "%2e%2e" in s.lower()
    )


def _rewrite_reference_values_in_node(
    node: Any,
    rewrite_map: Dict[Tuple[str, str], str],
    path_prefix: str = "",
) -> None:
    """Rewrites specific `(field_path, raw_reference) -> new_reference` entries in-place on a normalized resource."""
    if not rewrite_map:
        return
    if isinstance(node, dict):
        raw_ref = node.get("reference")
        if isinstance(raw_ref, str) and raw_ref.strip() and path_prefix:
            clean_raw = raw_ref.strip()
            replacement = rewrite_map.get((path_prefix, clean_raw)) or rewrite_map.get(("*", clean_raw))
            if replacement:
                node["reference"] = replacement
        for k, v in node.items():
            if k in ("_carefold_provenance", "contained", "text", "meta"):
                continue
            child_path = f"{path_prefix}.{k}" if path_prefix else k
            _rewrite_reference_values_in_node(v, rewrite_map, child_path)
    elif isinstance(node, list):
        for elem in node:
            _rewrite_reference_values_in_node(elem, rewrite_map, path_prefix)


def _canonicalize_patient_token(
    raw_token: str,
    bundle_symbol_table: Dict[str, Dict[str, Any]],
) -> str:
    """Normalizes a patient identifier or reference token into a comparable canonical key."""
    clean = (raw_token or "").strip()
    if not clean:
        return ""
    if clean in bundle_symbol_table:
        target = bundle_symbol_table[clean]
        if target.get("resource_type") == "Patient":
            return f"Patient/{target['logical_id']}"
    if clean.startswith("Patient/"):
        rel = clean
        if rel in bundle_symbol_table:
            target = bundle_symbol_table[rel]
            return f"Patient/{target['logical_id']}"
        return rel
    if f"Patient/{clean}" in bundle_symbol_table:
        target = bundle_symbol_table[f"Patient/{clean}"]
        return f"Patient/{target['logical_id']}"
    if clean.startswith("urn:uuid:") or clean.startswith("urn:oid:") or ":" in clean:
        return clean
    return f"Patient/{clean}"


def parse_fhir_bundle(
    raw_content: Union[str, bytes],
    source_name: str = "FHIR Bundle Import",
    *,
    profile_id: Optional[str] = None,
    expected_patient_id: Optional[str] = None,
    verified_source_patient_ids: Optional[Sequence[str]] = None,
    strict_patient_matching: bool = True,
) -> Dict[str, Any]:
    """Parses an HL7 FHIR R4 (`4.0.1`) Bundle JSON payload into normalized, reference-resolved staged records.

    Args:
        raw_content: Raw JSON string or UTF-8 bytes of a FHIR R4 Bundle.
        source_name: Human-readable origin label for provenance display.
        profile_id: Optional target Carefold profile ID. When provided, verified single-patient
            references are mapped to `Patient/{profile_id}` while preserving original source
            identity mappings in `_carefold_provenance["source_identity_mappings"]`.
        expected_patient_id: Optional expected source patient ID or `Patient/<id>` in the bundle.
            Resources referencing a different patient are quarantined.
        verified_source_patient_ids: Optional additional verified source patient identifiers/URIs.
        strict_patient_matching: When True (default), bundles with multiple distinct unverified
            patients or wrong-patient references quarantine those records before confirmation.

    Returns:
        Dictionary with `format`, `fhir_version`, `source_name`, `records`, `quarantined_records`,
        `diagnostics`, `provenance`, and `summary`.

    Raises:
        ValueError: If payload is not valid JSON or not a FHIR `Bundle`.
    """
    if isinstance(raw_content, bytes):
        text = raw_content.decode("utf-8", errors="replace")
    elif isinstance(raw_content, str):
        text = raw_content
    else:
        raise ValueError("FHIR bundle content must be str or bytes.")

    text = text.strip()
    if not text:
        raise ValueError("FHIR bundle content is empty.")

    try:
        bundle = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid FHIR Bundle JSON: {exc}") from exc

    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ValueError("Invalid FHIR payload: root object must have resourceType == 'Bundle'.")

    clean_source = (source_name or "FHIR Bundle Import").strip()
    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise ValueError("Invalid FHIR Bundle: 'entry' must be a list.")

    diagnostics: List[Dict[str, Any]] = []
    quarantined_records: List[Dict[str, Any]] = []
    unsupported_count = 0

    def _record_quarantine(
        *,
        entry_index: int,
        resource_type: Optional[str],
        source_id: Optional[str],
        reason_code: str,
        entry_diagnostics: Sequence[FhirDiagnostic],
    ) -> None:
        diag_dicts = [d.to_dict() for d in entry_diagnostics]
        diagnostics.extend(diag_dicts)
        quarantined_records.append({
            "entry_index": entry_index,
            "resource_type": resource_type or "Unknown",
            "source_id": source_id or f"entry:{entry_index}",
            "reason_code": reason_code,
            "diagnostics": diag_dicts,
        })

    # =========================================================================
    # Pass 1: Structural Validation, Contained Resources & Bundle Symbol Table
    # =========================================================================
    bundle_symbol_table: Dict[str, Dict[str, Any]] = {}
    validated_entries: List[Dict[str, Any]] = []
    bundle_patient_keys: Set[str] = set()
    patient_identifier_aliases: Dict[str, str] = {}

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            _record_quarantine(
                entry_index=idx,
                resource_type=None,
                source_id=f"entry:{idx}",
                reason_code="malformed_bundle_entry",
                entry_diagnostics=[
                    FhirDiagnostic(
                        code="malformed_bundle_entry",
                        severity="error",
                        message="Bundle entry must be a JSON object.",
                        entry_index=idx,
                    )
                ],
            )
            continue

        resource = entry.get("resource")
        if not isinstance(resource, dict):
            _record_quarantine(
                entry_index=idx,
                resource_type=None,
                source_id=f"entry:{idx}",
                reason_code="missing_or_invalid_entry_resource",
                entry_diagnostics=[
                    FhirDiagnostic(
                        code="missing_or_invalid_entry_resource",
                        severity="error",
                        message="Bundle entry is missing a JSON object 'resource'.",
                        entry_index=idx,
                        field_paths=("entry.resource",),
                    )
                ],
            )
            continue

        rtype = str(resource.get("resourceType") or "").strip()
        raw_id = resource.get("id")
        full_url = str(entry.get("fullUrl") or "").strip()

        # Derive source_id preserving backward compatibility with existing callers
        id_or_full = raw_id if (raw_id is not None and str(raw_id).strip()) else (full_url or None)
        if id_or_full:
            source_id = f"{rtype or 'Unknown'}:{str(id_or_full).strip()[:128]}"
        else:
            digest = hashlib.sha256(
                json.dumps(resource, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:16]
            source_id = f"{rtype or 'Unknown'}:{idx}:{digest}"

        # Guard against malicious resource.id or entry.fullUrl
        if raw_id is not None and _has_Unsafe_id_chars(str(raw_id)):
            _record_quarantine(
                entry_index=idx,
                resource_type=rtype or None,
                source_id=source_id,
                reason_code="malicious_resource_id",
                entry_diagnostics=[
                    FhirDiagnostic(
                        code="malicious_resource_id",
                        severity="error",
                        message="FHIR resource 'id' contains forbidden traversal or control characters.",
                        entry_index=idx,
                        resource_type=rtype or None,
                        source_id=source_id,
                        field_paths=("id",),
                    )
                ],
            )
            continue

        if full_url:
            classified_full_url = classify_fhir_reference(full_url)
            if classified_full_url["is_malicious"]:
                _record_quarantine(
                    entry_index=idx,
                    resource_type=rtype or None,
                    source_id=source_id,
                    reason_code=classified_full_url["diagnostic_code"] or "malicious_entry_fullurl",
                    entry_diagnostics=[
                        FhirDiagnostic(
                            code=classified_full_url["diagnostic_code"] or "malicious_entry_fullurl",
                            severity="error",
                            message="Bundle entry 'fullUrl' violates Carefold URI security policy.",
                            entry_index=idx,
                            resource_type=rtype or None,
                            source_id=source_id,
                            field_paths=("entry.fullUrl",),
                        )
                    ],
                )
                continue

        # Determine logical_id for canonical ResourceType/logical_id resolution
        if raw_id is not None and str(raw_id).strip():
            logical_id = str(raw_id).strip()
        elif full_url.startswith("urn:uuid:"):
            logical_id = full_url[len("urn:uuid:") :].strip()
        elif full_url:
            classified_fu = classify_fhir_reference(full_url)
            if classified_fu.get("target_id"):
                logical_id = str(classified_fu["target_id"])
            else:
                logical_id = hashlib.sha256(full_url.encode("utf-8")).hexdigest()[:16]
        else:
            digest = hashlib.sha256(
                json.dumps(resource, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:16]
            logical_id = f"{idx}-{digest}"

        val_res = validate_and_normalize_fhir_resource(
            resource,
            rtype=rtype,
            entry_index=idx,
            source_id=source_id,
        )
        if not val_res.is_valid:
            if not rtype or rtype not in SUPPORTED_FHIR_RESOURCE_TYPES:
                unsupported_count += 1
            reason = val_res.diagnostics[0].code if val_res.diagnostics else "validation_error"
            _record_quarantine(
                entry_index=idx,
                resource_type=rtype or None,
                source_id=source_id,
                reason_code=reason,
                entry_diagnostics=val_res.diagnostics,
            )
            continue

        # Inspect and validate any #contained resources inside the entry
        contained_symbol_table: Dict[str, Dict[str, Any]] = {}
        contained_diagnostics: List[FhirDiagnostic] = []
        contained_malicious = False
        raw_contained = resource.get("contained")
        if isinstance(raw_contained, list):
            for c_idx, c_res in enumerate(raw_contained):
                if not isinstance(c_res, dict):
                    contained_diagnostics.append(
                        FhirDiagnostic(
                            code="malformed_contained_resource",
                            severity="error",
                            message="Contained FHIR resource must be a JSON object.",
                            entry_index=idx,
                            resource_type=rtype,
                            source_id=source_id,
                            field_paths=(f"contained[{c_idx}]",),
                        )
                    )
                    continue
                c_rtype = str(c_res.get("resourceType") or "").strip()
                c_raw_id = str(c_res.get("id") or f"contained-{c_idx}").strip().lstrip("#")
                if _has_Unsafe_id_chars(c_raw_id):
                    contained_malicious = True
                    contained_diagnostics.append(
                        FhirDiagnostic(
                            code="malicious_contained_resource_id",
                            severity="error",
                            message="Contained resource 'id' contains forbidden characters.",
                            entry_index=idx,
                            resource_type=rtype,
                            source_id=source_id,
                            field_paths=(f"contained[{c_idx}].id",),
                        )
                    )
                    continue
                c_val = validate_and_normalize_fhir_resource(
                    c_res,
                    rtype=c_rtype,
                    entry_index=idx,
                    source_id=f"{source_id}#{c_raw_id}",
                )
                if not c_val.is_valid:
                    for cd in c_val.diagnostics:
                        contained_diagnostics.append(
                            FhirDiagnostic(
                                code=f"contained_{cd.code}",
                                severity="warning",
                                message=cd.message,
                                entry_index=idx,
                                resource_type=rtype,
                                source_id=source_id,
                                field_paths=tuple(f"contained[{c_idx}].{fp}" for fp in cd.field_paths)
                                or (f"contained[{c_idx}]",),
                            )
                        )
                    continue
                contained_symbol_table[c_raw_id] = {
                    "resource_type": c_rtype,
                    "logical_id": c_raw_id,
                    "source_id": f"{c_rtype}:{logical_id}#{c_raw_id}",
                    "contained": True,
                    "normalized": c_val.normalized,
                }

        if contained_malicious:
            _record_quarantine(
                entry_index=idx,
                resource_type=rtype,
                source_id=source_id,
                reason_code="malicious_contained_resource_id",
                entry_diagnostics=contained_diagnostics,
            )
            continue

        if contained_diagnostics:
            diagnostics.extend(d.to_dict() for d in contained_diagnostics)

        symbol_info = {
            "resource_type": rtype,
            "logical_id": logical_id,
            "source_id": source_id,
            "entry_index": idx,
            "full_url": full_url or None,
        }
        bundle_symbol_table[f"{rtype}/{logical_id}"] = symbol_info
        if raw_id is not None and str(raw_id).strip():
            bundle_symbol_table[f"{rtype}/{str(raw_id).strip()}"] = symbol_info
        if full_url:
            bundle_symbol_table[full_url] = symbol_info

        if rtype == "Patient":
            canonical_pat_key = f"Patient/{logical_id}"
            bundle_patient_keys.add(canonical_pat_key)
            patient_identifier_aliases[logical_id] = canonical_pat_key
            patient_identifier_aliases[canonical_pat_key] = canonical_pat_key
            if full_url:
                patient_identifier_aliases[full_url] = canonical_pat_key
            for ident in val_res.normalized.get("identifier") or []:
                if isinstance(ident, dict) and ident.get("value"):
                    id_val = str(ident["value"]).strip()
                    if id_val:
                        patient_identifier_aliases[id_val] = canonical_pat_key
                        patient_identifier_aliases[f"Patient/{id_val}"] = canonical_pat_key

        validated_entries.append({
            "entry_index": idx,
            "resource_type": rtype,
            "logical_id": logical_id,
            "source_id": source_id,
            "full_url": full_url or None,
            "validation": val_res,
            "contained_symbol_table": contained_symbol_table,
        })

    # =========================================================================
    # Pass 2: Resolve Outbound References & Inspect Patient Context
    # =========================================================================
    explicit_expected_tokens: Set[str] = set()
    if expected_patient_id and str(expected_patient_id).strip():
        explicit_expected_tokens.add(str(expected_patient_id).strip())
    if verified_source_patient_ids:
        for vp in verified_source_patient_ids:
            if vp and str(vp).strip():
                explicit_expected_tokens.add(str(vp).strip())

    has_explicit_patient_filter = bool(explicit_expected_tokens)
    verified_patient_keys: Set[str] = set()
    if has_explicit_patient_filter:
        for tok in explicit_expected_tokens:
            if tok in patient_identifier_aliases:
                verified_patient_keys.add(patient_identifier_aliases[tok])
            else:
                verified_patient_keys.add(_canonicalize_patient_token(tok, bundle_symbol_table))
        if profile_id and str(profile_id).strip():
            verified_patient_keys.add(f"Patient/{str(profile_id).strip()}")

    # Pre-resolve references for all validated entries and gather referenced patient identities
    referenced_patient_keys_across_bundle: Set[str] = set()
    entry_resolved_refs: Dict[int, List[Dict[str, Any]]] = {}
    entry_patient_check_errors: Dict[int, Tuple[str, List[FhirDiagnostic]]] = {}

    for item in validated_entries:
        idx = item["entry_index"]
        rtype = item["resource_type"]
        source_id = item["source_id"]
        val_res = item["validation"]
        contained_table = item["contained_symbol_table"]

        # Attach synthesized_defaults temporarily so extract_references skips boilerplate defaults
        probe_res = copy.deepcopy(val_res.normalized)
        probe_res["_carefold_provenance"] = {
            "synthesized_defaults": val_res.synthesized_defaults,
        }
        raw_refs = extract_references(probe_res, rtype=rtype)

        # 1. Check for malicious reference URIs anywhere in the resource
        malicious_diags: List[FhirDiagnostic] = []
        for ref in raw_refs:
            if ref.get("is_malicious"):
                malicious_diags.append(
                    FhirDiagnostic(
                        code=ref.get("diagnostic_code") or "malicious_reference_uri",
                        severity="error",
                        message="FHIR resource contains a malicious or forbidden reference URI.",
                        entry_index=idx,
                        resource_type=rtype,
                        source_id=source_id,
                        field_paths=(ref.get("field") or "reference",),
                    )
                )
        if malicious_diags:
            entry_patient_check_errors[idx] = (malicious_diags[0].code, malicious_diags)
            continue

        # 2. Resolve each reference against contained_table and bundle_symbol_table
        resolved_refs: List[Dict[str, Any]] = []
        dangling_diags: List[FhirDiagnostic] = []

        for ref in raw_refs:
            ref_copy = copy.deepcopy(ref)
            raw_ref_str = ref_copy.get("raw_reference") or ""
            kind = ref_copy.get("kind")

            if kind == "contained":
                c_id = ref_copy.get("target_id") or ""
                if c_id in contained_table:
                    c_target = contained_table[c_id]
                    ref_copy["target_type"] = c_target["resource_type"]
                    ref_copy["target_id"] = c_target["logical_id"]
                    ref_copy["target_source_id"] = c_target["source_id"]
                    ref_copy["resolved_reference"] = f"{c_target['resource_type']}/#{c_target['logical_id']}"
                    ref_copy["resolved"] = True
                    ref_copy["resolution_scope"] = "contained"
                else:
                    ref_copy["resolved_reference"] = raw_ref_str
                    ref_copy["target_source_id"] = None
                    ref_copy["resolved"] = False
                    ref_copy["resolution_scope"] = "unresolved_contained"
                    ref_copy["diagnostic_code"] = "dangling_contained_reference"
                    dangling_diags.append(
                        FhirDiagnostic(
                            code="dangling_contained_reference",
                            severity="error",
                            message="Contained reference does not match any resource in 'contained'.",
                            entry_index=idx,
                            resource_type=rtype,
                            source_id=source_id,
                            field_paths=(ref_copy.get("field") or "reference",),
                        )
                    )
            elif raw_ref_str in bundle_symbol_table:
                b_target = bundle_symbol_table[raw_ref_str]
                ref_copy["target_type"] = b_target["resource_type"]
                ref_copy["target_id"] = b_target["logical_id"]
                ref_copy["target_source_id"] = b_target["source_id"]
                ref_copy["resolved_reference"] = f"{b_target['resource_type']}/{b_target['logical_id']}"
                ref_copy["resolved"] = True
                ref_copy["resolution_scope"] = "bundle"
                ref_copy["is_external"] = False
            elif (
                ref_copy.get("target_type")
                and ref_copy.get("target_id")
                and f"{ref_copy['target_type']}/{ref_copy['target_id']}" in bundle_symbol_table
            ):
                rel_key = f"{ref_copy['target_type']}/{ref_copy['target_id']}"
                b_target = bundle_symbol_table[rel_key]
                ref_copy["target_type"] = b_target["resource_type"]
                ref_copy["target_id"] = b_target["logical_id"]
                ref_copy["target_source_id"] = b_target["source_id"]
                ref_copy["resolved_reference"] = rel_key
                ref_copy["resolved"] = True
                ref_copy["resolution_scope"] = "bundle"
                ref_copy["is_external"] = False
            elif kind == "relative" and ref_copy.get("target_type") and ref_copy.get("target_id"):
                rel_key = f"{ref_copy['target_type']}/{ref_copy['target_id']}"
                ref_copy["resolved_reference"] = rel_key
                ref_copy["target_source_id"] = f"{ref_copy['target_type']}:{ref_copy['target_id']}"
                ref_copy["resolved"] = False
                ref_copy["resolution_scope"] = "external_relative"
            else:
                ref_copy["resolved_reference"] = raw_ref_str
                ref_copy["target_source_id"] = None
                ref_copy["resolved"] = False
                ref_copy["resolution_scope"] = "external_unresolved"

            # Update is_patient_subject after target_type resolution
            subject_paths = set(RESOURCE_PATIENT_SUBJECT_PATHS.get(rtype, ()))
            ref_copy["is_patient_subject"] = (
                ref_copy.get("field") in subject_paths or ref_copy.get("target_type") == "Patient"
            )
            resolved_refs.append(ref_copy)

        if dangling_diags:
            entry_patient_check_errors[idx] = ("dangling_contained_reference", dangling_diags)
            continue

        # 3. Inspect patient/subject references on this resource
        subject_paths = set(RESOURCE_PATIENT_SUBJECT_PATHS.get(rtype, ()))
        subj_refs = [r for r in resolved_refs if r.get("field") in subject_paths]
        patient_Validation_diags: List[FhirDiagnostic] = []

        for sref in subj_refs:
            t_type = sref.get("target_type")
            s_kind = sref.get("kind")
            if s_kind == "invalid":
                patient_Validation_diags.append(
                    FhirDiagnostic(
                        code=sref.get("diagnostic_code") or "invalid_patient_reference",
                        severity="error",
                        message="Resource patient/subject reference has an invalid format.",
                        entry_index=idx,
                        resource_type=rtype,
                        source_id=source_id,
                        field_paths=(sref.get("field") or "subject",),
                    )
                )
            elif s_kind == "urn_uuid" and not sref.get("resolved"):
                patient_Validation_diags.append(
                    FhirDiagnostic(
                        code="unresolvable_patient_urn_uuid",
                        severity="error",
                        message="Resource patient/subject urn:uuid reference could not be resolved in the Bundle.",
                        entry_index=idx,
                        resource_type=rtype,
                        source_id=source_id,
                        field_paths=(sref.get("field") or "subject",),
                    )
                )
            elif t_type and t_type not in ("Patient", "Group"):
                patient_Validation_diags.append(
                    FhirDiagnostic(
                        code="invalid_patient_subject_target_type",
                        severity="error",
                        message=f"Resource patient/subject reference points to non-patient type '{t_type}'.",
                        entry_index=idx,
                        resource_type=rtype,
                        source_id=source_id,
                        field_paths=(sref.get("field") or "subject",),
                    )
                )
            elif t_type == "Patient" and sref.get("target_id"):
                pat_key = (
                    f"Patient/#{sref['target_id']}"
                    if sref.get("resolution_scope") == "contained"
                    else f"Patient/{sref['target_id']}"
                )
                sref["canonical_source_patient_key"] = pat_key
                if sref.get("resolution_scope") != "contained":
                    referenced_patient_keys_across_bundle.add(pat_key)

        if patient_Validation_diags:
            entry_patient_check_errors[idx] = (patient_Validation_diags[0].code, patient_Validation_diags)
            continue

        entry_resolved_refs[idx] = resolved_refs

    # =========================================================================
    # Pass 3: Determine Bundle-Level Patient Verification Context
    # =========================================================================
    patient_context_status = "implicit_profile_patient"
    ambiguous_multi_patient = False

    if has_explicit_patient_filter:
        patient_context_status = "explicit_patient_filter"
    elif len(bundle_patient_keys) > 1:
        ambiguous_multi_patient = True
        patient_context_status = "ambiguous_multiple_patients"
        diagnostics.append(
            FhirDiagnostic(
                code="ambiguous_multi_patient_bundle",
                severity="error",
                message=(
                    f"Bundle contains {len(bundle_patient_keys)} distinct Patient resources without "
                    f"an explicit expected_patient_id filter."
                ),
                field_paths=("entry",),
            ).to_dict()
        )
    elif len(bundle_patient_keys) == 1:
        verified_patient_keys = set(bundle_patient_keys)
        if profile_id and str(profile_id).strip():
            verified_patient_keys.add(f"Patient/{str(profile_id).strip()}")
        patient_context_status = "single_bundle_patient_verified"
    else:
        # 0 Patient resources in bundle; inspect referenced_patient_keys_across_bundle
        non_profile_refs = {
            k
            for k in referenced_patient_keys_across_bundle
            if not (profile_id and k == f"Patient/{str(profile_id).strip()}")
        }
        if len(non_profile_refs) > 1:
            ambiguous_multi_patient = True
            patient_context_status = "ambiguous_multiple_patients"
            diagnostics.append(
                FhirDiagnostic(
                    code="ambiguous_multi_patient_references",
                    severity="error",
                    message=(
                        f"Bundle resources reference {len(non_profile_refs)} distinct Patient identities "
                        f"without a disambiguating expected_patient_id filter."
                    ),
                    field_paths=("entry",),
                ).to_dict()
            )
        elif len(non_profile_refs) == 1:
            verified_patient_keys = set(referenced_patient_keys_across_bundle)
            if profile_id and str(profile_id).strip():
                verified_patient_keys.add(f"Patient/{str(profile_id).strip()}")
            patient_context_status = "single_source_patient_verified"
        elif referenced_patient_keys_across_bundle:
            verified_patient_keys = set(referenced_patient_keys_across_bundle)
            patient_context_status = "single_source_patient_verified"

    # =========================================================================
    # Pass 4: Finalize Staged Records, Quarantine Mismatched Patients & Rewrite
    # =========================================================================
    staged_records: List[Dict[str, Any]] = []
    counts_by_type: Dict[str, int] = {}
    counts_by_scope: Dict[str, int] = {}
    dates: List[str] = []
    clean_profile_id = str(profile_id).strip() if profile_id and str(profile_id).strip() else None

    for item in validated_entries:
        idx = item["entry_index"]
        rtype = item["resource_type"]
        logical_id = item["logical_id"]
        source_id = item["source_id"]
        full_url = item["full_url"]
        val_res = item["validation"]

        # Check if entry failed reference validation in Pass 2
        if idx in entry_patient_check_errors:
            err_code, err_diags = entry_patient_check_errors[idx]
            _record_quarantine(
                entry_index=idx,
                resource_type=rtype,
                source_id=source_id,
                reason_code=err_code,
                entry_diagnostics=err_diags,
            )
            continue

        resolved_refs = entry_resolved_refs.get(idx, [])

        # Check multi-patient ambiguity quarantine
        if ambiguous_multi_patient and strict_patient_matching:
            if rtype == "Patient" or rtype in PATIENT_SUBJECT_RESOURCE_TYPES:
                _record_quarantine(
                    entry_index=idx,
                    resource_type=rtype,
                    source_id=source_id,
                    reason_code="ambiguous_multi_patient_bundle",
                    entry_diagnostics=[
                        FhirDiagnostic(
                            code="ambiguous_multi_patient_bundle",
                            severity="error",
                            message=(
                                f"Resource '{rtype}' quarantined because the Bundle contains multiple "
                                f"distinct patient identities without an explicit patient filter."
                            ),
                            entry_index=idx,
                            resource_type=rtype,
                            source_id=source_id,
                        )
                    ],
                )
                continue

        # Check Patient entry against verified_patient_keys when filter is active
        if rtype == "Patient" and verified_patient_keys:
            pat_self_key = f"Patient/{logical_id}"
            if pat_self_key not in verified_patient_keys:
                _record_quarantine(
                    entry_index=idx,
                    resource_type=rtype,
                    source_id=source_id,
                    reason_code="wrong_patient_resource",
                    entry_diagnostics=[
                        FhirDiagnostic(
                            code="wrong_patient_resource",
                            severity="error",
                            message="Patient resource in Bundle does not match the target profile's expected patient identity.",
                            entry_index=idx,
                            resource_type=rtype,
                            source_id=source_id,
                            field_paths=("id",),
                        )
                    ],
                )
                continue

        # Check patient/subject references on clinical/paperwork resources against verified_patient_keys
        subject_paths = set(RESOURCE_PATIENT_SUBJECT_PATHS.get(rtype, ()))
        wrong_patient_diags: List[FhirDiagnostic] = []
        for sref in resolved_refs:
            if sref.get("field") in subject_paths or sref.get("target_type") == "Patient":
                pat_key = sref.get("canonical_source_patient_key")
                if not pat_key and sref.get("target_type") == "Patient" and sref.get("target_id"):
                    pat_key = f"Patient/{sref['target_id']}"
                if pat_key and sref.get("resolution_scope") != "contained" and verified_patient_keys:
                    if pat_key not in verified_patient_keys:
                        wrong_patient_diags.append(
                            FhirDiagnostic(
                                code="wrong_patient_reference",
                                severity="error",
                                message="Resource references a patient identity that does not match the verified patient for this import.",
                                entry_index=idx,
                                resource_type=rtype,
                                source_id=source_id,
                                field_paths=(sref.get("field") or "subject",),
                            )
                        )
                elif sref.get("is_external") and sref.get("kind") in ("absolute", "urn_oid", "logical"):
                    # External absolute/logical patient reference when a specific patient filter or bundle patient exists
                    if verified_patient_keys and sref.get("raw_reference") not in verified_patient_keys:
                        wrong_patient_diags.append(
                            FhirDiagnostic(
                                code="unverified_external_patient_reference",
                                severity="error",
                                message="Resource references an external unverified patient URI.",
                                entry_index=idx,
                                resource_type=rtype,
                                source_id=source_id,
                                field_paths=(sref.get("field") or "subject",),
                            )
                        )

        if wrong_patient_diags and strict_patient_matching:
            _record_quarantine(
                entry_index=idx,
                resource_type=rtype,
                source_id=source_id,
                reason_code=wrong_patient_diags[0].code,
                entry_diagnostics=wrong_patient_diags,
            )
            continue

        # Build reference rewrite map and provenance mappings
        fhir_copy = copy.deepcopy(val_res.normalized)
        rewrite_map: Dict[Tuple[str, str], str] = {}
        source_identity_mappings: List[Dict[str, Any]] = []
        reference_resolutions: List[Dict[str, Any]] = []

        if rtype == "Patient" and clean_profile_id:
            source_identity_mappings.append({
                "field": "id",
                "source_reference": full_url or f"Patient/{logical_id}",
                "source_patient_id": logical_id,
                "canonical_reference": f"Patient/{clean_profile_id}",
            })

        for ref_edge in resolved_refs:
            raw_ref_str = ref_edge.get("raw_reference") or ""
            field_path = ref_edge.get("field") or ""
            is_verified_patient_ref = (
                ref_edge.get("target_type") == "Patient"
                and ref_edge.get("resolution_scope") != "contained"
                and (
                    not verified_patient_keys
                    or f"Patient/{ref_edge.get('target_id')}" in verified_patient_keys
                )
            )

            if is_verified_patient_ref:
                src_pat_id = ref_edge.get("target_id")
                canonical_pat_ref = (
                    f"Patient/{clean_profile_id}"
                    if clean_profile_id
                    else f"Patient/{src_pat_id}"
                )
                source_identity_mappings.append({
                    "field": field_path,
                    "source_reference": raw_ref_str,
                    "source_patient_id": src_pat_id,
                    "canonical_reference": canonical_pat_ref,
                })
                ref_edge["source_patient_reference"] = raw_ref_str
                ref_edge["source_patient_id"] = src_pat_id
                if clean_profile_id:
                    ref_edge["target_type"] = "Patient"
                    ref_edge["target_id"] = clean_profile_id
                    ref_edge["target_source_id"] = f"Patient:{clean_profile_id}"
                    ref_edge["resolved_reference"] = canonical_pat_ref
                    ref_edge["resolved"] = True
                    rewrite_map[(field_path, raw_ref_str)] = canonical_pat_ref
                elif raw_ref_str != canonical_pat_ref and ref_edge.get("resolved"):
                    rewrite_map[(field_path, raw_ref_str)] = canonical_pat_ref
            elif ref_edge.get("resolution_scope") == "bundle" and ref_edge.get("resolved_reference"):
                # Non-patient bundle-internal reference (e.g. urn:uuid -> Practitioner/prac-1 or Encounter/enc-1)
                resolved_rel = ref_edge["resolved_reference"]
                if raw_ref_str != resolved_rel:
                    rewrite_map[(field_path, raw_ref_str)] = resolved_rel

            reference_resolutions.append({
                "field": field_path,
                "raw_reference": raw_ref_str,
                "resolved_reference": ref_edge.get("resolved_reference"),
                "target_type": ref_edge.get("target_type"),
                "target_id": ref_edge.get("target_id"),
                "resolution_scope": ref_edge.get("resolution_scope"),
                "resolved": bool(ref_edge.get("resolved")),
                "is_external": bool(ref_edge.get("is_external")),
            })

        if rewrite_map:
            _rewrite_reference_values_in_node(fhir_copy, rewrite_map)

        effective_iso, date_str = extract_effective_iso(fhir_copy, rtype=rtype)
        dates.append(date_str)
        code_val, display_val = extract_primary_coding_and_display(fhir_copy, rtype=rtype)
        codings_list = extract_codings(fhir_copy, rtype=rtype)
        resource_scope = resolve_resource_scope(rtype, fhir_copy)

        source_display = f"From {clean_source}, {date_str}"
        fhir_copy.setdefault("meta", {})
        if isinstance(fhir_copy["meta"], dict):
            fhir_copy["meta"]["source"] = clean_source
            fhir_copy["meta"]["trust"] = "untrusted"

        fhir_copy["_carefold_provenance"] = {
            "source_name": clean_source,
            "source_display": source_display,
            "trust": "untrusted",
            "fhir_version": TARGET_FHIR_VERSION,
            "scope": resource_scope,
            "entry_full_url": full_url,
            "source_logical_id": logical_id,
            "raw_resource": val_res.raw_resource,
            "synthesized_defaults": val_res.synthesized_defaults,
            "source_identity_mappings": source_identity_mappings,
            "reference_resolutions": reference_resolutions,
        }

        staged_records.append({
            "resource_type": rtype,
            "source_id": source_id,
            "logical_id": logical_id,
            "scope": resource_scope,
            "effective_at": effective_iso,
            "display": display_val,
            "code": code_val,
            "codings": codings_list,
            "references": resolved_refs,
            "data": fhir_copy,
            "source_display": source_display,
            "trust": "untrusted",
        })
        counts_by_type[rtype] = counts_by_type.get(rtype, 0) + 1
        counts_by_scope[resource_scope] = counts_by_scope.get(resource_scope, 0) + 1

    # Synthesize batch Provenance summary resource
    now_iso = datetime.now(timezone.utc).isoformat()
    now_date = now_iso[:10]
    bundle_id = str(bundle.get("id") or uuid.uuid4())
    prov_targets = [{"reference": r["source_id"]} for r in staged_records] or [{"display": clean_source}]
    non_prov_count = len(staged_records)
    prov_model = FhirProvenance.model_validate({
        "resourceType": "Provenance",
        "id": f"prov-{bundle_id}",
        "recorded": now_iso,
        "target": prov_targets,
        "agent": [
            {
                "who": {"display": clean_source},
            }
        ],
        "text": {
            "status": "generated",
            "div": (
                f'<div xmlns="http://www.w3.org/1999/xhtml">'
                f"From {clean_source}, {now_date} ({non_prov_count} clinical resources)"
                f"</div>"
            ),
        },
    })
    provenance_fhir: Dict[str, Any] = prov_model.model_dump(mode="json", exclude_none=True)
    provenance_fhir["_carefold_provenance"] = {
        "source_name": clean_source,
        "source_display": f"From {clean_source}, {now_date}",
        "trust": "untrusted",
        "fhir_version": TARGET_FHIR_VERSION,
        "scope": "health.clinical",
    }
    provenance_refs = [
        {
            "field": "target",
            "raw_reference": r["source_id"],
            "resolved_reference": f"{r['resource_type']}/{r.get('logical_id') or r['source_id'].split(':', 1)[-1]}",
            "kind": "relative",
            "target_type": r["resource_type"],
            "target_id": r.get("logical_id") or r["source_id"].split(":", 1)[-1],
            "target_source_id": r["source_id"],
            "resolved": True,
            "resolution_scope": "bundle",
            "is_external": False,
            "is_malicious": False,
            "is_patient_subject": r["resource_type"] == "Patient",
            "diagnostic_code": None,
        }
        for r in staged_records
    ]
    provenance_record: Dict[str, Any] = {
        "resource_type": "Provenance",
        "resourceType": "Provenance",
        "source_id": f"Provenance:{bundle_id}",
        "logical_id": f"prov-{bundle_id}",
        "scope": "health.clinical",
        "effective_at": now_iso,
        "display": f"Provenance: {clean_source} ({non_prov_count} records)",
        "code": "PROVENANCE",
        "codings": [],
        "references": provenance_refs,
        "data": provenance_fhir,
        "source_display": f"From {clean_source}, {now_date}",
        "trust": "untrusted",
    }

    staged_records.append(provenance_record)
    counts_by_type["Provenance"] = counts_by_type.get("Provenance", 0) + 1
    counts_by_scope["health.clinical"] = counts_by_scope.get("health.clinical", 0) + 1

    sorted_dates = sorted(d for d in dates if d)
    date_range = {
        "min": sorted_dates[0] if sorted_dates else now_date,
        "max": sorted_dates[-1] if sorted_dates else now_date,
    }

    return {
        "format": "fhir_r4",
        "fhir_version": TARGET_FHIR_VERSION,
        "validation_capabilities": FHIR_VALIDATION_CAPABILITIES,
        "source_name": clean_source,
        "records": staged_records,
        "quarantined_records": quarantined_records,
        "diagnostics": diagnostics,
        "provenance": provenance_record,
        "summary": {
            "total_records": len(staged_records),
            "clinical_records": len(staged_records) - 1,
            "counts_by_type": counts_by_type,
            "counts_by_scope": counts_by_scope,
            "quarantined_count": len(quarantined_records),
            "unsupported_count": unsupported_count,
            "diagnostics_count": len(diagnostics),
            "patient_context": {
                "status": patient_context_status,
                "bundle_patient_count": len(bundle_patient_keys),
                "verified_patient_keys": sorted(verified_patient_keys),
                "ambiguous_multi_patient": ambiguous_multi_patient,
            },
            "date_range": date_range,
            "source_name": clean_source,
        },
    }


__all__ = [
    "CARE_PLAN_AND_ADMIN_RESOURCE_TYPES",
    "CLINICAL_CORE_RESOURCE_TYPES",
    "CLINICAL_FHIR_RESOURCE_TYPES",
    "DEMOGRAPHIC_AND_CARE_TEAM_RESOURCE_TYPES",
    "DIAGNOSTIC_AND_VITALS_RESOURCE_TYPES",
    "FHIR_VALIDATION_CAPABILITIES",
    "INFRASTRUCTURE_AND_ACTOR_RESOURCE_TYPES",
    "PAPERWORK_FHIR_RESOURCE_TYPES",
    "PATIENT_SUBJECT_RESOURCE_TYPES",
    "R4B_ONLY_RESOURCE_TYPES",
    "RESOURCE_PATIENT_SUBJECT_PATHS",
    "SUPPORTED_FHIR_RESOURCE_TYPES",
    "TARGET_FHIR_RELEASE",
    "TARGET_FHIR_VERSION",
    "parse_fhir_bundle",
]
