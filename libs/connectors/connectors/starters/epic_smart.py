# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Epic MyChart (SMART on FHIR R4) starter connector (AU-56 / E5.3, E10.7)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fhir.resources.R4B.allergyintolerance import AllergyIntolerance as FhirAllergyIntolerance
from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.documentreference import DocumentReference as FhirDocumentReference
from fhir.resources.R4B.encounter import Encounter as FhirEncounter
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.medicationrequest import MedicationRequest as FhirMedicationRequest
from fhir.resources.R4B.observation import Observation as FhirObservation

from connectors.base import (
    Connector,
    NormalisedRecord,
    Page,
    StreamSpec,
    ToolContext,
    ToolSpec,
)
from connectors.http import ScopedHttp
from connectors.manifest import ConnectorManifest

_MANIFEST_PATH = Path(__file__).resolve().parent / "manifests" / "epic_smart.yaml"

EPIC_FHIR_BASE_URL = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"

USCDI_FHIR_STREAMS: Tuple[Tuple[str, str], ...] = (
    ("Condition", "Clinical problem list, diagnoses, and health concerns"),
    ("MedicationRequest", "Active and historical prescribed medications"),
    ("AllergyIntolerance", "Recorded drug, food, and environmental allergies"),
    ("Immunization", "Vaccine administration history"),
    ("Observation", "Laboratory results and clinical vital signs"),
    ("Encounter", "Outpatient, inpatient, and emergency clinical visits"),
    ("DocumentReference", "Clinical notes, summaries, and diagnostic documents"),
)

_FHIR_MODEL_REGISTRY: Dict[str, Any] = {
    "Condition": FhirCondition,
    "MedicationRequest": FhirMedicationRequest,
    "AllergyIntolerance": FhirAllergyIntolerance,
    "Immunization": FhirImmunization,
    "Observation": FhirObservation,
    "Encounter": FhirEncounter,
    "DocumentReference": FhirDocumentReference,
}


