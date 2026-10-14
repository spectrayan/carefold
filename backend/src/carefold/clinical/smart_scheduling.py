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

"""HL7 SMART Scheduling Links ($bulk-publish) slot discovery and calendar matching (AU-72 / E4.2)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fhir.resources.R4B.slot import Slot as FhirSlot


def _parse_iso_dt(value: Any) -> Optional[datetime]:
    """Parses an ISO-8601 timestamp string or datetime into a UTC-aware datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not value or not isinstance(value, str):
        return None
    clean = value.strip()
    if not clean:
        return None
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _extract_codeable_text(concepts: Any) -> Optional[str]:
    """Extracts a human-readable display string from a FHIR CodeableConcept or list of CodeableConcepts."""
    if isinstance(concepts, str) and concepts.strip():
        return concepts.strip()
    if isinstance(concepts, dict):
        concepts = [concepts]
    if isinstance(concepts, list):
        for item in concepts:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                if isinstance(item.get("text"), str) and item["text"].strip():
                    return item["text"].strip()
                for coding in item.get("coding") or []:
                    if isinstance(coding, dict):
                        disp = coding.get("display") or coding.get("code")
                        if isinstance(disp, str) and disp.strip():
                            return disp.strip()
    return None


def _extract_booking_url(raw_slot: Dict[str, Any], schedule_meta: Dict[str, Any]) -> Optional[str]:
    """Extracts a booking deep-link URL from a SMART Scheduling Links Slot or Schedule extension."""
    direct = raw_slot.get("booking_url") or schedule_meta.get("booking_url")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    for ext_source in (raw_slot.get("extension"), schedule_meta.get("extension")):
        if not isinstance(ext_source, list):
            continue
        for ext in ext_source:
            if not isinstance(ext, dict):
                continue
            url_key = str(ext.get("url") or "").lower()
            if "booking" in url_key or "deep-link" in url_key:
                val = ext.get("valueUrl") or ext.get("valueUri") or ext.get("valueString")
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return None


