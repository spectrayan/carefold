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

"""Async append-only JSONL audit logger with concurrency lock and fault isolation."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple, Union
import weakref

from carefold.audit.redaction import redact_audit_event
from carefold.config import settings
from carefold.constants.defaults import DEFAULT_AUDIT_LIMIT
from carefold.constants.paths import DEFAULT_AUDIT_LOG_FILE, LOGS_DIR
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


async def record_audit(
    event: Union[AuditEvent, Dict[str, Any]],
    log_path: Optional[Union[Path, str]] = None,
    store_bodies: Optional[bool] = None,
    workspace_root: Optional[Union[Path, str]] = None,
) -> AuditEvent:
    """Appends an audit event to the append-only JSONL log.

    Guarantees:
    1. Zero-Body redaction by default (strips prompt and completion unless store_bodies is True).
    2. Atomic append under async concurrency via per-loop asyncio.Lock and thread-safe file lock.
    3. Fault isolation: Disk write errors do not crash user requests.
    """
    if store_bodies is None:
        store_bodies = settings.audit_store_bodies

    redacted_dict = redact_audit_event(event, store_bodies=store_bodies)
    safe_event = AuditEvent(**redacted_dict)

    if workspace_root and not log_path:
        target_path = Path(workspace_root) / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE
    else:
        target_path = Path(log_path) if log_path else settings.get_audit_log_path()

    try:
        line = json.dumps(safe_event.model_dump(exclude_none=True)) + "\n"
        lock = _get_loop_lock()
        async with lock:
            # Run blocking file write in thread pool with thread-safe lock
            await asyncio.to_thread(_append_line, target_path, line)
    except Exception as err:
        # Fault isolation: log warning but never raise
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
    """Reads recent audit events, newest first, with optional filtering."""
    target_path = Path(log_path) if log_path else settings.get_audit_log_path()
    if not target_path.is_file():
        return 0, []

    events: List[AuditEvent] = []
    total_matching = 0

    try:
        raw_lines = await asyncio.to_thread(target_path.read_text, encoding="utf-8")
        lines = [line.strip() for line in raw_lines.splitlines() if line.strip()]

        # Iterate newest first
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
