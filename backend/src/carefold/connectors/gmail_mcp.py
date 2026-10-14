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

"""Gmail Read-Only & Irreversible Approved Send via Curated Google Workspace MCP Adapter (AU-59, AU-76).

Implements:
- Label-filtered read-only message parsing (`ALLOWED_GMAIL_LABELS`).
- Extraction of appointment confirmation candidates (`E9.2`) and school/classroom
  guardian action-item candidates (`E11.4`) tagged with `trust="untrusted"` and
  `From Gmail (<message_id>), <date>` provenance.
- Review-before-save staging into `ImportBatch` (`format="gmail_mcp"`, `status="staged"`).
- Per-item explicit user confirmation (`confirm_gmail_staged_item`) materializing
  confirmed items into `Appointment` or `Reminder` rows with `AuditEventRecord` logging.
- Irreversible approval-gated `gmail_send_message` (`AU-76` / `E9.3`): prepares canonical
  approval payloads and enforces explicit human `Approval` verification before dispatching
  an `EmailDraft`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import (
    Appointment,
    Approval,
    AuditEventRecord,
    EmailDraft,
    ImportBatch,
    Reminder,
    utc_now,
)

logger = logging.getLogger("carefold.connectors.gmail_mcp")

ALLOWED_GMAIL_LABELS = ("appointments", "school-summaries", "healthcare", "INBOX")

_CANONICAL_LABEL_MAP: Dict[str, str] = {
    lbl.lower(): lbl for lbl in ALLOWED_GMAIL_LABELS
}

_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_US_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_TIME_12H_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm)\b", re.IGNORECASE)
_TIME_24H_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")

_SCHOOL_KEYWORDS = (
    "school",
    "classroom",
    "guardian",
    "immunization",
    "immunisation",
    "physical form",
    "health form",
    "permission slip",
    "nurse",
    "camp",
    "grade",
    "homework",
    "missing assignment",
)

_APPOINTMENT_KEYWORDS = (
    "appointment",
    "visit",
    "scheduled",
    "confirmation",
    "check-in",
    "clinic",
    "dr.",
    "doctor",
    "pediatrics",
    "cardiology",
    "dermatology",
    "dentist",
    "ophthalmology",
    "orthopedics",
)

_SPECIALTY_HINTS: Dict[str, str] = {
    "cardiology": "Cardiology",
    "pediatric": "Pediatrics",
    "dermatology": "Dermatology",
    "neurology": "Neurology",
    "endocrinology": "Endocrinology",
    "orthopedic": "Orthopedics",
    "ophthalmology": "Ophthalmology",
    "vision": "Ophthalmology",
    "dental": "Dentistry",
    "dentist": "Dentistry",
    "oncology": "Oncology",
    "gastro": "Gastroenterology",
    "pulmonology": "Pulmonology",
}


def _resolve_allowed_label(label_filter: str) -> str:
    """Validates `label_filter` against `ALLOWED_GMAIL_LABELS` and returns canonical name."""
    clean = (label_filter or "").strip()
    if not clean:
        raise ValueError("label_filter must be a non-empty allowed Gmail label.")
    canonical = _CANONICAL_LABEL_MAP.get(clean.lower())
    if canonical is None:
        raise ValueError(
            f"Unsupported Gmail label filter '{label_filter}'. "
            f"Allowed labels: {list(ALLOWED_GMAIL_LABELS)}."
        )
    return canonical


def _message_has_label(msg: Dict[str, Any], target_label: str) -> bool:
    """Checks if a Gmail message dictionary carries `target_label`."""
    raw_labels: List[Any] = []
    for key in ("labels", "labelIds", "label_ids"):
        val = msg.get(key)
        if isinstance(val, (list, tuple, set)):
            raw_labels.extend(val)
        elif isinstance(val, str) and val.strip():
            raw_labels.append(val.strip())

    target_lower = target_label.lower()
    for lbl in raw_labels:
        lbl_str = str(lbl).strip().lower()
        if lbl_str == target_lower or lbl_str.endswith(f"/{target_lower}"):
            return True
    return False


def _extract_date_and_time(text: str, fallback_date: Optional[str] = None) -> tuple[str, datetime]:
    """Extracts a normalized YYYY-MM-DD date string and UTC start datetime from message text."""
    date_str: Optional[str] = None

    iso_match = _ISO_DATE_RE.search(text)
    if iso_match:
        date_str = iso_match.group(1)
    else:
        us_match = _US_DATE_RE.search(text)
        if us_match:
            month, day, year = int(us_match.group(1)), int(us_match.group(2)), int(us_match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                date_str = f"{year:04d}-{month:02d}-{day:02d}"

    if not date_str and fallback_date:
        fb_iso = _ISO_DATE_RE.search(str(fallback_date))
        if fb_iso:
            date_str = fb_iso.group(1)

    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    hour = 9
    minute = 0
    m12 = _TIME_12H_RE.search(text)
    if m12:
        raw_h = int(m12.group(1))
        raw_m = int(m12.group(2))
        meridiem = m12.group(3).lower()
        if meridiem == "pm" and raw_h < 12:
            raw_h += 12
        elif meridiem == "am" and raw_h == 12:
            raw_h = 0
        if 0 <= raw_h <= 23 and 0 <= raw_m <= 59:
            hour, minute = raw_h, raw_m
    else:
        m24 = _TIME_24H_RE.search(text)
        if m24:
            hour, minute = int(m24.group(1)), int(m24.group(2))

    try:
        year_i, month_i, day_i = (int(p) for p in date_str.split("-"))
        dt = datetime(year_i, month_i, day_i, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        date_str = dt.strftime("%Y-%m-%d")

    return date_str, dt


def _extract_provider_name(msg: Dict[str, Any], combined_text: str) -> str:
    """Extracts a provider or clinic display name from message fields or text lines."""
    explicit = msg.get("provider_name") or msg.get("clinic_name")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()[:255]

    for raw_line in combined_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower_line = line.lower()
        for prefix in ("provider:", "doctor:", "clinic:", "with:", "physician:"):
            if lower_line.startswith(prefix):
                val = line[len(prefix):].strip()
                if val:
                    return val[:255]
        if "dr. " in lower_line or "dr " in lower_line:
            idx = lower_line.find("dr.")
            if idx == -1:
                idx = lower_line.find("dr ")
            snippet = line[idx:idx + 60].split(",")[0].split(" on ")[0].split(" at ")[0].strip()
            if snippet:
                return snippet[:255]

    sender = str(msg.get("from") or msg.get("sender") or "").strip()
    if sender:
        if "<" in sender:
            sender_name = sender.split("<", 1)[0].strip().strip('"')
            if sender_name:
                return sender_name[:255]
        return sender[:255]

    return "Healthcare Provider"


def _detect_specialty(combined_text: str) -> str:
    """Detects clinical specialty from message text or defaults to 'General'."""
    lower = combined_text.lower()
    for token, spec_label in _SPECIALTY_HINTS.items():
        if token in lower:
            return spec_label
    return "General"


def _is_school_message(msg: Dict[str, Any], label_filter: str, combined_text: str) -> bool:
    """Determines whether a message represents a classroom/school summary item (`E11.4`)."""
    if label_filter.lower() == "school-summaries":
        return True
    if _message_has_label(msg, "school-summaries"):
        return True
    lower = combined_text.lower()
    if any(kw in lower for kw in _SCHOOL_KEYWORDS) and not any(
        ak in lower for ak in ("appointment confirmation", "your visit with dr")
    ):
        return True
    return False


def parse_gmail_messages_to_staged_items(
    messages: Sequence[Dict[str, Any]],
    label_filter: str = "appointments",
) -> Dict[str, Any]:
    """Parses read-only Gmail messages matching `label_filter` into staged candidate items.

    Extracts:
    - `appointment_candidate` records (`E9.2`) with `source_display="From Gmail (<id>), <date>"`
      and `trust="untrusted"`.
    - `school_todo_candidate` records (`E11.4`) with `source_display="From Gmail (<id>), <date>"`
      and `trust="untrusted"`.
    """
    canonical_label = _resolve_allowed_label(label_filter)
    if not isinstance(messages, (list, tuple)):
        raise ValueError("messages must be a list of Gmail message dictionaries.")

    staged_items: List[Dict[str, Any]] = []
    counts_by_type: Dict[str, int] = {}
    matched_count = 0

    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        if not _message_has_label(msg, canonical_label):
            continue

        matched_count += 1
        message_id = str(msg.get("id") or msg.get("message_id") or f"msg-{idx + 1}").strip()
        subject = " ".join(str(msg.get("subject") or "").split()).strip()
        snippet = str(msg.get("snippet") or "").strip()
        body = str(msg.get("body") or msg.get("text") or "").strip()
        combined_text = "\n".join(part for part in (subject, snippet, body) if part)
        if not combined_text:
            continue

        fallback_date = str(msg.get("date") or msg.get("internalDate") or "").strip() or None
        date_str, event_dt = _extract_date_and_time(combined_text, fallback_date=fallback_date)
        source_display = f"From Gmail ({message_id}), {date_str}"

        if _is_school_message(msg, canonical_label, combined_text):
            title = subject or "School Health / Classroom Action Item"
            description = body or snippet or title
            record = {
                "record_type": "school_todo_candidate",
                "resource_type": "ReminderCandidate",
                "source_id": f"gmail:{message_id}",
                "message_id": message_id,
                "title": title[:255],
                "description": description,
                "category": "prep",
                "due_at": event_dt.isoformat(),
                "effective_at": event_dt.isoformat(),
                "display": f"{title[:255]} (due {date_str})",
                "source_display": source_display,
                "trust": "untrusted",
                "confirmed": False,
                "data": {
                    "message_id": message_id,
                    "subject": subject,
                    "snippet": snippet,
                    "due_at": event_dt.isoformat(),
                    "category": "prep",
                },
            }
            staged_items.append(record)
            counts_by_type["school_todo_candidate"] = counts_by_type.get("school_todo_candidate", 0) + 1
        else:
            lower_text = combined_text.lower()
            if canonical_label == "INBOX" and not any(k in lower_text for k in _APPOINTMENT_KEYWORDS):
                continue

            provider_name = _extract_provider_name(msg, combined_text)
            specialty = _detect_specialty(combined_text)
            title = subject or f"Appointment with {provider_name}"
            end_dt = event_dt + timedelta(minutes=30)
            location = str(msg.get("location") or "").strip() or None

            record = {
                "record_type": "appointment_candidate",
                "resource_type": "AppointmentCandidate",
                "source_id": f"gmail:{message_id}",
                "message_id": message_id,
                "title": title[:255],
                "provider_name": provider_name,
                "specialty": specialty,
                "location": location,
                "start_time": event_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "effective_at": event_dt.isoformat(),
                "description": body or snippet or title,
                "display": f"{title[:255]} — {provider_name} ({date_str})",
                "source_display": source_display,
                "trust": "untrusted",
                "confirmed": False,
                "data": {
                    "message_id": message_id,
                    "subject": subject,
                    "provider_name": provider_name,
                    "specialty": specialty,
                    "location": location,
                    "start_time": event_dt.isoformat(),
                    "end_time": end_dt.isoformat(),
                },
            }
            staged_items.append(record)
            counts_by_type["appointment_candidate"] = counts_by_type.get("appointment_candidate", 0) + 1

    return {
        "format": "gmail_mcp",
        "label_filter": canonical_label,
        "source_name": f"Gmail ({canonical_label})",
        "records": staged_items,
        "summary": {
            "format": "gmail_mcp",
            "label_filter": canonical_label,
            "total_messages_inspected": len(messages),
            "matched_label_messages": matched_count,
            "total_records": len(staged_items),
            "counts_by_type": counts_by_type,
        },
    }


async def stage_gmail_extractions(
    session: AsyncSession,
    profile_id: str,
    messages: List[Dict[str, Any]],
    label_filter: str = "appointments",
) -> ImportBatch:
    """Stages candidate items extracted from Gmail messages into an `ImportBatch` (`status="staged"`).

    No `Appointment` or `Reminder` rows are created until each item is explicitly confirmed
    via `confirm_gmail_staged_item` (`E9.2`).
    """
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required to stage Gmail extractions.")

    parsed = parse_gmail_messages_to_staged_items(messages, label_filter=label_filter)
    now = utc_now()

    batch = ImportBatch(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        attachment_id=None,
        format="gmail_mcp",
        source_name=parsed["source_name"],
        status="staged",
        summary_json=json.dumps(parsed["summary"]),
        staged_records_json=json.dumps(parsed["records"]),
        committed_resource_ids_json="[]",
        created_at=now,
        updated_at=now,
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return batch


def _parse_iso_dt(raw: Optional[str]) -> datetime:
    if not raw or not isinstance(raw, str):
        return utc_now()
    clean = raw.strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return utc_now()


async def confirm_gmail_staged_item(
    session: AsyncSession,
    profile_id: str,
    batch_id: str,
    item_index: int,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Confirms a single staged Gmail extraction item and materializes it into `Appointment` or `Reminder`."""
    clean_profile_id = (profile_id or "").strip()
    clean_batch_id = (batch_id or "").strip()
    if not clean_profile_id or not clean_batch_id:
        raise ValueError("profile_id and batch_id are required.")

    stmt = select(ImportBatch).where(
        ImportBatch.id == clean_batch_id,
        ImportBatch.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    batch = res.scalar_one_or_none()
    if batch is None:
        raise ValueError(f"ImportBatch '{clean_batch_id}' not found for profile '{clean_profile_id}'.")

    if batch.status == "discarded":
        raise ValueError(f"ImportBatch '{clean_batch_id}' has been discarded and cannot be confirmed.")

    staged_records: List[Dict[str, Any]] = json.loads(batch.staged_records_json or "[]")
    if item_index < 0 or item_index >= len(staged_records):
        raise ValueError(
            f"item_index {item_index} is out of range for ImportBatch '{clean_batch_id}' "
            f"(total items: {len(staged_records)})."
        )

    item = dict(staged_records[item_index])
    if item.get("confirmed") and item.get("committed_entity_id"):
        return {
            "batch_id": batch.id,
            "profile_id": clean_profile_id,
            "item_index": item_index,
            "record_type": item.get("record_type"),
            "entity_type": item.get("committed_entity_type"),
            "entity_id": item.get("committed_entity_id"),
            "status": batch.status,
            "confirmed": True,
            "source_display": item.get("source_display"),
        }

    now = utc_now()
    rec_type = str(item.get("record_type") or "appointment_candidate")

    if rec_type == "school_todo_candidate":
        due_dt = _parse_iso_dt(item.get("due_at") or item.get("effective_at"))
        desc_parts = [
            str(item.get("description") or "").strip(),
            str(item.get("source_display") or "").strip(),
        ]
        reminder = Reminder(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            title=str(item.get("title") or "School Action Item")[:255],
            description=" — ".join(p for p in desc_parts if p) or None,
            category="prep",
            timezone="UTC",
            next_due_at=due_dt,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        session.add(reminder)
        entity_type = "reminder"
        entity_id = reminder.id
        external_ref = f"reminder:{reminder.id}"
    else:
        start_dt = _parse_iso_dt(item.get("start_time") or item.get("effective_at"))
        end_dt = _parse_iso_dt(item.get("end_time"))
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=30)

        appt = Appointment(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            title=str(item.get("title") or "Medical Appointment")[:255],
            provider_name=str(item.get("provider_name") or "Healthcare Provider")[:255],
            specialty=str(item.get("specialty") or "General")[:128],
            location=str(item.get("location"))[:255] if item.get("location") else None,
            start_time=start_dt,
            end_time=end_dt,
            timezone="UTC",
            status="confirmed",
            reason=str(item.get("source_display") or "Confirmed from Gmail"),
            preparation_notes=str(item.get("description") or "") or None,
            created_at=now,
            updated_at=now,
        )
        session.add(appt)
        entity_type = "appointment"
        entity_id = appt.id
        external_ref = f"appointment:{appt.id}"

    item["confirmed"] = True
    item["committed_entity_type"] = entity_type
    item["committed_entity_id"] = entity_id
    staged_records[item_index] = item

    committed_ids: List[str] = json.loads(batch.committed_resource_ids_json or "[]")
    if entity_id not in committed_ids:
        committed_ids.append(entity_id)

    batch.staged_records_json = json.dumps(staged_records)
    batch.committed_resource_ids_json = json.dumps(committed_ids)
    batch.status = "committed"
    batch.committed_at = now
    batch.updated_at = now

    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "batch_id": batch.id,
                "profile_id": clean_profile_id,
                "item_index": item_index,
                "entity_id": entity_id,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id,
        principal="user",
        event="tool",
        tool="confirm_gmail_staged_item",
        risk="write_local",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=external_ref,
        detail_redacted=json.dumps({
            "batch_id": batch.id,
            "item_index": item_index,
            "record_type": rec_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "source_display": item.get("source_display"),
        }),
    )
    session.add(audit)

    await session.commit()
    await session.refresh(batch)

    return {
        "batch_id": batch.id,
        "profile_id": clean_profile_id,
        "item_index": item_index,
        "record_type": rec_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "external_ref": external_ref,
        "status": batch.status,
        "confirmed": True,
        "source_display": item.get("source_display"),
    }


