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

"""Oura Ring, Google Health, and Microsoft Graph Calendar v2 connectors (AU-74 / E5.1, E5.2)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

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
from connectors.starters.calendar import (
    _extract_event_start_end,
    _parse_iso_dt,
    sanitize_calendar_event_title,
    suggest_free_slots,
)

_MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"
_OURA_MANIFEST_PATH = _MANIFESTS_DIR / "oura.yaml"
_GOOGLE_HEALTH_MANIFEST_PATH = _MANIFESTS_DIR / "google_health.yaml"
_MSGRAPH_MANIFEST_PATH = _MANIFESTS_DIR / "microsoft_graph.yaml"

OURA_DAILY_SUMMARY_URL = "https://api.ouraring.com/v2/usercollection/daily_sleep"
GOOGLE_HEALTH_DAILY_URL = "https://health.googleapis.com/v1/daily_metrics"
MSGRAPH_CALENDAR_VIEW_URL = "https://graph.microsoft.com/v1.0/me/calendarView"


def _resolve_day_timestamp(raw: Dict[str, Any]) -> Tuple[datetime, str, str]:
    """Resolves a daily summary record's `day` or `date` into `(utc_dt, iso_str, day_str)`."""
    day_val = str(raw.get("day") or raw.get("date") or raw.get("timestamp") or "").strip()
    if day_val:
        day_part = day_val[:10] if len(day_val) >= 10 else day_val
        iso_candidate = f"{day_part}T08:00:00+00:00" if "T" not in day_val else day_val
        try:
            dt = datetime.fromisoformat(iso_candidate.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, dt.isoformat(), day_part
        except ValueError:
            pass
    now = datetime.now(timezone.utc)
    return now, now.isoformat(), now.strftime("%Y-%m-%d")


def _build_validated_fhir_observation(
    obs_id: str,
    source_id: str,
    source_display: str,
    loinc_code: str,
    display_name: str,
    eff_iso: str,
    value: float,
    unit_label: str,
    ucum_code: str,
    components: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Builds and validates a FHIR R4 `Observation` via `fhir.resources.R4B.observation.Observation`."""
    candidate: Dict[str, Any] = {
        "resourceType": "Observation",
        "id": obs_id,
        "meta": {
            "source": source_id,
            "tag": [
                {
                    "system": "https://carefold.ai/trust",
                    "code": "trusted",
                    "display": source_display,
                }
            ],
        },
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                        "display": "Vital Signs",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": loinc_code,
                    "display": display_name,
                }
            ],
            "text": display_name,
        },
        "effectiveDateTime": eff_iso,
        "valueQuantity": {
            "value": round(float(value), 4),
            "unit": unit_label,
            "system": "http://unitsofmeasure.org",
            "code": ucum_code,
        },
    }
    if components:
        candidate["component"] = components

    validated = FhirObservation.model_validate(candidate).model_dump(mode="json", exclude_none=True)
    raw_hash = hashlib.sha256(json.dumps(validated, sort_keys=True).encode("utf-8")).hexdigest()
    return validated, raw_hash


class OuraConnector:
    """Oura Ring v2 connector mapping daily sleep, readiness, RHR (8867-4), and HRV (80404-7) into FHIR R4 Observations (AU-74)."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        summary_url: str = OURA_DAILY_SUMMARY_URL,
    ) -> None:
        self._manifest = manifest or ConnectorManifest.from_yaml(_OURA_MANIFEST_PATH)
        self._summary_url = summary_url
        self._latest_records: List[NormalisedRecord] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return [
            StreamSpec(
                name="daily_summaries",
                description="Daily aggregated Oura sleep, readiness, resting heart rate, and HRV metrics",
                read_mode="incremental",
                primary_key=["day"],
                cursor_field="start_date",
            )
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
        if stream != "daily_summaries":
            raise ValueError(f"Unsupported stream '{stream}' for OuraConnector.")

        url = self._summary_url
        if cursor:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}start_date={cursor}"

        response = await http.get(url)
        payload = response.json() if hasattr(response, "json") else {}
        items = (
            payload.get("data")
            if isinstance(payload, dict) and isinstance(payload.get("data"), list)
            else payload.get("records")
            if isinstance(payload, dict) and isinstance(payload.get("records"), list)
            else []
        )

        enriched: List[Dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict):
                copy_item = dict(item)
                copy_item.setdefault("profile_id", ctx.profile_id)
                enriched.append(copy_item)

        next_token = payload.get("next_token") if isinstance(payload, dict) else None
        return Page(
            stream=stream,
            records=enriched,
            next_cursor=str(next_token) if next_token else None,
            has_more=bool(next_token),
            metadata={"profile_id": ctx.profile_id, "user_id": ctx.user_id},
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        normalised: List[NormalisedRecord] = []
        default_profile_id = str(page.metadata.get("profile_id") or "default-profile")

        for idx, raw in enumerate(page.records):
            if not isinstance(raw, dict):
                continue
            profile_id = str(raw.get("profile_id") or default_profile_id)
            eff_dt, eff_iso, day_str = _resolve_day_timestamp(raw)
            rec_key = str(raw.get("id") or day_str or f"day-{idx}")
            source_display = f"From Oura Ring, {day_str}"

            # 1. Resting Heart Rate (LOINC 8867-4)
            rhr = raw.get("resting_heart_rate") or raw.get("lowest_heart_rate")
            if rhr is not None:
                obs_id = f"oura-{rec_key}-rhr"
                obs_data, raw_hash = _build_validated_fhir_observation(
                    obs_id=obs_id,
                    source_id="oura",
                    source_display=source_display,
                    loinc_code="8867-4",
                    display_name="Heart rate",
                    eff_iso=eff_iso,
                    value=float(rhr),
                    unit_label="beats/minute",
                    ucum_code="/min",
                )
                normalised.append(
                    NormalisedRecord(
                        id=obs_id,
                        stream=page.stream,
                        profile_id=profile_id,
                        source=self._manifest.id,
                        record_type="Observation",
                        timestamp=eff_dt,
                        data=obs_data,
                        raw_hash=raw_hash,
                    )
                )

            # 2. Heart Rate Variability (LOINC 80404-7)
            hrv = raw.get("hrv_ms") or raw.get("average_hrv") or raw.get("hrv")
            if hrv is not None:
                obs_id = f"oura-{rec_key}-hrv"
                obs_data, raw_hash = _build_validated_fhir_observation(
                    obs_id=obs_id,
                    source_id="oura",
                    source_display=source_display,
                    loinc_code="80404-7",
                    display_name="R-R interval.standard deviation (Heart rate variability)",
                    eff_iso=eff_iso,
                    value=float(hrv),
                    unit_label="ms",
                    ucum_code="ms",
                )
                normalised.append(
                    NormalisedRecord(
                        id=obs_id,
                        stream=page.stream,
                        profile_id=profile_id,
                        source=self._manifest.id,
                        record_type="Observation",
                        timestamp=eff_dt,
                        data=obs_data,
                        raw_hash=raw_hash,
                    )
                )

            # 3. Daily Sleep Duration / Score (LOINC 93832-4)
            sleep_hours = raw.get("sleep_duration_hours")
            if sleep_hours is None and raw.get("total_sleep_duration") is not None:
                sleep_hours = round(float(raw["total_sleep_duration"]) / 3600.0, 2)
            sleep_score = raw.get("sleep_score") or raw.get("score")
            if sleep_hours is not None or sleep_score is not None:
                val = float(sleep_hours) if sleep_hours is not None else float(sleep_score)
                unit_lbl = "h" if sleep_hours is not None else "{score}"
                sleep_components: List[Dict[str, Any]] = []
                if sleep_score is not None:
                    sleep_components.append(
                        {
                            "code": {"text": "Sleep score"},
                            "valueQuantity": {
                                "value": float(sleep_score),
                                "unit": "{score}",
                                "system": "http://unitsofmeasure.org",
                                "code": "{score}",
                            },
                        }
                    )
                if raw.get("readiness_score") is not None:
                    sleep_components.append(
                        {
                            "code": {"text": "Readiness score"},
                            "valueQuantity": {
                                "value": float(raw["readiness_score"]),
                                "unit": "{score}",
                                "system": "http://unitsofmeasure.org",
                                "code": "{score}",
                            },
                        }
                    )
                obs_id = f"oura-{rec_key}-sleep"
                obs_data, raw_hash = _build_validated_fhir_observation(
                    obs_id=obs_id,
                    source_id="oura",
                    source_display=source_display,
                    loinc_code="93832-4",
                    display_name="Sleep duration",
                    eff_iso=eff_iso,
                    value=val,
                    unit_label=unit_lbl,
                    ucum_code=unit_lbl,
                    components=sleep_components or None,
                )
                normalised.append(
                    NormalisedRecord(
                        id=obs_id,
                        stream=page.stream,
                        profile_id=profile_id,
                        source=self._manifest.id,
                        record_type="Observation",
                        timestamp=eff_dt,
                        data=obs_data,
                        raw_hash=raw_hash,
                    )
                )

        self._latest_records = list(normalised)
        return normalised

    def tools(self) -> List[ToolSpec]:
        async def _latest_metrics_handler(
            ctx: ToolContext,
            args: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            if not ctx.profile_id or not ctx.user_id:
                raise ValueError("ToolContext user_id and profile_id are required.")
            params = args or {}
            limit = int(params.get("limit", 10))
            records = [
                r.data
                for r in self._latest_records
                if r.profile_id in (ctx.profile_id, "default-profile")
            ]
            return {
                "connector_id": self._manifest.id,
                "profile_id": ctx.profile_id,
                "trust": "trusted",
                "count": len(records[:limit]),
                "observations": records[:limit],
            }

        return [
            ToolSpec(
                name="oura_latest_metrics",
                description="Retrieves the most recent normalized daily Oura Ring sleep, readiness, RHR, and HRV observations.",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10},
                    },
                },
                risk_class="read_only",
                risk_tier="read",
                trust="trusted",
                data_flows=("api.ouraring.com",),
                handler=_latest_metrics_handler,
            )
        ]


