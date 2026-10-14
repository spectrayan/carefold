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

"""Oracle Health, athenahealth, and CMS Blue Button 2.0 SMART R4 connectors (AU-73 / E5.3)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fhir.resources.R4B.coverage import Coverage as FhirCoverage
from fhir.resources.R4B.explanationofbenefit import (
    ExplanationOfBenefit as FhirExplanationOfBenefit,
)

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
from connectors.starters.epic_smart import (
    USCDI_FHIR_STREAMS,
    _extract_effective_datetime,
    _FHIR_MODEL_REGISTRY,
    validate_uscdi_fhir_resource,
)

_MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"
_ORACLE_MANIFEST_PATH = _MANIFESTS_DIR / "oracle_health.yaml"
_ATHENA_MANIFEST_PATH = _MANIFESTS_DIR / "athenahealth.yaml"
_CMS_MANIFEST_PATH = _MANIFESTS_DIR / "cms_blue_button.yaml"

ORACLE_HEALTH_FHIR_BASE_URL = "https://fhir-myrecord.cerner.com/r4/ec2458f2-1e24-41c8-b71b-0e701af7583d"
ATHENAHEALTH_FHIR_BASE_URL = "https://api.platform.athenahealth.com/fhir/r4"
CMS_BLUE_BUTTON_FHIR_BASE_URL = "https://sandbox.bluebutton.cms.gov/v2/fhir"

_PAYER_FHIR_REGISTRY: Dict[str, Any] = {
    "ExplanationOfBenefit": FhirExplanationOfBenefit,
    "Coverage": FhirCoverage,
}


class _BaseUscdiSmartConnector:
    """Shared USCDI SMART on FHIR R4 implementation for Oracle Health and athenahealth."""

    def __init__(
        self,
        manifest: ConnectorManifest,
        base_url: str,
        source_label: str,
        tool_name: str,
    ) -> None:
        self._manifest = manifest
        self._base_url = base_url.rstrip("/")
        self._source_label = source_label
        self._tool_name = tool_name
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
        if not ctx.profile_id or not ctx.user_id:
            raise ValueError("ToolContext user_id and profile_id are required.")
        if stream not in _FHIR_MODEL_REGISTRY:
            raise ValueError(f"Unsupported USCDI FHIR stream '{stream}' for {self._manifest.id}.")

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
        normalised: List[NormalisedRecord] = []
        default_profile_id = str(page.metadata.get("profile_id") or "default-profile")
        primary_host = (
            self._manifest.data_flows.allowed_hosts[0]
            if self._manifest.data_flows.allowed_hosts
            else self._manifest.id
        )

        for idx, raw in enumerate(page.records):
            if not isinstance(raw, dict):
                continue
            profile_id = str(raw.get("profile_id") or default_profile_id)
            clean_input = {k: v for k, v in raw.items() if k != "profile_id"}
            rtype = str(clean_input.get("resourceType") or page.stream).strip()

            validated_fhir = validate_uscdi_fhir_resource(clean_input, expected_type=page.stream)
            eff_dt, eff_iso, date_str = _extract_effective_datetime(validated_fhir)
            source_display = f"From {self._source_label}, {date_str}"

            rec_id = str(validated_fhir.get("id") or f"{rtype.lower()}-{idx}")
            validated_fhir["id"] = rec_id
            validated_fhir.setdefault("meta", {})
            if isinstance(validated_fhir["meta"], dict):
                validated_fhir["meta"]["source"] = f"https://{primary_host}"
                validated_fhir["meta"]["tag"] = [
                    {
                        "system": "https://carefold.ai/trust",
                        "code": "untrusted",
                        "display": source_display,
                    }
                ]

            canonical_fhir = _FHIR_MODEL_REGISTRY[rtype].model_validate(validated_fhir).model_dump(
                mode="json", exclude_none=True
            )

            record_data: Dict[str, Any] = copy.deepcopy(canonical_fhir)
            record_data["source_display"] = source_display
            record_data["trust"] = "untrusted"
            record_data["effective_at"] = eff_iso
            record_data["fhir_resource"] = canonical_fhir
            record_data["_carefold_provenance"] = {
                "source_name": self._source_label,
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
        allowed_hosts = tuple(self._manifest.data_flows.allowed_hosts)

        async def _search_handler(
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
                name=self._tool_name,
                description=f"Searches normalized USCDI FHIR R4 clinical records imported from {self._source_label}.",
                parameters={
                    "type": "object",
                    "properties": {
                        "resource_type": {"type": "string"},
                        "query": {"type": "string"},
                    },
                },
                risk_class="read_only",
                risk_tier="read",
                trust="untrusted",
                data_flows=allowed_hosts,
                handler=_search_handler,
            )
        ]


class OracleHealthConnector(_BaseUscdiSmartConnector):
    """Patient-facing Oracle Health (Cerner SMART on FHIR R4) connector (AU-73)."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        base_url: str = ORACLE_HEALTH_FHIR_BASE_URL,
    ) -> None:
        super().__init__(
            manifest=manifest or ConnectorManifest.from_yaml(_ORACLE_MANIFEST_PATH),
            base_url=base_url,
            source_label="Oracle Health",
            tool_name="oracle_health_search_records",
        )


