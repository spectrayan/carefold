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

"""Conservative cross-portal clinical deduplication, near-duplicate review linking, and reversible merge (#283).

Design & Safety Invariants:
1. **Conservative Strong-Identity Merging Only**:
   - A record is merged into an existing `HealthResource` **only** when both share a strong
     clinical identity within the exact same `(profile_id, scope)`:
     a) Same normalized `(resource_type, canonical_system, canonical_code, normalized_effective_time,
        normalized_value, normalized_unit, status)` after terminology and curated unit normalization, OR
     b) Same normalized source/business `identifier` `(resource_type, identifier.system, identifier.value)`.
   - Uncoded records, records with unknown/unmapped code systems, or Observations with unknown/unconvertible
     units are **never** eligible for strong-fingerprint merging.
2. **Near-Duplicates Are Linked & Flagged for Review (Never Silently Merged or Deleted)**:
   - Records that share the same clinical concept/code in the same `(profile_id, scope)` but differ in
     effective timestamp (e.g., two vitals/labs at different times on the same day), differ in measured
     value, differ in clinical/medication status, or match across different code systems via a curated
     concept group (e.g., SNOMED CT `44054006` vs ICD-10-CM `E11.9`) are persisted as distinct
     `HealthResource` rows, flagged with `review_required=True` in `_carefold_provenance["dedup"]`,
     and linked via `HealthResourceReference` (`reference_field="near_duplicate_of"`).
3. **Strict Profile & Scope Isolation**:
   - Every fingerprint and candidate lookup is strictly partitioned by `(profile_id, scope)`.
   - Cross-profile or cross-scope (`health.clinical` vs `health.paperwork`) matching is impossible.
4. **Full Reversibility & Provenance Preservation**:
   - Every merge records the pre-merge `version_id`, incoming source lineage, and full incoming
     normalized snapshot in `_carefold_provenance["merged_sources"]` and writes an immutable
     `HealthResourceVersion` row (`operation="merge"`).
   - `reverse_dedup_merge` restores the target `HealthResource` to its pre-merge version state
     (appending an immutable `operation="revert_merge"` version row) and optionally materializes
     the unmerged incoming record as a separate `HealthResource`.
   - All imported and merged records remain marked `trust="untrusted"`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.fhir.registry import (
    DECLARATIVE_EFFECTIVE_DATE_EXPRESSIONS,
    evaluate_fhirpath,
    extract_codings,
    extract_references,
    resolve_resource_scope,
)
from carefold.fhir.terminology import (
    CANONICAL_CODE_SYSTEM_URIS,
    LOINC_SYSTEM,
    ORIGINAL_QUANTITY_EXTENSION_URL,
    get_curated_concept_group,
    normalize_code_system_uri,
    normalize_fhir_terminology_and_units,
)
from carefold.models.health import (
    HealthResource,
    HealthResourceCoding,
    HealthResourceReference,
    HealthResourceVersion,
)
from carefold.scope.context import current_scope_context
from yarvelle_core.db.models import utc_now

DEDUP_ELIGIBLE_RESOURCE_TYPES = frozenset({
    "Observation",
    "Immunization",
    "Condition",
    "MedicationRequest",
    "MedicationStatement",
    "MedicationDispense",
    "AllergyIntolerance",
    "Procedure",
    "DiagnosticReport",
})

_ISO_DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _normalize_explicit_effective_time(
    resource: Dict[str, Any],
    rtype: str,
) -> Tuple[Optional[str], Optional[str], bool]:
    """Extracts and normalizes an explicit effective timestamp from a FHIR resource.

    Returns:
        `(canonical_utc_iso_or_none, yyyy_mm_dd_or_none, has_explicit_time_of_day)`
        Does NOT fall back to `datetime.now()`, ensuring resources without an explicit
        effective date never collide on wall-clock import time.
    """
    if not isinstance(resource, dict):
        return None, None, False

    priority_fields_by_type: Dict[str, Tuple[str, ...]] = {
        "Observation": ("effectiveDateTime", "effectivePeriod.start", "effectiveInstant"),
        "Immunization": ("occurrenceDateTime", "occurrencePeriod.start", "recorded"),
        "Condition": ("onsetDateTime", "onsetPeriod.start", "recordedDate"),
        "MedicationRequest": ("authoredOn", "effectiveDateTime", "effectivePeriod.start"),
        "MedicationStatement": ("effectiveDateTime", "effectivePeriod.start", "dateAsserted"),
        "MedicationDispense": ("whenHandedOver", "whenPrepared"),
        "AllergyIntolerance": ("recordedDate", "onsetDateTime", "onsetPeriod.start"),
        "Procedure": ("performedDateTime", "performedPeriod.start"),
        "DiagnosticReport": ("effectiveDateTime", "effectivePeriod.start", "issued"),
    }
    expressions = priority_fields_by_type.get(rtype, ()) + tuple(
        e for e in DECLARATIVE_EFFECTIVE_DATE_EXPRESSIONS if e != "meta.lastUpdated"
    )

    for expr in expressions:
        matches = evaluate_fhirpath(resource, expr)
        for raw in matches:
            if not raw or not isinstance(raw, str) or not raw.strip():
                continue
            clean = raw.strip()
            m = _ISO_DATE_PREFIX_RE.match(clean)
            if not m:
                continue
            yyyy, mm, dd = m.groups()
            date_str = f"{yyyy}-{mm}-{dd}"
            if "T" not in clean:
                return f"{date_str}T00:00:00+00:00", date_str, False

            iso_candidate = clean[:-1] + "+00:00" if clean.endswith("Z") else clean
            try:
                dt = datetime.fromisoformat(iso_candidate)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                canonical_iso = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
                utc_date = dt.strftime("%Y-%m-%d")
                has_time = not (dt.hour == 0 and dt.minute == 0 and dt.second == 0)
                return canonical_iso, utc_date, has_time
            except ValueError:
                return f"{date_str}T00:00:00+00:00", date_str, False

    return None, None, False


def _extract_primary_canonical_coding(
    resource: Dict[str, Any],
    rtype: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extracts `(canonical_system, code, concept_group)` from the primary clinical code element."""
    primary_paths_by_type: Dict[str, Tuple[str, ...]] = {
        "Observation": ("code.coding",),
        "Immunization": ("vaccineCode.coding", "code.coding"),
        "Condition": ("code.coding",),
        "MedicationRequest": ("medicationCodeableConcept.coding", "code.coding"),
        "MedicationStatement": ("medicationCodeableConcept.coding", "code.coding"),
        "MedicationDispense": ("medicationCodeableConcept.coding", "code.coding"),
        "AllergyIntolerance": ("code.coding", "reaction.substance.coding"),
        "Procedure": ("code.coding",),
        "DiagnosticReport": ("code.coding",),
    }
    paths = primary_paths_by_type.get(rtype, ("code.coding", "type.coding"))
    for path in paths:
        matches = evaluate_fhirpath(resource, path)
        for item in matches:
            if not isinstance(item, dict):
                continue
            raw_code = item.get("code")
            code_str = str(raw_code).strip() if raw_code is not None and str(raw_code).strip() else None
            if not code_str or code_str.lower() == "unknown":
                continue
            raw_sys = item.get("system")
            sys_outcome = normalize_code_system_uri(raw_sys, code=code_str, resource_type=rtype)
            if sys_outcome.is_known_system and sys_outcome.canonical_system in CANONICAL_CODE_SYSTEM_URIS:
                c_sys = sys_outcome.canonical_system
                c_group = get_curated_concept_group(c_sys, code_str)
                return c_sys, code_str, c_group
    return None, None, None


