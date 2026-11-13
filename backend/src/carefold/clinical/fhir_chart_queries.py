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

"""Domain query service for scope-isolated FHIR R4 chart summaries and trends (#287, #344).

Executed inside governed `McpDatabaseToolbox` database sessions via `carefold.clinical.db_hooks`
so `carefold.tools.fhir_tools` never opens raw ORM sessions directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.scoped_session import register_scope_listeners
from carefold.fhir.registry import (
    CLINICAL_FHIR_RESOURCE_TYPES as CLINICAL_RESOURCE_TYPES,
    PAPERWORK_FHIR_RESOURCE_TYPES as PAPERWORK_RESOURCE_TYPES,
    SUPPORTED_FHIR_RESOURCE_TYPES,
    extract_codings,
    resolve_resource_scope,
)
from carefold.fhir.sql_pushdown import (
    build_category_sql_filter,
    build_code_sql_filter,
    build_fhir_status_sql_filter,
    get_session_dialect_name,
)
from carefold.fhir.terminology import (
    CURATED_CLINICAL_CODES,
    extract_original_quantity_from_extension,
    normalize_code_system_uri,
)
from carefold.models.health import HealthResource

register_scope_listeners()

REQUIRED_CLINICAL_SCOPE = "health.clinical"

NON_CLINICAL_FHIR_TOOL_DISCLAIMER: str = (
    "Informational chart summary for visit preparation only; not a medical diagnosis, "
    "treatment decision, or dosing recommendation. Review all records with your healthcare provider."
)

_CANONICAL_RESOURCE_TYPE_MAP: Dict[str, str] = {
    rtype.lower(): rtype for rtype in SUPPORTED_FHIR_RESOURCE_TYPES
}

_INACTIVE_CONDITION_STATUSES = frozenset({
    "inactive",
    "remission",
    "resolved",
    "entered-in-error",
    "refuted",
})

_INACTIVE_MEDICATION_STATUSES = frozenset({
    "stopped",
    "completed",
    "cancelled",
    "entered-in-error",
    "draft",
    "declined",
})

_INACTIVE_ALLERGY_STATUSES = frozenset({
    "inactive",
    "resolved",
    "entered-in-error",
    "refuted",
})


def _parse_iso_filter(raw_date: Optional[str]) -> Optional[datetime]:
    """Parses a `YYYY-MM-DD` or ISO-8601 datetime filter into a UTC-aware datetime."""
    if not raw_date or not isinstance(raw_date, str) or not raw_date.strip():
        return None
    clean = raw_date.strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as exc:
        raise ValueError(f"Invalid ISO-8601 date_from parameter '{raw_date}'.") from exc


def _resolve_canonical_resource_type(raw_type: str) -> str:
    """Resolves a resource type name case-insensitively and validates that it belongs to `health.clinical`."""
    clean = (raw_type or "").strip()
    if not clean:
        raise ValueError("Parameter 'resource_type' is required and must be a non-empty string.")
    canonical = _CANONICAL_RESOURCE_TYPE_MAP.get(clean.lower())
    if canonical is None:
        raise ValueError(
            f"Unsupported FHIR R4 resource_type '{clean}'. Must be one of the allowlisted clinical resource types."
        )
    if canonical in PAPERWORK_RESOURCE_TYPES or canonical not in CLINICAL_RESOURCE_TYPES:
        raise ValueError(
            f"Scope violation: resource_type '{canonical}' belongs to 'health.paperwork' and cannot be queried "
            f"via 'health.clinical' chart tools."
        )
    return canonical


def _is_resource_untrusted(hr: HealthResource) -> bool:
    """Determines whether a `HealthResource` carries untrusted external taint."""
    data = hr.data if isinstance(hr.data, dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    prov = data.get("_carefold_provenance") if isinstance(data.get("_carefold_provenance"), dict) else {}
    if meta.get("trust") == "untrusted" or prov.get("trust") == "untrusted":
        return True
    if (hr.source_type or "").lower() in ("file", "connector", "companion", "smart_health_card", "external"):
        return True
    return False


def _extract_source_name(hr: HealthResource) -> str:
    """Extracts a human-readable source name for provenance citations."""
    data = hr.data if isinstance(hr.data, dict) else {}
    prov = data.get("_carefold_provenance") if isinstance(data.get("_carefold_provenance"), dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

    source_name = (
        prov.get("source_name")
        or meta.get("source")
        or hr.source_ref
        or hr.source_type
        or "Local Health Chart"
    )
    clean_source = str(source_name).strip()
    if clean_source in ("manual", "user"):
        return "Patient Manual Entry"
    if clean_source == "profile_anchor" or clean_source == "canonical_profile":
        return "Carefold Profile"
    return clean_source


def _format_effective_date(hr: HealthResource) -> Tuple[str, str]:
    """Returns `(iso_timestamp, yyyy_mm_dd)` for a `HealthResource`."""
    dt = hr.effective_at or hr.recorded_at or hr.created_at
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        iso_str = dt.isoformat()
        date_str = dt.strftime("%Y-%m-%d")
        return iso_str, date_str
    raw_str = str(dt or "")
    return raw_str, (raw_str[:10] if len(raw_str) >= 10 else "unknown-date")


def _build_provenance_summary(hr: HealthResource) -> Tuple[str, Dict[str, Any]]:
    """Constructs the human-readable provenance citation (`From <source>, <date>`) and metadata dict."""
    source_name = _extract_source_name(hr)
    iso_str, date_str = _format_effective_date(hr)
    data = hr.data if isinstance(hr.data, dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    prov = data.get("_carefold_provenance") if isinstance(data.get("_carefold_provenance"), dict) else {}
    merged_sources = prov.get("merged_sources") if isinstance(prov.get("merged_sources"), list) else []
    untrusted = _is_resource_untrusted(hr)
    trust_label = "untrusted" if untrusted else "trusted"

    citation = f"From {source_name}, {date_str}"
    return citation, {
        "citation": citation,
        "source_name": source_name,
        "source_type": hr.source_type,
        "source_ref": hr.source_ref,
        "date": date_str,
        "effective_at": iso_str,
        "version_id": str(meta.get("versionId") or prov.get("version_id") or "1"),
        "trust": trust_label,
        "merged_sources_count": len(merged_sources),
    }


def _extract_resource_display_and_codes(hr: HealthResource) -> Tuple[str, List[Dict[str, Optional[str]]]]:
    """Extracts a human-readable display label and normalized coding tuples from a `HealthResource`."""
    data = hr.data if isinstance(hr.data, dict) else {}
    rtype = str(data.get("resourceType") or hr.resource_type or "").strip()
    canonical_rtype = _CANONICAL_RESOURCE_TYPE_MAP.get(rtype.lower(), rtype)
    codings = extract_codings(data, rtype=canonical_rtype)

    code_summaries: List[Dict[str, Optional[str]]] = []
    primary_display: Optional[str] = None
    for c in codings:
        sys_uri = c.get("system")
        code_val = c.get("code")
        disp = c.get("display")
        if not disp and sys_uri and code_val:
            disp = CURATED_CLINICAL_CODES.get((sys_uri, code_val))
        code_summaries.append({
            "system": sys_uri,
            "code": code_val,
            "display": disp,
        })
        if not primary_display and disp:
            primary_display = disp

    if not primary_display:
        for concept_key in ("code", "medicationCodeableConcept", "vaccineCode", "type", "description"):
            concept_val = data.get(concept_key)
            if isinstance(concept_val, dict):
                text_val = concept_val.get("text")
                if isinstance(text_val, str) and text_val.strip():
                    primary_display = text_val.strip()
                    break
                coding_list = concept_val.get("coding")
                if isinstance(coding_list, list):
                    for item in coding_list:
                        if isinstance(item, dict) and item.get("display"):
                            primary_display = str(item["display"]).strip()
                            break
                if primary_display:
                    break
            elif isinstance(concept_val, str) and concept_val.strip():
                primary_display = concept_val.strip()
                break

    if not primary_display:
        if code_summaries and code_summaries[0].get("code"):
            primary_display = f"{canonical_rtype} ({code_summaries[0]['code']})"
        else:
            primary_display = canonical_rtype or "Clinical Resource"

    return primary_display, code_summaries


def _extract_resource_status(hr: HealthResource) -> str:
    """Extracts the clinical or workflow status from a FHIR resource payload."""
    data = hr.data if isinstance(hr.data, dict) else {}
    clin_status = data.get("clinicalStatus")
    if isinstance(clin_status, dict):
        codings = clin_status.get("coding")
        if isinstance(codings, list) and codings and isinstance(codings[0], dict) and codings[0].get("code"):
            return str(codings[0]["code"]).strip().lower()
        if clin_status.get("text"):
            return str(clin_status["text"]).strip().lower()
    elif isinstance(clin_status, str) and clin_status.strip():
        return clin_status.strip().lower()

    raw_status = data.get("status")
    if isinstance(raw_status, str) and raw_status.strip():
        return raw_status.strip().lower()

    return (hr.status or "active").lower()


def _extract_observation_value_summary(data: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str], Optional[str]]:
    """Extracts `(raw_value, unit, formatted_value)` from an Observation or clinical resource."""
    vq = data.get("valueQuantity")
    if isinstance(vq, dict) and vq.get("value") is not None:
        val = vq.get("value")
        unit = str(vq.get("unit") or vq.get("code") or "").strip() or None
        formatted = f"{val} {unit}".strip() if unit else str(val)
        return val, unit, formatted

    if isinstance(data.get("valueString"), str) and data["valueString"].strip():
        vs = data["valueString"].strip()
        return vs, None, vs

    vcc = data.get("valueCodeableConcept")
    if isinstance(vcc, dict):
        text_val = vcc.get("text")
        if isinstance(text_val, str) and text_val.strip():
            return text_val.strip(), None, text_val.strip()
        codings = vcc.get("coding")
        if isinstance(codings, list) and codings and isinstance(codings[0], dict):
            disp = codings[0].get("display") or codings[0].get("code")
            if disp:
                return str(disp), None, str(disp)

    components = data.get("component")
    if isinstance(components, list) and components:
        comp_parts: List[str] = []
        comp_values: Dict[str, Any] = {}
        common_unit: Optional[str] = None
        for comp in components:
            if not isinstance(comp, dict):
                continue
            c_vq = comp.get("valueQuantity")
            if not isinstance(c_vq, dict) or c_vq.get("value") is None:
                continue
            c_val = c_vq.get("value")
            c_unit = str(c_vq.get("unit") or c_vq.get("code") or "").strip() or None
            if c_unit and not common_unit:
                common_unit = c_unit
            c_codings = (comp.get("code") or {}).get("coding") if isinstance(comp.get("code"), dict) else None
            c_code = (
                c_codings[0].get("code")
                if isinstance(c_codings, list) and c_codings and isinstance(c_codings[0], dict)
                else None
            )
            c_disp = (
                c_codings[0].get("display")
                if isinstance(c_codings, list) and c_codings and isinstance(c_codings[0], dict)
                else None
            )
            key = c_code or c_disp or f"component_{len(comp_values) + 1}"
            comp_values[str(key)] = {"value": c_val, "unit": c_unit, "display": c_disp}
            comp_parts.append(f"{c_val}")

        if comp_values:
            if "8480-6" in comp_values and "8462-4" in comp_values:
                sys_v = comp_values["8480-6"]["value"]
                dia_v = comp_values["8462-4"]["value"]
                bp_unit = comp_values["8480-6"].get("unit") or common_unit or "mmHg"
                return comp_values, bp_unit, f"{sys_v}/{dia_v} {bp_unit}".strip()
            joined = "/".join(comp_parts)
            formatted = f"{joined} {common_unit}".strip() if common_unit else joined
            return comp_values, common_unit, formatted

    return None, None, None


def _summarize_health_resource(hr: HealthResource) -> Dict[str, Any]:
    """Formats a `HealthResource` into a coordinator-ready summary dictionary with provenance citation."""
    data = hr.data if isinstance(hr.data, dict) else {}
    raw_rtype = str(data.get("resourceType") or hr.resource_type or "").strip()
    canonical_rtype = _CANONICAL_RESOURCE_TYPE_MAP.get(raw_rtype.lower(), raw_rtype)
    display, codes = _extract_resource_display_and_codes(hr)
    status = _extract_resource_status(hr)
    raw_val, unit, formatted_val = _extract_observation_value_summary(data)
    iso_str, date_str = _format_effective_date(hr)
    citation, prov_dict = _build_provenance_summary(hr)
    untrusted = _is_resource_untrusted(hr)

    summary: Dict[str, Any] = {
        "id": hr.id,
        "resource_type": canonical_rtype,
        "display": display,
        "status": status,
        "codes": codes,
        "effective_at": iso_str,
        "date": date_str,
        "provenance_citation": citation,
        "provenance": prov_dict,
        "trust": "untrusted" if untrusted else "trusted",
    }
    if formatted_val is not None:
        summary["value"] = formatted_val
        summary["raw_value"] = raw_val
        summary["unit"] = unit

    if canonical_rtype == "AllergyIntolerance":
        if data.get("criticality"):
            summary["criticality"] = str(data["criticality"])
        reactions = data.get("reaction")
        if isinstance(reactions, list) and reactions:
            manifestations: List[str] = []
            for rx in reactions:
                if isinstance(rx, dict):
                    for man in rx.get("manifestation") or []:
                        if isinstance(man, dict):
                            if man.get("text"):
                                manifestations.append(str(man["text"]))
                            elif isinstance(man.get("coding"), list) and man["coding"]:
                                first_c = man["coding"][0]
                                if isinstance(first_c, dict) and (first_c.get("display") or first_c.get("code")):
                                    manifestations.append(str(first_c.get("display") or first_c.get("code")))
            if manifestations:
                summary["manifestations"] = manifestations

    if canonical_rtype in (
        "MedicationRequest",
        "MedicationStatement",
        "MedicationAdministration",
        "MedicationDispense",
    ):
        dosage = data.get("dosageInstruction") or data.get("dosage")
        if isinstance(dosage, list) and dosage and isinstance(dosage[0], dict) and dosage[0].get("text"):
            summary["dosage_text"] = str(dosage[0]["text"])

    return summary


def _matches_category_filter(data: Dict[str, Any], category_filter: str) -> bool:
    """Checks whether a FHIR resource matches a `category` code or text filter."""
    target = category_filter.strip().lower()
    if not target:
        return True
    raw_cat = data.get("category")
    cats = raw_cat if isinstance(raw_cat, list) else ([raw_cat] if isinstance(raw_cat, dict) else [])
    for cat in cats:
        if not isinstance(cat, dict):
            continue
        if isinstance(cat.get("text"), str) and target in cat["text"].strip().lower():
            return True
        codings = cat.get("coding")
        if isinstance(codings, list):
            for c in codings:
                if not isinstance(c, dict):
                    continue
                code_val = str(c.get("code") or "").strip().lower()
                disp_val = str(c.get("display") or "").strip().lower()
                if code_val == target or target in disp_val:
                    return True
    return False


def _parse_code_token(raw_code: Optional[str], resource_type: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Parses a FHIR search token (`code` or `system|code`) into `(canonical_system, code)`."""
    if not raw_code or not isinstance(raw_code, str) or not raw_code.strip():
        return None, None
    token = raw_code.strip()
    if "|" in token:
        raw_sys, code_part = token.split("|", 1)
        clean_code = code_part.strip() or None
        clean_sys = raw_sys.strip()
        if clean_sys:
            norm_sys = normalize_code_system_uri(
                clean_sys, code=clean_code, resource_type=resource_type
            ).canonical_system
            return norm_sys or clean_sys, clean_code
        return None, clean_code
    return None, token


