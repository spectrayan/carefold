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

"""Zocdoc Appointment Booking starter connector with irreversible approval gate (AU-71 / E4.2)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

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

_MANIFEST_PATH = Path(__file__).resolve().parent / "manifests" / "zocdoc.yaml"

ZOCDOC_PROVIDERS_URL = "https://api.zocdoc.com/v1/providers"
ZOCDOC_BOOKINGS_URL = "https://api.zocdoc.com/v1/bookings"


def _canonical_json(payload: Dict[str, Any]) -> str:
    """Serializes `payload` into deterministic RFC-8785 canonical JSON."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def prepare_zocdoc_booking_payload(
    profile_id: str,
    provider_id: str,
    provider_name: str,
    specialty: str,
    slot_id: str,
    start_time: str,
    insurance_carrier: Optional[str] = None,
) -> Dict[str, Any]:
    """Prepares a canonical Zocdoc appointment booking payload with `irreversible` risk tier (`AU-71`).

    Booking a live clinical slot with an external provider is classified as `irreversible`
    and always requires explicit human approval even when the profile or connector operates
    at `A2` autonomy.
    """
    clean_profile_id = (profile_id or "").strip()
    clean_provider_id = (provider_id or "").strip()
    clean_provider_name = (provider_name or "").strip()
    clean_specialty = (specialty or "").strip() or "General"
    clean_slot_id = (slot_id or "").strip()
    clean_start_time = (start_time or "").strip()
    clean_insurance = (insurance_carrier or "").strip() or None

    if not clean_profile_id:
        raise ValueError("profile_id is required to prepare a Zocdoc booking payload.")
    if not clean_provider_id or not clean_provider_name:
        raise ValueError("provider_id and provider_name are required.")
    if not clean_slot_id or not clean_start_time:
        raise ValueError("slot_id and start_time are required.")

    booking_args: Dict[str, Any] = {
        "insurance_carrier": clean_insurance,
        "profile_id": clean_profile_id,
        "provider_id": clean_provider_id,
        "provider_name": clean_provider_name,
        "slot_id": clean_slot_id,
        "specialty": clean_specialty,
        "start_time": clean_start_time,
    }
    canonical_str = _canonical_json(booking_args)
    payload_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    return {
        "connector_id": "zocdoc",
        "tool_name": "zocdoc_book_appointment",
        "profile_id": clean_profile_id,
        "provider_id": clean_provider_id,
        "provider_name": clean_provider_name,
        "specialty": clean_specialty,
        "slot_id": clean_slot_id,
        "start_time": clean_start_time,
        "insurance_carrier": clean_insurance,
        "risk_tier": "irreversible",
        "requires_approval": True,
        "trust": "untrusted",
        "destination_hosts": ["api.zocdoc.com"],
        "args": booking_args,
        "args_redacted": canonical_str,
        "payload_hash": payload_hash,
        "summary": (
            f"Book {clean_specialty} appointment with {clean_provider_name} "
            f"at {clean_start_time} (slot {clean_slot_id})"
        ),
    }


