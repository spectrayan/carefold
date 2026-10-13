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

"""Activity Timeline query engine, human-readable synthesizer, and undo eligibility evaluation (AU-40)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import AuditEventRecord
from carefold.schemas.activity import (
    ActivityItemResponse,
    ActivityTimelineResponse,
    ActivityUndoResponse,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Section 1: Human-Readable Description Synthesis Engine
# ============================================================================

def _safe_float(val: Any) -> Optional[float]:
    """Defensively casts value to float, returning None on ValueError or TypeError."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def synthesize_activity_summary(
    action: Optional[str],
    tool: Optional[str],
    details: Optional[Dict[str, Any]],
    external_ref: Optional[str],
    principal: Optional[str] = "user",
    fallback_event: Optional[str] = None,
) -> Tuple[str, str]:
    """Deterministically maps audit event telemetry to natural patient-friendly summaries.

    Returns:
        (summary: str, description: str)
    """
    det = details or {}
    tool_name = (tool or "").strip()
    action_name = (action or fallback_event or "").strip()

    # 1. Undo actions
    if tool_name == "undo" or action_name == "undo":
        reverted_summary = det.get("reverted_summary")
        if reverted_summary:
            return (
                f"Reverted action: {reverted_summary}",
                "Rolled back changes and restored previous state.",
            )
        if external_ref and ":" in external_ref:
            entity_type = external_ref.split(":", 1)[0]
            if entity_type == "health_resource":
                return ("Reverted action: Logged vitals", "Tombstoned vital signs observation.")
            if entity_type == "appointment":
                return ("Reverted action: Scheduled appointment", "Cancelled scheduled appointment.")
            if entity_type == "reminder":
                return ("Reverted action: Created reminder", "Cancelled reminder and removed active alerts.")
            if entity_type == "note":
                return ("Reverted action: Created note", "Removed clinical note and purged search index.")
        return ("Reverted previous action", "Rolled back changes and restored previous state.")

    # 2. Vitals recording (record_vitals)
    if tool_name in ("record_vitals", "vitals"):
        vitals_payload = det.get("vitals") or det
        components: List[str] = []
        desc_components: List[str] = []

        sys_f = _safe_float(vitals_payload.get("systolic"))
        dia_f = _safe_float(vitals_payload.get("diastolic"))
        if sys_f is not None and dia_f is not None:
            components.append(f"blood pressure {sys_f:.0f}/{dia_f:.0f} mmHg")
            desc_components.append(f"blood pressure reading of {sys_f:.0f}/{dia_f:.0f} mmHg")

        hr_f = _safe_float(vitals_payload.get("heart_rate") or vitals_payload.get("pulse"))
        if hr_f is not None:
            components.append(f"heart rate {hr_f:.0f} bpm")
            desc_components.append(f"pulse rate of {hr_f:.0f} bpm")

        glu_val = vitals_payload.get("blood_glucose") or vitals_payload.get("glucose")
        if glu_val is not None:
            glu_unit = vitals_payload.get("unit") or "mg/dL"
            components.append(f"blood glucose {glu_val} {glu_unit}")
            desc_components.append(f"blood glucose reading of {glu_val} {glu_unit}")

        spo2_f = _safe_float(vitals_payload.get("spo2") or vitals_payload.get("oxygen_saturation"))
        if spo2_f is not None:
            components.append(f"oxygen saturation {spo2_f:.0f}%")
            desc_components.append(f"pulse oximetry reading of {spo2_f:.0f}% SpO2")

        wt_val = vitals_payload.get("weight") or vitals_payload.get("body_weight")
        if wt_val is not None and _safe_float(wt_val) is not None:
            wt_unit = vitals_payload.get("unit") or "kg"
            components.append(f"weight {wt_val} {wt_unit}")
            desc_components.append(f"body weight measurement of {wt_val} {wt_unit}")

        ht_val = vitals_payload.get("height")
        if ht_val is not None and _safe_float(ht_val) is not None:
            ht_unit = vitals_payload.get("unit") or "cm"
            components.append(f"height {ht_val} {ht_unit}")
            desc_components.append(f"body height measurement of {ht_val} {ht_unit}")

        if len(components) == 1:
            comp_str = components[0]
            prefix = "Recorded" if comp_str.startswith(("weight", "height")) else "Logged"
            return (f"{prefix} {comp_str}", f"Recorded {desc_components[0]}.")
        if len(components) > 1:
            joined = " and ".join(components[:2]) if len(components) == 2 else ", ".join(components)
            return (f"Logged {joined}", "Recorded vital signs observation panel.")
        return ("Logged vital signs observation", "Recorded clinical observation in health resources.")

    # 3. Appointments (create_appointment, book_appointment, cancel_appointment, update_appointment_status)
    if tool_name in ("create_appointment", "book_appointment"):
        title = det.get("title") or "Consultation"
        provider = det.get("provider_name")
        specialty = det.get("specialty")
        status_val = det.get("status")
        start_time = det.get("start_time")

        prefix = "Requested" if status_val == "requested" else "Scheduled"
        if provider and specialty:
            summary = f"{prefix} appointment with {provider} ({specialty})"
        elif provider:
            summary = f"{prefix} appointment with {provider}"
        else:
            summary = f"{prefix} appointment: {title}"

        if status_val == "requested":
            description = "Draft booking request prepared for scheduling."
        elif start_time:
            description = f"Consultation scheduled for {start_time}."
        elif provider:
            description = f"Appointment booked with {provider}."
        else:
            description = f"Appointment scheduled: {title}."
        return (summary, description)

    if tool_name in ("cancel_appointment", "delete_appointment") or action_name == "cancel_appointment":
        title = det.get("title")
        provider = det.get("provider_name")
        if provider:
            summary = f"Cancelled appointment with {provider}"
        elif title:
            summary = f"Cancelled appointment: {title}"
        else:
            summary = "Cancelled appointment"
        description = "Appointment cancelled."
        return (summary, description)

    if tool_name == "update_appointment_status":
        new_status = det.get("new_status") or det.get("status") or "updated"
        prev_status = det.get("previous_status") or det.get("prev_status")
        summary = f"Updated appointment status to {new_status}"
        if new_status == "completed":
            description = "Encounter marked completed."
        elif new_status == "cancelled":
            description = "Appointment cancelled."
        elif prev_status:
            description = f"Appointment status updated from {prev_status} to {new_status}."
        else:
            description = f"Appointment status updated to {new_status}."
        return (summary, description)

    # 4. Reminders (create_reminder, complete_reminder, update_reminder)
    if tool_name in ("complete_reminder", "update_reminder"):
        title = det.get("title")
        summary = f"Completed reminder: {title}" if title else "Completed reminder"
        description = "Reminder marked complete."
        return (summary, description)

    if tool_name == "create_reminder":
        category = det.get("category") or "general"
        title = det.get("title") or "Reminder"
        if category in ("medication", "vitals"):
            summary = f"Created {category} reminder: {title}"
        else:
            summary = f"Created reminder: {title}"

        if category == "medication":
            description = f"Recurring reminder scheduled for {title}."
        elif category == "vitals":
            description = f"Reminder scheduled for {title}."
        else:
            description = "Reminder scheduled."
        return (summary, description)

    # 5. Consultation Prep Pack (generate_prep_pack)
    if tool_name == "generate_prep_pack":
        specialty = det.get("specialty")
        if specialty:
            summary = f"Generated consultation prep pack for {specialty} visit"
        else:
            summary = "Generated consultation prep pack"
        description = "Synthesized clinical questions, vitals trends, and medication history."
        return (summary, description)

    # 6. Typed Notes (create_typed_note, api_notes, create_clinical_note)
    if tool_name in ("create_typed_note", "api_notes", "create_clinical_note"):
        note_type = det.get("type") or "clinical"
        title = det.get("title") or "Note"
        summary = f"Created {note_type} note: {title}"
        if note_type == "after_visit":
            description = "Extracted post-encounter summary and next steps."
        elif note_type == "visit":
            description = "Clinical visit note saved."
        elif note_type == "symptom":
            description = "Logged patient symptom log."
        else:
            description = f"Saved {note_type} note."
        return (summary, description)

    # 7. Safety refusal and boundaries (refuse)
    if action_name == "refuse":
        reason = det.get("reason") or "Emergency directive"
        return (
            f"Safety boundary refusal: {reason}",
            "Non-clinical boundary triggered emergency escalation.",
        )

    # 8. Workflow executions (run)
    if action_name == "run":
        agent = det.get("agent_id") or "assistant"
        return (
            f"Consultation session with {agent}",
            f"Completed consultation workflow with {agent}.",
        )

    # 9. Generic fallbacks
    if tool_name:
        return (f"Executed {tool_name}", f"Action executed via {tool_name}.")
    return (
        f"Completed action: {action_name or 'event'}",
        f"System processed {action_name or 'action'}.",
    )