def _resource_matches_code(
    hr: HealthResource,
    *,
    target_system: Optional[str],
    target_code: Optional[str],
) -> bool:
    """Checks whether a `HealthResource` matches `(target_system, target_code)` across its codings or display."""
    if not target_code and not target_system:
        return True
    data = hr.data if isinstance(hr.data, dict) else {}
    raw_rtype = str(data.get("resourceType") or hr.resource_type or "").strip()
    canonical_rtype = _CANONICAL_RESOURCE_TYPE_MAP.get(raw_rtype.lower(), raw_rtype)
    codings = extract_codings(data, rtype=canonical_rtype)
    target_code_lower = target_code.lower() if target_code else None

    for c in codings:
        c_code = str(c.get("code") or "").strip()
        c_sys = str(c.get("system") or "").strip()
        c_disp = str(c.get("display") or "").strip()
        norm_sys = (
            normalize_code_system_uri(c_sys, code=c_code, resource_type=canonical_rtype).canonical_system
            if c_sys
            else None
        )

        if target_system and (norm_sys or c_sys) != target_system:
            continue
        if target_code_lower:
            if c_code.lower() == target_code_lower or target_code_lower in c_disp.lower():
                return True
        else:
            return True
    return False


async def query_fhir_search_resources(
    session: AsyncSession,
    *,
    profile_id: str,
    resource_type: str,
    code: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    limit: int = 25,
) -> Dict[str, Any]:
    """Executes `fhir_search_resources` inside a governed database session."""
    canonical_rtype = _resolve_canonical_resource_type(resource_type)
    clamped_limit = max(1, min(int(limit or 25), 100))
    parsed_date_from = _parse_iso_filter(date_from)
    target_system, target_code = _parse_code_token(code, resource_type=canonical_rtype)

    dialect = get_session_dialect_name(session)
    stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == profile_id,
            HealthResource.scope == REQUIRED_CLINICAL_SCOPE,
            HealthResource.status != "tombstone",
            func.lower(HealthResource.resource_type) == canonical_rtype.lower(),
        )
        .order_by(HealthResource.effective_at.desc(), HealthResource.updated_at.desc())
    )
    if parsed_date_from is not None:
        stmt = stmt.where(HealthResource.effective_at >= parsed_date_from)
    if category:
        stmt = stmt.where(build_category_sql_filter(category, dialect_name=dialect))
    if target_code or target_system:
        stmt = stmt.where(
            build_code_sql_filter(
                target_code,
                system=target_system,
                scope=REQUIRED_CLINICAL_SCOPE,
                match_display=True,
                dialect_name=dialect,
            )
        )

    stmt = stmt.limit(clamped_limit)
    res = await session.execute(stmt)
    candidate_rows = list(res.scalars().all())

    matched_summaries: List[Dict[str, Any]] = []
    any_untrusted = False

    for hr in candidate_rows:
        if hr.profile_id != profile_id or hr.scope != REQUIRED_CLINICAL_SCOPE:
            continue
        data = hr.data if isinstance(hr.data, dict) else {}
        if resolve_resource_scope(canonical_rtype, data) != REQUIRED_CLINICAL_SCOPE:
            continue
        if category and not _matches_category_filter(data, category):
            continue
        if target_code or target_system:
            if not _resource_matches_code(hr, target_system=target_system, target_code=target_code):
                continue

        summary = _summarize_health_resource(hr)
        if summary["trust"] == "untrusted":
            any_untrusted = True
        matched_summaries.append(summary)
        if len(matched_summaries) >= clamped_limit:
            break

    overall_trust = "untrusted" if any_untrusted else "trusted"
    return {
        "profile_id": profile_id,
        "scope": REQUIRED_CLINICAL_SCOPE,
        "resource_type": canonical_rtype,
        "filters": {
            "code": code,
            "category": category,
            "date_from": date_from,
            "limit": clamped_limit,
        },
        "count": len(matched_summaries),
        "records": matched_summaries,
        "trust": overall_trust,
        "tainted": any_untrusted,
        "disclaimer": NON_CLINICAL_FHIR_TOOL_DISCLAIMER,
    }