class ZocdocConnector:
    """Starter connector for Zocdoc provider discovery and irreversible appointment booking (AU-71)."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        providers_url: str = ZOCDOC_PROVIDERS_URL,
    ) -> None:
        self._manifest = manifest or ConnectorManifest.from_yaml(_MANIFEST_PATH)
        self._providers_url = providers_url
        self._cached_providers: List[NormalisedRecord] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return [
            StreamSpec(
                name="providers",
                description="Available healthcare providers and open appointment slots",
                read_mode="full_refresh",
                primary_key=["id"],
                cursor_field=None,
            )
        ]

    async def fetch(
        self,
        ctx: ToolContext,
        stream: str,
        cursor: Optional[str],
        http: ScopedHttp,
    ) -> Page:
        """Fetches provider availability records from `https://api.zocdoc.com/v1/providers`."""
        if not ctx.profile_id or not ctx.user_id:
            raise ValueError("ToolContext user_id and profile_id are required.")
        if stream != "providers":
            raise ValueError(f"Unsupported stream '{stream}' for ZocdocConnector.")

        url = self._providers_url
        if cursor:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}cursor={cursor}"

        response = await http.get(url)
        payload = response.json() if hasattr(response, "json") else {}
        items = (
            payload.get("providers")
            if isinstance(payload, dict) and isinstance(payload.get("providers"), list)
            else payload.get("records")
            if isinstance(payload, dict) and isinstance(payload.get("records"), list)
            else []
        )

        enriched: List[Dict[str, Any]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            rec = dict(item)
            rec.setdefault("id", f"zocdoc-prov-{idx + 1}")
            rec.setdefault("profile_id", ctx.profile_id)
            enriched.append(rec)

        next_cursor = str(payload["next_cursor"]) if isinstance(payload, dict) and payload.get("next_cursor") else None
        return Page(
            stream=stream,
            records=enriched,
            next_cursor=next_cursor,
            has_more=bool(next_cursor),
            metadata={"profile_id": ctx.profile_id, "user_id": ctx.user_id},
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        """Normalizes Zocdoc provider directory and slot records with untrusted provenance."""
        normalised: List[NormalisedRecord] = []
        default_profile_id = str(page.metadata.get("profile_id") or "default-profile")
        now_dt = datetime.now(timezone.utc)
        date_str = now_dt.strftime("%Y-%m-%d")

        for idx, raw in enumerate(page.records):
            if not isinstance(raw, dict):
                continue
            prov_id = str(raw.get("id") or raw.get("provider_id") or f"zocdoc-prov-{idx + 1}")
            profile_id = str(raw.get("profile_id") or default_profile_id)
            provider_name = str(raw.get("name") or raw.get("provider_name") or "Zocdoc Provider")
            specialty = str(raw.get("specialty") or "General")
            location = str(raw.get("location") or raw.get("address") or "")
            slots = raw.get("slots") if isinstance(raw.get("slots"), list) else []
            source_display = f"From Zocdoc, {date_str}"

            record_data = {
                "provider_id": prov_id,
                "provider_name": provider_name,
                "specialty": specialty,
                "location": location,
                "in_network_carriers": list(raw.get("in_network_carriers") or []),
                "slots": slots,
                "source_display": source_display,
                "trust": "untrusted",
            }
            raw_hash = hashlib.sha256(
                json.dumps(record_data, sort_keys=True).encode("utf-8")
            ).hexdigest()

            normalised.append(
                NormalisedRecord(
                    id=f"zocdoc:{prov_id}",
                    stream=page.stream,
                    profile_id=profile_id,
                    source=self._manifest.id,
                    record_type="provider_availability",
                    timestamp=now_dt,
                    data=record_data,
                    raw_hash=raw_hash,
                )
            )

        self._cached_providers = list(normalised)
        return normalised

    def tools(self) -> List[ToolSpec]:
        async def _search_providers_handler(
            ctx: ToolContext,
            args: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            if not ctx.profile_id or not ctx.user_id:
                raise ValueError("ToolContext user_id and profile_id are required.")
            params = args or {}
            specialty_q = str(params.get("specialty") or "").strip().lower()
            carrier_q = str(params.get("insurance_carrier") or "").strip().lower()

            matches: List[Dict[str, Any]] = []
            for rec in self._cached_providers:
                if rec.profile_id not in (ctx.profile_id, "default-profile"):
                    continue
                if specialty_q and specialty_q not in str(rec.data.get("specialty", "")).lower():
                    continue
                if carrier_q:
                    carriers = [str(c).lower() for c in (rec.data.get("in_network_carriers") or [])]
                    if carriers and not any(carrier_q in c for c in carriers):
                        continue
                matches.append(rec.data)

            return {
                "connector_id": self._manifest.id,
                "profile_id": ctx.profile_id,
                "trust": "untrusted",
                "count": len(matches),
                "providers": matches,
            }

        async def _book_appointment_handler(
            ctx: ToolContext,
            args: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            if not ctx.profile_id or not ctx.user_id:
                raise ValueError("ToolContext user_id and profile_id are required.")
            params = args or {}
            provider_id = str(params.get("provider_id") or "zocdoc-prov-1").strip()
            provider_name = str(params.get("provider_name") or "Healthcare Provider").strip()
            specialty = str(params.get("specialty") or "General").strip()
            slot_id = str(params.get("slot_id") or "").strip()
            start_time = str(params.get("start_time") or "").strip()
            if not slot_id or not start_time:
                raise ValueError("slot_id and start_time are required to book a Zocdoc appointment.")

            booking_id = str(params.get("booking_id") or uuid.uuid4().hex[:12])
            preview = prepare_zocdoc_booking_payload(
                profile_id=ctx.profile_id,
                provider_id=provider_id,
                provider_name=provider_name,
                specialty=specialty,
                slot_id=slot_id,
                start_time=start_time,
                insurance_carrier=params.get("insurance_carrier"),
            )
            return {
                "status": "confirmed",
                "booking_id": booking_id,
                "external_ref": f"zocdoc_booking:{booking_id}",
                "connector_id": self._manifest.id,
                "profile_id": ctx.profile_id,
                "provider_id": provider_id,
                "provider_name": provider_name,
                "specialty": specialty,
                "slot_id": slot_id,
                "start_time": start_time,
                "risk_tier": "irreversible",
                "trust": "untrusted",
                "payload_hash": preview["payload_hash"],
            }

        return [
            ToolSpec(
                name="zocdoc_search_providers",
                description="Searches available healthcare providers and open appointment slots on Zocdoc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "specialty": {"type": "string", "description": "Clinical specialty filter"},
                        "insurance_carrier": {"type": "string", "description": "Optional insurance carrier filter"},
                    },
                },
                risk_class="read_only",
                risk_tier="read",
                trust="untrusted",
                data_flows=("api.zocdoc.com",),
                handler=_search_providers_handler,
            ),
            ToolSpec(
                name="zocdoc_book_appointment",
                description="Books a confirmed healthcare appointment on Zocdoc (irreversible action).",
                parameters={
                    "type": "object",
                    "properties": {
                        "provider_id": {"type": "string"},
                        "provider_name": {"type": "string"},
                        "specialty": {"type": "string"},
                        "slot_id": {"type": "string"},
                        "start_time": {"type": "string"},
                        "insurance_carrier": {"type": "string"},
                    },
                    "required": ["provider_id", "provider_name", "slot_id", "start_time"],
                },
                risk_class="admin",
                risk_tier="irreversible",
                trust="untrusted",
                data_flows=("api.zocdoc.com",),
                handler=_book_appointment_handler,
            ),
        ]


__all__ = [
    "ZOCDOC_BOOKINGS_URL",
    "ZOCDOC_PROVIDERS_URL",
    "ZocdocConnector",
    "prepare_zocdoc_booking_payload",
]