# ============================================================================
# Section 2: Undoability Evaluation Engine
# ============================================================================

def compute_is_undoable(
    risk: Optional[str],
    ts: datetime,
    event_id: str,
    undone_event_ids: Set[str],
    tool: Optional[str] = None,
    event: Optional[str] = None,
    action: Optional[str] = None,
    external_ref: Optional[str] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Evaluates whether an audit event meets all single-click undo criteria."""
    if risk != "write_local":
        return False

    current_time = now or datetime.now(timezone.utc)
    event_dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    # Strict 7-day window boundary
    if (current_time - event_dt) > timedelta(days=7):
        return False

    # Already undone
    if event_id in undone_event_ids:
        return False

    # Never allow undoing an undo event
    if tool == "undo" or event == "undo" or action == "undo":
        return False

    # Must have resolvable entity reference
    if not external_ref or ":" not in external_ref:
        return False

    return True


def format_audit_event_as_activity_item(
    record: AuditEventRecord,
    undone_event_ids: Set[str],
    now: Optional[datetime] = None,
) -> ActivityItemResponse:
    """Transforms a database AuditEventRecord into an ActivityItemResponse."""
    details_dict: Dict[str, Any] = {}
    if record.detail_redacted:
        try:
            details_dict = json.loads(record.detail_redacted)
        except Exception:
            details_dict = {}

    # Check for nested details if present
    effective_details = details_dict.get("details") if isinstance(details_dict.get("details"), dict) else details_dict

    action_val = details_dict.get("action") or record.event
    summary, description = synthesize_activity_summary(
        action=action_val,
        tool=record.tool,
        details=effective_details,
        external_ref=record.external_ref,
        principal=record.principal,
        fallback_event=record.event,
    )

    is_undone = record.id in undone_event_ids
    is_undoable = compute_is_undoable(
        risk=record.risk,
        ts=record.ts,
        event_id=record.id,
        undone_event_ids=undone_event_ids,
        tool=record.tool,
        event=record.event,
        action=action_val,
        external_ref=record.external_ref,
        now=now,
    )

    return ActivityItemResponse(
        id=record.id,
        event_id=record.id,
        ts=record.ts,
        profile_id=record.profile_id or "",
        actor_user_id=record.actor_user_id,
        principal=record.principal or "user",
        actor=record.principal or "user",
        event=record.event,
        action=action_val,
        tool=record.tool,
        risk=record.risk,
        external_ref=record.external_ref,
        summary=summary,
        description=description,
        undoable=is_undoable,
        undone=is_undone,
        details=effective_details,
    )


# ============================================================================
# Section 3: Timeline Query Engine
# ============================================================================

async def get_profile_activity_timeline(
    db: AsyncSession,
    profile_id: str,
    limit: int = 50,
    offset: int = 0,
    undoable_only: bool = False,
    event: Optional[str] = None,
    tool: Optional[str] = None,
    now: Optional[datetime] = None,
) -> ActivityTimelineResponse:
    """Executes profile-scoped timeline query with pagination, sorting, and synthesis."""
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id must not be empty.")

    current_now = now or datetime.now(timezone.utc)

    # 1. Collect all undone event IDs for this profile
    undo_query = select(AuditEventRecord).where(
        AuditEventRecord.profile_id == clean_profile_id,
        or_(AuditEventRecord.event == "undo", AuditEventRecord.tool == "undo"),
    )
    undo_res = await db.execute(undo_query)
    undone_event_ids: Set[str] = set()
    for undo_record in undo_res.scalars().all():
        if undo_record.detail_redacted:
            try:
                meta = json.loads(undo_record.detail_redacted)
                undone_id = (
                    meta.get("undone_event_id")
                    or meta.get("reverted_event_id")
                    or (meta.get("details", {}).get("undone_event_id") if isinstance(meta.get("details"), dict) else None)
                )
                if undone_id:
                    undone_event_ids.add(str(undone_id))
            except Exception:
                pass

    # 2. Build base query strictly scoped to profile_id NOT NULL
    stmt = select(AuditEventRecord).where(
        AuditEventRecord.profile_id == clean_profile_id,
        AuditEventRecord.profile_id.isnot(None),
    )

    if event:
        stmt = stmt.where(AuditEventRecord.event == event)
    if tool:
        stmt = stmt.where(AuditEventRecord.tool == tool)

    # If undoable_only is requested at query level
    if undoable_only:
        seven_days_ago = current_now - timedelta(days=7)
        stmt = stmt.where(
            AuditEventRecord.risk == "write_local",
            AuditEventRecord.ts >= seven_days_ago,
            AuditEventRecord.event != "undo",
            AuditEventRecord.tool != "undo",
            AuditEventRecord.external_ref.isnot(None),
        )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = (await db.execute(count_stmt)).scalar() or 0

    # Fetch page ordered chronologically descending (newest first)
    stmt = stmt.order_by(AuditEventRecord.ts.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    records = res.scalars().all()

    items: List[ActivityItemResponse] = []
    for rec in records:
        item = format_audit_event_as_activity_item(rec, undone_event_ids, now=current_now)
        if undoable_only and not item.undoable:
            continue
        items.append(item)

    return ActivityTimelineResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
        profile_id=clean_profile_id,
        has_more=(offset + len(items)) < total_count,
    )
