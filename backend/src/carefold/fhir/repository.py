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

"""Scoped FHIR R4 relational repository, version history, coding index, and reference graph (#282).

Implements atomic persistence across:
- `health_resources` (current active/tombstone resource state)
- `health_resource_versions` (immutable version snapshots `1`, `2`, ... with `meta.versionId` & `meta.lastUpdated`)
- `health_resource_codings` (multi-coding terminology index tuples without free-text PHI)
- `health_resource_references` (directed resource graph edges without free-text display PHI)

Enforces `profile_id` ownership and `ScopeContext` (`health.clinical` vs `health.paperwork`)
isolation across all reads, writes, history queries, and reference graph traversals.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.scoped_session import register_scope_listeners
from carefold.fhir.dedup import (
    find_dedup_matches_in_repository,
    merge_fhir_resource_payloads,
    reverse_dedup_merge,
)
from carefold.fhir.registry import (
    RESOURCE_PATIENT_SUBJECT_PATHS,
    SUPPORTED_FHIR_RESOURCE_TYPES,
    TARGET_FHIR_VERSION,
    extract_codings,
    extract_effective_iso,
    extract_references,
    resolve_resource_scope,
    validate_and_normalize_fhir_resource,
)
from carefold.fhir.terminology import (
    normalize_code_system_uri,
    normalize_fhir_terminology_and_units,
)
from carefold.models.health import (
    HealthResource,
    HealthResourceCoding,
    HealthResourceReference,
    HealthResourceVersion,
)
from yarvelle_core.db.models import Profile, utc_now

register_scope_listeners()


def _parse_iso_datetime(raw_iso: Optional[str]) -> datetime:
    """Parses an ISO-8601 timestamp string into a timezone-aware UTC datetime."""
    if not raw_iso or not isinstance(raw_iso, str):
        return utc_now()
    clean = raw_iso.strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return utc_now()


def compute_canonical_fhir_content_hash(fhir_data: Dict[str, Any]) -> str:
    """Computes a stable SHA-256 hex digest of a FHIR R4 resource excluding volatile version timestamps.

    Strips `meta.versionId` and `meta.lastUpdated` before canonical JSON serialization so
    re-importing an identical clinical payload yields the same content hash across versions.
    """
    if not isinstance(fhir_data, dict):
        return hashlib.sha256(b"{}").hexdigest()

    canonical = copy.deepcopy(fhir_data)
    meta = canonical.get("meta")
    if isinstance(meta, dict):
        meta.pop("versionId", None)
        meta.pop("lastUpdated", None)
        if not meta:
            canonical.pop("meta", None)

    prov = canonical.get("_carefold_provenance")
    if isinstance(prov, dict):
        prov.pop("version_id", None)
        prov.pop("last_updated", None)

    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _verify_and_bind_patient_references_for_profile(
    fhir_data: Dict[str, Any],
    *,
    rtype: str,
    profile_id: str,
    expected_patient_id: Optional[str] = None,
    verified_source_patient_ids: Optional[Sequence[str]] = None,
    strict_patient_matching: bool = True,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Verifies patient/subject references on a resource before commit and binds verified refs to `Patient/{profile_id}`."""
    clean_profile = profile_id.strip()
    bound = copy.deepcopy(fhir_data)
    prov = bound.get("_carefold_provenance") if isinstance(bound.get("_carefold_provenance"), dict) else {}
    existing_mappings: List[Dict[str, Any]] = list(prov.get("source_identity_mappings") or [])
    verified_sources_from_prov: Set[str] = {
        str(m.get("source_reference") or "").strip()
        for m in existing_mappings
        if isinstance(m, dict) and m.get("source_reference")
    } | {
        f"Patient/{str(m.get('source_patient_id') or '').strip()}"
        for m in existing_mappings
        if isinstance(m, dict) and m.get("source_patient_id")
    }

    allowed_tokens: Set[str] = {
        clean_profile,
        f"Patient/{clean_profile}",
    } | verified_sources_from_prov

    if expected_patient_id and str(expected_patient_id).strip():
        exp = str(expected_patient_id).strip()
        allowed_tokens.add(exp)
        if not exp.startswith("Patient/"):
            allowed_tokens.add(f"Patient/{exp}")

    if verified_source_patient_ids:
        for vp in verified_source_patient_ids:
            if vp and str(vp).strip():
                v_clean = str(vp).strip()
                allowed_tokens.add(v_clean)
                if not v_clean.startswith("Patient/"):
                    allowed_tokens.add(f"Patient/{v_clean}")

    has_explicit_restriction = bool(expected_patient_id or verified_source_patient_ids)

    if rtype == "Patient":
        raw_pat_id = str(bound.get("id") or "").strip()
        if raw_pat_id and raw_pat_id != clean_profile:
            if has_explicit_restriction and raw_pat_id not in allowed_tokens and f"Patient/{raw_pat_id}" not in allowed_tokens:
                raise ValueError(
                    f"Patient resource ID '{raw_pat_id}' does not match expected patient context for profile '{clean_profile}'."
                )
            existing_mappings.append({
                "field": "id",
                "source_reference": f"Patient/{raw_pat_id}",
                "source_patient_id": raw_pat_id,
                "canonical_reference": f"Patient/{clean_profile}",
            })
        bound["id"] = clean_profile

    subject_paths = set(RESOURCE_PATIENT_SUBJECT_PATHS.get(rtype, ()))
    refs = extract_references(bound, rtype=rtype)

    for ref in refs:
        if ref.get("is_malicious"):
            raise ValueError(
                f"Resource '{rtype}' contains a malicious reference URI in field '{ref.get('field')}'."
            )
        field_path = ref.get("field") or ""
        if field_path in subject_paths or ref.get("target_type") == "Patient":
            if ref.get("kind") == "contained":
                continue
            t_type = ref.get("target_type")
            t_id = ref.get("target_id")
            raw_ref = ref.get("raw_reference") or ""

            if t_type and t_type not in ("Patient", "Group"):
                raise ValueError(
                    f"Resource '{rtype}' patient/subject field '{field_path}' points to non-patient type '{t_type}'."
                )
            if ref.get("kind") == "urn_uuid":
                raise ValueError(
                    f"Resource '{rtype}' has an unresolved patient urn:uuid reference in '{field_path}'."
                )

            if t_type == "Patient" and t_id:
                pat_token = f"Patient/{t_id}"
                if has_explicit_restriction and strict_patient_matching:
                    if pat_token not in allowed_tokens and raw_ref not in allowed_tokens and t_id not in allowed_tokens:
                        raise ValueError(
                            f"Resource '{rtype}' references unverified patient '{pat_token}' for profile '{clean_profile}'."
                        )
                if t_id != clean_profile:
                    existing_mappings.append({
                        "field": field_path,
                        "source_reference": raw_ref,
                        "source_patient_id": t_id,
                        "canonical_reference": f"Patient/{clean_profile}",
                    })
                    # Rewrite verified top-level subject/patient reference to Patient/{profile_id}
                    if field_path in bound and isinstance(bound[field_path], dict):
                        bound[field_path]["reference"] = f"Patient/{clean_profile}"

    if isinstance(bound.get("_carefold_provenance"), dict):
        bound["_carefold_provenance"]["source_identity_mappings"] = existing_mappings
    elif existing_mappings:
        bound["_carefold_provenance"] = {
            "trust": "untrusted",
            "source_identity_mappings": existing_mappings,
        }

    return bound, existing_mappings