def _extract_clinical_status_token(resource: Dict[str, Any], rtype: str) -> str:
    """Extracts normalized status or clinicalStatus token for a FHIR resource."""
    if rtype in ("Condition", "AllergyIntolerance"):
        cs = resource.get("clinicalStatus")
        if isinstance(cs, dict):
            codings = cs.get("coding")
            if isinstance(codings, list) and codings and isinstance(codings[0], dict):
                c = codings[0].get("code")
                if c and str(c).strip():
                    return str(c).strip().lower()
            txt = cs.get("text")
            if txt and str(txt).strip():
                return str(txt).strip().lower()
        elif isinstance(cs, str) and cs.strip():
            return cs.strip().lower()
        raw_status = resource.get("status")
        if isinstance(raw_status, str) and raw_status.strip():
            return raw_status.strip().lower()
        return "active"

    raw_status = resource.get("status")
    if isinstance(raw_status, str) and raw_status.strip():
        return raw_status.strip().lower()
    return "active"


def _extract_observation_value_and_unit_tokens(
    resource: Dict[str, Any],
    *,
    has_unknown_units: bool,
) -> Tuple[Optional[str], Optional[str], bool]:
    """Extracts `(normalized_value_token, normalized_unit_token, is_strong_value_valid)` from an Observation."""
    if has_unknown_units:
        return None, None, False

    vq = resource.get("valueQuantity")
    if isinstance(vq, dict) and vq.get("value") is not None:
        try:
            num_val = round(float(vq["value"]), 2)
        except (ValueError, TypeError):
            return None, None, False
        unit_tok = str(vq.get("code") or vq.get("unit") or "").strip()
        if not unit_tok:
            return None, None, False
        return f"{num_val:.2f}", unit_tok, True

    components = resource.get("component")
    if isinstance(components, list) and components:
        comp_tokens: List[str] = []
        comp_units: List[str] = []
        for comp in components:
            if not isinstance(comp, dict):
                continue
            c_vq = comp.get("valueQuantity")
            if not isinstance(c_vq, dict) or c_vq.get("value") is None:
                return None, None, False
            try:
                c_val = round(float(c_vq["value"]), 2)
            except (ValueError, TypeError):
                return None, None, False
            c_unit = str(c_vq.get("code") or c_vq.get("unit") or "").strip()
            if not c_unit:
                return None, None, False
            c_code = ""
            c_code_obj = comp.get("code")
            if isinstance(c_code_obj, dict):
                c_codings = c_code_obj.get("coding")
                if isinstance(c_codings, list) and c_codings and isinstance(c_codings[0], dict):
                    c_code = str(c_codings[0].get("code") or "").strip()
                elif c_code_obj.get("text"):
                    c_code = str(c_code_obj.get("text")).strip().lower()
            comp_tokens.append(f"{c_code}:{c_val:.2f}:{c_unit}")
            comp_units.append(c_unit)
        if comp_tokens:
            comp_tokens.sort()
            return ";".join(comp_tokens), ",".join(sorted(set(comp_units))), True

    vcc = resource.get("valueCodeableConcept")
    if isinstance(vcc, dict) and isinstance(vcc.get("coding"), list):
        for c_item in vcc["coding"]:
            if isinstance(c_item, dict) and c_item.get("code") and c_item.get("system"):
                sys_out = normalize_code_system_uri(c_item.get("system"), code=str(c_item.get("code")))
                if sys_out.is_known_system and sys_out.canonical_system:
                    return f"concept:{sys_out.canonical_system}|{str(c_item['code']).strip()}", "CodeableConcept", True

    v_str = resource.get("valueString")
    if isinstance(v_str, str) and v_str.strip():
        return f"string:{v_str.strip()}", "string", True

    return None, None, False