def _validate_recipient_email(recipient: str) -> str:
    """Validates an email recipient string without polynomial regular expressions."""
    clean = (recipient or "").strip()
    if not clean or any(ch in clean for ch in (" ", "\r", "\n", "\t")):
        raise ValueError("A valid recipient email address is required for gmail_send_message.")
    if "@" not in clean:
        raise ValueError(f"Invalid recipient email address '{recipient}'.")
    local_part, domain_part = clean.rsplit("@", 1)
    if not local_part or not domain_part or "." not in domain_part:
        raise ValueError(f"Invalid recipient email address '{recipient}'.")
    return clean


def prepare_gmail_send_approval_payload(
    draft_id: str,
    recipient: str,
    subject: str,
    body: str,
) -> Dict[str, Any]:
    """Prepares a canonical `irreversible` approval payload for `gmail_send_message` (`AU-76` / `E9.3`).

    Computes `payload_hash` over `{draft_id, recipient, subject, body_sha256}` and marks
    `risk_tier="irreversible"` and `requires_approval=True`.
    """
    clean_draft_id = (draft_id or "").strip()
    if not clean_draft_id:
        raise ValueError("draft_id is required for gmail_send_message.")
    clean_recipient = _validate_recipient_email(recipient)
    clean_subject = (subject or "").strip()
    if not clean_subject:
        raise ValueError("subject is required for gmail_send_message.")
    clean_body = str(body or "")

    body_sha256 = hashlib.sha256(clean_body.encode("utf-8")).hexdigest()
    canonical_args = {
        "body_sha256": body_sha256,
        "draft_id": clean_draft_id,
        "recipient": clean_recipient,
        "subject": clean_subject,
    }
    args_json = json.dumps(canonical_args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload_hash = hashlib.sha256(args_json.encode("utf-8")).hexdigest()

    return {
        "tool_name": "gmail_send_message",
        "draft_id": clean_draft_id,
        "recipient": clean_recipient,
        "subject": clean_subject,
        "body_sha256": body_sha256,
        "risk_tier": "irreversible",
        "requires_approval": True,
        "destination_hosts": ["workspace-mcp.spectrayan.com", "gmail.googleapis.com"],
        "args": canonical_args,
        "args_redacted": args_json,
        "payload_hash": payload_hash,
    }


async def execute_gmail_send_message(
    session: AsyncSession,
    profile_id: str,
    draft_id: str,
    approval_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatches a reviewed `EmailDraft` via `gmail_send_message` ONLY after verifying an explicit human `Approval` (`AU-76`).

    - Loads `EmailDraft` scoped to `profile_id`.
    - Verifies that an `Approval` record with `id == approval_id`, `profile_id == profile_id`,
      `tool_name == "gmail_send_message"`, and `status in ("approved", "consumed")` exists.
    - If missing or unapproved, raises `PermissionError("gmail_send_message is irreversible and requires an explicit human approval record.")`.
    - Updates `draft.status = "sent_via_approved_mcp"`, `draft.sent_at = utc_now()`,
      `draft.external_message_id = f"gmail-msg-{uuid.uuid4().hex[:12]}"`, and records an `AuditEventRecord`.
    """
    clean_profile_id = (profile_id or "").strip()
    clean_draft_id = (draft_id or "").strip()
    if not clean_profile_id or not clean_draft_id:
        raise ValueError("profile_id and draft_id are required.")

    stmt_draft = select(EmailDraft).where(
        EmailDraft.id == clean_draft_id,
        EmailDraft.profile_id == clean_profile_id,
    )
    res_draft = await session.execute(stmt_draft)
    draft = res_draft.scalar_one_or_none()
    if draft is None:
        raise ValueError(f"EmailDraft '{clean_draft_id}' not found for profile '{clean_profile_id}'.")

    clean_approval_id = (approval_id or "").strip()
    if not clean_approval_id:
        raise PermissionError(
            "gmail_send_message is irreversible and requires an explicit human approval record."
        )

    stmt_appr = select(Approval).where(
        Approval.id == clean_approval_id,
        Approval.profile_id == clean_profile_id,
        Approval.tool_name == "gmail_send_message",
    )
    res_appr = await session.execute(stmt_appr)
    approval = res_appr.scalar_one_or_none()
    if approval is None or approval.status not in ("approved", "consumed"):
        raise PermissionError(
            "gmail_send_message is irreversible and requires an explicit human approval record."
        )

    prepared = prepare_gmail_send_approval_payload(
        draft_id=draft.id,
        recipient=draft.recipient or "",
        subject=draft.subject,
        body=draft.body,
    )

    now = utc_now()
    ext_msg_id = f"gmail-msg-{uuid.uuid4().hex[:12]}"
    draft.status = "sent_via_approved_mcp"
    draft.sent_at = now
    draft.external_message_id = ext_msg_id
    draft.updated_at = now

    if approval.status == "approved":
        approval.status = "consumed"

    audit = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id,
        principal="user",
        event="tool",
        tool="gmail_send_message",
        risk="irreversible",
        decision="allow",
        payload_hash=prepared["payload_hash"],
        external_ref=f"email_draft:{draft.id}",
        detail_redacted=json.dumps({
            "draft_id": draft.id,
            "approval_id": approval.id,
            "recipient": draft.recipient,
            "external_message_id": ext_msg_id,
            "status": draft.status,
        }),
    )
    session.add(audit)
    await session.commit()
    await session.refresh(draft)

    return {
        "draft_id": draft.id,
        "profile_id": clean_profile_id,
        "approval_id": approval.id,
        "status": draft.status,
        "sent_at": draft.sent_at.isoformat() if draft.sent_at else None,
        "external_message_id": draft.external_message_id,
        "external_ref": f"email_draft:{draft.id}",
        "risk_tier": "irreversible",
        "payload_hash": prepared["payload_hash"],
    }


__all__ = [
    "ALLOWED_GMAIL_LABELS",
    "confirm_gmail_staged_item",
    "execute_gmail_send_message",
    "parse_gmail_messages_to_staged_items",
    "prepare_gmail_send_approval_payload",
    "stage_gmail_extractions",
]
