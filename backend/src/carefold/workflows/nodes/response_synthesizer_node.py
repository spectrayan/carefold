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

"""Response synthesis and output guardrailing node (R5).

Consolidates multi-agent specialist outputs into a unified patient consultation master agenda,
reconciles cardiorenal tradeoffs (fluid restriction vs renal clearance) into collaborative
doctor-discussion questions without prescribing or diagnosing, deduplicates constituent disclaimers,
appends the canonical disclaimer footer, and records zero-body audit events.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Union

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import AIMessage
from langgraph.store.base import BaseStore

from carefold.audit.logger import _file_lock
from carefold.audit.redaction import redact_audit_event
from carefold.config import settings
from carefold.constants.paths import DEFAULT_AUDIT_LOG_FILE, LOGS_DIR
from carefold.workflows.nodes.base import BaseNode

logger = logging.getLogger(__name__)

CANONICAL_DISCLAIMER = (
    "DISCLAIMER: Carefold is an educational and administrative navigation companion, not a licensed healthcare provider. "
    "Do not alter prescription medications or therapy plans without consulting your physician."
)

CONSTITUENT_DISCLAIMER_PATTERNS = [
    re.compile(r"DISCLAIMER:.*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
    re.compile(r"NOTE: I am not a (?:doctor|licensed physician|clinician).*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
    re.compile(r"Please consult your (?:doctor|physician) before.*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
    re.compile(r"\*Disclaimer:.*?\*(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
]


class ResponseSynthesizerNode(BaseNode):
    """Discrete node consolidating multi-agent specialist outputs into a master agenda."""

    def __init__(self, name: str = "response_synthesizer") -> None:
        super().__init__(name=name)

    async def __call__(
        self, state: Dict[str, Any], *, store: Optional[BaseStore] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """LangGraph node execution callable interface supporting store injection."""
        return await self.execute(state, store=store, **kwargs)

    @classmethod
    def strip_reference_preamble(cls, text: str) -> str:
        """Strips robotic 'Based on the provided reference document/guide...' opening phrases."""
        if not text:
            return ""
        pattern = r"^(?:(?:\*|_){0,2}(?:(?:Based on|According to|From) (?:the )?(?:provided )?reference (?:document|guide|material|checklist|information|docs?)(?: provided)?)[,:]?(?:\*|_){0,2}[,:]?\s*)"
        cleaned = re.sub(pattern, "", text.lstrip(), flags=re.IGNORECASE)
        cleaned = cleaned.lstrip("*_ \t")
        if cleaned and cleaned != text:
            cleaned = cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper()
        return cleaned

    @classmethod
    def strip_disclaimers(cls, text: str) -> str:
        """Removes constituent agent disclaimers and reference preambles from specialist text."""
        if not text:
            return ""
        cleaned = cls.strip_reference_preamble(text)
        for pat in CONSTITUENT_DISCLAIMER_PATTERNS:
            cleaned = pat.sub("", cleaned).strip()
        cleaned = re.sub(
            r"(?m)^\s*(?:\*|_)?DISCLAIMER:.*(?:\*|_)?\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        return cleaned

    @classmethod
    def synthesize_response(cls, state: Dict[str, Any]) -> str:
        """Synthesizes specialist outputs into a master agenda with cardiorenal reconciliation."""
        specialist_outputs = state.get("specialist_outputs")
        if specialist_outputs is None:
            specialist_outputs = {}

        # If no specialist_outputs, check if single output exists in state
        if not specialist_outputs:
            single_out = state.get("output")
            if not single_out:
                for m in reversed(state.get("messages", [])):
                    if isinstance(m, AIMessage) and m.content:
                        single_out = m.content
                        break
                    elif isinstance(m, dict) and m.get("role") in ("assistant", "ai") and m.get("content"):
                        single_out = m.get("content")
                        break
            if single_out:
                clean_text = cls.strip_disclaimers(str(single_out))
                full_output = f"{clean_text}\n\n{CANONICAL_DISCLAIMER}"
                state["output"] = full_output
                return full_output
            full_output = f"No specialist outputs were generated.\n\n{CANONICAL_DISCLAIMER}"
            state["output"] = full_output
            return full_output

        # Single agent fast-path
        if len(specialist_outputs) == 1:
            single_text = str(list(specialist_outputs.values())[0])
            clean_text = cls.strip_disclaimers(single_text)
            full_output = f"{clean_text}\n\n{CANONICAL_DISCLAIMER}"
            state["output"] = full_output
            return full_output

        # Multi-agent synthesis
        sections: List[str] = ["# Patient Consultation Master Agenda\n"]

        # Check for cardiorenal fluid/sodium tradeoff
        has_cardio = any("cardio" in str(k).lower() for k in specialist_outputs.keys())
        has_nephro = any("nephro" in str(k).lower() for k in specialist_outputs.keys())
        combined_text = " ".join(str(v) for v in specialist_outputs.values()).lower()
        has_fluid_conflict = ("fluid" in combined_text or "sodium" in combined_text) and (has_cardio and has_nephro)

        # 1. Cardiorenal Tradeoff Framing (collaborative doctor-discussion questions without prescribing)
        if has_fluid_conflict:
            sections.append(
                "## Priority Doctor-Discussion Questions (Cardiorenal Coordination)\n"
                "- How should daily fluid restriction and sodium intake be balanced to protect heart function while accommodating renal clearance?\n"
                "- What target weight range and lab monitoring intervals (electrolytes, BUN, creatinine) are recommended when adjusting diuretic therapies?\n"
            )

        # 2. Specialist Domain Agendas
        for agent_id, output_text in specialist_outputs.items():
            specialty_title = str(agent_id).replace("-", " ").replace("_", " ").title()
            clean_output = cls.strip_disclaimers(str(output_text))
            sections.append(f"## {specialty_title} Guidance\n{clean_output}\n")

        # 3. Canonical Deduplicated Disclaimer Footer
        sections.append(CANONICAL_DISCLAIMER)

        full_output = "\n".join(sections)
        state["output"] = full_output
        return full_output

    async def execute(
        self, state: Dict[str, Any], *, store: Optional[BaseStore] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """LangGraph node execution interface with Phase 5 turn persistence."""
        full_output = self.synthesize_response(state)

        # Zero-body structured audit event logging (event="synthesis")
        iso_timestamp = datetime.now(timezone.utc).isoformat()
        agent_id = str(state.get("current_agent") or "response-synthesizer")
        specialist_outputs = state.get("specialist_outputs") or {}
        specialist_ids = list(specialist_outputs.keys())
        thread_id = state.get("thread_id")

        audit_payload: Dict[str, Any] = {
            "timestamp": iso_timestamp,
            "ts": iso_timestamp,
            "agent_id": agent_id,
            "event": "synthesis",
            "allowed": True,
            "target_agents": specialist_ids,
        }
        if thread_id:
            audit_payload["thread_id"] = str(thread_id)
        if state.get("prompt"):
            audit_payload["prompt"] = str(state["prompt"])
        if state.get("output"):
            audit_payload["completion"] = str(state["output"])

        store_bodies = bool(state.get("store_bodies", settings.audit_store_bodies))
        redacted = redact_audit_event(audit_payload, store_bodies=store_bodies)
        redacted = {k: v for k, v in redacted.items() if v is not None}
        redacted["timestamp"] = iso_timestamp
        redacted["ts"] = iso_timestamp

        if settings.audit_log_path:
            log_path = Path(settings.audit_log_path)
        else:
            ws_root = state.get("workspace_root") or settings.workspace_root
            log_path = Path(ws_root) / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(redacted) + "\n"
            with _file_lock:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
        except Exception as err:
            self.logger.warning("ResponseSynthesizerNode failed to write audit event: %s", err)

        accumulated = list(state.get("audit_events", []))
        accumulated.append(redacted)

        # Suggestion chips
        follow_ups = list(state.get("follow_up_suggestions") or [])
        if not follow_ups:
            combined_text = " ".join(str(v) for v in state.get("specialist_outputs", {}).values()).lower()
            has_cardio = any("cardio" in k.lower() for k in state.get("specialist_outputs", {}))
            has_nephro = any("nephro" in k.lower() for k in state.get("specialist_outputs", {}))
            if ("fluid" in combined_text or "sodium" in combined_text) and (has_cardio and has_nephro):
                follow_ups = [
                    "Ask doctor about daily fluid and sodium balance",
                    "Inquire about target weight range and lab monitoring",
                    "Schedule coordinated cardiology and nephrology follow-up",
                ]
            elif len(state.get("specialist_outputs", {})) > 1:
                follow_ups = [
                    "Review consultation master agenda with doctor",
                    "Prioritize questions for upcoming appointment",
                    "Verify insurance coverage for recommended assessments",
                ]

        # Phase 5 Turn Persistence: Commit interaction into episodic memory
        if store is not None and thread_id:
            try:
                turn_key = f"turn_{int(time.time() * 1000)}"
                user_prompt = state.get("prompt") or self.get_prompt_text(state) or ""
                turn_payload = {
                    "role": "assistant",
                    "user_query": user_prompt,
                    "user_prompt": user_prompt,
                    "prompt": user_prompt,
                    "agent_response": full_output,
                    "response": full_output,
                    "output": full_output,
                    "agent_id": agent_id,
                    "tier": "EPISODIC",
                    "timestamp": iso_timestamp,
                    "text": f"User: {user_prompt}\nCarefold: {full_output}",
                    "metadata": {
                        "thread_id": str(thread_id),
                        "agent_id": agent_id,
                        "turn_key": turn_key,
                        "specialist_outputs": specialist_ids,
                    },
                    "created_at": iso_timestamp,
                    "updated_at": iso_timestamp,
                }
                await store.aput(
                    ("memories", str(thread_id)),
                    turn_key,
                    turn_payload,
                )
            except Exception as err:
                self.logger.warning("Phase 5 turn persistence failed gracefully: %s", err)

        # SSE custom event dispatching
        if specialist_outputs:
            try:
                await adispatch_custom_event(
                    "synthesis",
                    {
                        "type": "synthesis",
                        "output": full_output,
                    },
                )
            except Exception:
                pass

        clean_completion = self.strip_disclaimers(full_output)
        result_payload: Dict[str, Any] = {
            "output": clean_completion if not specialist_outputs else full_output,
            "next_step": "output_guardrail",
            "audit_events": accumulated,
        }
        if specialist_outputs or not any(isinstance(m, AIMessage) for m in state.get("messages", [])):
            result_payload["messages"] = [AIMessage(content=full_output)]
        if follow_ups:
            result_payload["follow_up_suggestions"] = follow_ups

        return result_payload

    # Method alias for process requirement compatibility
    process = execute


__all__ = ["ResponseSynthesizerNode", "CANONICAL_DISCLAIMER"]