class GoogleHealthConnector:
    """Google Health / Fit connector mapping daily step totals (41950-7), HR min/max/avg (8867-4), and weight (29463-7) into FHIR R4 Observations (AU-74)."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        daily_url: str = GOOGLE_HEALTH_DAILY_URL,
    ) -> None:
        self._manifest = manifest or ConnectorManifest.from_yaml(_GOOGLE_HEALTH_MANIFEST_PATH)
        self._daily_url = daily_url
        self._latest_records: List[NormalisedRecord] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return [
            StreamSpec(
                name="daily_metrics",
                description="Daily aggregated step counts, heart rate min/max/avg, and weight",
                read_mode="incremental",
                primary_key=["day"],
                cursor_field="startTimeMillis",
            )
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
        if stream != "daily_metrics":
            raise ValueError(f"Unsupported stream '{stream}' for GoogleHealthConnector.")

        url = self._daily_url
        if cursor:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}startTimeMillis={cursor}"

        response = await http.get(url)
        payload = response.json() if hasattr(response, "json") else {}
        items = (
            payload.get("bucket")
            if isinstance(payload, dict) and isinstance(payload.get("bucket"), list)
            else payload.get("records")
            if isinstance(payload, dict) and isinstance(payload.get("records"), list)
            else payload.get("data")
            if isinstance(payload, dict) and isinstance(payload.get("data"), list)
            else []
        )

        enriched: List[Dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict):
                copy_item = dict(item)
                copy_item.setdefault("profile_id", ctx.profile_id)
                enriched.append(copy_item)

        next_cursor = str(payload["next_cursor"]) if isinstance(payload, dict) and payload.get("next_cursor") else None
        return Page(
            stream=stream,
            records=enriched,
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
            eff_dt, eff_iso, day_str = _resolve_day_timestamp(raw)
            rec_key = str(raw.get("id") or day_str or f"day-{idx}")
            source_display = f"From Google Health, {day_str}"

            # 1. Daily Step Totals (LOINC 41950-7)
            steps = raw.get("steps")
            if steps is not None:
                obs_id = f"ghealth-{rec_key}-steps"
                obs_data, raw_hash = _build_validated_fhir_observation(
                    obs_id=obs_id,
                    source_id="google-health",
                    source_display=source_display,
                    loinc_code="41950-7",
                    display_name="Number of steps in 24 hour Measured",
                    eff_iso=eff_iso,
                    value=float(steps),
                    unit_label="steps/day",
                    ucum_code="/d",
                )
                normalised.append(
                    NormalisedRecord(
                        id=obs_id,
                        stream=page.stream,
                        profile_id=profile_id,
                        source=self._manifest.id,
                        record_type="Observation",
                        timestamp=eff_dt,
                        data=obs_data,
                        raw_hash=raw_hash,
                    )
                )

            # 2. Daily Heart Rate Min / Max / Avg (LOINC 8867-4)
            hr_avg = raw.get("heart_rate_avg") or raw.get("heart_rate")
            hr_min = raw.get("heart_rate_min")
            hr_max = raw.get("heart_rate_max")
            if hr_avg is not None or hr_min is not None or hr_max is not None:
                primary_hr = float(hr_avg if hr_avg is not None else (hr_min if hr_min is not None else hr_max))
                components: List[Dict[str, Any]] = []
                if hr_min is not None:
                    components.append(
                        {
                            "code": {"text": "Minimum heart rate"},
                            "valueQuantity": {
                                "value": float(hr_min),
                                "unit": "beats/minute",
                                "system": "http://unitsofmeasure.org",
                                "code": "/min",
                            },
                        }
                    )
                if hr_max is not None:
                    components.append(
                        {
                            "code": {"text": "Maximum heart rate"},
                            "valueQuantity": {
                                "value": float(hr_max),
                                "unit": "beats/minute",
                                "system": "http://unitsofmeasure.org",
                                "code": "/min",
                            },
                        }
                    )
                obs_id = f"ghealth-{rec_key}-hr"
                obs_data, raw_hash = _build_validated_fhir_observation(
                    obs_id=obs_id,
                    source_id="google-health",
                    source_display=source_display,
                    loinc_code="8867-4",
                    display_name="Heart rate",
                    eff_iso=eff_iso,
                    value=primary_hr,
                    unit_label="beats/minute",
                    ucum_code="/min",
                    components=components or None,
                )
                normalised.append(
                    NormalisedRecord(
                        id=obs_id,
                        stream=page.stream,
                        profile_id=profile_id,
                        source=self._manifest.id,
                        record_type="Observation",
                        timestamp=eff_dt,
                        data=obs_data,
                        raw_hash=raw_hash,
                    )
                )

            # 3. Body Weight (LOINC 29463-7)
            weight = raw.get("weight_kg") if raw.get("weight_kg") is not None else raw.get("weight")
            if weight is not None:
                obs_id = f"ghealth-{rec_key}-weight"
                obs_data, raw_hash = _build_validated_fhir_observation(
                    obs_id=obs_id,
                    source_id="google-health",
                    source_display=source_display,
                    loinc_code="29463-7",
                    display_name="Body weight",
                    eff_iso=eff_iso,
                    value=float(weight),
                    unit_label="kg",
                    ucum_code="kg",
                )
                normalised.append(
                    NormalisedRecord(
                        id=obs_id,
                        stream=page.stream,
                        profile_id=profile_id,
                        source=self._manifest.id,
                        record_type="Observation",
                        timestamp=eff_dt,
                        data=obs_data,
                        raw_hash=raw_hash,
                    )
                )

        self._latest_records = list(normalised)
        return normalised

    def tools(self) -> List[ToolSpec]:
        allowed_hosts = tuple(self._manifest.data_flows.allowed_hosts)

        async def _latest_metrics_handler(
            ctx: ToolContext,
            args: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            if not ctx.profile_id or not ctx.user_id:
                raise ValueError("ToolContext user_id and profile_id are required.")
            params = args or {}
            limit = int(params.get("limit", 10))
            records = [
                r.data
                for r in self._latest_records
                if r.profile_id in (ctx.profile_id, "default-profile")
            ]
            return {
                "connector_id": self._manifest.id,
                "profile_id": ctx.profile_id,
                "trust": "trusted",
                "count": len(records[:limit]),
                "observations": records[:limit],
            }

        return [
            ToolSpec(
                name="google_health_latest_metrics",
                description="Retrieves the most recent daily aggregated Google Health step, heart rate, and weight observations.",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10},
                    },
                },
                risk_class="read_only",
                risk_tier="read",
                trust="trusted",
                data_flows=allowed_hosts,
                handler=_latest_metrics_handler,
            )
        ]


class MicrosoftGraphCalendarConnector:
    """Microsoft 365 / Outlook Calendar connector via Microsoft Graph API (AU-74 / E5.2)."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        calendar_url: str = MSGRAPH_CALENDAR_VIEW_URL,
    ) -> None:
        self._manifest = manifest or ConnectorManifest.from_yaml(_MSGRAPH_MANIFEST_PATH)
        self._calendar_url = calendar_url
        self._cached_busy: List[NormalisedRecord] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return [
            StreamSpec(
                name="events",
                description="Outlook / Microsoft 365 calendar events and free/busy blocks",
                read_mode="incremental",
                primary_key=["id"],
                cursor_field="deltaToken",
            )
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
        if stream != "events":
            raise ValueError(f"Unsupported stream '{stream}' for MicrosoftGraphCalendarConnector.")

        url = self._calendar_url
        if cursor:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}$deltatoken={cursor}"

        response = await http.get(url)
        payload = response.json() if hasattr(response, "json") else {}
        items = (
            payload.get("value")
            if isinstance(payload, dict) and isinstance(payload.get("value"), list)
            else payload.get("items")
            if isinstance(payload, dict) and isinstance(payload.get("items"), list)
            else payload.get("records")
            if isinstance(payload, dict) and isinstance(payload.get("records"), list)
            else []
        )

        enriched: List[Dict[str, Any]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            copy_item = dict(item)
            copy_item.setdefault("id", f"msgraph-evt-{idx + 1}")
            copy_item.setdefault("profile_id", ctx.profile_id)
            enriched.append(copy_item)

        next_token = payload.get("@odata.nextLink") or payload.get("next_cursor") if isinstance(payload, dict) else None
        return Page(
            stream=stream,
            records=enriched,
            next_cursor=str(next_token) if next_token else None,
            has_more=bool(next_token),
            metadata={"profile_id": ctx.profile_id, "user_id": ctx.user_id},
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        normalised: List[NormalisedRecord] = []
        default_profile_id = str(page.metadata.get("profile_id") or "default-profile")

        for idx, raw in enumerate(page.records):
            if not isinstance(raw, dict):
                continue
            rec_id = str(raw.get("id") or f"msgraph-slot-{idx + 1}")
            profile_id = str(raw.get("profile_id") or default_profile_id)
            start_iso, end_iso = _extract_event_start_end(raw)
            start_dt = _parse_iso_dt(start_iso)
            show_as = str(raw.get("showAs") or "busy").strip().lower()

            slot_data = {
                "id": rec_id,
                "start": start_iso,
                "end": end_iso,
                "busy": show_as != "free",
                "status": "confirmed" if not raw.get("isCancelled") else "cancelled",
                "title": "Busy",
                "source": self._manifest.id,
            }
            raw_hash = hashlib.sha256(
                json.dumps(slot_data, sort_keys=True).encode("utf-8")
            ).hexdigest()

            normalised.append(
                NormalisedRecord(
                    id=rec_id,
                    stream=page.stream,
                    profile_id=profile_id,
                    source=self._manifest.id,
                    record_type="schedule_slot",
                    timestamp=start_dt,
                    data=slot_data,
                    raw_hash=raw_hash,
                )
            )

        self._cached_busy = list(normalised)
        return normalised

    def tools(self) -> List[ToolSpec]:
        allowed_hosts = tuple(self._manifest.data_flows.allowed_hosts)

        async def _suggest_slots_handler(
            ctx: ToolContext,
            args: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            if not ctx.profile_id or not ctx.user_id:
                raise ValueError("ToolContext user_id and profile_id are required.")
            params = args or {}
            busy_input = params.get("busy_windows")
            if busy_input is None:
                busy_input = self._cached_busy
            window_start = params.get("window_start") or "2026-10-14T09:00:00+00:00"
            window_end = params.get("window_end") or "2026-10-14T12:00:00+00:00"
            duration = int(params.get("duration_minutes", 30))

            slots = suggest_free_slots(
                busy_windows=busy_input,
                window_start=window_start,
                window_end=window_end,
                duration_minutes=duration,
            )
            return {
                "connector_id": self._manifest.id,
                "profile_id": ctx.profile_id,
                "note": "Suggested times that fit my calendar. Nothing booked",
                "slots": slots,
            }

        async def _create_event_handler(
            ctx: ToolContext,
            args: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            if not ctx.profile_id or not ctx.user_id:
                raise ValueError("ToolContext user_id and profile_id are required.")
            params = args or {}
            raw_title = str(params.get("title") or "Medical Appointment")
            strip_phi = bool(params.get("strip_phi", True))
            sanitized_title = sanitize_calendar_event_title(raw_title, strip_phi=strip_phi)
            event_id = str(params.get("event_id") or uuid.uuid4().hex[:12])
            return {
                "status": "created",
                "external_ref": f"msgraph_event:{event_id}",
                "title": sanitized_title,
                "start": params.get("start"),
                "end": params.get("end"),
                "connector_id": self._manifest.id,
            }

        return [
            ToolSpec(
                name="msgraph_suggest_slots",
                description="Suggests conflict-free appointment slots from Outlook / Microsoft 365 calendar during clinic hours.",
                parameters={
                    "type": "object",
                    "properties": {
                        "window_start": {"type": "string"},
                        "window_end": {"type": "string"},
                        "duration_minutes": {"type": "integer", "default": 30},
                    },
                },
                risk_class="read_only",
                risk_tier="read",
                trust="trusted",
                data_flows=allowed_hosts,
                handler=_suggest_slots_handler,
            ),
            ToolSpec(
                name="msgraph_create_event",
                description="Creates a sanitized Outlook / Microsoft 365 calendar event for a confirmed appointment.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "strip_phi": {"type": "boolean", "default": True},
                    },
                    "required": ["start", "end"],
                },
                risk_class="admin",
                risk_tier="write_external",
                trust="trusted",
                data_flows=allowed_hosts,
                handler=_create_event_handler,
            ),
        ]


__all__ = [
    "GOOGLE_HEALTH_DAILY_URL",
    "GoogleHealthConnector",
    "MSGRAPH_CALENDAR_VIEW_URL",
    "MicrosoftGraphCalendarConnector",
    "OURA_DAILY_SUMMARY_URL",
    "OuraConnector",
]
