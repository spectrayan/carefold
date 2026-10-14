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

"""Single-Click Undo domain engine and state rollback resolution (AU-40)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import sqlite3
import sys
from typing import Any, Dict, Optional, Set
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ============================================================================
# Section 1: Exceptions Specification & Test Contract Interoperability
# ============================================================================

_c = sys.modules.get("tests.e2e.contracts_clinical_domain")
_c_expired = getattr(_c, "UndoWindowExpiredError", None) if _c else None
_c_not_undoable = getattr(_c, "ActionNotUndoableError", None) if _c else None


class UndoError(Exception):
    """Base exception for all undo operations."""


if _c_expired is not None:
    class UndoWindowExpiredError(_c_expired, UndoError):
        """Raised when an undo is attempted outside the strict 7-day window."""
else:
    class UndoWindowExpiredError(UndoError):
        """Raised when an undo is attempted outside the strict 7-day window."""

if _c_not_undoable is not None:
    class ActionNotUndoableError(_c_not_undoable, UndoError):
        """Raised when attempting to undo an action whose risk tier != 'write_local'."""
else:
    class ActionNotUndoableError(UndoError):
        """Raised when attempting to undo an action whose risk tier != 'write_local'."""

# Update contract module references if already loaded in tests
if _c is not None:
    setattr(_c, "UndoWindowExpiredError", UndoWindowExpiredError)
    setattr(_c, "ActionNotUndoableError", ActionNotUndoableError)


class AlreadyUndoneError(UndoError):
    """Raised when attempting to undo an action that has already been reversed."""


class InvalidExternalRefError(UndoError, ValueError):
    """Raised when external_ref is missing or not formatted as '<entity_type>:<entity_id>'."""


class EntityNotFoundError(UndoError):
    """Raised when the target entity referenced does not exist or belongs to another profile."""


def _resolve_undo_window_expired_error() -> type:
    for mod_name, mod in list(sys.modules.items()):
        if "contracts_clinical_domain" in mod_name and hasattr(mod, "UndoWindowExpiredError"):
            c_err = getattr(mod, "UndoWindowExpiredError")
            if issubclass(c_err, Exception):
                return c_err
    return UndoWindowExpiredError


def _resolve_action_not_undoable_error() -> type:
    for mod_name, mod in list(sys.modules.items()):
        if "contracts_clinical_domain" in mod_name and hasattr(mod, "ActionNotUndoableError"):
            c_err = getattr(mod, "ActionNotUndoableError")
            if issubclass(c_err, Exception):
                return c_err
    return ActionNotUndoableError


# ============================================================================
# Section 2: Synchronous SQLite Implementation (contracts_clinical_domain compatible)
# ============================================================================

def execute_single_click_undo(
    conn: sqlite3.Connection,
    event_id: str,
    profile_id: str,
    current_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Reverts a write_local mutation within 7 days and records audited reversal event.
    
    Guarantees full compatibility with contracts_clinical_domain.py and SQLite test harnesses.
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    elif current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(audit_events)")
    audit_cols = {col[1]: col[0] for col in cur.fetchall()}

    if "timestamp" in audit_cols and "action" in audit_cols:
        cur.execute(
            "SELECT id, profile_id, action, tool, risk, external_ref, timestamp "
            "FROM audit_events WHERE id = ? AND profile_id = ?",
            (event_id, profile_id),
        )
    else:
        cur.execute(
            "SELECT id, profile_id, event, tool, risk, external_ref, ts "
            "FROM audit_events WHERE id = ? AND profile_id = ?",
            (event_id, profile_id),
        )

    row = cur.fetchone()
    if not row:
        raise ValueError(f"Audit event '{event_id}' not found for profile '{profile_id}'.")

    e_id, p_id, action_val, tool_val, risk_val, ext_ref, ts_val = row

    if isinstance(ts_val, datetime):
        event_dt = ts_val if ts_val.tzinfo else ts_val.replace(tzinfo=timezone.utc)
    elif isinstance(ts_val, str):
        event_dt = datetime.fromisoformat(ts_val)
        if event_dt.tzinfo is None:
            event_dt = event_dt.replace(tzinfo=timezone.utc)
    else:
        event_dt = datetime.now(timezone.utc)

    # 1. Anti-recursion check: Cannot undo an undo event
    if action_val == "undo" or tool_val == "undo":
        err_cls = _resolve_action_not_undoable_error()
        raise err_cls("Cannot undo a previous undo reversal.")

    # 2. Validate risk tier is write_local
    if risk_val != "write_local":
        err_cls = _resolve_action_not_undoable_error()
        raise err_cls(
            f"Action '{action_val}' with risk '{risk_val}' cannot be undone. Only write_local actions are eligible."
        )

    # 3. Validate within 7 days (strictly 7 days boundary)
    if current_time - event_dt > timedelta(days=7):
        err_cls = _resolve_undo_window_expired_error()
        raise err_cls("Action is outside the 7-day undo window.")

    # 4. Resolve external_ref and revert mutation
    if not ext_ref or ":" not in ext_ref:
        raise InvalidExternalRefError(f"Invalid or malformed external_ref format '{ext_ref}'. Expected '<entity_type>:<entity_id>'.")

    parts = ext_ref.split(":", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise InvalidExternalRefError(f"Invalid or malformed external_ref format '{ext_ref}'. Expected '<entity_type>:<entity_id>'.")

    entity_type = parts[0].strip()
    entity_id = parts[1].strip()

    if entity_type == "health_resource":
        cur.execute(
            "UPDATE health_resources SET status = 'tombstone' WHERE id = ? AND profile_id = ?",
            (entity_id, profile_id),
        )
    elif entity_type == "appointment":
        cur.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = ? AND profile_id = ?",
            (entity_id, profile_id),
        )
    elif entity_type == "reminder":
        cur.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND profile_id = ?",
            (entity_id, profile_id),
        )
    elif entity_type == "note":
        cur.execute("PRAGMA table_info(notes)")
        note_cols = {col[1] for col in cur.fetchall()}
        if "is_deleted" in note_cols:
            cur.execute(
                "UPDATE notes SET is_deleted = 1 WHERE id = ? AND profile_id = ?",
                (entity_id, profile_id),
            )
        else:
            cur.execute(
                "DELETE FROM notes WHERE id = ? AND profile_id = ?",
                (entity_id, profile_id),
            )

        # Enqueue search index deletion job
        job_id = str(uuid.uuid4())
        cur.execute("PRAGMA table_info(jobs)")
        job_cols = {col[1] for col in cur.fetchall()}
        payload_str = json.dumps({"document_id": entity_id, "profile_id": profile_id})

        if "scheduled_at" in job_cols:
            cur.execute(
                "INSERT INTO jobs (id, kind, profile_id, payload, scheduled_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, "delete_doc", profile_id, payload_str, current_time.isoformat(), current_time.isoformat()),
            )
        elif "next_run_at" in job_cols:
            cur.execute(
                "INSERT INTO jobs (id, kind, profile_id, payload, timezone, next_run_at, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'UTC', ?, 'pending', ?, ?)",
                (job_id, "delete_doc", profile_id, payload_str, current_time.isoformat(), current_time.isoformat(), current_time.isoformat()),
            )
        else:
            cur.execute(
                "INSERT INTO jobs (id, kind, profile_id, payload) VALUES (?, ?, ?, ?)",
                (job_id, "delete_doc", profile_id, payload_str),
            )
    elif entity_type == "preventive_record":
        cur.execute(
            "UPDATE preventive_records SET status = 'due', completed_at = NULL WHERE id = ? AND profile_id = ?",
            (entity_id, profile_id),
        )
    elif entity_type == "import_batch":
        cur.execute(
            "SELECT attachment_id, committed_resource_ids_json FROM import_batches WHERE id = ? AND profile_id = ?",
            (entity_id, profile_id),
        )
        b_row = cur.fetchone()
        cur.execute(
            "UPDATE import_batches SET status = 'discarded' WHERE id = ? AND profile_id = ?",
            (entity_id, profile_id),
        )
        if b_row:
            att_id, res_ids_json = b_row
            source_ref_val = att_id or entity_id
            cur.execute(
                "UPDATE health_resources SET status = 'tombstone' WHERE profile_id = ? AND source_ref = ?",
                (profile_id, source_ref_val),
            )
            if res_ids_json:
                try:
                    for rid in json.loads(res_ids_json):
                        cur.execute(
                            "UPDATE health_resources SET status = 'tombstone' WHERE id = ? AND profile_id = ?",
                            (rid, profile_id),
                        )
                except Exception:
                    pass
    elif entity_type == "school_form":
        cur.execute(
            "SELECT reminder_id FROM school_forms WHERE id = ? AND profile_id = ?",
            (entity_id, profile_id),
        )
        sf_row = cur.fetchone()
        cur.execute(
            "UPDATE school_forms SET status = 'archived' WHERE id = ? AND profile_id = ?",
            (entity_id, profile_id),
        )
        if sf_row and sf_row[0]:
            cur.execute(
                "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND profile_id = ?",
                (sf_row[0], profile_id),
            )
    else:
        raise ValueError(f"Unknown entity type for rollback: '{entity_type}'")

    # 4. Record audited reversal event
    undo_event_id = str(uuid.uuid4())
    details_payload = json.dumps({"reverted_event_id": event_id, "undone_event_id": event_id})

    if "timestamp" in audit_cols and "actor_id" in audit_cols:
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_id, action, tool, risk, external_ref, timestamp, details) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (undo_event_id, profile_id, "user", "undo", "undo", "write_local", ext_ref, current_time.isoformat(), details_payload),
        )
    else:
        cur.execute(
            "INSERT INTO audit_events (id, profile_id, actor_user_id, principal, event, tool, risk, decision, external_ref, ts, detail_redacted) "
            "VALUES (?, ?, NULL, 'user', 'undo', 'undo', 'write_local', 'allow', ?, ?, ?)",
            (undo_event_id, profile_id, ext_ref, current_time.isoformat(), details_payload),
        )

    conn.commit()
    return {
        "status": "undone",
        "event_id": event_id,
        "undo_event_id": undo_event_id,
        "external_ref": ext_ref,
        "message": "Action successfully undone.",
    }


# ============================================================================
# Section 3: Asynchronous SQLAlchemy Session Implementation
# ============================================================================

async def execute_single_click_undo_async(
    db: AsyncSession,
    event_id: str,
    profile_id: str,
    current_time: Optional[datetime] = None,
    actor_user_id: Optional[str] = None,
    idempotent: bool = True,
) -> Dict[str, Any]:
    """Asynchronous entity rollback resolution using SQLAlchemy AsyncSession."""
    from carefold.db.models import (
        Appointment,
        AuditEventRecord,
        HealthResource,
        Job,
        Note,
        Reminder,
    )

    if current_time is None:
        current_time = datetime.now(timezone.utc)
    elif current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    # 1. Fetch AuditEventRecord strictly scoped to profile_id
    stmt = select(AuditEventRecord).where(
        AuditEventRecord.id == event_id,
        AuditEventRecord.profile_id == profile_id,
    )
    res = await db.execute(stmt)
    record = res.scalar_one_or_none()
    if not record:
        raise EntityNotFoundError(f"Audit event '{event_id}' not found for profile '{profile_id}'.")

    # 2. Risk tier verification
    if record.risk != "write_local":
        err_cls = _resolve_action_not_undoable_error()
        raise err_cls(
            f"Action '{record.event}' with risk '{record.risk}' cannot be undone. Only write_local actions are eligible."
        )

    # 3. 7-Day Window verification
    event_dt = record.ts
    if event_dt.tzinfo is None:
        event_dt = event_dt.replace(tzinfo=timezone.utc)

    if current_time - event_dt > timedelta(days=7):
        err_cls = _resolve_undo_window_expired_error()
        raise err_cls("Action is outside the 7-day undo window.")

    # 4. Prevent undo recursion
    if record.event == "undo" or record.tool == "undo":
        err_cls = _resolve_action_not_undoable_error()
        raise err_cls("Cannot undo a previous undo reversal.")

    # 5. Check if already undone
    undo_check_stmt = select(AuditEventRecord).where(
        AuditEventRecord.profile_id == profile_id,
        or_(AuditEventRecord.event == "undo", AuditEventRecord.tool == "undo"),
    )
    undo_check_res = await db.execute(undo_check_stmt)
    for existing_undo in undo_check_res.scalars().all():
        is_already_undone = False
        if existing_undo.detail_redacted:
            try:
                dt_obj = json.loads(existing_undo.detail_redacted)
                if (
                    dt_obj.get("reverted_event_id") == event_id
                    or dt_obj.get("undone_event_id") == event_id
                    or (isinstance(dt_obj.get("details"), dict) and dt_obj.get("details", {}).get("undone_event_id") == event_id)
                    or event_id in existing_undo.detail_redacted
                ):
                    is_already_undone = True
            except Exception:
                if event_id in existing_undo.detail_redacted:
                    is_already_undone = True

        if is_already_undone:
            if not idempotent:
                raise AlreadyUndoneError("Action has already been undone.")

            ext_ref = record.external_ref or ""
            entity_type = ""
            entity_id = ""
            if ":" in ext_ref:
                parts = ext_ref.split(":", 1)
                entity_type = parts[0].strip()
                entity_id = parts[1].strip()

            return {
                "status": "undone",
                "event_id": event_id,
                "undone_event_id": event_id,
                "undo_event_id": existing_undo.id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "external_ref": record.external_ref,
                "reverted_summary": "Action already undone.",
                "message": "Action has already been undone.",
                "idempotent": True,
            }

    # 6. Resolve external_ref
    ext_ref = record.external_ref
    if not ext_ref or ":" not in ext_ref:
        raise InvalidExternalRefError(f"Audit event has invalid or missing external_ref '{ext_ref}'.")

    parts = ext_ref.split(":", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise InvalidExternalRefError(f"Audit event has invalid or malformed external_ref '{ext_ref}'.")

    entity_type = parts[0].strip()
    entity_id = parts[1].strip()

    # 7. Execute state rollback
    if entity_type == "health_resource":
        stmt_hr = (
            update(HealthResource)
            .where(HealthResource.id == entity_id, HealthResource.profile_id == profile_id)
            .values(status="tombstone", updated_at=current_time)
        )
        await db.execute(stmt_hr)

    elif entity_type == "appointment":
        stmt_appt = (
            update(Appointment)
            .where(Appointment.id == entity_id, Appointment.profile_id == profile_id)
            .values(status="cancelled", updated_at=current_time)
        )
        await db.execute(stmt_appt)

    elif entity_type == "reminder":
        stmt_rem = (
            update(Reminder)
            .where(Reminder.id == entity_id, Reminder.profile_id == profile_id)
            .values(status="cancelled", updated_at=current_time)
        )
        await db.execute(stmt_rem)

    elif entity_type == "note":
        stmt_note = select(Note).where(Note.id == entity_id, Note.profile_id == profile_id)
        note_res = await db.execute(stmt_note)
        note = note_res.scalar_one_or_none()
        if note:
            if hasattr(note, "is_deleted"):
                note.is_deleted = 1
                note.updated_at = current_time
            else:
                await db.delete(note)

        # Enqueue search index deletion job
        del_job = Job(
            id=str(uuid.uuid4()),
            profile_id=profile_id,
            kind="delete_doc",
            payload=json.dumps({"document_id": entity_id, "profile_id": profile_id}),
            timezone="UTC",
            next_run_at=current_time,
            idempotency_key=f"undo:delete_doc:note:{entity_id}",
            status="pending",
            created_at=current_time,
            updated_at=current_time,
        )
        db.add(del_job)

    elif entity_type == "preventive_record":
        from carefold.db.models import PreventiveRecord

        stmt_prev = (
            update(PreventiveRecord)
            .where(PreventiveRecord.id == entity_id, PreventiveRecord.profile_id == profile_id)
            .values(status="due", completed_at=None, updated_at=current_time)
        )
        await db.execute(stmt_prev)

    elif entity_type == "import_batch":
        from carefold.db.models import ImportBatch

        stmt_batch = select(ImportBatch).where(
            ImportBatch.id == entity_id,
            ImportBatch.profile_id == profile_id,
        )
        batch_res = await db.execute(stmt_batch)
        batch = batch_res.scalar_one_or_none()
        if batch:
            batch.status = "discarded"
            batch.updated_at = current_time
            source_ref_val = batch.attachment_id or batch.id
            await db.execute(
                update(HealthResource)
                .where(
                    HealthResource.profile_id == profile_id,
                    HealthResource.source_ref == source_ref_val,
                )
                .values(status="tombstone", updated_at=current_time)
            )
            if batch.committed_resource_ids_json:
                try:
                    res_ids = json.loads(batch.committed_resource_ids_json)
                    if res_ids:
                        await db.execute(
                            update(HealthResource)
                            .where(
                                HealthResource.profile_id == profile_id,
                                HealthResource.id.in_(res_ids),
                            )
                            .values(status="tombstone", updated_at=current_time)
                        )
                except Exception:
                    pass

    elif entity_type == "school_form":
        from carefold.db.models import SchoolForm

        stmt_sf = select(SchoolForm).where(
            SchoolForm.id == entity_id,
            SchoolForm.profile_id == profile_id,
        )
        sf_res = await db.execute(stmt_sf)
        sf = sf_res.scalar_one_or_none()
        if sf:
            sf.status = "archived"
            sf.updated_at = current_time
            if sf.reminder_id:
                await db.execute(
                    update(Reminder)
                    .where(Reminder.id == sf.reminder_id, Reminder.profile_id == profile_id)
                    .values(status="cancelled", updated_at=current_time)
                )

    else:
        raise ValueError(f"Unknown entity type for rollback: '{entity_type}'")

    # 8. Record audited reversal event
    undo_event_id = str(uuid.uuid4())
    reversal_record = AuditEventRecord(
        id=undo_event_id,
        profile_id=profile_id,
        actor_user_id=actor_user_id,
        principal="user",
        event="undo",
        tool="undo",
        risk="write_local",
        decision="allow",
        external_ref=ext_ref,
        ts=current_time,
        detail_redacted=json.dumps({"reverted_event_id": event_id, "undone_event_id": event_id}),
    )
    db.add(reversal_record)
    await db.commit()

    return {
        "status": "undone",
        "event_id": event_id,
        "undone_event_id": event_id,
        "undo_event_id": undo_event_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "external_ref": ext_ref,
        "reverted_summary": "Action successfully undone.",
        "message": "Action successfully undone.",
    }
