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

"""Clinical appointment state machine, 'How to Book' drafts, and post-visit transitions (AU-29)."""

from __future__ import annotations

from datetime import datetime, timezone
import enum
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.audit.logger import record_audit
from carefold.db.models import Appointment
from carefold.logging import get_logger

logger = get_logger("carefold.clinical.appointments")


# ============================================================================
# Section 1: Appointment Lifecycle State Machine
# ============================================================================


class AppointmentStatus(str, enum.Enum):
    """Canonical lifecycle statuses for clinical appointments."""

    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


VALID_STATUS_TRANSITIONS: Dict[AppointmentStatus, Set[AppointmentStatus]] = {
    AppointmentStatus.REQUESTED: {
        AppointmentStatus.SCHEDULED,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CANCELLED,
    },
    AppointmentStatus.SCHEDULED: {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.REQUESTED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
    },
    AppointmentStatus.CONFIRMED: {
        AppointmentStatus.COMPLETED,
        AppointmentStatus.SCHEDULED,
        AppointmentStatus.CANCELLED,
    },
    AppointmentStatus.COMPLETED: {
        AppointmentStatus.CANCELLED,  # Undo / administrative rollback only
    },
    AppointmentStatus.CANCELLED: {
        AppointmentStatus.REQUESTED,  # Re-open booking draft
    },
}


class InvalidStatusTransitionError(ValueError):
    """Raised when an illegal appointment status transition is attempted."""

    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(f"Invalid status transition from '{from_status}' to '{to_status}'.")
        self.from_status = from_status
        self.to_status = to_status


def validate_status_transition(current_status: str, new_status: str) -> None:
    """Validates state machine transition rules. Idempotent if current == new.

    Args:
        current_status: Existing status string.
        new_status: Proposed target status string.

    Raises:
        ValueError: If status string is unknown.
        InvalidStatusTransitionError: If the transition is prohibited by state machine.
    """
    try:
        curr = AppointmentStatus(str(current_status).strip().lower())
        target = AppointmentStatus(str(new_status).strip().lower())
    except ValueError as exc:
        raise ValueError(f"Unknown appointment status: {exc}") from exc

    if curr == target:
        return  # Idempotent no-op

    if target not in VALID_STATUS_TRANSITIONS[curr]:
        raise InvalidStatusTransitionError(curr.value, target.value)


# ============================================================================
# Section 2: "How to Book" Drafts Generator (AU-29)
# ============================================================================


def generate_how_to_book_drafts(
    title: str,
    provider_name: str,
    specialty: str,
    clinic_phone: str,
    reason: str,
    insurance_name: Optional[str] = "Carefold Health Plan",
    insurance_member_id: Optional[str] = None,
    insurance_group_number: Optional[str] = None,
    preferred_days: Optional[List[str]] = None,
    preferred_time_of_day: Optional[str] = "Morning",
    visit_mode: Optional[str] = "in-person",
) -> Dict[str, Any]:
    """Generates structured call script, portal draft, and pre-visit checklist (AU-29).

    Args:
        title: Appointment title or consultation intent.
        provider_name: Target clinician or practice name.
        specialty: Medical specialty (e.g. Cardiology, Endocrinology).
        clinic_phone: Scheduling phone number.
        reason: Chief complaint or visit reason.
        insurance_name: Plan or payer name.
        insurance_member_id: Optional member identifier.
        insurance_group_number: Optional plan group number.
        preferred_days: Preferred days of week.
        preferred_time_of_day: Preferred time window (Morning / Afternoon).
        visit_mode: 'in-person' or 'telehealth'.

    Returns:
        Dict with status 'requested', phone_script, portal_draft, and checklist.
    """
    ins_label = insurance_name or "Carefold Health Plan"
    ins_details = ins_label
    if insurance_member_id:
        ins_details += f" (Member ID: {insurance_member_id}"
        if insurance_group_number:
            ins_details += f", Group: {insurance_group_number}"
        ins_details += ")"

    pref_days_str = ", ".join(preferred_days) if preferred_days else "upcoming weekdays"
    avail_prompt = (
        f"What is the earliest available opening for an {visit_mode} consultation? "
        f"My preference is {pref_days_str} ({preferred_time_of_day})."
    )

    phone_script = (
        f"Phone Script for calling {provider_name} ({clinic_phone}):\n"
        f"1. GREETING: 'Hello, I would like to schedule an appointment with {provider_name} ({specialty}).'\n"
        f"2. REASON FOR VISIT: 'I am calling regarding {reason}.'\n"
        f"3. INSURANCE CHECKLIST: 'I have {ins_details}. Does your office accept this plan, and is a referral required?'\n"
        f"4. AVAILABILITY: '{avail_prompt}'\n"
        f"5. CONFIRMATION: 'Please confirm the clinic address, arrival time, and any required intake forms.'"
    )

    portal_message = (
        f"Subject: Appointment Request — {reason}\n\n"
        f"Dear {provider_name} Care Team,\n\n"
        f"I would like to request an appointment regarding {reason}. "
        f"My current insurance is {ins_details}.\n"
        f"Please let me know your upcoming available dates and times. "
        f"My preference is {pref_days_str} ({preferred_time_of_day}).\n\n"
        f"Thank you."
    )

    checklist = [
        "Verify in-network coverage with insurance",
        "Obtain PCP referral if required by plan",
        "Prepare current medication list and recent vitals",
        "Bring photo ID and insurance card",
        "Confirm clinic arrival time (typically 15-30 minutes prior to scheduled visit)",
    ]

    return {
        "status": "requested",
        "title": title,
        "phone_script": phone_script,
        "portal_draft": portal_message,
        "checklist": checklist,
    }