class AthenahealthConnector(_BaseUscdiSmartConnector):
    """Patient-facing athenahealth SMART on FHIR R4 connector (AU-73)."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        base_url: str = ATHENAHEALTH_FHIR_BASE_URL,
    ) -> None:
        super().__init__(
            manifest=manifest or ConnectorManifest.from_yaml(_ATHENA_MANIFEST_PATH),
            base_url=base_url,
            source_label="athenahealth",
            tool_name="athenahealth_search_records",
        )


def validate_payer_fhir_resource(resource: Dict[str, Any], expected_type: str) -> Dict[str, Any]:
    """Validates and normalizes `ExplanationOfBenefit` or `Coverage` via `fhir.resources.R4B`."""
    rtype = str(resource.get("resourceType") or expected_type).strip()
    model_cls = _PAYER_FHIR_REGISTRY.get(rtype)
    if model_cls is None:
        raise ValueError(f"Unsupported payer FHIR resourceType '{rtype}'.")

    candidate = copy.deepcopy(resource)
    candidate["resourceType"] = rtype

    if rtype == "ExplanationOfBenefit":
        candidate.setdefault("status", "active")
        candidate.setdefault(
            "type",
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/claim-type",
                        "code": "professional",
                    }
                ]
            },
        )
        candidate.setdefault("use", "claim")
        candidate.setdefault("patient", {"reference": "Patient/pat-1"})
        candidate.setdefault("created", "2026-10-01")
        candidate.setdefault("insurer", {"display": "CMS Medicare"})
        candidate.setdefault("provider", {"display": "Medicare Provider"})
        candidate.setdefault("outcome", "complete")
        candidate.setdefault(
            "insurance",
            [{"focal": True, "coverage": {"reference": "Coverage/cov-default"}}],
        )
    elif rtype == "Coverage":
        candidate.setdefault("status", "active")
        candidate.setdefault("beneficiary", {"reference": "Patient/pat-1"})
        candidate.setdefault("payor", [{"display": "CMS Medicare"}])

    validated = model_cls.model_validate(candidate)
    return validated.model_dump(mode="json", exclude_none=True)


def _extract_claim_summary_fields(canonical_fhir: Dict[str, Any], rtype: str) -> Dict[str, Any]:
    """Extracts claim totals, service dates, and provider details from ExplanationOfBenefit or Coverage."""
    if rtype == "ExplanationOfBenefit":
        total_amount: Optional[float] = None
        currency = "USD"
        totals = canonical_fhir.get("total")
        if isinstance(totals, list) and totals:
            first_tot = totals[0]
            if isinstance(first_tot, dict) and isinstance(first_tot.get("amount"), dict):
                amt = first_tot["amount"]
                if amt.get("value") is not None:
                    total_amount = float(amt["value"])
                if amt.get("currency"):
                    currency = str(amt["currency"])
        elif isinstance(canonical_fhir.get("payment"), dict):
            pmt_amt = canonical_fhir["payment"].get("amount")
            if isinstance(pmt_amt, dict) and pmt_amt.get("value") is not None:
                total_amount = float(pmt_amt["value"])

        billable_period = canonical_fhir.get("billablePeriod") or {}
        service_date = (
            str(billable_period.get("start") or canonical_fhir.get("created") or "")[:10]
            if isinstance(billable_period, dict)
            else str(canonical_fhir.get("created") or "")[:10]
        )
        provider_obj = canonical_fhir.get("provider") or {}
        provider_display = (
            str(provider_obj.get("display") or provider_obj.get("reference") or "Medicare Provider")
            if isinstance(provider_obj, dict)
            else "Medicare Provider"
        )
        return {
            "claim_total": total_amount,
            "currency": currency,
            "service_date": service_date or "2026-10-01",
            "provider_display": provider_display,
        }

    payor_list = canonical_fhir.get("payor") or []
    payor_display = "CMS Medicare"
    if isinstance(payor_list, list) and payor_list and isinstance(payor_list[0], dict):
        payor_display = str(payor_list[0].get("display") or payor_list[0].get("reference") or "CMS Medicare")
    period = canonical_fhir.get("period") or {}
    coverage_start = str(period.get("start") or "")[:10] if isinstance(period, dict) else ""
    return {
        "payor_display": payor_display,
        "coverage_start": coverage_start or "2026-01-01",
        "subscriber_id": canonical_fhir.get("subscriberId"),
    }


class CmsBlueButtonConnector:
    """CMS Blue Button 2.0 FHIR R4 connector for Medicare claims and coverage (AU-73)."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        base_url: str = CMS_BLUE_BUTTON_FHIR_BASE_URL,
    ) -> None:
        self._manifest = manifest or ConnectorManifest.from_yaml(_CMS_MANIFEST_PATH)
        self._base_url = base_url.rstrip("/")
        self._indexed_records: List[NormalisedRecord] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return [
            StreamSpec(
                name="ExplanationOfBenefit",
                description="Medicare Part A, Part B, and Part D claims and adjudication details",
                read_mode="incremental",
                primary_key=["id"],
                cursor_field="_lastUpdated",
            ),
            StreamSpec(
                name="Coverage",
                description="Medicare beneficiary enrollment and coverage periods",
                read_mode="incremental",
                primary_key=["id"],
                cursor_field="_lastUpdated",
            ),
        ]

    async def fetch(
        self,
        ctx: ToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        if not ctx.profile_id or not ctx.user_id:
            raise ValueError("ToolContext user_id and profile_id are required.")
        if stream not in _PAYER_FHIR_REGISTRY:
            raise ValueError(f"Unsupported stream '{stream}' for CmsBlueButtonConnector.")

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
        elif isinstance(payload, dict) and payload.get("resourceType") in _PAYER_FHIR_REGISTRY:
            res = dict(payload)
            res.setdefault("profile_id", ctx.profile_id)
            raw_resources.append(res)

        next_cursor: Optional[str] = None
        if isinstance(payload, dict) and payload.get("next_cursor"):
            next_cursor = str(payload["next_cursor"])

        return Page(
            stream=stream,
            records=raw_resources,
            next_cursor=next_cursor,
            has_more=bool(next_cursor),
            metadata={"profile_id": ctx.profile_id, "user_id": ctx.user_id},
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        normalised: List[NormalisedRecord] = []
        default_profile_id = str(page.metadata.get("profile_id") or "default-profile")

        for idx, raw in enumerate(page.records):
            if not isinstance(raw, dict):
                continue
            profile_id = str(raw.get("profile_id") or default_profile_id)
            clean_input = {k: v for k, v in raw.items() if k != "profile_id"}
            rtype = str(clean_input.get("resourceType") or page.stream).strip()

            validated_fhir = validate_payer_fhir_resource(clean_input, expected_type=page.stream)
            eff_dt, eff_iso, date_str = _extract_effective_datetime(validated_fhir)
            if rtype == "ExplanationOfBenefit" and isinstance(validated_fhir.get("billablePeriod"), dict):
                bp_start = validated_fhir["billablePeriod"].get("start")
                if isinstance(bp_start, str) and len(bp_start) >= 10:
                    date_str = bp_start[:10]

            source_display = f"From CMS Blue Button 2.0, {date_str}"
            rec_id = str(validated_fhir.get("id") or f"{rtype.lower()}-{idx}")
            validated_fhir["id"] = rec_id
            validated_fhir.setdefault("meta", {})
            if isinstance(validated_fhir["meta"], dict):
                validated_fhir["meta"]["source"] = "https://api.bluebutton.cms.gov"
                validated_fhir["meta"]["tag"] = [
                    {
                        "system": "https://carefold.ai/trust",
                        "code": "untrusted",
                        "display": source_display,
                    }
                ]

            canonical_fhir = _PAYER_FHIR_REGISTRY[rtype].model_validate(validated_fhir).model_dump(
                mode="json", exclude_none=True
            )
            summary_fields = _extract_claim_summary_fields(canonical_fhir, rtype)

            record_data: Dict[str, Any] = copy.deepcopy(canonical_fhir)
            record_data.update(summary_fields)
            record_data["source_display"] = source_display
            record_data["trust"] = "untrusted"
            record_data["effective_at"] = eff_iso
            record_data["fhir_resource"] = canonical_fhir
            record_data["_carefold_provenance"] = {
                "source_name": "CMS Blue Button 2.0",
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
        allowed_hosts = tuple(self._manifest.data_flows.allowed_hosts)

        async def _search_claims_handler(
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
                name="cms_blue_button_search_claims",
                description="Searches Medicare ExplanationOfBenefit claims and Coverage records from CMS Blue Button 2.0.",
                parameters={
                    "type": "object",
                    "properties": {
                        "resource_type": {
                            "type": "string",
                            "description": "Optional filter: ExplanationOfBenefit or Coverage",
                        },
                        "query": {"type": "string"},
                    },
                },
                risk_class="read_only",
                risk_tier="read",
                trust="untrusted",
                data_flows=allowed_hosts,
                handler=_search_claims_handler,
            )
        ]


__all__ = [
    "ATHENAHEALTH_FHIR_BASE_URL",
    "AthenahealthConnector",
    "CMS_BLUE_BUTTON_FHIR_BASE_URL",
    "CmsBlueButtonConnector",
    "ORACLE_HEALTH_FHIR_BASE_URL",
    "OracleHealthConnector",
    "validate_payer_fhir_resource",
]