async def query_fhir_patient_summary(
    session: AsyncSession,
    *,
    profile_id: str,
    limit_per_section: int = 15,
) -> Dict[str, Any]:
    """Executes `fhir_get_patient_summary` (IPS digest) inside a governed database session."""
    clamped_limit = max(1, min(int(limit_per_section or 15), 50))
    dialect = get_session_dialect_name(session)
    section_type_groups: List[Tuple[str, ...]] = [
        ("Condition",),
        ("MedicationRequest", "MedicationStatement", "MedicationAdministration", "MedicationDispense"),
        ("AllergyIntolerance",),
        ("Observation", "DiagnosticReport"),
        ("Immunization",),
        ("Procedure",),
    ]
    all_rows: List[HealthResource] = []
    for rt_group in section_type_groups:
        sec_stmt = (
            select(HealthResource)
            .where(
                HealthResource.profile_id == profile_id,
                HealthResource.scope == REQUIRED_CLINICAL_SCOPE,
                HealthResource.status != "tombstone",
                func.lower(HealthResource.resource_type).in_([t.lower() for t in rt_group]),
                not_(build_fhir_status_sql_filter("entered-in-error", dialect_name=dialect)),
            )
            .order_by(HealthResource.effective_at.desc(), HealthResource.updated_at.desc())
            .limit(clamped_limit * 2)
        )
        all_rows.extend((await session.execute(sec_stmt)).scalars().all())

    active_conditions: List[Dict[str, Any]] = []
    active_medications: List[Dict[str, Any]] = []
    allergies: List[Dict[str, Any]] = []
    recent_labs_and_vitals: List[Dict[str, Any]] = []
    immunizations: List[Dict[str, Any]] = []
    procedures: List[Dict[str, Any]] = []
    any_untrusted = False

    for hr in all_rows:
        if hr.profile_id != profile_id or hr.scope != REQUIRED_CLINICAL_SCOPE:
            continue
        data = hr.data if isinstance(hr.data, dict) else {}
        raw_rtype = str(data.get("resourceType") or hr.resource_type or "").strip()
        canonical_rtype = _CANONICAL_RESOURCE_TYPE_MAP.get(raw_rtype.lower(), raw_rtype)
        if canonical_rtype in PAPERWORK_RESOURCE_TYPES:
            continue
        if resolve_resource_scope(canonical_rtype, data) != REQUIRED_CLINICAL_SCOPE:
            continue

        summary = _summarize_health_resource(hr)
        status = summary.get("status", "active")

        if canonical_rtype == "Condition":
            if status not in _INACTIVE_CONDITION_STATUSES and len(active_conditions) < clamped_limit:
                active_conditions.append(summary)
                if summary["trust"] == "untrusted":
                    any_untrusted = True
        elif canonical_rtype in (
            "MedicationRequest",
            "MedicationStatement",
            "MedicationAdministration",
            "MedicationDispense",
        ):
            if status not in _INACTIVE_MEDICATION_STATUSES and len(active_medications) < clamped_limit:
                active_medications.append(summary)
                if summary["trust"] == "untrusted":
                    any_untrusted = True
        elif canonical_rtype == "AllergyIntolerance":
            if status not in _INACTIVE_ALLERGY_STATUSES and len(allergies) < clamped_limit:
                allergies.append(summary)
                if summary["trust"] == "untrusted":
                    any_untrusted = True
        elif canonical_rtype in ("Observation", "DiagnosticReport"):
            if status != "entered-in-error" and len(recent_labs_and_vitals) < clamped_limit:
                recent_labs_and_vitals.append(summary)
                if summary["trust"] == "untrusted":
                    any_untrusted = True
        elif canonical_rtype == "Immunization":
            if status != "entered-in-error" and len(immunizations) < clamped_limit:
                immunizations.append(summary)
                if summary["trust"] == "untrusted":
                    any_untrusted = True
        elif canonical_rtype == "Procedure":
            if status != "entered-in-error" and len(procedures) < clamped_limit:
                procedures.append(summary)
                if summary["trust"] == "untrusted":
                    any_untrusted = True

    total_records = (
        len(active_conditions)
        + len(active_medications)
        + len(allergies)
        + len(recent_labs_and_vitals)
        + len(immunizations)
        + len(procedures)
    )
    overall_trust = "untrusted" if any_untrusted else "trusted"

    return {
        "profile_id": profile_id,
        "scope": REQUIRED_CLINICAL_SCOPE,
        "summary_type": "IPS",
        "empty_chart": total_records == 0,
        "total_records": total_records,
        "sections": {
            "active_conditions": active_conditions,
            "active_medications": active_medications,
            "allergies": allergies,
            "recent_labs_and_vitals": recent_labs_and_vitals,
            "immunizations": immunizations,
            "procedures": procedures,
        },
        "active_conditions": active_conditions,
        "active_medications": active_medications,
        "allergies": allergies,
        "recent_labs_and_vitals": recent_labs_and_vitals,
        "immunizations": immunizations,
        "procedures": procedures,
        "trust": overall_trust,
        "tainted": any_untrusted,
        "disclaimer": NON_CLINICAL_FHIR_TOOL_DISCLAIMER,
    }


