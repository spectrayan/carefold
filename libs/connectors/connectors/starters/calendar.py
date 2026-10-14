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

"""Google Calendar and CalDAV starter connectors (AU-55 / E5.2)."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
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

_GOOGLE_MANIFEST_PATH = Path(__file__).resolve().parent / "manifests" / "google_calendar.yaml"
_CALDAV_MANIFEST_PATH = Path(__file__).resolve().parent / "manifests" / "caldav.yaml"

GOOGLE_CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
CALDAV_DEFAULT_EVENTS_URL = "https://caldav.icloud.com/calendars/user/default"

_SAFE_GENERIC_TITLES = frozenset({
    "medical appointment",
    "clinic visit",
    "doctor appointment",
    "healthcare visit",
    "provider appointment",
})


def _parse_iso_dt(value: Union[str, datetime]) -> datetime:
    """Parses an ISO-8601 timestamp or datetime into a timezone-aware UTC datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    clean = str(value).strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    dt = datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sanitize_calendar_event_title(title: str, strip_phi: bool = True) -> str:
    """Strips clinical diagnoses, medications, and sensitive PHI from calendar event titles.

    By default (`strip_phi=True`), external calendar titles are replaced with a neutral
    `"Medical Appointment"` label unless the provided title is already an approved generic
    placeholder, preventing accidental disclosure of diagnoses or medications to third-party
    calendar providers.
    """
    cleaned = " ".join(str(title or "").split()).strip()
    if not cleaned:
        return "Medical Appointment"
    if not strip_phi:
        return cleaned
    if cleaned.lower() in _SAFE_GENERIC_TITLES:
        return cleaned
    return "Medical Appointment"


def suggest_free_slots(
    busy_windows: Sequence[Any],
    window_start: Union[str, datetime],
    window_end: Union[str, datetime],
    duration_minutes: int = 30,
) -> List[Dict[str, Any]]:
    """Computes deterministic conflict-free appointment slots during clinic hours (09:00-17:00).

    Args:
        busy_windows: Sequence of busy intervals as `{"start": ..., "end": ...}` dicts,
            `(start, end)` tuples, or `NormalisedRecord` instances.
        window_start: Start of search window (ISO-8601 string or `datetime`).
        window_end: End of search window (ISO-8601 string or `datetime`).
        duration_minutes: Desired appointment slot duration in minutes (default 30).

    Returns:
        List of conflict-free slot dictionaries within 09:00-17:00 clinic hours.
    """
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive.")

    start_dt = _parse_iso_dt(window_start)
    end_dt = _parse_iso_dt(window_end)
    if end_dt <= start_dt:
        return []

    parsed_busy: List[Tuple[datetime, datetime]] = []
    for item in busy_windows:
        raw_start: Any = None
        raw_end: Any = None
        if isinstance(item, NormalisedRecord):
            raw_start = item.data.get("start")
            raw_end = item.data.get("end")
        elif isinstance(item, dict):
            raw_start = item.get("start")
            raw_end = item.get("end")
            if isinstance(raw_start, dict):
                raw_start = raw_start.get("dateTime") or raw_start.get("date")
            if isinstance(raw_end, dict):
                raw_end = raw_end.get("dateTime") or raw_end.get("date")
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            raw_start, raw_end = item[0], item[1]

        if raw_start and raw_end:
            b_start = _parse_iso_dt(raw_start)
            b_end = _parse_iso_dt(raw_end)
            if b_end > b_start:
                parsed_busy.append((b_start, b_end))

    parsed_busy.sort(key=lambda pair: pair[0])
    slot_delta = timedelta(minutes=duration_minutes)
    suggestions: List[Dict[str, Any]] = []

    current_date = start_dt.date()
    end_date = end_dt.date()

    while current_date <= end_date:
        clinic_open = datetime.combine(current_date, time(9, 0), tzinfo=timezone.utc)
        clinic_close = datetime.combine(current_date, time(17, 0), tzinfo=timezone.utc)

        day_start = max(start_dt, clinic_open)
        day_end = min(end_dt, clinic_close)

        cursor = day_start
        while cursor + slot_delta <= day_end:
            candidate_end = cursor + slot_delta
            conflict = False
            for b_start, b_end in parsed_busy:
                if cursor < b_end and candidate_end > b_start:
                    conflict = True
                    # Advance cursor to end of conflicting busy block
                    if b_end > cursor:
                        cursor = b_end
                    break
            if not conflict:
                suggestions.append(
                    {
                        "start": cursor.isoformat(),
                        "end": candidate_end.isoformat(),
                        "duration_minutes": duration_minutes,
                        "status": "suggested",
                        "summary": "Suggested times that fit my calendar. Nothing booked",
                    }
                )
                cursor = candidate_end
        current_date += timedelta(days=1)

    return suggestions


