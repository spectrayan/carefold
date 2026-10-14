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

"""Per-Child Read-Only School Calendar ICS Feed Subscription & Sync Service (AU-61 / E4.4).

Implements:
- `normalize_and_validate_ics_feed_url`: enforces `https://` or `webcal://` (normalized to
  `https://`) and blocks `file://` or private/loopback IP literals (`127.0.0.1`, `10.x`,
  `192.168.x`, `169.254.x`, `::1`).
- `create_school_ics_feed`: persists a `SchoolIcsFeed` subscription row (`status="active"`).
- `sync_school_ics_feed`: parses RFC 5545 `.ics` `VEVENT` components (`UID`, `SUMMARY`,
  `DTSTART`, `DTEND`, `LOCATION`, `DESCRIPTION`) and idempotently upserts `Appointment`
  rows (`specialty="School Calendar"`, `provider_name=feed.label`, `status="confirmed"`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import logging
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse
import uuid
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import (
    Appointment,
    AuditEventRecord,
    SchoolIcsFeed,
    utc_now,
)

logger = logging.getLogger("carefold.clinical.school_ics")


class _IcsDtProp:
    """Wrapper matching `icalendar` vDDDTypes `.dt` attribute semantics."""

    def __init__(self, dt_val: Union[datetime, date]) -> None:
        self.dt = dt_val

    def __str__(self) -> str:
        return self.dt.isoformat()


class _IcsComponent(dict):
    """RFC 5545 component representation compatible with `icalendar.Component`."""

    def __init__(self, name: str, properties: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(properties or {})
        self.name = name.upper()
        self.subcomponents: List[_IcsComponent] = []

    def walk(self, name: Optional[str] = None) -> List[_IcsComponent]:
        target = name.upper() if name else None
        results: List[_IcsComponent] = []
        if target is None or self.name == target:
            results.append(self)
        for sub in self.subcomponents:
            results.extend(sub.walk(target))
        return results


def _unfold_ics_lines(raw_ics: str) -> List[str]:
    """Unfolds RFC 5545 folded lines (CRLF/LF followed by space or tab)."""
    normalized = raw_ics.replace("\r\n", "\n").replace("\r", "\n")
    unfolded: List[str] = []
    for line in normalized.split("\n"):
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _unescape_ics_text(val: str) -> str:
    """Unescapes RFC 5545 text escapes (`\\n`, `\\,`, `\\;`, `\\\\`)."""
    return (
        val.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _parse_ics_datetime_token(raw_val: str, params: Dict[str, str]) -> datetime:
    """Parses an RFC 5545 DTSTART/DTEND value into a timezone-aware UTC datetime."""
    clean = raw_val.strip()
    tzid = params.get("TZID")
    tz = ZoneInfo("UTC")
    if tzid:
        try:
            tz = ZoneInfo(tzid)
        except Exception:
            tz = ZoneInfo("UTC")

    if clean.endswith("Z"):
        core = clean[:-1]
        if "T" in core:
            dt = datetime.strptime(core[:15], "%Y%m%dT%H%M%S")
            return dt.replace(tzinfo=timezone.utc)
        dt = datetime.strptime(core[:8], "%Y%m%d")
        return dt.replace(hour=9, minute=0, tzinfo=timezone.utc)

    if "T" in clean:
        try:
            dt = datetime.strptime(clean[:15], "%Y%m%dT%H%M%S")
            return dt.replace(tzinfo=tz).astimezone(timezone.utc)
        except ValueError:
            pass

    if len(clean) == 8 and clean.isdigit():
        dt = datetime.strptime(clean, "%Y%m%d")
        return dt.replace(hour=9, minute=0, tzinfo=tz).astimezone(timezone.utc)

    # Fallback ISO-8601 parsing
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    dt = datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


class _FallbackCalendar:
    """Pure-Python RFC 5545 Calendar parser matching `icalendar.Calendar.from_ical`."""

    @staticmethod
    def from_ical(raw_ics: Union[str, bytes]) -> _IcsComponent:
        text = raw_ics.decode("utf-8", errors="replace") if isinstance(raw_ics, bytes) else str(raw_ics)
        if "BEGIN:VCALENDAR" not in text.upper():
            raise ValueError("Invalid ICS content: missing BEGIN:VCALENDAR header.")

        lines = _unfold_ics_lines(text)
        root = _IcsComponent("VCALENDAR")
        stack: List[_IcsComponent] = [root]

        for line in lines:
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue
            left, val = stripped.split(":", 1)
            upper_left = left.strip().upper()
            upper_val = val.strip().upper()

            if upper_left == "BEGIN":
                if upper_val == "VCALENDAR" and len(stack) == 1:
                    continue
                comp = _IcsComponent(upper_val)
                stack[-1].subcomponents.append(comp)
                stack.append(comp)
                continue

            if upper_left == "END":
                if len(stack) > 1 and stack[-1].name == upper_val:
                    stack.pop()
                continue

            parts = left.split(";")
            prop_name = parts[0].strip().upper()
            params: Dict[str, str] = {}
            for p in parts[1:]:
                if "=" in p:
                    pk, pv = p.split("=", 1)
                    params[pk.strip().upper()] = pv.strip().strip('"')

            current = stack[-1]
            if prop_name in ("DTSTART", "DTEND"):
                dt_val = _parse_ics_datetime_token(val, params)
                current[prop_name] = _IcsDtProp(dt_val)
            else:
                current[prop_name] = _unescape_ics_text(val)

        return root


try:
    from icalendar import Calendar as Calendar  # type: ignore[import-not-found]
except ImportError:
    Calendar = _FallbackCalendar  # type: ignore[assignment]


def _coerce_prop_datetime(prop: Any) -> Optional[datetime]:
    """Coerces an `icalendar` or fallback property into a UTC `datetime`."""
    if prop is None:
        return None
    raw = getattr(prop, "dt", prop)
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day, 9, 0, tzinfo=timezone.utc)
    if isinstance(raw, str) and raw.strip():
        return _parse_ics_datetime_token(raw, {})
    return None


def normalize_and_validate_ics_feed_url(feed_url: str) -> str:
    """Validates and normalizes a school `.ics` feed URL.

    - Requires `https://` or `webcal://` (normalizing `webcal://` -> `https://`).
    - Rejects `file://`, `http://`, or private/loopback IP literals (`127.0.0.1`, `::1`,
      `10.0.0.0/8`, `192.168.0.0/16`, `169.254.0.0/16`) while allowing `localhost` in test mode.
    """
    raw = (feed_url or "").strip()
    if not raw:
        raise ValueError("feed_url is required.")

    lower = raw.lower()
    if lower.startswith("file://"):
        raise ValueError("Invalid feed_url: file:// URLs are forbidden.")

    if lower.startswith("webcal://"):
        normalized = "https://" + raw[len("webcal://"):]
    elif lower.startswith("https://"):
        normalized = raw
    else:
        raise ValueError("Invalid feed_url: scheme must be 'https://' or 'webcal://'.")

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("Invalid feed_url: hostname is required.")

    if host != "localhost":
        try:
            ip_obj = ipaddress.ip_address(host)
            if (
                ip_obj.is_loopback
                or ip_obj.is_private
                or ip_obj.is_link_local
                or ip_obj.is_reserved
                or ip_obj.is_multicast
                or ip_obj.is_unspecified
            ):
                raise ValueError(
                    f"Invalid feed_url: private or loopback IP address '{host}' is not allowed."
                )
        except ValueError as exc:
            if "private or loopback" in str(exc):
                raise

    return normalized


def serialize_school_ics_feed(feed: SchoolIcsFeed) -> Dict[str, Any]:
    """Serializes a `SchoolIcsFeed` ORM row to a dictionary."""
    return {
        "id": feed.id,
        "feed_id": feed.id,
        "profile_id": feed.profile_id,
        "label": feed.label,
        "feed_url": feed.feed_url,
        "status": feed.status,
        "events_synced": feed.events_synced,
        "last_synced_at": feed.last_synced_at.isoformat() if feed.last_synced_at else None,
        "last_error": feed.last_error,
        "created_at": feed.created_at.isoformat() if feed.created_at else None,
        "updated_at": feed.updated_at.isoformat() if feed.updated_at else None,
    }


async def create_school_ics_feed(
    session: AsyncSession,
    profile_id: str,
    label: str,
    feed_url: str,
    actor_user_id: Optional[str] = None,
) -> SchoolIcsFeed:
    """Validates `feed_url` and creates an active `SchoolIcsFeed` subscription row."""
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required to register a school ICS feed.")

    clean_label = " ".join(str(label or "").split()).strip()
    if not clean_label:
        raise ValueError("label is required to register a school ICS feed.")

    normalized_url = normalize_and_validate_ics_feed_url(feed_url)
    now = utc_now()

    feed = SchoolIcsFeed(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        label=clean_label[:255],
        feed_url=normalized_url[:1024],
        status="active",
        events_synced=0,
        last_synced_at=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )
    session.add(feed)

    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "profile_id": clean_profile_id,
                "label": clean_label[:255],
                "feed_url": normalized_url[:1024],
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id,
        principal="user" if actor_user_id else "agent",
        event="tool",
        tool="create_school_ics_feed",
        risk="write_local",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"school_ics_feed:{feed.id}",
        detail_redacted=json.dumps({
            "feed_id": feed.id,
            "label": clean_label[:255],
            "feed_url": normalized_url[:1024],
        }),
    )
    session.add(audit)

    await session.commit()
    await session.refresh(feed)
    return feed


async def sync_school_ics_feed(
    session: AsyncSession,
    profile_id: str,
    feed_id: str,
    raw_ics_content: Optional[str] = None,
) -> Dict[str, Any]:
    """Parses RFC 5545 `.ics` VEVENTs and upserts them into `Appointment` rows."""
    clean_profile_id = (profile_id or "").strip()
    clean_feed_id = (feed_id or "").strip()
    if not clean_profile_id or not clean_feed_id:
        raise ValueError("profile_id and feed_id are required.")

    stmt = select(SchoolIcsFeed).where(
        SchoolIcsFeed.id == clean_feed_id,
        SchoolIcsFeed.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    feed = res.scalar_one_or_none()
    if feed is None:
        raise ValueError(f"SchoolIcsFeed '{clean_feed_id}' not found for profile '{clean_profile_id}'.")

    ics_text = raw_ics_content
    if ics_text is None:
        normalized_url = normalize_and_validate_ics_feed_url(feed.feed_url)
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            resp = await client.get(normalized_url)
            resp.raise_for_status()
            ics_text = resp.text

    if not ics_text or not str(ics_text).strip():
        raise ValueError("ICS feed content is empty.")

    cal = Calendar.from_ical(ics_text)
    vevents = [comp for comp in cal.walk() if getattr(comp, "name", "").upper() == "VEVENT"]

    now = utc_now()
    appointment_ids: List[str] = []
    created_count = 0
    updated_count = 0

    for idx, vevent in enumerate(vevents):
        uid = str(vevent.get("UID") or f"school-evt-{idx + 1}").strip()
        summary = str(vevent.get("SUMMARY") or "School Event").strip()[:255]
        location_raw = vevent.get("LOCATION")
        location = str(location_raw).strip()[:255] if location_raw else None
        desc_raw = vevent.get("DESCRIPTION")
        description = str(desc_raw).strip() if desc_raw else None

        start_dt = _coerce_prop_datetime(vevent.get("DTSTART"))
        if start_dt is None:
            continue
        end_dt = _coerce_prop_datetime(vevent.get("DTEND"))
        if end_dt is None or end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)

        existing_stmt = select(Appointment).where(
            Appointment.profile_id == clean_profile_id,
            Appointment.title == summary,
            Appointment.start_time == start_dt,
        )
        existing_res = await session.execute(existing_stmt)
        appt = existing_res.scalars().first()

        prep_note = f"Synced from {feed.label} (UID: {uid})"
        if appt is not None:
            appt.provider_name = feed.label
            appt.specialty = "School Calendar"
            appt.location = location
            appt.end_time = end_dt
            appt.status = "confirmed"
            appt.reason = description or f"School calendar event from {feed.label}"
            appt.preparation_notes = prep_note
            appt.updated_at = now
            appointment_ids.append(appt.id)
            updated_count += 1
        else:
            appt = Appointment(
                id=str(uuid.uuid4()),
                profile_id=clean_profile_id,
                title=summary,
                provider_name=feed.label,
                specialty="School Calendar",
                location=location,
                start_time=start_dt,
                end_time=end_dt,
                timezone="UTC",
                status="confirmed",
                reason=description or f"School calendar event from {feed.label}",
                preparation_notes=prep_note,
                created_at=now,
                updated_at=now,
            )
            session.add(appt)
            appointment_ids.append(appt.id)
            created_count += 1

    feed.last_synced_at = now
    feed.events_synced = len(appointment_ids)
    feed.status = "active"
    feed.last_error = None
    feed.updated_at = now

    await session.commit()
    await session.refresh(feed)

    return {
        "feed_id": feed.id,
        "profile_id": clean_profile_id,
        "label": feed.label,
        "status": feed.status,
        "events_synced": feed.events_synced,
        "created_count": created_count,
        "updated_count": updated_count,
        "appointment_ids": appointment_ids,
        "last_synced_at": feed.last_synced_at.isoformat() if feed.last_synced_at else now.isoformat(),
    }


async def list_school_ics_feeds(
    session: AsyncSession,
    profile_id: str,
) -> List[SchoolIcsFeed]:
    """Lists all `SchoolIcsFeed` subscriptions for `profile_id`."""
    stmt = (
        select(SchoolIcsFeed)
        .where(SchoolIcsFeed.profile_id == profile_id.strip())
        .order_by(SchoolIcsFeed.created_at.desc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def delete_school_ics_feed(
    session: AsyncSession,
    profile_id: str,
    feed_id: str,
) -> bool:
    """Deletes a `SchoolIcsFeed` subscription scoped to `profile_id`."""
    stmt = select(SchoolIcsFeed).where(
        SchoolIcsFeed.id == feed_id.strip(),
        SchoolIcsFeed.profile_id == profile_id.strip(),
    )
    res = await session.execute(stmt)
    feed = res.scalar_one_or_none()
    if feed is None:
        return False
    await session.delete(feed)
    await session.commit()
    return True


__all__ = [
    "Calendar",
    "create_school_ics_feed",
    "delete_school_ics_feed",
    "list_school_ics_feeds",
    "normalize_and_validate_ics_feed_url",
    "serialize_school_ics_feed",
    "sync_school_ics_feed",
]