def _extract_medication_dosage_token(resource: Dict[str, Any], rtype: str) -> str:
    """Extracts a canonical dosage signature token if present on a MedicationRequest/Statement."""
    dosage_list = (
        resource.get("dosageInstruction")
        if rtype == "MedicationRequest"
        else resource.get("dosage")
    )
    if not isinstance(dosage_list, list) or not dosage_list:
        return "unspecified_dosage"
    parts: List[str] = []
    for d_item in dosage_list:
        if not isinstance(d_item, dict):
            continue
        txt = str(d_item.get("text") or "").strip().lower()
        dose_and_rate = d_item.get("doseAndRate")
        if isinstance(dose_and_rate, list) and dose_and_rate and isinstance(dose_and_rate[0], dict):
            dq = dose_and_rate[0].get("doseQuantity")
            if isinstance(dq, dict) and dq.get("value") is not None:
                try:
                    val = round(float(dq["value"]), 2)
                    unit = str(dq.get("code") or dq.get("unit") or "").strip().lower()
                    parts.append(f"{val:.2f}:{unit}")
                    continue
                except (ValueError, TypeError):
                    pass
        if txt:
            parts.append(txt)
    return "|".join(parts) if parts else "unspecified_dosage"


def _extract_business_identifiers(
    resource: Dict[str, Any],
    rtype: str,
) -> List[Tuple[str, str]]:
    """Extracts normalized `(system, value)` business identifier pairs from `resource.identifier`."""
    raw_idents = resource.get("identifier")
    if not isinstance(raw_idents, list):
        return []
    pairs: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for ident in raw_idents:
        if not isinstance(ident, dict):
            continue
        raw_sys = ident.get("system")
        raw_val = ident.get("value")
        if not raw_sys or not raw_val:
            continue
        sys_str = str(raw_sys).strip()
        val_str = str(raw_val).strip()
        if not sys_str or not val_str:
            continue
        norm_sys = normalize_code_system_uri(sys_str, resource_type=rtype).canonical_system or sys_str
        pair = (norm_sys, val_str)
        if pair not in seen:
            seen.add(pair)
            pairs.append(pair)
    return pairs