def _extract_effective_datetime(resource: Dict[str, Any]) -> Tuple[datetime, str, str]:
    """Extracts UTC datetime, ISO timestamp, and YYYY-MM-DD date string from a FHIR resource."""
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
            iso_candidate = f"{clean}T00:00:00+00:00" if ("T" not in clean and len(clean) == 10) else clean
            try:
                dt = datetime.fromisoformat(iso_candidate.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt, dt.isoformat(), date_part
            except ValueError:
                return datetime.now(timezone.utc), iso_candidate, date_part

    now = datetime.now(timezone.utc)
    return now, now.isoformat(), now.strftime("%Y-%m-%d")


def validate_uscdi_fhir_resource(resource: Dict[str, Any], expected_type: str) -> Dict[str, Any]:
    """Validates and normalizes a USCDI FHIR R4 resource via `fhir.resources.R4B`."""
    rtype = str(resource.get("resourceType") or expected_type).strip()
    model_cls = _FHIR_MODEL_REGISTRY.get(rtype)
    if model_cls is None:
        raise ValueError(f"Unsupported USCDI FHIR resourceType '{rtype}'.")

    candidate = copy.deepcopy(resource)
    candidate["resourceType"] = rtype

    if rtype == "Observation":
        candidate.setdefault("status", "final")
        candidate.setdefault("code", {"text": "Clinical Observation"})
    elif rtype == "MedicationRequest":
        candidate.setdefault("status", "active")
        candidate.setdefault("intent", "order")
        candidate.setdefault("subject", {"display": "Patient"})
        if "medicationCodeableConcept" not in candidate and "medicationReference" not in candidate:
            candidate["medicationCodeableConcept"] = {"text": "Medication"}
    elif rtype == "Condition":
        candidate.setdefault("subject", {"display": "Patient"})
    elif rtype == "AllergyIntolerance":
        candidate.setdefault("patient", {"display": "Patient"})
    elif rtype == "Immunization":
        candidate.setdefault("status", "completed")
        candidate.setdefault("vaccineCode", {"text": "Vaccine"})
        candidate.setdefault("patient", {"display": "Patient"})
        if "occurrenceDateTime" not in candidate and "occurrenceString" not in candidate:
            candidate["occurrenceDateTime"] = "2026-01-01"
    elif rtype == "Encounter":
        candidate.setdefault("status", "finished")
        candidate.setdefault(
            "class",
            {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
        )
    elif rtype == "DocumentReference":
        candidate.setdefault("status", "current")
        candidate.setdefault("content", [{"attachment": {"contentType": "text/plain"}}])

    validated = model_cls.model_validate(candidate)
    return validated.model_dump(mode="json", exclude_none=True)


class EpicSmartConnector:
    """Patient-facing Epic on FHIR SMART R4 starter connector (AU-56)."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        base_url: str = EPIC_FHIR_BASE_URL,
    ) -> None:
        self._manifest = manifest or ConnectorManifest.from_yaml(_MANIFEST_PATH)
        self._base_url = base_url.rstrip("/")
        self._indexed_records: List[NormalisedRecord] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return [
            StreamSpec(
                name=stream_name,
                description=desc,
                read_mode="incremental",
                primary_key=["id"],
                cursor_field="_lastUpdated",
            )
            for stream_name, desc in USCDI_FHIR_STREAMS
        ]

    async def fetch(
        self,
        ctx: ToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        """Queries `https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/{stream}` via ScopedHttp."""
        if not ctx.profile_id or not ctx.user_id:
            raise ValueError("ToolContext user_id and profile_id are required.")
        if stream not in _FHIR_MODEL_REGISTRY:
            raise ValueError(f"Unsupported USCDI FHIR stream '{stream}' for EpicSmartConnector.")

        url = f"{self._base_url}/{stream}"
        if cursor:
            url = f"{url}?_lastUpdated=gt{cursor}"

        response = await http.get(url)
        payload = response.json() if hasattr(response, "json") else {}

        raw_resources: List[Dict[str, Any]] = []
        if isinstance(payload, dict) and payload.get("resourceType") == "Bundle":
            for entry in payload.get("entry") or []:
                if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
                    res = dict(entry["resource"])
                    res.setdefault("profile_id", ctx.profile_id)
                    raw_resources.append(res)
        elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
            for rec in payload["records"]:
                if isinstance(rec, dict):
                    res = dict(rec)
                    res.setdefault("profile_id", ctx.profile_id)
                    raw_resources.append(res)
        elif isinstance(payload, dict) and payload.get("resourceType") in _FHIR_MODEL_REGISTRY:
            res = dict(payload)
            res.setdefault("profile_id", ctx.profile_id)
            raw_resources.append(res)

        next_cursor: Optional[str] = None
        if isinstance(payload, dict):
            for link in payload.get("link") or []:
                if isinstance(link, dict) and link.get("relation") == "next":
                    next_cursor = str(link.get("url") or "")
                    break
            if not next_cursor and payload.get("next_cursor"):
                next_cursor = str(payload["next_cursor"])

        return Page(
            stream=stream,
            records=raw_resources,
            next_cursor=next_cursor,
            has_more=bool(next_cursor),
            metadata={"profile_id": ctx.profile_id, "user_id": ctx.user_id},
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        """Validates USCDI FHIR R4 resources and attaches untrusted provenance (`E10.7`)."""
        normalised: List[NormalisedRecord] = []
        default_profile_id = str(page.metadata.get("profile_id") or "default-profile")

        for idx, raw in enumerate(page.records):
            if not isinstance(raw, dict):
                continue
            profile_id = str(raw.get("profile_id") or default_profile_id)
            clean_input = {k: v for k, v in raw.items() if k != "profile_id"}
            rtype = str(clean_input.get("resourceType") or page.stream).strip()

            validated_fhir = validate_uscdi_fhir_resource(clean_input, expected_type=page.stream)
            eff_dt, eff_iso, date_str = _extract_effective_datetime(validated_fhir)
            source_display = f"From Epic SMART, {date_str}"

            rec_id = str(validated_fhir.get("id") or f"{rtype.lower()}-{idx}")
            validated_fhir["id"] = rec_id
            validated_fhir.setdefault("meta", {})
            if isinstance(validated_fhir["meta"], dict):
                validated_fhir["meta"]["source"] = "https://fhir.epic.com"
                validated_fhir["meta"]["tag"] = [
                    {
                        "system": "https://carefold.ai/trust",
                        "code": "untrusted",
                        "display": source_display,
                    }
                ]

            # Re-validate after attaching FHIR-compliant meta tag
            canonical_fhir = _FHIR_MODEL_REGISTRY[rtype].model_validate(validated_fhir).model_dump(
                mode="json", exclude_none=True
            )

            record_data: Dict[str, Any] = copy.deepcopy(canonical_fhir)
            record_data["source_display"] = source_display
            record_data["trust"] = "untrusted"
            record_data["effective_at"] = eff_iso
            record_data["fhir_resource"] = canonical_fhir
            record_data["_carefold_provenance"] = {
                "source_name": "Epic SMART",
                "source_display": source_display,
                "trust": "untrusted",
            }

            raw_hash = hashlib.sha256(
                json.dumps(canonical_fhir, sort_keys=True).encode("utf-8")
            ).hexdigest()

            normalised.append(
                NormalisedRecord(
                    id=f"{rtype}:{rec_id}",
                    stream=page.stream,
                    profile_id=profile_id,
                    source=self._manifest.id,
                    record_type=rtype,
                    timestamp=eff_dt,
                    data=record_data,
                    raw_hash=raw_hash,
                )
            )

        self._indexed_records.extend(normalised)
        return normalised

    def tools(self) -> List[ToolSpec]:
        async def _search_records_handler(
            ctx: ToolContext,
            args: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            if not ctx.profile_id or not ctx.user_id:
                raise ValueError("ToolContext user_id and profile_id are required.")
            params = args or {}
            resource_type = params.get("resource_type")
            query = str(params.get("query") or "").strip().lower()

            matches: List[Dict[str, Any]] = []
            for rec in self._indexed_records:
                if rec.profile_id not in (ctx.profile_id, "default-profile"):
                    continue
                if resource_type and rec.record_type != resource_type:
                    continue
                if query and query not in json.dumps(rec.data).lower():
                    continue
                matches.append(rec.data)

            return {
                "connector_id": self._manifest.id,
                "profile_id": ctx.profile_id,
                "trust": "untrusted",
                "count": len(matches),
                "records": matches,
            }

        return [
            ToolSpec(
                name="epic_smart_search_records",
                description="Searches normalized USCDI FHIR R4 clinical records imported from Epic MyChart.",
                parameters={
                    "type": "object",
                    "properties": {
                        "resource_type": {
                            "type": "string",
                            "description": "Optional FHIR resourceType filter (e.g. Condition, Observation)",
                        },
                        "query": {
                            "type": "string",
                            "description": "Free-text search filter",
                        },
                    },
                },
                risk_class="read_only",
                risk_tier="read",
                trust="untrusted",
                data_flows=("fhir.epic.com",),
                handler=_search_records_handler,
            )
        ]


__all__ = [
    "EPIC_FHIR_BASE_URL",
    "EpicSmartConnector",
    "USCDI_FHIR_STREAMS",
    "validate_uscdi_fhir_resource",
]