def _derive_interpretation_flag(
    data: Dict[str, Any],
    raw_val: Any,
    ref_range: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Extracts FHIR `interpretation` code (`H`, `L`, `N`) or derives it when numeric bounds exist."""
    interp = data.get("interpretation")
    if isinstance(interp, list) and interp and isinstance(interp[0], dict):
        codings = interp[0].get("coding")
        if isinstance(codings, list) and codings and isinstance(codings[0], dict) and codings[0].get("code"):
            return str(codings[0]["code"]).strip().upper()
        if interp[0].get("text"):
            return str(interp[0]["text"]).strip()

    if isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool) and isinstance(ref_range, dict):
        low = ref_range.get("low")
        high = ref_range.get("high")
        try:
            val_f = float(raw_val)
            if high is not None and val_f > float(high):
                return "H"
            if low is not None and val_f < float(low):
                return "L"
            if low is not None or high is not None:
                return "N"
        except (ValueError, TypeError):
            pass
    return None


def _extract_observation_point_for_code(
    hr: HealthResource,
    *,
    target_system: Optional[str],
    target_code: str,
) -> Optional[Dict[str, Any]]:
    """Extracts a single chronological observation data point if `hr` matches `target_code`."""
    data = hr.data if isinstance(hr.data, dict) else {}
    target_lower = target_code.strip().lower()
    if not target_lower:
        return None

    display, _codes = _extract_resource_display_and_codes(hr)
    iso_str, date_str = _format_effective_date(hr)
    citation, prov_dict = _build_provenance_summary(hr)
    untrusted = _is_resource_untrusted(hr)
    trust_label = "untrusted" if untrusted else "trusted"

    ref_range_summary: Optional[Dict[str, Any]] = None
    ref_ranges = data.get("referenceRange")
    if isinstance(ref_ranges, list) and ref_ranges and isinstance(ref_ranges[0], dict):
        rr = ref_ranges[0]
        low_val = rr.get("low", {}).get("value") if isinstance(rr.get("low"), dict) else None
        high_val = rr.get("high", {}).get("value") if isinstance(rr.get("high"), dict) else None
        rr_unit = (
            (rr.get("low", {}).get("unit") if isinstance(rr.get("low"), dict) else None)
            or (rr.get("high", {}).get("unit") if isinstance(rr.get("high"), dict) else None)
        )
        ref_range_summary = {
            "low": low_val,
            "high": high_val,
            "unit": rr_unit,
            "text": rr.get("text"),
        }

    top_code_matched = False
    matched_code_str = target_code
    matched_system_str = target_system or "http://loinc.org"
    top_concept = data.get("code") if isinstance(data.get("code"), dict) else {}
    top_codings = top_concept.get("coding") if isinstance(top_concept.get("coding"), list) else []
    for c in top_codings:
        if not isinstance(c, dict):
            continue
        c_code = str(c.get("code") or "").strip()
        c_sys = str(c.get("system") or "").strip()
        c_disp = str(c.get("display") or "").strip()
        norm_sys = (
            normalize_code_system_uri(c_sys, code=c_code, resource_type="Observation").canonical_system
            if c_sys
            else None
        )
        if target_system and (norm_sys or c_sys) != target_system:
            continue
        if c_code.lower() == target_lower or (c_disp and target_lower in c_disp.lower()):
            top_code_matched = True
            matched_code_str = c_code or target_code
            matched_system_str = norm_sys or c_sys or matched_system_str
            if c_disp:
                display = c_disp
            break

    if not top_code_matched and isinstance(top_concept.get("text"), str):
        if target_lower in top_concept["text"].strip().lower():
            top_code_matched = True

    components = data.get("component") if isinstance(data.get("component"), list) else []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_concept = comp.get("code") if isinstance(comp.get("code"), dict) else {}
        comp_codings = comp_concept.get("coding") if isinstance(comp_concept.get("coding"), list) else []
        for cc in comp_codings:
            if not isinstance(cc, dict):
                continue
            cc_code = str(cc.get("code") or "").strip()
            cc_sys = str(cc.get("system") or "").strip()
            cc_disp = str(cc.get("display") or "").strip()
            norm_sys = (
                normalize_code_system_uri(cc_sys, code=cc_code, resource_type="Observation").canonical_system
                if cc_sys
                else None
            )
            if target_system and (norm_sys or cc_sys) != target_system:
                continue
            if cc_code.lower() == target_lower or (cc_disp and target_lower == cc_disp.lower()):
                comp_vq = comp.get("valueQuantity") if isinstance(comp.get("valueQuantity"), dict) else {}
                c_val = comp_vq.get("value")
                c_unit = str(comp_vq.get("unit") or comp_vq.get("code") or "").strip() or None
                orig_qty = extract_original_quantity_from_extension(comp_vq)
                return {
                    "id": hr.id,
                    "effective_at": iso_str,
                    "date": date_str,
                    "system": norm_sys or cc_sys or "http://loinc.org",
                    "code": cc_code,
                    "display": cc_disp or CURATED_CLINICAL_CODES.get(("http://loinc.org", cc_code)) or display,
                    "value": c_val,
                    "formatted_value": f"{c_val} {c_unit}".strip() if c_unit and c_val is not None else str(c_val),
                    "unit": c_unit,
                    "original_quantity": orig_qty,
                    "reference_range": ref_range_summary,
                    "interpretation": _derive_interpretation_flag(data, c_val, ref_range_summary),
                    "provenance_citation": citation,
                    "provenance": prov_dict,
                    "trust": trust_label,
                }

    if not top_code_matched:
        return None

    raw_val, unit, formatted_val = _extract_observation_value_summary(data)
    vq = data.get("valueQuantity") if isinstance(data.get("valueQuantity"), dict) else {}
    orig_qty = extract_original_quantity_from_extension(vq) if vq else None

    return {
        "id": hr.id,
        "effective_at": iso_str,
        "date": date_str,
        "system": matched_system_str,
        "code": matched_code_str,
        "display": CURATED_CLINICAL_CODES.get((matched_system_str, matched_code_str)) or display,
        "value": raw_val,
        "formatted_value": formatted_val,
        "unit": unit,
        "original_quantity": orig_qty,
        "reference_range": ref_range_summary,
        "interpretation": _derive_interpretation_flag(data, raw_val, ref_range_summary),
        "provenance_citation": citation,
        "provenance": prov_dict,
        "trust": trust_label,
    }


async def query_fhir_observation_trends(
    session: AsyncSession,
    *,
    profile_id: str,
    loinc_or_code: str,
    limit: int = 12,
) -> Dict[str, Any]:
    """Executes `fhir_get_observation_trends` inside a governed database session."""
    if not loinc_or_code or not isinstance(loinc_or_code, str) or not loinc_or_code.strip():
        raise ValueError("Parameter 'loinc_or_code' is required and must be a non-empty string.")

    clamped_limit = max(1, min(int(limit or 12), 100))
    target_system, target_code = _parse_code_token(loinc_or_code, resource_type="Observation")
    assert target_code is not None

    dialect = get_session_dialect_name(session)
    stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == profile_id,
            HealthResource.scope == REQUIRED_CLINICAL_SCOPE,
            HealthResource.status != "tombstone",
            func.lower(HealthResource.resource_type) == "observation",
            build_code_sql_filter(
                target_code,
                system=target_system,
                scope=REQUIRED_CLINICAL_SCOPE,
                match_display=True,
                dialect_name=dialect,
            ),
        )
        .order_by(HealthResource.effective_at.desc(), HealthResource.updated_at.desc())
        .limit(clamped_limit)
    )
    res = await session.execute(stmt)
    obs_rows = list(res.scalars().all())

    recent_points_desc: List[Dict[str, Any]] = []
    any_untrusted = False

    for hr in obs_rows:
        if hr.profile_id != profile_id or hr.scope != REQUIRED_CLINICAL_SCOPE:
            continue
        point = _extract_observation_point_for_code(
            hr,
            target_system=target_system,
            target_code=target_code,
        )
        if point is not None:
            if point["trust"] == "untrusted":
                any_untrusted = True
            recent_points_desc.append(point)
            if len(recent_points_desc) >= clamped_limit:
                break

    chronological_points = list(reversed(recent_points_desc))

    numeric_vals: List[float] = [
        float(p["value"])
        for p in chronological_points
        if isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool)
    ]

    trend_summary: Dict[str, Any] = {
        "count": len(chronological_points),
        "unit": chronological_points[-1].get("unit") if chronological_points else None,
        "latest_value": chronological_points[-1].get("value") if chronological_points else None,
        "latest_date": chronological_points[-1].get("date") if chronological_points else None,
        "min_value": min(numeric_vals) if numeric_vals else None,
        "max_value": max(numeric_vals) if numeric_vals else None,
        "delta_from_first": (
            round(numeric_vals[-1] - numeric_vals[0], 4) if len(numeric_vals) >= 2 else None
        ),
    }

    overall_trust = "untrusted" if any_untrusted else "trusted"
    display_label = (
        chronological_points[-1].get("display")
        if chronological_points
        else CURATED_CLINICAL_CODES.get((target_system or "http://loinc.org", target_code)) or target_code
    )

    return {
        "profile_id": profile_id,
        "scope": REQUIRED_CLINICAL_SCOPE,
        "code": target_code,
        "system": target_system or "http://loinc.org",
        "display": display_label,
        "count": len(chronological_points),
        "data_points": chronological_points,
        "summary": trend_summary,
        "trust": overall_trust,
        "tainted": any_untrusted,
        "disclaimer": NON_CLINICAL_FHIR_TOOL_DISCLAIMER,
    }