def _hash_tuple(components: Sequence[Any]) -> str:
    payload = json.dumps(list(components), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ClinicalDedupFingerprint:
    """Deterministic clinical deduplication fingerprint for a normalized FHIR R4 resource."""

    profile_id: str
    scope: str
    resource_type: str
    strong_fingerprint: Optional[str]
    strong_components: Optional[Tuple[Any, ...]]
    near_fingerprint: Optional[str]
    near_components: Optional[Tuple[Any, ...]]
    identifier_fingerprints: Tuple[str, ...] = ()
    identifier_tuples: Tuple[Tuple[str, str], ...] = ()
    canonical_system: Optional[str] = None
    canonical_code: Optional[str] = None
    concept_group: Optional[str] = None
    effective_time_token: Optional[str] = None
    effective_date: Optional[str] = None
    normalized_value_token: Optional[str] = None
    normalized_unit: Optional[str] = None
    status_token: Optional[str] = None
    is_merge_eligible: bool = False


def compute_clinical_dedup_fingerprint(
    resource: Dict[str, Any],
    *,
    profile_id: str,
    scope: Optional[str] = None,
    rtype: Optional[str] = None,
) -> ClinicalDedupFingerprint:
    """Computes conservative strong-identity and near-duplicate fingerprints for a FHIR R4 resource.

     Partitioned strictly by `(profile_id, scope)`.
    """
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required to compute a clinical deduplication fingerprint.")

    resolved_type = (rtype or str((resource or {}).get("resourceType") or "")).strip()
    norm_res = normalize_fhir_terminology_and_units(resource, rtype=resolved_type)
    norm_data = norm_res.normalized
    resolved_scope = (scope or resolve_resource_scope(resolved_type, norm_data)).strip()

    # 1. Business identifiers
    ident_tuples = tuple(_extract_business_identifiers(norm_data, resolved_type))
    ident_hashes = tuple(
        _hash_tuple(("ident", clean_profile_id, resolved_scope, resolved_type, sys_u, val_u))
        for sys_u, val_u in ident_tuples
    )

    if resolved_type not in DEDUP_ELIGIBLE_RESOURCE_TYPES:
        return ClinicalDedupFingerprint(
            profile_id=clean_profile_id,
            scope=resolved_scope,
            resource_type=resolved_type,
            strong_fingerprint=None,
            strong_components=None,
            near_fingerprint=None,
            near_components=None,
            identifier_fingerprints=ident_hashes,
            identifier_tuples=ident_tuples,
            is_merge_eligible=bool(ident_hashes),
        )

    c_sys, c_code, c_group = _extract_primary_canonical_coding(norm_data, resolved_type)
    eff_iso, eff_date, _has_time = _normalize_explicit_effective_time(norm_data, resolved_type)
    status_tok = _extract_clinical_status_token(norm_data, resolved_type)

    if not c_sys or not c_code:
        # Uncoded or unknown-system resource: never merge on clinical fingerprint
        return ClinicalDedupFingerprint(
            profile_id=clean_profile_id,
            scope=resolved_scope,
            resource_type=resolved_type,
            strong_fingerprint=None,
            strong_components=None,
            near_fingerprint=None,
            near_components=None,
            identifier_fingerprints=ident_hashes,
            identifier_tuples=ident_tuples,
            canonical_system=c_sys,
            canonical_code=c_code,
            concept_group=c_group,
            effective_time_token=eff_iso,
            effective_date=eff_date,
            status_token=status_tok,
            is_merge_eligible=bool(ident_hashes),
        )

    strong_components: Optional[Tuple[Any, ...]] = None
    near_components: Optional[Tuple[Any, ...]] = None
    val_token: Optional[str] = None
    unit_token: Optional[str] = None

    if resolved_type == "Observation":
        val_token, unit_token, val_ok = _extract_observation_value_and_unit_tokens(
            norm_data,
            has_unknown_units=norm_res.has_unknown_units,
        )
        if eff_iso and val_ok and val_token is not None and unit_token is not None:
            strong_components = (
                "Observation",
                clean_profile_id,
                resolved_scope,
                c_sys,
                c_code,
                eff_iso,
                val_token,
                unit_token,
                status_tok,
            )
        if eff_date:
            near_components = (
                "Observation:near",
                clean_profile_id,
                resolved_scope,
                c_group or f"{c_sys}|{c_code}",
                eff_date,
            )

    elif resolved_type == "Immunization":
        if eff_iso:
            strong_components = (
                "Immunization",
                clean_profile_id,
                resolved_scope,
                c_sys,
                c_code,
                eff_iso,
                status_tok,
            )
        near_components = (
            "Immunization:near",
            clean_profile_id,
            resolved_scope,
            c_group or f"{c_sys}|{c_code}",
            eff_date or "any_date",
        )

    elif resolved_type == "Condition":
        if eff_iso:
            strong_components = (
                "Condition",
                clean_profile_id,
                resolved_scope,
                c_sys,
                c_code,
                status_tok,
                eff_iso,
            )
        near_components = (
            "Condition:near",
            clean_profile_id,
            resolved_scope,
            c_group or f"{c_sys}|{c_code}",
            status_tok,
        )

    elif resolved_type in ("MedicationRequest", "MedicationStatement", "MedicationDispense"):
        dosage_tok = _extract_medication_dosage_token(norm_data, resolved_type)
        if eff_iso:
            strong_components = (
                resolved_type,
                clean_profile_id,
                resolved_scope,
                c_sys,
                c_code,
                status_tok,
                eff_iso,
                dosage_tok,
            )
        near_components = (
            "Medication:near",
            clean_profile_id,
            resolved_scope,
            c_group or f"{c_sys}|{c_code}",
        )

    elif resolved_type == "AllergyIntolerance":
        if eff_iso:
            strong_components = (
                "AllergyIntolerance",
                clean_profile_id,
                resolved_scope,
                c_sys,
                c_code,
                status_tok,
                eff_iso,
            )
        near_components = (
            "AllergyIntolerance:near",
            clean_profile_id,
            resolved_scope,
            c_group or f"{c_sys}|{c_code}",
        )

    else:
        if eff_iso:
            strong_components = (
                resolved_type,
                clean_profile_id,
                resolved_scope,
                c_sys,
                c_code,
                status_tok,
                eff_iso,
            )
        near_components = (
            f"{resolved_type}:near",
            clean_profile_id,
            resolved_scope,
            c_group or f"{c_sys}|{c_code}",
            eff_date or "any_date",
        )

    strong_hash = _hash_tuple(strong_components) if strong_components is not None else None
    near_hash = _hash_tuple(near_components) if near_components is not None else None

    return ClinicalDedupFingerprint(
        profile_id=clean_profile_id,
        scope=resolved_scope,
        resource_type=resolved_type,
        strong_fingerprint=strong_hash,
        strong_components=strong_components,
        near_fingerprint=near_hash,
        near_components=near_components,
        identifier_fingerprints=ident_hashes,
        identifier_tuples=ident_tuples,
        canonical_system=c_sys,
        canonical_code=c_code,
        concept_group=c_group,
        effective_time_token=eff_iso,
        effective_date=eff_date,
        normalized_value_token=val_token,
        normalized_unit=unit_token,
        status_token=status_tok,
        is_merge_eligible=bool(strong_hash or ident_hashes),
    )


@dataclass
class DedupEvaluationMatch:
    """Result of evaluating a normalized incoming FHIR resource against existing scoped `HealthResource` rows."""

    decision: str  # 'no_match', 'strong_merge', 'near_duplicate_review'
    match_kind: Optional[str] = None  # 'strong_fingerprint', 'source_identifier', 'near_duplicate'
    matched_resource: Optional[HealthResource] = None
    near_duplicate_candidates: List[HealthResource] = field(default_factory=list)
    near_duplicate_reason: Optional[str] = None
    fingerprint: Optional[ClinicalDedupFingerprint] = None


def _classify_near_duplicate_reason(
    incoming_fp: ClinicalDedupFingerprint,
    candidate_fp: ClinicalDedupFingerprint,
) -> str:
    if incoming_fp.resource_type != candidate_fp.resource_type:
        return "cross_resource_type_medication_match"
    if incoming_fp.canonical_system != candidate_fp.canonical_system or incoming_fp.canonical_code != candidate_fp.canonical_code:
        return "cross_code_system_concept_match"
    if incoming_fp.effective_time_token != candidate_fp.effective_time_token:
        return "same_code_different_effective_time"
    if incoming_fp.normalized_value_token != candidate_fp.normalized_value_token:
        return "same_code_different_value"
    if incoming_fp.status_token != candidate_fp.status_token:
        return "same_code_different_status"
    return "near_duplicate_requires_review"


async def find_dedup_matches_in_repository(
    session: AsyncSession,
    *,
    profile_id: str,
    scope: str,
    resource_type: str,
    fhir_data: Dict[str, Any],
    exclude_resource_id: Optional[str] = None,
) -> DedupEvaluationMatch:
    """Finds strong-identity or near-duplicate matches strictly within `(profile_id, scope)`."""
    clean_profile_id = (profile_id or "").strip()
    clean_scope = (scope or "").strip()
    if not clean_profile_id or not clean_scope:
        raise ValueError("profile_id and scope are required for deduplication lookup.")

    incoming_fp = compute_clinical_dedup_fingerprint(
        fhir_data,
        profile_id=clean_profile_id,
        scope=clean_scope,
        rtype=resource_type,
    )
    if not incoming_fp.strong_fingerprint and not incoming_fp.near_fingerprint and not incoming_fp.identifier_fingerprints:
        return DedupEvaluationMatch(decision="no_match", fingerprint=incoming_fp)

    compatible_types: Tuple[str, ...]
    if resource_type in ("MedicationRequest", "MedicationStatement"):
        compatible_types = ("MedicationRequest", "MedicationStatement")
    else:
        compatible_types = (resource_type,)

    stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == clean_profile_id,
            HealthResource.scope == clean_scope,
            HealthResource.status == "active",
            HealthResource.resource_type.in_(compatible_types),
        )
        .order_by(HealthResource.created_at.asc())
    )
    res = await session.execute(stmt)
    candidates = list(res.scalars().all())

    incoming_ident_set = set(incoming_fp.identifier_fingerprints)
    near_candidates: List[HealthResource] = []
    near_reason: Optional[str] = None

    for cand in candidates:
        if exclude_resource_id and cand.id == exclude_resource_id:
            continue
        if cand.profile_id != clean_profile_id or cand.scope != clean_scope:
            continue
        cand_data = cand.data if isinstance(cand.data, dict) else {}
        cand_fp = compute_clinical_dedup_fingerprint(
            cand_data,
            profile_id=cand.profile_id,
            scope=cand.scope,
            rtype=cand.resource_type,
        )

        # 1. Strong match on business/source identifier within same resource_type
        if (
            cand.resource_type == resource_type
            and incoming_ident_set
            and incoming_ident_set.intersection(cand_fp.identifier_fingerprints)
        ):
            return DedupEvaluationMatch(
                decision="strong_merge",
                match_kind="source_identifier",
                matched_resource=cand,
                fingerprint=incoming_fp,
            )

        # 2. Strong match on normalized clinical fingerprint within same resource_type
        if (
            cand.resource_type == resource_type
            and incoming_fp.strong_fingerprint is not None
            and incoming_fp.strong_fingerprint == cand_fp.strong_fingerprint
        ):
            return DedupEvaluationMatch(
                decision="strong_merge",
                match_kind="strong_fingerprint",
                matched_resource=cand,
                fingerprint=incoming_fp,
            )

        # 3. Near-duplicate check (same concept/date bucket, different timestamp/value/system/type)
        if (
            incoming_fp.near_fingerprint is not None
            and incoming_fp.near_fingerprint == cand_fp.near_fingerprint
        ):
            near_candidates.append(cand)
            if near_reason is None:
                near_reason = _classify_near_duplicate_reason(incoming_fp, cand_fp)

    if near_candidates:
        return DedupEvaluationMatch(
            decision="near_duplicate_review",
            match_kind="near_duplicate",
            matched_resource=None,
            near_duplicate_candidates=near_candidates,
            near_duplicate_reason=near_reason or "near_duplicate_requires_review",
            fingerprint=incoming_fp,
        )

    return DedupEvaluationMatch(decision="no_match", fingerprint=incoming_fp)