def _extract_event_start_end(raw_event: Dict[str, Any]) -> Tuple[str, str]:
    """Extracts start and end ISO strings from a Google Calendar or CalDAV event dictionary."""
    raw_start = raw_event.get("start")
    raw_end = raw_event.get("end")
    if isinstance(raw_start, dict):
        raw_start = raw_start.get("dateTime") or raw_start.get("date")
    if isinstance(raw_end, dict):
        raw_end = raw_end.get("dateTime") or raw_end.get("date")

    start_iso = (
        _parse_iso_dt(raw_start).isoformat()
        if raw_start
        else datetime.now(timezone.utc).isoformat()
    )
    end_iso = (
        _parse_iso_dt(raw_end).isoformat()
        if raw_end
        else (_parse_iso_dt(start_iso) + timedelta(minutes=30)).isoformat()
    )
    return start_iso, end_iso


class _BaseCalendarConnector:
    """Shared calendar connector implementation for Google Calendar and CalDAV."""

    def __init__(self, manifest: ConnectorManifest, default_events_url: str) -> None:
        self._manifest = manifest
        self._default_events_url = default_events_url
        self._cached_Busy: List[NormalisedRecord] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def streams(self) -> List[StreamSpec]:
        return [
            StreamSpec(
                name="events",
                description="Calendar events and busy windows",
                read_mode="incremental",
                primary_key=["id"],
                cursor_field="updatedMin",
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
            raise ValueError(f"Unsupported stream '{stream}' for {self._manifest.id}.")

        url = self._default_events_url
        if cursor:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}updatedMin={cursor}"

        response = await http.get(url)
        payload = response.json() if hasattr(response, "json") else {}
        items = (
            payload.get("items")
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
            copy_item.setdefault("id", f"evt-{idx}")
            copy_item.setdefault("profile_id", ctx.profile_id)
            enriched.append(copy_item)

        next_token = (
            payload.get("nextSyncToken") or payload.get("nextPageToken")
            if isinstance(payload, dict)
            else None
        )
        return Page(
            stream=stream,
            records=enriched,
            next_cursor=str(next_token) if next_token else None,
            has_more=bool(payload.get("nextPageToken")) if isinstance(payload, dict) else False,
            metadata={"profile_id": ctx.profile_id, "user_id": ctx.user_id},
        )

    def map(self, page: Page) -> List[NormalisedRecord]:
        normalised: List[NormalisedRecord] = []
        default_profile_id = str(page.metadata.get("profile_id") or "default-profile")

        for idx, raw in enumerate(page.records):
            if not isinstance(raw, dict):
                continue
            rec_id = str(raw.get("id") or f"slot-{idx}")
            profile_id = str(raw.get("profile_id") or default_profile_id)
            start_iso, end_iso = _extract_event_start_end(raw)
            start_dt = _parse_iso_dt(start_iso)

            slot_data = {
                "id": rec_id,
                "start": start_iso,
                "end": end_iso,
                "busy": raw.get("transparency", "opaque") != "transparent",
                "status": raw.get("status", "confirmed"),
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

        self._cached_Busy = list(normalised)
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
                busy_input = self._cached_Busy
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
                "external_ref": f"calendar_event:{event_id}",
                "title": sanitized_title,
                "start": params.get("start"),
                "end": params.get("end"),
                "connector_id": self._manifest.id,
            }

        return [
            ToolSpec(
                name="calendar_suggest_slots",
                description="Suggests conflict-free appointment slots during clinic hours (09:00-17:00).",
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
                name="calendar_create_event",
                description="Creates a sanitized external calendar event for a confirmed appointment.",
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


class GoogleCalendarConnector(_BaseCalendarConnector):
    """Google Calendar OAuth2 starter connector (AU-55)."""

    def __init__(self, manifest: Optional[ConnectorManifest] = None) -> None:
        super().__init__(
            manifest=manifest or ConnectorManifest.from_yaml(_GOOGLE_MANIFEST_PATH),
            default_events_url=GOOGLE_CALENDAR_EVENTS_URL,
        )


class CalDavConnector(_BaseCalendarConnector):
    """Standards-based CalDAV starter connector (AU-55)."""

    def __init__(
        self,
        manifest: Optional[ConnectorManifest] = None,
        events_url: str = CALDAV_DEFAULT_EVENTS_URL,
    ) -> None:
        super().__init__(
            manifest=manifest or ConnectorManifest.from_yaml(_CALDAV_MANIFEST_PATH),
            default_events_url=events_url,
        )


__all__ = [
    "CALDAV_DEFAULT_EVENTS_URL",
    "CalDavConnector",
    "GOOGLE_CALENDAR_EVENTS_URL",
    "GoogleCalendarConnector",
    "sanitize_calendar_event_title",
    "suggest_free_slots",
]
