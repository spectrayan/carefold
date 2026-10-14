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

"""FHIR R4 Bundle clinical record parser and normalizer (AU-38 / E10.1, E10.7).

Parses FHIR R4 `Bundle` JSON documents, extracts clinical resources
(`Observation`, `Condition`, `MedicationStatement`, `MedicationRequest`,
`AllergyIntolerance`, `Immunization`, `Encounter`, `DocumentReference`),
attaches provenance (`From <source_name>, <date>`) and `"trust": "untrusted"`,
and synthesizes a `Provenance` summary resource.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from fhir.resources.R4B.allergyintolerance import AllergyIntolerance as FhirAllergyIntolerance
from fhir.resources.R4B.bundle import Bundle as FhirBundle
from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.documentreference import DocumentReference as FhirDocumentReference
from fhir.resources.R4B.encounter import Encounter as FhirEncounter
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.medicationrequest import MedicationRequest as FhirMedicationRequest
from fhir.resources.R4B.medicationstatement import MedicationStatement as FhirMedicationStatement
from fhir.resources.R4B.observation import Observation as FhirObservation
from fhir.resources.R4B.provenance import Provenance as FhirProvenance

_FHIR_MODEL_REGISTRY: Dict[str, Any] = {
    "Observation": FhirObservation,
    "Condition": FhirCondition,
    "MedicationStatement": FhirMedicationStatement,
    "MedicationRequest": FhirMedicationRequest,
    "AllergyIntolerance": FhirAllergyIntolerance,
    "Immunization": FhirImmunization,
    "Encounter": FhirEncounter,
    "DocumentReference": FhirDocumentReference,
}

SUPPORTED_FHIR_RESOURCE_TYPES = frozenset(_FHIR_MODEL_REGISTRY.keys())


def _validate_and_normalize_fhir_resource(resource: Dict[str, Any], rtype: str) -> Dict[str, Any]:
    """Validates and normalizes a FHIR R4 resource dict using official `fhir.resources.R4B` models."""
    model_cls = _FHIR_MODEL_REGISTRY.get(rtype)
    if model_cls is None:
        return copy.deepcopy(resource)

    candidate = copy.deepcopy(resource)
    # Provide standard R4 defaults for minimal partial resources before strict validation
    if rtype == "Observation":
        candidate.setdefault("status", "final")
        candidate.setdefault("code", {"text": "Clinical Observation"})
    elif rtype == "MedicationStatement":
        candidate.setdefault("status", "active")
        candidate.setdefault("subject", {"display": "Patient"})
    elif rtype == "MedicationRequest":
        candidate.setdefault("status", "active")
        candidate.setdefault("intent", "order")
        candidate.setdefault("subject", {"display": "Patient"})
    elif rtype == "Immunization":
        candidate.setdefault("status", "completed")
        candidate.setdefault("vaccineCode", {"text": "Immunization"})
        candidate.setdefault("patient", {"display": "Patient"})
    elif rtype == "AllergyIntolerance":
        candidate.setdefault("patient", {"display": "Patient"})
    elif rtype == "Condition":
        candidate.setdefault("subject", {"display": "Patient"})
    elif rtype == "Encounter":
        candidate.setdefault("status", "finished")
        candidate.setdefault("class", {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"})
    elif rtype == "DocumentReference":
        candidate.setdefault("status", "current")
        candidate.setdefault("content", [{"attachment": {"contentType": "text/plain"}}])

    try:
        validated = model_cls.model_validate(candidate)
        normalized = validated.model_dump(mode="json", exclude_none=True)
        # Preserve any original fields alongside validated canonical fields
        merged = copy.deepcopy(resource)
        merged.update(normalized)
        return merged
    except Exception:
        return copy.deepcopy(resource)


def _extract_coding_and_display(resource: Dict[str, Any], rtype: str) -> Tuple[Optional[str], str]:
    """Extracts primary code and human-readable display string from a FHIR R4 resource."""
    code_obj = (
        resource.get("code")
        or resource.get("medicationCodeableConcept")
        or resource.get("vaccineCode")
        or resource.get("type")
    )
    if isinstance(code_obj, list) and code_obj:
        code_obj = code_obj[0]

    code_val: Optional[str] = None
    display_val: Optional[str] = None

    if isinstance(code_obj, dict):
        display_val = code_obj.get("text")
        codings = code_obj.get("coding") or []
        if isinstance(codings, list) and codings:
            first_coding = codings[0] if isinstance(codings[0], dict) else {}
            code_val = first_coding.get("code")
            if not display_val:
                display_val = first_coding.get("display")

    if not display_val:
        display_val = (
            resource.get("description")
            or resource.get("title")
            or f"{rtype} ({code_val or resource.get('id') or 'record'})"
        )

    # Append value summary for Observations if present
    if rtype == "Observation":
        vq = resource.get("valueQuantity")
        if isinstance(vq, dict) and vq.get("value") is not None:
            unit = vq.get("unit") or vq.get("code") or ""
            display_val = f"{display_val}: {vq['value']} {unit}".strip()
        elif resource.get("valueString"):
            display_val = f"{display_val}: {resource['valueString']}".strip()

    return code_val, str(display_val)


def _extract_effective_iso(resource: Dict[str, Any]) -> Tuple[str, str]:
    """Extracts an ISO-8601 timestamp and YYYY-MM-DD date string from a FHIR resource."""
    candidates = [
        resource.get("effectiveDateTime"),
        (resource.get("effectivePeriod") or {}).get("start")
        if isinstance(resource.get("effectivePeriod"), dict)
        else None,
        resource.get("onsetDateTime"),
        resource.get("recordedDate"),
        resource.get("occurrenceDateTime"),
        resource.get("authoredOn"),
        resource.get("date"),
        (resource.get("period") or {}).get("start")
        if isinstance(resource.get("period"), dict)
        else None,
        resource.get("issued"),
    ]
    for raw in candidates:
        if raw and isinstance(raw, str) and raw.strip():
            clean = raw.strip()
            date_part = clean[:10] if len(clean) >= 10 else clean
            if "T" not in clean and len(clean) == 10:
                return f"{clean}T00:00:00+00:00", date_part
            return clean, date_part

    now = datetime.now(timezone.utc)
    return now.isoformat(), now.strftime("%Y-%m-%d")


def parse_fhir_bundle(
    raw_content: Union[str, bytes],
    source_name: str = "FHIR Bundle Import",
) -> Dict[str, Any]:
    """Parses a FHIR R4 Bundle JSON payload into normalized staged records.

    Args:
        raw_content: Raw JSON string or UTF-8 bytes of a FHIR R4 Bundle.
        source_name: Human-readable origin label for provenance display.

    Returns:
        Dictionary with `format`, `source_name`, `records`, `provenance`, and `summary`.

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

    staged_records: List[Dict[str, Any]] = []
    counts_by_type: Dict[str, int] = {}
    dates: List[str] = []

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            continue

        rtype = str(resource.get("resourceType") or "").strip()
        if rtype not in SUPPORTED_FHIR_RESOURCE_TYPES:
            continue

        effective_iso, date_str = _extract_effective_iso(resource)
        dates.append(date_str)
        code_val, display_val = _extract_coding_and_display(resource, rtype)

        raw_id = resource.get("id") or entry.get("fullUrl")
        if raw_id and str(raw_id).strip():
            source_id = f"{rtype}:{str(raw_id).strip()}"
        else:
            digest = hashlib.sha256(
                json.dumps(resource, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:16]
            source_id = f"{rtype}:{idx}:{digest}"

        source_display = f"From {clean_source}, {date_str}"
        fhir_copy = _validate_and_normalize_fhir_resource(resource, rtype)
        fhir_copy.setdefault("meta", {})
        if isinstance(fhir_copy["meta"], dict):
            fhir_copy["meta"]["source"] = clean_source
            fhir_copy["meta"]["trust"] = "untrusted"
        fhir_copy["_carefold_provenance"] = {
            "source_name": clean_source,
            "source_display": source_display,
            "trust": "untrusted",
        }

        staged_records.append({
            "resource_type": rtype,
            "source_id": source_id,
            "effective_at": effective_iso,
            "display": display_val,
            "code": code_val,
            "data": fhir_copy,
            "source_display": source_display,
            "trust": "untrusted",
        })
        counts_by_type[rtype] = counts_by_type.get(rtype, 0) + 1

    now_iso = datetime.now(timezone.utc).isoformat()
    now_date = now_iso[:10]
    bundle_id = str(bundle.get("id") or uuid.uuid4())
    prov_targets = [{"reference": r["source_id"]} for r in staged_records] or [{"display": clean_source}]
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
            "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">From {clean_source}, {now_date} ({len(staged_records)} clinical resources)</div>",
        },
    })
    provenance_fhir: Dict[str, Any] = prov_model.model_dump(mode="json", exclude_none=True)
    provenance_fhir["_carefold_provenance"] = {
        "source_name": clean_source,
        "source_display": f"From {clean_source}, {now_date}",
        "trust": "untrusted",
    }
    provenance_record: Dict[str, Any] = {
        "resource_type": "Provenance",
        "resourceType": "Provenance",
        "source_id": f"Provenance:{bundle_id}",
        "effective_at": now_iso,
        "display": f"Provenance: {clean_source} ({len(staged_records)} records)",
        "code": "PROVENANCE",
        "data": provenance_fhir,
        "source_display": f"From {clean_source}, {now_date}",
        "trust": "untrusted",
    }

    staged_records.append(provenance_record)
    counts_by_type["Provenance"] = 1

    sorted_dates = sorted(d for d in dates if d)
    date_range = {
        "min": sorted_dates[0] if sorted_dates else now_date,
        "max": sorted_dates[-1] if sorted_dates else now_date,
    }

    return {
        "format": "fhir_r4",
        "source_name": clean_source,
        "records": staged_records,
        "provenance": provenance_record,
        "summary": {
            "total_records": len(staged_records),
            "clinical_records": len(staged_records) - 1,
            "counts_by_type": counts_by_type,
            "date_range": date_range,
            "source_name": clean_source,
        },
    }


__all__ = [
    "SUPPORTED_FHIR_RESOURCE_TYPES",
    "parse_fhir_bundle",
]
