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

"""Database-backed audit logger with SHA-256 payload hashing and secondary JSONL sink."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid
import weakref

from carefold.audit.redaction import redact_audit_event
from carefold.config import settings
from carefold.constants.defaults import DEFAULT_AUDIT_LIMIT
from carefold.constants.paths import DEFAULT_AUDIT_LOG_FILE, LOGS_DIR
from carefold.db.models import AuditEventRecord
from carefold.db.session import get_session_factory
from carefold.schemas.audit import AuditEvent

logger = logging.getLogger(__name__)

# Loop-safe lock registry: ensures each event loop has its own asyncio.Lock
_loop_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = weakref.WeakKeyDictionary()
_locks_guard = threading.Lock()

# Thread-safe file append lock: protects file descriptor across threads and loops
_file_lock = threading.Lock()


def _get_loop_lock() -> asyncio.Lock:
    """Retrieves or creates an asyncio.Lock bound to the current running event loop."""
    loop = asyncio.get_running_loop()
    with _locks_guard:
        lock = _loop_locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _loop_locks[loop] = lock
        return lock


def compute_payload_hash(payload: Any) -> Optional[str]:
    """Computes SHA-256 hash over canonical JSON representation (sort_keys=True).

    Returns None if payload is None or empty.
    """
    if payload is None:
        return None
    if isinstance(payload, str) and not payload.strip():
        return None
    try:
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    except Exception as err:
        logger.debug("Failed to compute payload hash: %s", err)
        return None


async def _persist_to_db(record: AuditEventRecord, db: Optional[Any] = None, session_factory: Optional[Any] = None) -> None:
    """Persists an AuditEventRecord to the relational database with non-blocking fault isolation."""
    try:
        if db is not None:
            db.add(record)
            await db.commit()
            return

        # Check for FastAPI dependency override (e.g. during pytest with in-memory SQLite)
        written = False
        try:
            from carefold.main import app
            from carefold.api.deps import get_db

            override = app.dependency_overrides.get(get_db)
            if override is not None:
                gen = override()
                if hasattr(gen, "__anext__"):
                    session = await gen.__anext__()
                    try:
                        session.add(record)
                        await session.commit()
                        written = True
                    finally:
                        try:
                            await gen.__anext__()
                        except StopAsyncIteration:
                            pass
                elif hasattr(gen, "__next__"):
                    session = next(gen)
                    try:
                        session.add(record)
                        await session.commit()
                        written = True
                    finally:
                        try:
                            next(gen)
                        except StopIteration:
                            pass
        except Exception as override_err:
            logger.debug("Dependency override DB session failed: %s", override_err)

        if not written:
            factory = session_factory or get_session_factory()
            async with factory() as session:
                session.add(record)
                await session.commit()
    except Exception as err:
        # Non-blocking fault isolation: log warning and do not crash agent execution
        logger.warning("Failed to persist audit event to database: %s", err)


async def record_audit(
    event: Union[AuditEvent, Dict[str, Any]],
    log_path: Optional[Union[Path, str]] = None,
    store_bodies: Optional[bool] = None,
    workspace_root: Optional[Union[Path, str]] = None,
    *,
    payload: Any = None,
    payload_hash: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    principal: Optional[str] = None,
    risk: Optional[str] = None,
    decision: Optional[str] = None,
    external_ref: Optional[str] = None,
    run_id: Optional[str] = None,
    session_factory: Any = None,
    db: Any = None,
) -> AuditEvent:
    """Records an audit event to the SQL database and secondary append-only JSONL sink.

    Guarantees:
    1. Zero-Body redaction by default (strips prompt and completion unless store_bodies is True).
    2. Primary persistence to AuditEventRecord in carefold.db via get_session_factory().
    3. SHA-256 payload hash computed over canonical JSON representation for tool calls and actions.
    4. Optional secondary sink writing to logs/audit.jsonl.
    5. Non-blocking fault isolation: Database or disk write errors do not crash caller requests.
    """
    if store_bodies is None:
        store_bodies = settings.audit_store_bodies

    redacted_dict = redact_audit_event(event, store_bodies=store_bodies)
    safe_event = AuditEvent(**redacted_dict)

    # Extract raw parameters from original event
    if isinstance(event, dict):
        raw_data = dict(event)
    elif hasattr(event, "model_dump"):
        raw_data = event.model_dump()
    elif hasattr(event, "__dict__"):
        raw_data = dict(event.__dict__)
    else:
        raw_data = {}

    event_type = raw_data.get("event") or safe_event.event or "run"
    tool_name = raw_data.get("tool") or safe_event.tool
    profile_id = raw_data.get("profile_id") or safe_event.profile_id
    effective_run_id = run_id or raw_data.get("run_id") or raw_data.get("thread_id") or safe_event.thread_id
    effective_actor_user_id = actor_user_id or raw_data.get("actor_user_id")
    effective_principal = principal or raw_data.get("principal") or "user"
    effective_risk = risk or raw_data.get("risk")

    effective_decision = decision or raw_data.get("decision")
    if not effective_decision:
        if safe_event.allowed is True:
            effective_decision = "allow"
        elif safe_event.allowed is False:
            effective_decision = "refuse"

    # Compute or resolve payload_hash
    effective_payload_hash = payload_hash or raw_data.get("payload_hash")
    if not effective_payload_hash:
        resolved_payload = payload if payload is not None else raw_data.get("payload")
        if resolved_payload is None and event_type == "tool":
            resolved_payload = raw_data.get("args") or raw_data.get("params") or raw_data.get("tool_input")
        if resolved_payload is None and raw_data.get("prompt"):
            resolved_payload = raw_data.get("prompt")
        if resolved_payload is not None:
            effective_payload_hash = compute_payload_hash(resolved_payload)

    effective_external_ref = external_ref or raw_data.get("external_ref")

    # Detail redacted JSON metadata: stores agent_id, reason, duration_ms, prompt/completion if allowed
    detail_data = {
        "agent_id": safe_event.agent_id,
        "skill_id": safe_event.skill_id,
        "skill_version": safe_event.skill_version,
        "allowed": safe_event.allowed,
        "reason": safe_event.reason,
        "duration_ms": safe_event.duration_ms,
        "thread_id": safe_event.thread_id,
    }
    if store_bodies:
        if safe_event.prompt:
            detail_data["prompt"] = safe_event.prompt
        if safe_event.completion:
            detail_data["completion"] = safe_event.completion
    if raw_data.get("details") is not None:
        detail_data["details"] = raw_data.get("details")
    if raw_data.get("action") is not None:
        detail_data["action"] = raw_data.get("action")
    detail_redacted = json.dumps({k: v for k, v in detail_data.items() if v is not None}, default=str)


    # Timestamp parsing
    ts_val = raw_data.get("ts") or safe_event.ts
    if isinstance(ts_val, datetime):
        event_ts = ts_val if ts_val.tzinfo else ts_val.replace(tzinfo=timezone.utc)
    elif isinstance(ts_val, str):
        try:
            event_ts = datetime.fromisoformat(ts_val)
            if not event_ts.tzinfo:
                event_ts = event_ts.replace(tzinfo=timezone.utc)
        except Exception:
            event_ts = datetime.now(timezone.utc)
    else:
        event_ts = datetime.now(timezone.utc)

    record_id = raw_data.get("id") or str(uuid.uuid4())

    record = AuditEventRecord(
        id=record_id,
        ts=event_ts,
        profile_id=str(profile_id).strip() if profile_id else None,
        actor_user_id=str(effective_actor_user_id).strip() if effective_actor_user_id else None,
        principal=str(effective_principal),
        run_id=str(effective_run_id).strip() if effective_run_id else None,
        event=str(event_type),
        tool=str(tool_name).strip() if tool_name else None,
        risk=str(effective_risk).strip() if effective_risk else None,
        decision=str(effective_decision).strip() if effective_decision else None,
        payload_hash=effective_payload_hash,
        external_ref=str(effective_external_ref).strip() if effective_external_ref else None,
        detail_redacted=detail_redacted,
    )

    # 1. Primary Sink: SQL Database persistence
    await _persist_to_db(record, db=db, session_factory=session_factory)

    # 2. Secondary Sink: JSONL append
    if workspace_root and not log_path:
        target_path = Path(workspace_root) / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE
    else:
        target_path = Path(log_path) if log_path else settings.get_audit_log_path()

    try:
        line_data = safe_event.model_dump(exclude_none=True)
        if effective_payload_hash:
            line_data["payload_hash"] = effective_payload_hash
        line = json.dumps(line_data) + "\n"
        lock = _get_loop_lock()
        async with lock:
            await asyncio.to_thread(_append_line, target_path, line)
    except Exception as err:
        logger.warning("Failed to write audit event to %s: %s", target_path, err)

    return safe_event


def _append_line(target_path: Path, line: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock:
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()


async def get_recent_audit_events(
    log_path: Optional[Union[Path, str]] = None,
    limit: int = DEFAULT_AUDIT_LIMIT,
    agent_id: Optional[str] = None,
    event: Optional[str] = None,
    full: bool = False,
    profile_id: Optional[str] = None,
) -> Tuple[int, List[AuditEvent]]:
    """Reads recent audit events, newest first, with optional filtering from JSONL or database."""
    target_path = Path(log_path) if log_path else settings.get_audit_log_path()
    if not target_path.is_file():
        return 0, []

    events: List[AuditEvent] = []
    total_matching = 0

    try:
        raw_lines = await asyncio.to_thread(target_path.read_text, encoding="utf-8")
        lines = [line.strip() for line in raw_lines.splitlines() if line.strip()]

        for line in reversed(lines):
            try:
                data = json.loads(line)
            except Exception:
                continue

            if agent_id and data.get("agent_id") != agent_id:
                continue
            if event and data.get("event") != event:
                continue
            if profile_id and data.get("profile_id") != profile_id:
                continue

            total_matching += 1

            if len(events) < limit:
                if not full:
                    data.pop("prompt", None)
                    data.pop("completion", None)
                try:
                    events.append(AuditEvent(**data))
                except Exception:
                    pass

    except Exception as err:
        logger.warning("Failed to read audit events from %s: %s", target_path, err)

    return total_matching, events


def read_recent_audit_events(
    limit: int = DEFAULT_AUDIT_LIMIT,
    log_path: Optional[Union[Path, str]] = None,
    workspace_root: Optional[Union[Path, str]] = None,
) -> List[AuditEvent]:
    """Synchronous reader returning the last N audit events in chronological order."""
    if workspace_root and not log_path:
        target_path = Path(workspace_root) / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE
    else:
        target_path = Path(log_path) if log_path else settings.get_audit_log_path()

    if not target_path.is_file():
        return []

    lines = [l.strip() for l in target_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    events: List[AuditEvent] = []
    selected = lines[-limit:] if limit > 0 else []
    for line in selected:
        try:
            events.append(AuditEvent(**json.loads(line)))
        except Exception:
            pass
    return events


class AuditLogger:
    """Database-backed audit logging facility with non-blocking persistence and JSONL sink."""

    @staticmethod
    def compute_payload_hash(payload: Any) -> Optional[str]:
        """Computes SHA-256 hash over canonical JSON representation."""
        return compute_payload_hash(payload)

    @classmethod
    async def record_audit(
        cls,
        event: Union[AuditEvent, Dict[str, Any]],
        **kwargs: Any,
    ) -> AuditEvent:
        """Records an audit event to SQL database and secondary sink."""
        return await record_audit(event, **kwargs)

    @classmethod
    async def record(
        cls,
        event: Union[AuditEvent, Dict[str, Any]],
        **kwargs: Any,
    ) -> AuditEvent:
        """Convenience alias for record_audit."""
        return await record_audit(event, **kwargs)

    @classmethod
    async def get_recent_events(
        cls,
        **kwargs: Any,
    ) -> Tuple[int, List[AuditEvent]]:
        """Retrieves recent audit events."""
        return await get_recent_audit_events(**kwargs)

    @staticmethod
    def read_recent_events(
        **kwargs: Any,
    ) -> List[AuditEvent]:
        """Synchronous reader for recent audit events."""
        return read_recent_audit_events(**kwargs)


__all__ = [
    "compute_payload_hash",
    "record_audit",
    "get_recent_audit_events",
    "read_recent_audit_events",
    "AuditLogger",
]