def _index_schedules_and_locations(manifest_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Indexes FHIR Schedule metadata from a SMART Scheduling Links payload."""
    schedule_map: Dict[str, Dict[str, Any]] = {}
    location_map: Dict[str, str] = {}

    raw_locations = manifest_payload.get("locations") or []
    if isinstance(raw_locations, list):
        for loc in raw_locations:
            if isinstance(loc, dict) and loc.get("id"):
                loc_id = str(loc["id"]).strip()
                loc_name = str(loc.get("name") or loc.get("address") or loc_id).strip()
                location_map[loc_id] = loc_name
                location_map[f"Location/{loc_id}"] = loc_name

    raw_schedules: List[Dict[str, Any]] = []
    if isinstance(manifest_payload.get("schedules"), list):
        raw_schedules.extend(s for s in manifest_payload["schedules"] if isinstance(s, dict))
    if isinstance(manifest_payload.get("entry"), list):
        for entry in manifest_payload["entry"]:
            res = entry.get("resource") if isinstance(entry, dict) else None
            if isinstance(res, dict):
                rtype = res.get("resourceType")
                if rtype == "Location" and res.get("id"):
                    loc_id = str(res["id"]).strip()
                    loc_name = str(res.get("name") or loc_id).strip()
                    location_map[loc_id] = loc_name
                    location_map[f"Location/{loc_id}"] = loc_name
                elif rtype == "Schedule":
                    raw_schedules.append(res)

    for sched in raw_schedules:
        sched_id = str(sched.get("id") or "").strip()
        if not sched_id:
            continue
        provider_name = str(sched.get("provider_name") or sched.get("name") or "").strip()
        location_name = str(sched.get("location") or "").strip()
        for actor in sched.get("actor") or []:
            if isinstance(actor, dict):
                ref = str(actor.get("reference") or "").strip()
                disp = str(actor.get("display") or "").strip()
                if ref in location_map and not location_name:
                    location_name = location_map[ref]
                if disp and not provider_name:
                    provider_name = disp
        specialty = (
            str(sched.get("specialty") or "").strip()
            if isinstance(sched.get("specialty"), str)
            else _extract_codeable_text(sched.get("specialty"))
            or _extract_codeable_text(sched.get("serviceType"))
            or "General"
        )
        meta = {
            "provider_name": provider_name or "SMART Scheduling Provider",
            "specialty": specialty or "General",
            "location": location_name or "Outpatient Clinic",
            "booking_url": sched.get("booking_url"),
            "extension": sched.get("extension"),
        }
        schedule_map[sched_id] = meta
        schedule_map[f"Schedule/{sched_id}"] = meta

    return schedule_map


def _collect_raw_slots(manifest_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extracts raw Slot dictionaries from `$bulk-publish` manifest payloads, Bundles, or NDJSON lines."""
    slots: List[Dict[str, Any]] = []

    if isinstance(manifest_payload.get("slots"), list):
        for item in manifest_payload["slots"]:
            if isinstance(item, dict):
                slots.append(item)
            elif isinstance(item, str) and item.strip():
                try:
                    parsed = json.loads(item)
                    if isinstance(parsed, dict):
                        slots.append(parsed)
                except ValueError:
                    continue

    if isinstance(manifest_payload.get("entry"), list):
        for entry in manifest_payload["entry"]:
            res = entry.get("resource") if isinstance(entry, dict) else None
            if isinstance(res, dict) and res.get("resourceType") == "Slot":
                slots.append(res)

    if isinstance(manifest_payload.get("output"), list):
        for out_item in manifest_payload["output"]:
            if not isinstance(out_item, dict):
                continue
            if out_item.get("type") == "Slot":
                if isinstance(out_item.get("records"), list):
                    slots.extend(r for r in out_item["records"] if isinstance(r, dict))
                elif isinstance(out_item.get("ndjson"), str):
                    for line in out_item["ndjson"].splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                            if isinstance(parsed, dict):
                                slots.append(parsed)
                        except ValueError:
                            continue

    if manifest_payload.get("resourceType") == "Slot":
        slots.append(manifest_payload)

    return slots


def _parse_busy_intervals(
    busy_windows: Optional[Sequence[Dict[str, Any]]],
) -> List[Tuple[datetime, datetime]]:
    """Parses busy calendar intervals into UTC `(start_dt, end_dt)` pairs."""
    intervals: List[Tuple[datetime, datetime]] = []
    if not busy_windows:
        return intervals

    for win in busy_windows:
        if not isinstance(win, dict):
            continue
        raw_start = win.get("start") or win.get("start_time")
        raw_end = win.get("end") or win.get("end_time")
        if isinstance(raw_start, dict):
            raw_start = raw_start.get("dateTime") or raw_start.get("date")
        if isinstance(raw_end, dict):
            raw_end = raw_end.get("dateTime") or raw_end.get("date")
        b_start = _parse_iso_dt(raw_start)
        b_end = _parse_iso_dt(raw_end)
        if b_start and b_end and b_end > b_start:
            intervals.append((b_start, b_end))
    return intervals


def discover_smart_scheduling_slots(
    manifest_payload: Dict[str, Any],
    specialty_filter: Optional[str] = None,
    busy_windows: Optional[Sequence[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Discovers open appointment slots from HL7 SMART Scheduling Links `$bulk-publish` payloads (`AU-72`).

    - Validates each candidate `Slot` resource via `fhir.resources.R4B.slot.Slot`.
    - Retains only slots with `status == "free"` (filtering out `"busy"`, `"busy-unavailable"`, etc.).
    - Filters by `specialty_filter` when provided.
    - Cross-references each free slot against `busy_windows` to compute `fits_calendar: bool`.
    """
    if not isinstance(manifest_payload, dict):
        raise ValueError("manifest_payload must be a dictionary.")

    schedule_map = _index_schedules_and_locations(manifest_payload)
    raw_slots = _collect_raw_slots(manifest_payload)
    busy_intervals = _parse_busy_intervals(busy_windows)
    target_specialty = (specialty_filter or "").strip().lower()

    results: List[Dict[str, Any]] = []

    for idx, raw_slot in enumerate(raw_slots):
        slot_id = str(raw_slot.get("id") or raw_slot.get("slot_id") or f"smart-slot-{idx + 1}").strip()
        raw_status = str(raw_slot.get("status") or "free").strip().lower()
        raw_start = str(raw_slot.get("start") or raw_slot.get("start_time") or "").strip()
        raw_end = str(raw_slot.get("end") or raw_slot.get("end_time") or "").strip()
        if not raw_start or not raw_end:
            continue

        sched_ref_field = raw_slot.get("schedule")
        if isinstance(sched_ref_field, dict):
            sched_ref = str(sched_ref_field.get("reference") or "Schedule/default").strip()
        elif isinstance(sched_ref_field, str) and sched_ref_field.strip():
            sched_ref = sched_ref_field.strip()
            if not sched_ref.startswith("Schedule/"):
                sched_ref = f"Schedule/{sched_ref}"
        else:
            sched_ref = "Schedule/default"

        fhir_candidate: Dict[str, Any] = {
            "resourceType": "Slot",
            "id": slot_id,
            "schedule": {"reference": sched_ref},
            "status": raw_status,
            "start": raw_start,
            "end": raw_end,
        }
        validated_slot = FhirSlot.model_validate(fhir_candidate)
        if validated_slot.status != "free":
            continue

        sched_meta = schedule_map.get(sched_ref) or schedule_map.get(sched_ref.split("/", 1)[-1]) or {}

        provider_name = (
            str(raw_slot.get("provider_name") or "").strip()
            or str(sched_meta.get("provider_name") or "").strip()
            or "SMART Scheduling Provider"
        )
        specialty = (
            str(raw_slot.get("specialty") or "").strip()
            if isinstance(raw_slot.get("specialty"), str)
            else _extract_codeable_text(raw_slot.get("specialty"))
            or _extract_codeable_text(raw_slot.get("serviceType"))
            or str(sched_meta.get("specialty") or "").strip()
            or "General"
        )
        location = (
            str(raw_slot.get("location") or "").strip()
            or str(sched_meta.get("location") or "").strip()
            or "Outpatient Clinic"
        )
        booking_url = _extract_booking_url(raw_slot, sched_meta)

        if target_specialty and target_specialty not in specialty.lower():
            continue

        slot_start_dt = _parse_iso_dt(raw_start)
        slot_end_dt = _parse_iso_dt(raw_end)
        if slot_start_dt is None or slot_end_dt is None or slot_end_dt <= slot_start_dt:
            continue

        fits_calendar = True
        for b_start, b_end in busy_intervals:
            if slot_start_dt < b_end and slot_end_dt > b_start:
                fits_calendar = False
                break

        results.append(
            {
                "slot_id": slot_id,
                "provider_name": provider_name,
                "specialty": specialty,
                "location": location,
                "start_time": slot_start_dt.isoformat(),
                "end_time": slot_end_dt.isoformat(),
                "status": "free",
                "fits_calendar": fits_calendar,
                "booking_url": booking_url,
                "source": "smart_scheduling_links",
                "trust": "untrusted",
                "fhir_slot": validated_slot.model_dump(mode="json", exclude_none=True),
            }
        )

    results.sort(key=lambda item: item["start_time"])
    return results


__all__ = [
    "discover_smart_scheduling_slots",
]