async def ensure_canonical_patient_resource(
    session: AsyncSession,
    profile_id: str,
    *,
    source_patient: Optional[Dict[str, Any]] = None,
    source_batch_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> HealthResource:
    """Ensures a canonical `Patient/{profile_id}` FHIR R4 anchor resource exists for `profile_id`."""
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required.")

    prof_res = await session.execute(select(Profile).where(Profile.id == clean_profile_id))
    prof = prof_res.scalar_one_or_none()

    pat_dict: Dict[str, Any] = copy.deepcopy(source_patient) if isinstance(source_patient, dict) else {}
    pat_dict["resourceType"] = "Patient"
    pat_dict["id"] = clean_profile_id

    if prof is not None:
        if not pat_dict.get("name") and getattr(prof, "name", None):
            parts = str(prof.name).strip().split()
            if len(parts) >= 2:
                pat_dict["name"] = [{"given": parts[:-1], "family": parts[-1], "text": prof.name}]
            elif parts:
                pat_dict["name"] = [{"text": prof.name, "family": parts[0]}]
        if not pat_dict.get("birthDate") and getattr(prof, "date_of_birth", None):
            dob = str(prof.date_of_birth).strip()
            if len(dob) >= 10:
                pat_dict["birthDate"] = dob[:10]

    hr, _version, _created = await upsert_fhir_resource_with_history(
        session,
        profile_id=clean_profile_id,
        resource_type="Patient",
        fhir_data=pat_dict,
        source_type="profile_anchor" if source_patient is None else "file",
        source_ref=source_batch_id or "canonical_profile",
        source_id=f"Patient:{clean_profile_id}",
        scope="health.clinical",
        source_batch_id=source_batch_id,
        actor_user_id=actor_user_id,
    )
    return hr


async def upsert_fhir_resource_with_history(
    session: AsyncSession,
    *,
    profile_id: str,
    resource_type: str,
    fhir_data: Dict[str, Any],
    source_type: str = "file",
    source_ref: Optional[str] = None,
    source_id: Optional[str] = None,
    effective_at: Optional[datetime] = None,
    scope: Optional[str] = None,
    codings: Optional[Sequence[Dict[str, Optional[str]]]] = None,
    references: Optional[Sequence[Dict[str, Any]]] = None,
    source_batch_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    expected_patient_id: Optional[str] = None,
    verified_source_patient_ids: Optional[Sequence[str]] = None,
    strict_patient_matching: bool = True,
    strict_fhir_validation: bool = True,
    enable_dedup: bool = True,
) -> Tuple[HealthResource, HealthResourceVersion, bool]:
    """Atomically creates, updates, or merges a `HealthResource` and writes its version snapshot, codings, and references.

    Returns:
        `(health_resource, resource_version, is_created)` within the caller's database transaction.
    """
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required.")

    rtype = (resource_type or str((fhir_data or {}).get("resourceType") or "")).strip()
    if not rtype or rtype not in SUPPORTED_FHIR_RESOURCE_TYPES:
        raise ValueError(f"Unsupported or missing FHIR R4 resourceType '{rtype}'.")

    # 1. Verify and bind patient references to Patient/{profile_id}
    bound_data, _mappings = _verify_and_bind_patient_references_for_profile(
        fhir_data,
        rtype=rtype,
        profile_id=clean_profile_id,
        expected_patient_id=expected_patient_id,
        verified_source_patient_ids=verified_source_patient_ids,
        strict_patient_matching=strict_patient_matching,
    )

    # 2. Validate against the declarative FHIR R4 registry
    val_res = validate_and_normalize_fhir_resource(bound_data, rtype=rtype, source_id=source_id)
    if not val_res.is_valid and strict_fhir_validation:
        diag_codes = ", ".join(d.code for d in val_res.diagnostics) or "validation_error"
        raise ValueError(f"FHIR R4 validation failed for '{rtype}': {diag_codes}")

    normalized_data = copy.deepcopy(val_res.normalized)
    if "_carefold_provenance" in bound_data and isinstance(bound_data["_carefold_provenance"], dict):
        normalized_data["_carefold_provenance"] = copy.deepcopy(bound_data["_carefold_provenance"])

    # 2b. Normalize terminology CodeSystem OIDs/URIs and curated UCUM units via Pint (#283)
    term_res = normalize_fhir_terminology_and_units(
        normalized_data,
        rtype=rtype,
        source_id=source_id,
    )
    normalized_data = term_res.normalized

    resolved_scope = (scope or resolve_resource_scope(rtype, normalized_data)).strip()
    clean_source_type = (source_type or "file").strip()
    clean_source_id = (
        str(source_id).strip()
        if source_id and str(source_id).strip()
        else f"{rtype}:{normalized_data.get('id') or uuid.uuid4()}"
    )

    if effective_at is None:
        eff_iso, _ = extract_effective_iso(normalized_data, rtype=rtype)
        effective_dt = _parse_iso_datetime(eff_iso)
    else:
        effective_dt = effective_at

    now = utc_now()
    now_iso = now.isoformat()

    # 3. Check for existing HealthResource row by exact source key
    existing_stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == clean_profile_id,
            HealthResource.source_type == clean_source_type,
            HealthResource.source_ref == source_ref,
            HealthResource.source_id == clean_source_id,
        )
        .execution_options(include_all_scopes=True)
    )
    existing_res = await session.execute(existing_stmt)
    hr = existing_res.scalar_one_or_none()
    is_created = hr is None
    version_operation = "create" if is_created else "update"
    was_dedup_merged = False
    near_duplicate_edges: List[Dict[str, Any]] = []

    # 3b. Cross-source clinical deduplication & near-duplicate review linking (#283)
    if hr is None and enable_dedup:
        dedup_match = await find_dedup_matches_in_repository(
            session,
            profile_id=clean_profile_id,
            scope=resolved_scope,
            resource_type=rtype,
            fhir_data=normalized_data,
        )
        if dedup_match.decision == "strong_merge" and dedup_match.matched_resource is not None:
            hr = dedup_match.matched_resource
            is_created = False
            was_dedup_merged = True
            version_operation = "merge"
        elif dedup_match.decision == "near_duplicate_review" and dedup_match.near_duplicate_candidates:
            prov = (
                normalized_data.setdefault("_carefold_provenance", {})
                if isinstance(normalized_data.get("_carefold_provenance"), dict)
                else {}
            )
            if not isinstance(prov, dict):
                prov = {}
                normalized_data["_carefold_provenance"] = prov
            prov.setdefault("trust", "untrusted")
            prov["dedup"] = {
                "status": "near_duplicate_needs_review",
                "review_required": True,
                "reason": dedup_match.near_duplicate_reason,
                "candidate_resource_ids": [c.id for c in dedup_match.near_duplicate_candidates],
                "near_fingerprint": (
                    dedup_match.fingerprint.near_fingerprint if dedup_match.fingerprint else None
                ),
            }
            for cand_hr in dedup_match.near_duplicate_candidates:
                near_duplicate_edges.append({
                    "field": "near_duplicate_of",
                    "target_type": cand_hr.resource_type,
                    "target_id": cand_hr.id,
                    "target_resource_id": cand_hr.id,
                    "resolved_reference": f"{cand_hr.resource_type}/{cand_hr.id}",
                    "raw_reference": f"{cand_hr.resource_type}/{cand_hr.id}",
                    "is_external": False,
                    "resolution_scope": "repository_dedup",
                })

    if hr is not None:
        max_ver_stmt = (
            select(func.coalesce(func.max(HealthResourceVersion.version_id), 0))
            .where(HealthResourceVersion.resource_id == hr.id)
            .execution_options(include_all_scopes=True)
        )
        max_ver_res = await session.execute(max_ver_stmt)
        prev_max_ver = int(max_ver_res.scalar_one() or 0)
        if prev_max_ver == 0:
            # Backfill version counter from existing meta.versionId if present
            existing_meta = (hr.data or {}).get("meta") if isinstance(hr.data, dict) else {}
            try:
                prev_max_ver = int((existing_meta or {}).get("versionId") or 1)
            except (ValueError, TypeError):
                prev_max_ver = 1
        next_version_id = prev_max_ver + 1

        if was_dedup_merged:
            existing_hr_data = hr.data if isinstance(hr.data, dict) else {"resourceType": rtype, "id": hr.id}
            normalized_data, _merge_entry = merge_fhir_resource_payloads(
                existing_hr_data,
                normalized_data,
                match_kind=dedup_match.match_kind or "strong_fingerprint",
                fingerprint_hash=(
                    dedup_match.fingerprint.strong_fingerprint if dedup_match.fingerprint else None
                ),
                pre_merge_version_id=prev_max_ver,
                incoming_source_type=clean_source_type,
                incoming_source_ref=source_ref,
                incoming_source_id=clean_source_id,
                incoming_source_batch_id=source_batch_id,
            )
    else:
        next_version_id = 1

    # 4. Stamp FHIR R4 meta.versionId and meta.lastUpdated
    normalized_data.setdefault("meta", {})
    if not isinstance(normalized_data["meta"], dict):
        normalized_data["meta"] = {}
    normalized_data["meta"]["versionId"] = str(next_version_id)
    normalized_data["meta"]["lastUpdated"] = now_iso
    if (
        isinstance(normalized_data.get("_carefold_provenance"), dict)
        and normalized_data["_carefold_provenance"].get("trust") == "untrusted"
    ) or (
        isinstance(bound_data.get("meta"), dict)
        and bound_data["meta"].get("trust") == "untrusted"
    ):
        normalized_data["meta"]["trust"] = "untrusted"

    content_hash = compute_canonical_fhir_content_hash(normalized_data)

    if hr is not None:
        hr.resource_type = rtype
        hr.scope = resolved_scope
        hr.content_hash = content_hash
        hr.data = normalized_data
        hr.effective_at = effective_dt
        hr.status = "active"
        hr.updated_at = now
    else:
        hr_id = str(uuid.uuid4())
        if not normalized_data.get("id"):
            normalized_data["id"] = hr_id
        hr = HealthResource(
            id=hr_id,
            profile_id=clean_profile_id,
            resource_type=rtype,
            source_type=clean_source_type,
            source_ref=source_ref,
            source_id=clean_source_id,
            content_hash=content_hash,
            data=normalized_data,
            status="active",
            effective_at=effective_dt,
            recorded_at=now,
            created_at=now,
            updated_at=now,
            scope=resolved_scope,
        )
        session.add(hr)

    await session.flush()

    # 5. Append immutable HealthResourceVersion snapshot
    version_row = HealthResourceVersion(
        id=str(uuid.uuid4()),
        resource_id=hr.id,
        profile_id=clean_profile_id,
        scope=resolved_scope,
        resource_type=rtype,
        version_id=next_version_id,
        operation=version_operation,
        content_hash=content_hash,
        fhir_json=copy.deepcopy(normalized_data),
        source_batch_id=source_batch_id,
        actor_user_id=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(version_row)

    # 6. Replace HealthResourceCoding index rows for this resource
    if not is_created:
        await session.execute(
            delete(HealthResourceCoding).where(HealthResourceCoding.resource_id == hr.id)
        )

    codings_to_index = (
        list(codings)
        if (codings is not None and not was_dedup_merged)
        else extract_codings(normalized_data, rtype=rtype)
    )
    seen_coding_keys: Set[Tuple[str, str, str]] = set()
    for c_item in codings_to_index:
        if not isinstance(c_item, dict):
            continue
        c_code = str(c_item.get("code") or "").strip()
        if not c_code:
            continue
        c_path = str(c_item.get("element_path") or "code").strip()[:128]
        c_sys_raw = c_item.get("system")
        norm_sys = normalize_code_system_uri(c_sys_raw, code=c_code, resource_type=rtype).canonical_system
        c_sys = str(norm_sys).strip()[:255] if norm_sys and str(norm_sys).strip() else None
        c_disp_raw = c_item.get("display")
        c_disp = str(c_disp_raw).strip()[:255] if c_disp_raw and str(c_disp_raw).strip() else None

        dedup_key = (c_path, c_sys or "", c_code)
        if dedup_key in seen_coding_keys:
            continue
        seen_coding_keys.add(dedup_key)

        session.add(
            HealthResourceCoding(
                id=str(uuid.uuid4()),
                resource_id=hr.id,
                profile_id=clean_profile_id,
                scope=resolved_scope,
                resource_type=rtype,
                element_path=c_path,
                system=c_sys,
                code=c_code[:128],
                display=c_disp,
                created_at=now,
                updated_at=now,
            )
        )

    # 7. Replace HealthResourceReference graph edges for this resource
    if not is_created:
        await session.execute(
            delete(HealthResourceReference).where(HealthResourceReference.source_resource_id == hr.id)
        )

    refs_to_index = (
        list(references)
        if (references is not None and not was_dedup_merged)
        else extract_references(normalized_data, rtype=rtype)
    )
    if near_duplicate_edges:
        refs_to_index.extend(near_duplicate_edges)
    seen_ref_keys: Set[Tuple[str, str, str, str]] = set()
    for r_item in refs_to_index:
        if not isinstance(r_item, dict):
            continue
        ref_field = str(r_item.get("field") or r_item.get("reference_field") or "reference").strip()[:128]
        t_type = str(r_item.get("target_type") or "Resource").strip()[:64]
        t_id = str(r_item.get("target_id") or "").strip()[:128]
        raw_ref = str(
            r_item.get("resolved_reference") or r_item.get("raw_reference") or ""
        ).strip()[:255]
        is_ext = bool(r_item.get("is_external", False))

        # Ensure verified Patient references point to canonical Patient/{profile_id}
        if t_type == "Patient" and r_item.get("resolution_scope") != "contained":
            t_id = clean_profile_id
            raw_ref = f"Patient/{clean_profile_id}"
            is_ext = False

        if not t_id and raw_ref:
            t_id = raw_ref[:128]
        if not t_id or not raw_ref:
            continue

        edge_key = (ref_field, t_type, t_id, raw_ref)
        if edge_key in seen_ref_keys:
            continue
        seen_ref_keys.add(edge_key)

        target_res_id = r_item.get("target_resource_id") or await _resolve_local_target_resource_id(
            session,
            profile_id=clean_profile_id,
            target_type=t_type,
            target_id=t_id,
            target_source_id=r_item.get("target_source_id"),
        )

        session.add(
            HealthResourceReference(
                id=str(uuid.uuid4()),
                source_resource_id=hr.id,
                profile_id=clean_profile_id,
                scope=resolved_scope,
                source_type=rtype,
                reference_field=ref_field,
                target_type=t_type,
                target_id=t_id,
                target_resource_id=target_res_id,
                raw_reference=raw_ref,
                is_external=is_ext,
                created_at=now,
                updated_at=now,
            )
        )

    await session.flush()
    return hr, version_row, is_created


async def _resolve_local_target_resource_id(
    session: AsyncSession,
    *,
    profile_id: str,
    target_type: str,
    target_id: str,
    target_source_id: Optional[str] = None,
) -> Optional[str]:
    """Resolves a target `(target_type, target_id)` to a local `HealthResource.id` within the same profile."""
    candidate_source_ids = [f"{target_type}:{target_id}", target_id]
    if target_source_id and str(target_source_id).strip():
        candidate_source_ids.insert(0, str(target_source_id).strip())

    stmt = (
        select(HealthResource.id)
        .where(
            HealthResource.profile_id == profile_id,
            HealthResource.resource_type == target_type,
            (HealthResource.id == target_id) | (HealthResource.source_id.in_(candidate_source_ids)),
        )
        .execution_options(include_all_scopes=True)
        .limit(1)
    )
    res = await session.execute(stmt)
    found_id = res.scalars().first()
    if found_id is not None:
        return found_id

    if target_type == "Patient" and target_id == profile_id:
        pat_stmt = (
            select(HealthResource.id)
            .where(
                HealthResource.profile_id == profile_id,
                HealthResource.resource_type == "Patient",
                HealthResource.status == "active",
            )
            .execution_options(include_all_scopes=True)
            .order_by(HealthResource.updated_at.desc())
            .limit(1)
        )
        pat_res = await session.execute(pat_stmt)
        return pat_res.scalars().first()

    return None


async def link_intra_batch_references(
    session: AsyncSession,
    *,
    profile_id: str,
    resource_ids: Sequence[str],
) -> None:
    """Backfills `target_resource_id` on `HealthResourceReference` rows after a multi-resource batch upsert."""
    if not resource_ids:
        return
    clean_profile_id = profile_id.strip()

    stmt = (
        select(HealthResourceReference)
        .where(
            HealthResourceReference.profile_id == clean_profile_id,
            HealthResourceReference.source_resource_id.in_(list(resource_ids)),
            HealthResourceReference.target_resource_id.is_(None),
        )
        .execution_options(include_all_scopes=True)
    )
    res = await session.execute(stmt)
    unresolved_edges = list(res.scalars().all())
    for edge in unresolved_edges:
        resolved_id = await _resolve_local_target_resource_id(
            session,
            profile_id=clean_profile_id,
            target_type=edge.target_type,
            target_id=edge.target_id,
        )
        if resolved_id is not None:
            edge.target_resource_id = resolved_id
    await session.flush()


async def delete_fhir_resource_with_history(
    session: AsyncSession,
    *,
    profile_id: str,
    resource_id: str,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthResourceVersion]:
    """Tombstones a `HealthResource`, appends a `delete` version snapshot, and removes active search index rows."""
    clean_profile_id = (profile_id or "").strip()
    clean_resource_id = (resource_id or "").strip()
    if not clean_profile_id or not clean_resource_id:
        raise ValueError("profile_id and resource_id are required.")

    stmt = select(HealthResource).where(
        HealthResource.id == clean_resource_id,
        HealthResource.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    hr = res.scalar_one_or_none()
    if hr is None:
        return None

    max_ver_stmt = select(func.coalesce(func.max(HealthResourceVersion.version_id), 0)).where(
        HealthResourceVersion.resource_id == hr.id
    )
    max_ver_res = await session.execute(max_ver_stmt)
    next_version_id = int(max_ver_res.scalar_one() or 0) + 1

    now = utc_now()
    now_iso = now.isoformat()
    tombstone_data = copy.deepcopy(hr.data) if isinstance(hr.data, dict) else {"resourceType": hr.resource_type}
    tombstone_data.setdefault("meta", {})
    if isinstance(tombstone_data["meta"], dict):
        tombstone_data["meta"]["versionId"] = str(next_version_id)
        tombstone_data["meta"]["lastUpdated"] = now_iso

    content_hash = compute_canonical_fhir_content_hash(tombstone_data)
    hr.status = "tombstone"
    hr.data = tombstone_data
    hr.content_hash = content_hash
    hr.updated_at = now

    del_version = HealthResourceVersion(
        id=str(uuid.uuid4()),
        resource_id=hr.id,
        profile_id=clean_profile_id,
        scope=hr.scope,
        resource_type=hr.resource_type,
        version_id=next_version_id,
        operation="delete",
        content_hash=content_hash,
        fhir_json=tombstone_data,
        actor_user_id=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(del_version)

    await session.execute(
        delete(HealthResourceCoding).where(HealthResourceCoding.resource_id == hr.id)
    )
    await session.execute(
        delete(HealthResourceReference).where(HealthResourceReference.source_resource_id == hr.id)
    )
    await session.flush()
    return del_version


async def get_resource_version_history(
    session: AsyncSession,
    profile_id: str,
    resource_id: str,
) -> List[HealthResourceVersion]:
    """Returns ordered `HealthResourceVersion` snapshots (`version_id` 1, 2, ...) scoped to `profile_id` and active `ScopeContext`."""
    stmt = (
        select(HealthResourceVersion)
        .where(
            HealthResourceVersion.profile_id == profile_id.strip(),
            HealthResourceVersion.resource_id == resource_id.strip(),
        )
        .order_by(HealthResourceVersion.version_id.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def search_resources_by_coding(
    session: AsyncSession,
    profile_id: str,
    *,
    code: Optional[str] = None,
    system: Optional[str] = None,
    resource_type: Optional[str] = None,
    element_path: Optional[str] = None,
) -> List[HealthResource]:
    """Queries active `HealthResource` rows via `HealthResourceCoding` scoped to `profile_id` and active `ScopeContext`."""
    clean_profile_id = profile_id.strip()
    coding_stmt = select(HealthResourceCoding.resource_id).where(
        HealthResourceCoding.profile_id == clean_profile_id
    )
    if code and code.strip():
        coding_stmt = coding_stmt.where(HealthResourceCoding.code == code.strip())
    if system and system.strip():
        norm_sys = normalize_code_system_uri(system.strip(), code=code, resource_type=resource_type).canonical_system
        coding_stmt = coding_stmt.where(HealthResourceCoding.system == (norm_sys or system.strip()))
    if resource_type and resource_type.strip():
        coding_stmt = coding_stmt.where(HealthResourceCoding.resource_type == resource_type.strip())
    if element_path and element_path.strip():
        coding_stmt = coding_stmt.where(HealthResourceCoding.element_path == element_path.strip())

    stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == clean_profile_id,
            HealthResource.status == "active",
            HealthResource.id.in_(coding_stmt),
        )
        .order_by(HealthResource.effective_at.desc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_outbound_references(
    session: AsyncSession,
    profile_id: str,
    source_resource_id: str,
    *,
    reference_field: Optional[str] = None,
) -> List[HealthResourceReference]:
    """Returns outbound `HealthResourceReference` edges from `source_resource_id` within `profile_id` and active `ScopeContext`."""
    stmt = select(HealthResourceReference).where(
        HealthResourceReference.profile_id == profile_id.strip(),
        HealthResourceReference.source_resource_id == source_resource_id.strip(),
    )
    if reference_field and reference_field.strip():
        stmt = stmt.where(HealthResourceReference.reference_field == reference_field.strip())
    stmt = stmt.order_by(HealthResourceReference.reference_field.asc(), HealthResourceReference.target_type.asc())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_inbound_references(
    session: AsyncSession,
    profile_id: str,
    *,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    target_resource_id: Optional[str] = None,
) -> List[HealthResourceReference]:
    """Returns inbound `HealthResourceReference` edges pointing to a target within `profile_id` and active `ScopeContext`."""
    stmt = select(HealthResourceReference).where(
        HealthResourceReference.profile_id == profile_id.strip()
    )
    if target_type and target_type.strip():
        stmt = stmt.where(HealthResourceReference.target_type == target_type.strip())
    if target_id and target_id.strip():
        stmt = stmt.where(HealthResourceReference.target_id == target_id.strip())
    if target_resource_id and target_resource_id.strip():
        stmt = stmt.where(HealthResourceReference.target_resource_id == target_resource_id.strip())
    res = await session.execute(stmt)
    return list(res.scalars().all())


__all__ = [
    "compute_canonical_fhir_content_hash",
    "delete_fhir_resource_with_history",
    "ensure_canonical_patient_resource",
    "get_inbound_references",
    "get_outbound_references",
    "get_resource_version_history",
    "link_intra_batch_references",
    "reverse_dedup_merge",
    "search_resources_by_coding",
    "upsert_fhir_resource_with_history",
]