# ============================================================================
# Section 3: Post-Visit Auto-Transition Engine (AU-29)
# ============================================================================


def evaluate_post_visit_transitions(
    appointments: List[Any],
    current_time: Optional[datetime] = None,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Evaluates appointments and transitions confirmed visits past end_time to completed.

    Args:
        appointments: List of appointment dicts or Appointment ORM instances.
        current_time: Evaluation anchor datetime (defaults to datetime.now(timezone.utc)).

    Returns:
        Tuple of (completed_ids, prompts) where:
        - completed_ids: List of appointment IDs transitioned to 'completed'
        - prompts: List of structured post-visit prompt payloads
    """
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now_utc = now.replace(tzinfo=timezone.utc)
    else:
        now_utc = now.astimezone(timezone.utc)

    completed_ids: List[str] = []
    prompts: List[Dict[str, Any]] = []

    for appt in appointments:
        if isinstance(appt, dict):
            status = appt.get("status")
            end_time_raw = appt.get("end_time")
            appt_id = str(appt.get("id"))
            title = appt.get("title") or "Appointment"
        else:
            status = getattr(appt, "status", None)
            end_time_raw = getattr(appt, "end_time", None)
            appt_id = str(getattr(appt, "id", ""))
            title = getattr(appt, "title", "Appointment") or "Appointment"

        if status != "confirmed" or not end_time_raw:
            continue

        if isinstance(end_time_raw, str):
            try:
                end_dt = datetime.fromisoformat(end_time_raw)
            except Exception:
                continue
        elif isinstance(end_time_raw, datetime):
            end_dt = end_time_raw
        else:
            continue

        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        else:
            end_dt = end_dt.astimezone(timezone.utc)

        if end_dt <= now_utc:
            completed_ids.append(appt_id)
            prompts.append({
                "appointment_id": appt_id,
                "title": title,
                "prompt_type": "post_visit_followup",
                "message": (
                    f"Your appointment '{title}' has concluded. "
                    f"Would you like to record visit notes or extract next steps?"
                ),
                "suggested_actions": [
                    {
                        "action": "create_after_visit_note",
                        "label": "Draft After-Visit Note",
                        "note_type": "after_visit",
                        "linked_appointment_id": appt_id,
                    },
                    {
                        "action": "create_followup_reminder",
                        "label": "Schedule Reminders",
                    },
                ],
            })

    return completed_ids, prompts


async def sweep_post_visit_transitions(
    db: AsyncSession,
    profile_id: Optional[str] = None,
    current_time: Optional[datetime] = None,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Queries DB for confirmed appointments past end_time, transitions them, and audits.

    Args:
        db: SQLAlchemy AsyncSession.
        profile_id: Optional profile ID to scope the sweep.
        current_time: Evaluation anchor datetime.

    Returns:
        Tuple of (completed_ids, prompts).
    """
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now_utc = now.replace(tzinfo=timezone.utc)
    else:
        now_utc = now.astimezone(timezone.utc)

    stmt = select(Appointment).where(
        Appointment.status == "confirmed",
        Appointment.end_time <= now_utc,
    )
    if profile_id:
        stmt = stmt.where(Appointment.profile_id == profile_id)

    res = await db.execute(stmt)
    records = list(res.scalars().all())

    if not records:
        return [], []

    completed_ids: List[str] = []
    prompts: List[Dict[str, Any]] = []

    for appt in records:
        appt.status = "completed"
        appt.updated_at = now_utc
        completed_ids.append(appt.id)
        prompts.append({
            "appointment_id": appt.id,
            "title": appt.title,
            "prompt_type": "post_visit_followup",
            "message": (
                f"Your appointment '{appt.title}' has concluded. "
                f"Would you like to record visit notes or extract next steps?"
            ),
            "suggested_actions": [
                {
                    "action": "create_after_visit_note",
                    "label": "Draft After-Visit Note",
                    "note_type": "after_visit",
                    "linked_appointment_id": appt.id,
                },
                {
                    "action": "create_followup_reminder",
                    "label": "Schedule Reminders",
                },
            ],
        })

        try:
            await record_audit(
                {
                    "profile_id": appt.profile_id,
                    "action": "update",
                    "tool": "evaluate_post_visit_transitions",
                    "risk": "write_local",
                    "external_ref": f"appointment:{appt.id}",
                    "details": {
                        "previous_status": "confirmed",
                        "new_status": "completed",
                        "reason": "end_time_elapsed",
                    },
                },
                risk="write_local",
            )
        except Exception as audit_err:
            logger.warning(
                "audit_record_failed for appointment post-visit transition %s: %s",
                appt.id,
                audit_err,
            )

    await db.commit()
    return completed_ids, prompts


__all__ = [
    "AppointmentStatus",
    "InvalidStatusTransitionError",
    "VALID_STATUS_TRANSITIONS",
    "evaluate_post_visit_transitions",
    "generate_how_to_book_drafts",
    "sweep_post_visit_transitions",
    "validate_status_transition",
]