def merge_fhir_resource_payloads(
    existing_data: Dict[str, Any],
    incoming_data: Dict[str, Any],
    *,
    match_kind: str,
    fingerprint_hash: Optional[str],
    pre_merge_version_id: int,
    incoming_source_type: str,
    incoming_source_ref: Optional[str],
    incoming_source_id: str,
    incoming_source_batch_id: Optional[str] = None,
    merge_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Conservatively merges an incoming duplicate resource into `existing_data` with full reversibility metadata.

    Preserves:
    - All existing codings and identifiers plus any newly supplied codings/identifiers.
    - Original quantity extension (`iso21090-PQ-translation`) if incoming record was unit-converted.
    - Full `incoming_snapshot` and `pre_merge_version_id` in `_carefold_provenance["merged_sources"]`.
    - `trust="untrusted"` on both `meta` and `_carefold_provenance`.
    """
    merged = copy.deepcopy(existing_data)
    incoming_copy = copy.deepcopy(incoming_data)
    resolved_merge_id = merge_id or str(uuid.uuid4())
    now_iso = utc_now().isoformat()

    existing_prov = (
        copy.deepcopy(merged.get("_carefold_provenance"))
        if isinstance(merged.get("_carefold_provenance"), dict)
        else {}
    )
    incoming_prov = (
        copy.deepcopy(incoming_copy.get("_carefold_provenance"))
        if isinstance(incoming_copy.get("_carefold_provenance"), dict)
        else {}
    )

    existing_source_name = str(
        existing_prov.get("source_name")
        or (merged.get("meta") or {}).get("source")
        or "Primary Source"
    ).strip()
    incoming_source_name = str(
        incoming_prov.get("source_name")
        or (incoming_copy.get("meta") or {}).get("source")
        or "Secondary Source"
    ).strip()
    existing_source_display = str(
        existing_prov.get("source_display") or f"From {existing_source_name}"
    ).strip()
    incoming_source_display = str(
        incoming_prov.get("source_display") or f"From {incoming_source_name}"
    ).strip()

    # Merge primary CodeableConcept.coding entries without duplicating (system, code)
    for cc_field in ("code", "medicationCodeableConcept", "vaccineCode"):
        if isinstance(merged.get(cc_field), dict) and isinstance(incoming_copy.get(cc_field), dict):
            m_codings = merged[cc_field].setdefault("coding", [])
            i_codings = incoming_copy[cc_field].get("coding") or []
            if isinstance(m_codings, list) and isinstance(i_codings, list):
                seen_codings = {
                    (str(c.get("system") or "").strip(), str(c.get("code") or "").strip())
                    for c in m_codings
                    if isinstance(c, dict)
                }
                for ic in i_codings:
                    if isinstance(ic, dict):
                        key = (str(ic.get("system") or "").strip(), str(ic.get("code") or "").strip())
                        if key not in seen_codings and key[1]:
                            seen_codings.add(key)
                            m_codings.append(copy.deepcopy(ic))

    # Merge business identifiers without duplicating (system, value)
    if isinstance(incoming_copy.get("identifier"), list):
        m_idents = merged.setdefault("identifier", [])
        if isinstance(m_idents, list):
            seen_idents = {
                (str(i.get("system") or "").strip(), str(i.get("value") or "").strip())
                for i in m_idents
                if isinstance(i, dict)
            }
            for ii in incoming_copy["identifier"]:
                if isinstance(ii, dict):
                    ikey = (str(ii.get("system") or "").strip(), str(ii.get("value") or "").strip())
                    if ikey not in seen_idents and ikey[1]:
                        seen_idents.add(ikey)
                        m_idents.append(copy.deepcopy(ii))

    # Preserve original-quantity extension on valueQuantity if present on incoming record
    if isinstance(merged.get("valueQuantity"), dict) and isinstance(incoming_copy.get("valueQuantity"), dict):
        inc_exts = incoming_copy["valueQuantity"].get("extension")
        if isinstance(inc_exts, list) and inc_exts:
            m_exts = merged["valueQuantity"].setdefault("extension", [])
            if isinstance(m_exts, list):
                existing_urls = {e.get("url") for e in m_exts if isinstance(e, dict)}
                for ext in inc_exts:
                    if isinstance(ext, dict) and ext.get("url") not in existing_urls:
                        m_exts.append(copy.deepcopy(ext))

    # Build reversible merge provenance entry
    merged_sources: List[Dict[str, Any]] = list(existing_prov.get("merged_sources") or [])
    merge_entry: Dict[str, Any] = {
        "merge_id": resolved_merge_id,
        "merged_at": now_iso,
        "match_kind": match_kind,
        "fingerprint": fingerprint_hash,
        "pre_merge_version_id": pre_merge_version_id,
        "source_name": incoming_source_name,
        "source_type": incoming_source_type,
        "source_ref": incoming_source_ref,
        "source_id": incoming_source_id,
        "source_batch_id": incoming_source_batch_id,
        "source_display": incoming_source_display,
        "incoming_snapshot": incoming_copy,
    }
    merged_sources.append(merge_entry)

    contributing_sources: List[str] = list(existing_prov.get("sources") or [existing_source_name])
    if incoming_source_name not in contributing_sources:
        contributing_sources.append(incoming_source_name)

    combined_display = existing_source_display
    if incoming_source_display and incoming_source_display not in combined_display:
        combined_display = f"{existing_source_display}; merged with {incoming_source_display}"

    existing_prov["source_name"] = existing_source_name
    existing_prov["source_display"] = combined_display
    existing_prov["sources"] = contributing_sources
    existing_prov["merged_sources"] = merged_sources
    existing_prov["trust"] = "untrusted"
    existing_prov["dedup"] = {
        "status": "merged",
        "match_kind": match_kind,
        "fingerprint": fingerprint_hash,
        "merge_count": len(merged_sources),
        "last_merge_id": resolved_merge_id,
    }
    if incoming_prov.get("original_quantities") and not existing_prov.get("original_quantities"):
        existing_prov["original_quantities"] = copy.deepcopy(incoming_prov["original_quantities"])

    merged["_carefold_provenance"] = existing_prov
    merged.setdefault("meta", {})
    if isinstance(merged["meta"], dict):
        merged["meta"]["source"] = ", ".join(contributing_sources)[:255]
        merged["meta"]["trust"] = "untrusted"

    return merged, merge_entry


@dataclass
class DedupRevertResult:
    """Result of reversing a deduplication merge via `reverse_dedup_merge`."""

    target_resource_id: str
    restored_version_id: int
    restored_from_version_id: int
    merge_id: str
    separated_resource_id: Optional[str] = None
    separated_version_id: Optional[int] = None


async def reverse_dedup_merge(
    session: AsyncSession,
    *,
    profile_id: str,
    resource_id: str,
    merge_id: Optional[str] = None,
    restore_separate_resource: bool = True,
    actor_user_id: Optional[str] = None,
) -> DedupRevertResult:
    """Reverses a deduplication merge on `resource_id`, restoring its pre-merge version and optionally splitting out the merged record.

    Enforces `profile_id` and active `ScopeContext` isolation.
    """
    from carefold.fhir.repository import (
        compute_canonical_fhir_content_hash,
        upsert_fhir_resource_with_history,
    )

    clean_profile_id = (profile_id or "").strip()
    clean_resource_id = (resource_id or "").strip()
    if not clean_profile_id or not clean_resource_id:
        raise ValueError("profile_id and resource_id are required to reverse a deduplication merge.")

    stmt = select(HealthResource).where(
        HealthResource.id == clean_resource_id,
        HealthResource.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    hr = res.scalar_one_or_none()
    if hr is None:
        raise ValueError(
            f"HealthResource '{clean_resource_id}' not found in profile '{clean_profile_id}' or current scope."
        )

    # Enforce active ScopeContext if set
    scope_ctx = current_scope_context()
    if scope_ctx is not None:
        allowed_scopes = getattr(scope_ctx, "active_scopes", None) or getattr(scope_ctx, "granted_scopes", None)
        if allowed_scopes and hr.scope not in allowed_scopes and "*" not in allowed_scopes and "health.*" not in allowed_scopes:
            raise ValueError(f"Scope violation: resource '{clean_resource_id}' is not accessible in current scope.")

    current_data = copy.deepcopy(hr.data) if isinstance(hr.data, dict) else {}
    prov = current_data.get("_carefold_provenance") if isinstance(current_data.get("_carefold_provenance"), dict) else {}
    merged_sources: List[Dict[str, Any]] = list(prov.get("merged_sources") or [])
    if not merged_sources:
        raise ValueError(f"HealthResource '{clean_resource_id}' has no recorded deduplication merges to reverse.")

    target_idx = -1
    if merge_id and str(merge_id).strip():
        clean_merge_id = str(merge_id).strip()
        for idx, entry in enumerate(merged_sources):
            if isinstance(entry, dict) and entry.get("merge_id") == clean_merge_id:
                target_idx = idx
                break
        if target_idx == -1:
            raise ValueError(f"Merge ID '{clean_merge_id}' not found on HealthResource '{clean_resource_id}'.")
    else:
        target_idx = len(merged_sources) - 1

    popped_merge = merged_sources.pop(target_idx)
    pre_merge_ver_id = int(popped_merge.get("pre_merge_version_id") or 1)
    resolved_merge_id = str(popped_merge.get("merge_id") or "")

    # Fetch the immutable pre-merge snapshot from health_resource_versions
    ver_stmt = select(HealthResourceVersion).where(
        HealthResourceVersion.resource_id == hr.id,
        HealthResourceVersion.profile_id == clean_profile_id,
        HealthResourceVersion.version_id == pre_merge_ver_id,
    )
    ver_res = await session.execute(ver_stmt)
    pre_merge_ver_row = ver_res.scalar_one_or_none()
    if pre_merge_ver_row is None or not isinstance(pre_merge_ver_row.fhir_json, dict):
        raise ValueError(
            f"Pre-merge version snapshot (version_id={pre_merge_ver_id}) not found for resource '{clean_resource_id}'."
        )

    restored_data = copy.deepcopy(pre_merge_ver_row.fhir_json)
    restored_prov = (
        restored_data.setdefault("_carefold_provenance", {})
        if isinstance(restored_data.get("_carefold_provenance"), dict)
        else {}
    )
    if not isinstance(restored_prov, dict):
        restored_prov = {}
        restored_data["_carefold_provenance"] = restored_prov

    reverted_list: List[Dict[str, Any]] = list(restored_prov.get("reverted_merges") or [])
    reverted_list.append({
        "merge_id": resolved_merge_id,
        "reverted_at": utc_now().isoformat(),
        "restored_from_version_id": pre_merge_ver_id,
        "source_name": popped_merge.get("source_name"),
        "source_id": popped_merge.get("source_id"),
    })
    restored_prov["reverted_merges"] = reverted_list
    restored_prov["merged_sources"] = merged_sources
    restored_prov["trust"] = "untrusted"
    restored_prov["dedup"] = {
        "status": "reverted" if not merged_sources else "merged",
        "merge_count": len(merged_sources),
        "last_reverted_merge_id": resolved_merge_id,
    }
    restored_data.setdefault("meta", {})
    if isinstance(restored_data["meta"], dict):
        restored_data["meta"]["trust"] = "untrusted"

    max_ver_stmt = select(func.coalesce(func.max(HealthResourceVersion.version_id), 0)).where(
        HealthResourceVersion.resource_id == hr.id
    )
    max_ver_res = await session.execute(max_ver_stmt)
    next_version_id = int(max_ver_res.scalar_one() or 0) + 1

    now = utc_now()
    now_iso = now.isoformat()
    restored_data["meta"]["versionId"] = str(next_version_id)
    restored_data["meta"]["lastUpdated"] = now_iso

    content_hash = compute_canonical_fhir_content_hash(restored_data)
    hr.data = restored_data
    hr.content_hash = content_hash
    hr.status = "active"
    hr.updated_at = now

    revert_ver_row = HealthResourceVersion(
        id=str(uuid.uuid4()),
        resource_id=hr.id,
        profile_id=clean_profile_id,
        scope=hr.scope,
        resource_type=hr.resource_type,
        version_id=next_version_id,
        operation="revert_merge",
        content_hash=content_hash,
        fhir_json=copy.deepcopy(restored_data),
        source_batch_id=popped_merge.get("source_batch_id"),
        actor_user_id=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(revert_ver_row)

    # Re-sync coding and reference index rows for restored resource
    await session.execute(delete(HealthResourceCoding).where(HealthResourceCoding.resource_id == hr.id))
    for c_item in extract_codings(restored_data, rtype=hr.resource_type):
        c_code = str(c_item.get("code") or "").strip()
        if not c_code:
            continue
        session.add(
            HealthResourceCoding(
                id=str(uuid.uuid4()),
                resource_id=hr.id,
                profile_id=clean_profile_id,
                scope=hr.scope,
                resource_type=hr.resource_type,
                element_path=str(c_item.get("element_path") or "code")[:128],
                system=str(c_item.get("system"))[:255] if c_item.get("system") else None,
                code=c_code[:128],
                display=str(c_item.get("display"))[:255] if c_item.get("display") else None,
                created_at=now,
                updated_at=now,
            )
        )

    await session.execute(
        delete(HealthResourceReference).where(HealthResourceReference.source_resource_id == hr.id)
    )
    for r_item in extract_references(restored_data, rtype=hr.resource_type):
        t_type = str(r_item.get("target_type") or "Resource")[:64]
        t_id = str(r_item.get("target_id") or "")[:128]
        raw_ref = str(r_item.get("resolved_reference") or r_item.get("raw_reference") or "")[:255]
        if not t_id or not raw_ref:
            continue
        session.add(
            HealthResourceReference(
                id=str(uuid.uuid4()),
                source_resource_id=hr.id,
                profile_id=clean_profile_id,
                scope=hr.scope,
                source_type=hr.resource_type,
                reference_field=str(r_item.get("field") or "reference")[:128],
                target_type=t_type,
                target_id=t_id,
                target_resource_id=None,
                raw_reference=raw_ref,
                is_external=bool(r_item.get("is_external", False)),
                created_at=now,
                updated_at=now,
            )
        )

    separated_resource_id: Optional[str] = None
    separated_version_id: Optional[int] = None

    if restore_separate_resource and isinstance(popped_merge.get("incoming_snapshot"), dict):
        sep_snapshot = copy.deepcopy(popped_merge["incoming_snapshot"])
        sep_snapshot["id"] = str(uuid.uuid4())
        sep_prov = (
            sep_snapshot.setdefault("_carefold_provenance", {})
            if isinstance(sep_snapshot.get("_carefold_provenance"), dict)
            else {}
        )
        if not isinstance(sep_prov, dict):
            sep_prov = {}
            sep_snapshot["_carefold_provenance"] = sep_prov
        sep_prov["trust"] = "untrusted"
        sep_prov["dedup"] = {
            "status": "unmerged_separate",
            "unmerged_from_resource_id": hr.id,
            "merge_id": resolved_merge_id,
        }
        sep_hr, sep_ver, _ = await upsert_fhir_resource_with_history(
            session,
            profile_id=clean_profile_id,
            resource_type=hr.resource_type,
            fhir_data=sep_snapshot,
            source_type=str(popped_merge.get("source_type") or "file"),
            source_ref=popped_merge.get("source_ref") or f"unmerged:{resolved_merge_id}",
            source_id=f"{popped_merge.get('source_id') or hr.resource_type}:unmerged:{resolved_merge_id[:8]}",
            scope=hr.scope,
            source_batch_id=popped_merge.get("source_batch_id"),
            actor_user_id=actor_user_id,
            strict_fhir_validation=False,
            enable_dedup=False,
        )
        separated_resource_id = sep_hr.id
        separated_version_id = sep_ver.version_id

    await session.flush()
    return DedupRevertResult(
        target_resource_id=hr.id,
        restored_version_id=next_version_id,
        restored_from_version_id=pre_merge_ver_id,
        merge_id=resolved_merge_id,
        separated_resource_id=separated_resource_id,
        separated_version_id=separated_version_id,
    )


async def evaluate_staged_records_dedup_preview(
    session: AsyncSession,
    *,
    profile_id: str,
    staged_records: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Computes a non-mutating deduplication preview for staged records during `stage_import`.

    Annotates each staged record's `_carefold_provenance["dedup_preview"]` and returns aggregate
    counts (`exact_duplicate_count`, `near_duplicate_count`, `new_record_count`).
    """
    clean_profile_id = (profile_id or "").strip()
    exact_duplicate_count = 0
    near_duplicate_count = 0
    new_record_count = 0

    seen_batch_strong: Dict[str, str] = {}
    seen_batch_near: Dict[str, str] = {}

    for idx, rec in enumerate(staged_records):
        if not isinstance(rec, dict):
            continue
        rtype = str(rec.get("resource_type") or "").strip()
        if rtype == "Provenance":
            continue
        fhir_data = rec.get("data") if isinstance(rec.get("data"), dict) else {"resourceType": rtype}
        rec_scope = str(rec.get("scope") or resolve_resource_scope(rtype, fhir_data)).strip()

        match = await find_dedup_matches_in_repository(
            session,
            profile_id=clean_profile_id,
            scope=rec_scope,
            resource_type=rtype,
            fhir_data=fhir_data,
        )
        fp = match.fingerprint
        source_id = str(rec.get("source_id") or f"{rtype}:{idx}")

        preview: Dict[str, Any]
        if match.decision == "strong_merge" and match.matched_resource is not None:
            exact_duplicate_count += 1
            preview = {
                "status": "exact_duplicate_will_merge",
                "match_kind": match.match_kind,
                "target_resource_id": match.matched_resource.id,
                "fingerprint": fp.strong_fingerprint if fp else None,
            }
        elif match.decision == "near_duplicate_review" and match.near_duplicate_candidates:
            near_duplicate_count += 1
            preview = {
                "status": "near_duplicate_flagged_for_review",
                "review_required": True,
                "reason": match.near_duplicate_reason,
                "candidate_resource_ids": [c.id for c in match.near_duplicate_candidates],
                "near_fingerprint": fp.near_fingerprint if fp else None,
            }
        elif fp and fp.strong_fingerprint and fp.strong_fingerprint in seen_batch_strong:
            exact_duplicate_count += 1
            preview = {
                "status": "intra_batch_exact_duplicate_will_merge",
                "match_kind": "strong_fingerprint",
                "target_source_id": seen_batch_strong[fp.strong_fingerprint],
                "fingerprint": fp.strong_fingerprint,
            }
        elif fp and fp.near_fingerprint and fp.near_fingerprint in seen_batch_near:
            near_duplicate_count += 1
            preview = {
                "status": "intra_batch_near_duplicate_flagged_for_review",
                "review_required": True,
                "reason": "intra_batch_near_duplicate",
                "candidate_source_ids": [seen_batch_near[fp.near_fingerprint]],
                "near_fingerprint": fp.near_fingerprint,
            }
        else:
            new_record_count += 1
            preview = {
                "status": "new_record",
                "fingerprint": fp.strong_fingerprint if fp else None,
            }

        if fp and fp.strong_fingerprint and fp.strong_fingerprint not in seen_batch_strong:
            seen_batch_strong[fp.strong_fingerprint] = source_id
        if fp and fp.near_fingerprint and fp.near_fingerprint not in seen_batch_near:
            seen_batch_near[fp.near_fingerprint] = source_id

        rec["dedup_preview"] = preview
        if isinstance(rec.get("data"), dict):
            prov = rec["data"].setdefault("_carefold_provenance", {})
            if isinstance(prov, dict):
                prov["dedup_preview"] = preview

    return {
        "new_record_count": new_record_count,
        "exact_duplicate_count": exact_duplicate_count,
        "near_duplicate_count": near_duplicate_count,
    }


__all__ = [
    "DEDUP_ELIGIBLE_RESOURCE_TYPES",
    "ClinicalDedupFingerprint",
    "DedupEvaluationMatch",
    "DedupRevertResult",
    "compute_clinical_dedup_fingerprint",
    "evaluate_staged_records_dedup_preview",
    "find_dedup_matches_in_repository",
    "merge_fhir_resource_payloads",
    "reverse_dedup_merge",
]
