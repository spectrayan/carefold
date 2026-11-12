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

"""Epic MyChart (SMART on FHIR R4 / SMART App Launch v2) starter connector (AU-56 & #286).

Ingests read-only USCDI FHIR R4 clinical resources (`Patient`, `Condition`, `MedicationRequest`,
`AllergyIntolerance`, `Immunization`, `Observation`, `DiagnosticReport`, `Procedure`, `CarePlan`,
`Encounter`, `DocumentReference`), supports `.well-known/smart-configuration` discovery with
`/metadata` fallback, SMART v2 `.rs` granular scopes, multi-page `Bundle.link[relation='next']`
pagination over `ScopedHttp`, and persistent sync into the `#282`/`#283` FHIR repository.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
import uuid

from fhir.resources.R4B.allergyintolerance import (
    AllergyIntolerance as FhirAllergyIntolerance,
)
from fhir.resources.R4B.careplan import CarePlan as FhirCarePlan
from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.diagnosticreport import (
    DiagnosticReport as FhirDiagnosticReport,
)
from fhir.resources.R4B.documentreference import (
    DocumentReference as FhirDocumentReference,
)
from fhir.resources.R4B.encounter import Encounter as FhirEncounter
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.medicationrequest import (
    MedicationRequest as FhirMedicationRequest,
)
from fhir.resources.R4B.observation import Observation as FhirObservation
from fhir.resources.R4B.patient import Patient as FhirPatient
from fhir.resources.R4B.procedure import Procedure as FhirProcedure
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.connectors.smart_fhir import (
    DEFAULT_MAX_BUNDLE_PAGES,
    SMART_V1_CLINICAL_SCOPES,
    SMART_V2_CLINICAL_SCOPES,
    SmartConfiguration,
    SmartUntrustedResult,
    build_smart_authorization_url,
    discover_smart_configuration,
    fetch_paginated_fhir_bundle_resources,
    persist_smart_fhir_records,
    search_smart_fhir_records,
)
from carefold.models.health import HealthResource
from yarvelle_core.connectors.base import (
    NormalisedRecord,
    Page,
    StreamSpec,
    ToolContext,
    ToolSpec,
)
from yarvelle_core.connectors.errors import ConnectorError
from yarvelle_core.connectors.http import ScopedHttp
from yarvelle_core.connectors.manifest import ConnectorManifest

_MANIFEST_PATH = Path(__file__).resolve().parent / "manifests" / "epic_smart.yaml"

DEFAULT_EPIC_FHIR_BASE_URL = (
    "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
)

_USCDI_STREAMS: tuple[StreamSpec, ...] = (
    StreamSpec(
        name="Condition",
        description="Patient problem list and clinical conditions (USCDI Condition)",
        read_mode="full_refresh",
        primary_key=["id"],
        cursor_field="recordedDate",
    ),
    StreamSpec(
        name="MedicationRequest",
        description="Active and historical outpatient medication orders (USCDI MedicationRequest)",
        read_mode="full_refresh",
        primary_key=["id"],
        cursor_field="authoredOn",
    ),
    StreamSpec(
        name="AllergyIntolerance",
        description="Documented allergies and adverse reactions (USCDI AllergyIntolerance)",
        read_mode="full_refresh",
        primary_key=["id"],
        cursor_field="recordedDate",
    ),
    StreamSpec(
        name="Immunization",
        description="Vaccine administration history (USCDI Immunization)",
        read_mode="full_refresh",
        primary_key=["id"],
        cursor_field="occurrenceDateTime",
    ),
    StreamSpec(
        name="Observation",
        description="Laboratory results and clinical vital sign observations (USCDI Observation)",
        read_mode="incremental",
        primary_key=["id"],
        cursor_field="effectiveDateTime",
    ),
    StreamSpec(
        name="Encounter",
        description="Clinical visits and hospital encounters (USCDI Encounter)",
        read_mode="incremental",
        primary_key=["id"],
        cursor_field="period.start",
    ),
    StreamSpec(
        name="DocumentReference",
        description="Clinical notes and visit summaries (USCDI DocumentReference)",
        read_mode="incremental",
        primary_key=["id"],
        cursor_field="date",
    ),
)

_USCDI_MODEL_VALIDATORS: Dict[str, Any] = {
    "Patient": FhirPatient,
    "Condition": FhirCondition,
    "MedicationRequest": FhirMedicationRequest,
    "AllergyIntolerance": FhirAllergyIntolerance,
    "Immunization": FhirImmunization,
    "Observation": FhirObservation,
    "DiagnosticReport": FhirDiagnosticReport,
    "Procedure": FhirProcedure,
    "CarePlan": FhirCarePlan,
    "Encounter": FhirEncounter,
    "DocumentReference": FhirDocumentReference,
}


def _extract_fhir_effective_datetime(resource: Mapping[str, Any]) -> datetime:
    """Extracts a timezone-aware UTC timestamp from a FHIR R4 resource."""
    candidates = (
        resource.get("effectiveDateTime"),
        resource.get("recordedDate"),
        resource.get("authoredOn"),
        resource.get("occurrenceDateTime"),
        resource.get("issued"),
        resource.get("date"),
        (resource.get("period") or {}).get("start")
        if isinstance(resource.get("period"), dict)
        else None,
        (resource.get("effectivePeriod") or {}).get("start")
        if isinstance(resource.get("effectivePeriod"), dict)
        else None,
    )
    for raw in candidates:
        if isinstance(raw, str) and raw.strip():
            clean = raw.strip()
            if clean.endswith("Z"):
                clean = clean[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(clean)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def _extract_fhir_display_summary(resource: Mapping[str, Any]) -> str:
    """Extracts a human-readable code/display summary from a FHIR R4 resource."""
    for field_name in ("code", "medicationCodeableConcept", "vaccineCode", "type"):
        field_val = resource.get(field_name)
        if isinstance(field_val, dict):
            text = field_val.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            codings = field_val.get("coding")
            if isinstance(codings, list) and codings:
                first = codings[0]
                if isinstance(first, dict):
                    disp = first.get("display") or first.get("code")
                    if isinstance(disp, str) and disp.strip():
                        return disp.strip()
        elif isinstance(field_val, list) and field_val:
            first_concept = field_val[0]
            if isinstance(first_concept, dict):
                text = first_concept.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return str(resource.get("resourceType", "FHIR Resource"))


class EpicSmartConnector:
    """Read-only SMART on FHIR R4 / v2 patient portal connector for Epic MyChart."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        base_url: str = DEFAULT_EPIC_FHIR_BASE_URL,
        max_pages: int = DEFAULT_MAX_BUNDLE_PAGES,
    ) -> None:
        self._manifest = manifest or ConnectorManifest.from_yaml(_MANIFEST_PATH)
        self._base_url = base_url.rstrip("/")
        self._max_pages = max(1, int(max_pages or DEFAULT_MAX_BUNDLE_PAGES))
        self._indexed_records: List[NormalisedRecord] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return list(_USCDI_STREAMS)

    def tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="epic_smart_search_records",
                description=(
                    "Searches normalized USCDI FHIR R4 clinical records imported from "
                    "Epic MyChart (SMART on FHIR). Output is marked untrusted."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "resource_type": {
                            "type": "string",
                            "description": (
                                "Optional FHIR R4 resourceType filter (Condition, "
                                "MedicationRequest, AllergyIntolerance, Immunization, "
                                "Observation, DiagnosticReport, Procedure, CarePlan, "
                                "Encounter, DocumentReference)."
                            ),
                        },
                        "query": {
                            "type": "string",
                            "description": "Case-insensitive substring filter over display text or codes.",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 20,
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                },
                risk_class="read_only",
                trust="untrusted",
                data_flows=tuple(self._manifest.data_flows.allowed_hosts),
                handler=self._handle_search_records,
            )
        ]

    async def discover_smart_configuration(
        self,
        http: ScopedHttp,
        *,
        require_pkce_s256: bool = True,
    ) -> SmartConfiguration:
        """Discovers SMART on FHIR v2 metadata for this Epic endpoint (`.well-known` with `/metadata` fallback)."""
        return await discover_smart_configuration(
            self._base_url,
            http,
            require_pkce_s256=require_pkce_s256,
        )

    def build_authorization_url(
        self,
        *,
        smart_config: SmartConfiguration,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        code_verifier: Optional[str] = None,
        scopes: Optional[Sequence[str]] = None,
    ) -> str:
        """Builds a SMART v2 authorization URL enforcing PKCE S256 and `aud` binding."""
        return build_smart_authorization_url(
            smart_config=smart_config,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_verifier=code_verifier,
            scopes=scopes or SMART_V2_CLINICAL_SCOPES,
        )

    async def fetch(
        self,
        ctx: ToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
        *,
        max_pages: Optional[int] = None,
    ) -> Page:
        """Fetches a FHIR R4 Bundle for the requested USCDI resource stream and follows `Bundle.link[relation='next']`."""
        if stream not in _USCDI_MODEL_VALIDATORS:
            raise ConnectorError(
                f"Unsupported Epic SMART stream '{stream}'. Supported: {sorted(_USCDI_MODEL_VALIDATORS)}"
            )

        params: Dict[str, str] = {"_count": "50"}
        if cursor and cursor.startswith(("http://", "https://")):
            url = cursor
            params = {}
        else:
            url = f"{self._base_url}/{stream}"
            if cursor:
                params["_page_token"] = cursor

        records, next_cursor, has_more, pages_fetched = await fetch_paginated_fhir_bundle_resources(
            http=http,
            initial_url=url,
            params=params,
            max_pages=max_pages or self._max_pages,
            connector_label="Epic SMART",
            stream_name=stream,
        )

        return Page(
            stream=stream,
            records=records,
            next_cursor=next_cursor,
            has_more=has_more,
            metadata={"profile_id": ctx.profile_id, "pages_fetched": pages_fetched},
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        """Validates raw FHIR R4 resources with `fhir.resources` and wraps them in untrusted `NormalisedRecord` items."""
        profile_id = str(page.metadata.get("profile_id") or "unknown-profile")
        stream_name = page.stream
        validator_cls = _USCDI_MODEL_VALIDATORS.get(stream_name)
        if validator_cls is None:
            raise ConnectorError(f"No FHIR validator registered for stream '{stream_name}'.")

        normalised: List[NormalisedRecord] = []
        for raw_res in page.records:
            if not isinstance(raw_res, dict):
                continue

            res_copy = dict(raw_res)
            res_copy.setdefault("resourceType", stream_name)
            res_copy.setdefault("id", f"{stream_name.lower()}-{uuid.uuid4().hex[:10]}")

            validated_model = validator_cls.model_validate(res_copy)
            validated_dict = json.loads(validated_model.model_dump_json())

            effective_dt = _extract_fhir_effective_datetime(validated_dict)
            date_str = effective_dt.date().isoformat()
            display = _extract_fhir_display_summary(validated_dict)

            payload: Dict[str, Any] = {
                "resourceType": stream_name,
                "fhir_resource": validated_dict,
                "code_display": display,
                "effective_date": date_str,
                "source_display": f"From Epic SMART, {date_str}",
                "trust": "untrusted",
            }
            raw_hash = hashlib.sha256(
                json.dumps(validated_dict, sort_keys=True).encode("utf-8")
            ).hexdigest()

            rec = NormalisedRecord(
                id=str(validated_dict.get("id")),
                stream=stream_name,
                profile_id=profile_id,
                source=self._manifest.id,
                record_type=stream_name,
                timestamp=effective_dt,
                data=payload,
                raw_hash=raw_hash,
            )
            normalised.append(rec)

        self._indexed_records.extend(normalised)
        return normalised

    async def persist_records(
        self,
        session: AsyncSession,
        *,
        profile_id: str,
        records: Optional[Sequence[NormalisedRecord]] = None,
        connection_id: Optional[str] = None,
        actor_user_id: Optional[str] = None,
    ) -> List[HealthResource]:
        """Persists mapped `NormalisedRecord` items into the `#282`/`#283` FHIR R4 repository."""
        target_records = list(records) if records is not None else [
            r for r in self._indexed_records if r.profile_id == profile_id
        ]
        return await persist_smart_fhir_records(
            session,
            profile_id=profile_id,
            records=target_records,
            connection_id=connection_id,
            connector_id=self._manifest.id,
            actor_user_id=actor_user_id,
        )

    async def _handle_search_records(
        self,
        ctx: ToolContext,
        args: Mapping[str, Any],
    ) -> SmartUntrustedResult:
        """Searches persisted `HealthResource` rows (and any in-memory mapped records) with untrusted taint."""
        return await search_smart_fhir_records(
            ctx,
            args,
            fallback_indexed_records=self._indexed_records,
            default_source_label="Epic SMART",
            connector_source=self._manifest.id,
        )


__all__ = [
    "DEFAULT_EPIC_FHIR_BASE_URL",
    "EpicSmartConnector",
    "SMART_V1_CLINICAL_SCOPES",
    "SMART_V2_CLINICAL_SCOPES",
]
