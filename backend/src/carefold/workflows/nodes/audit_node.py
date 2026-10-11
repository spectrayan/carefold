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

"""Zero-body audit event logging node (F-31).

Logs audit records to the append-only JSONL log with ISO8601 timestamps.
Applies Zero-Body privacy redaction via `carefold.audit.redaction.redact_audit_event`
to strip user prompts and completion text by default.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict

from carefold.audit.logger import _file_lock
from carefold.audit.redaction import redact_audit_event
from carefold.config import settings
from carefold.constants.paths import DEFAULT_AUDIT_LOG_FILE, LOGS_DIR
from carefold.workflows.nodes.base import BaseNode

logger = logging.getLogger(__name__)


class AuditNode(BaseNode):
    """Zero-body audit event logger."""

    def __init__(self, name: str = "audit") -> None:
        super().__init__(name=name)

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Flushes an audit event to the append-only JSONL log with an ISO8601 timestamp."""
        iso_timestamp = datetime.now(timezone.utc).isoformat()
        agent_id = str(state.get("current_agent") or state.get("agent_id") or "carefold-agent")
        thread_id = state.get("thread_id")

        event_type = "refuse" if (state.get("is_refusal") or state.get("refused")) else ("error" if state.get("error") else "run")
        allowed = not (state.get("is_refusal") or state.get("refused"))

        audit_payload: Dict[str, Any] = {
            "timestamp": iso_timestamp,
            "ts": iso_timestamp,
            "agent_id": agent_id,
            "event": event_type,
            "allowed": allowed,
        }
        if thread_id:
            audit_payload["thread_id"] = str(thread_id)
        if state.get("refusal_reason"):
            audit_payload["reason"] = str(state["refusal_reason"])
        if state.get("prompt"):
            audit_payload["prompt"] = str(state["prompt"])
        if state.get("output"):
            audit_payload["completion"] = str(state["output"])

        # Zero-body privacy redaction
        store_bodies = bool(state.get("store_bodies", settings.audit_store_bodies))
        redacted = redact_audit_event(audit_payload, store_bodies=store_bodies)
        # Guarantee timestamp and ts presence for F-31 assertion compatibility
        redacted["timestamp"] = iso_timestamp
        redacted["ts"] = iso_timestamp

        # Determine target audit log path
        if settings.audit_log_path:
            log_path = Path(settings.audit_log_path)
        else:
            ws_root = state.get("workspace_root")
            if ws_root and not (Path(ws_root) / "backend").is_dir() and Path(ws_root).resolve() != settings.workspace_root:
                log_path = Path(ws_root) / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE
            else:
                log_path = settings.get_audit_log_path()

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(redacted) + "\n"
            with _file_lock:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
        except Exception as err:
            logger.warning("AuditNode failed to write audit event to %s: %s", log_path, err)

        accumulated = list(state.get("audit_events", []))
        accumulated.append(redacted)

        return {
            "audit_logged": True,
            "audit_events": accumulated,
            "next_step": "done",
        }


__all__ = ["AuditNode"]
