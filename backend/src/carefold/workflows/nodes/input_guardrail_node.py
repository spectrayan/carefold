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

"""Pre-execution clinical safety guardrail node (F-22).

Evaluates user prompt against 34 clinical refusal patterns in refusal_patterns.yaml
via `check_safety_refusal`. Intercepts clinical diagnosis, dosing, emergency diversion,
and medication discontinuation before model or tool invocation.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.store.base import BaseStore

from carefold.safety.classifier import check_safety_refusal
from carefold.safety.emergency import check_emergency_red_flags
from carefold.workflows.nodes.base import BaseNode


class InputGuardrailNode(BaseNode):
    """Pre-execution guardrail evaluating clinical safety and recalling memory context."""

    def __init__(self, name: str = "input_guardrail") -> None:
        super().__init__(name=name)

    async def __call__(
        self, state: Dict[str, Any], *, store: Optional[BaseStore] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """LangGraph node execution callable interface supporting store injection."""
        return await self.execute(state, store=store, **kwargs)

    async def execute(
        self, state: Dict[str, Any], *, store: Optional[BaseStore] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """Evaluates clinical safety and executes Phase 1 context recall on the user prompt."""
        messages: List[Any] = state.get("messages", [])
        prompt_text = ""

        # Extract latest human message content
        for m in reversed(messages):
            if isinstance(m, dict):
                if m.get("role") in ("user", "human"):
                    prompt_text = str(m.get("content") or "")
                    break
            elif isinstance(m, HumanMessage) or getattr(m, "type", "") in ("human", "user"):
                prompt_text = str(getattr(m, "content", "") or "")
                break
            elif isinstance(m, BaseMessage):
                prompt_text = str(getattr(m, "content", "") or "")
                break

        if not prompt_text and state.get("prompt"):
            prompt_text = str(state.get("prompt"))

        # 1. Acute Emergency Red-Flag Gating (Immediate 911 / ER diversion)
        emergency_flag = check_emergency_red_flags(prompt_text)
        if emergency_flag is not None:
            referral_msg = emergency_flag.referral_message or (
                "EMERGENCY WARNING: Acute symptoms detected. Please call 911 or visit the nearest emergency room immediately."
            )
            flag_dict = emergency_flag.to_dict() if hasattr(emergency_flag, "to_dict") else dict(emergency_flag)

            # Check if prompt also explicitly attempts forbidden emergency diversion / triage
            safety_check = check_safety_refusal(prompt_text)
            if safety_check.refused and safety_check.reason and "replace_emergency_care" in safety_check.reason:
                refusal_reason = "emergency_red_flag:replace_emergency_care"
            else:
                refusal_reason = "emergency_red_flag"

            return {
                "is_refusal": True,
                "refused": True,
                "refusal_reason": refusal_reason,
                "refusal_message": referral_msg,
                "emergency_red_flags": flag_dict,
                "next_step": "refusal",
                "tool_calls": [],  # Suppress pending tool calls on emergency
                "recalled_memories": [],
                "safety_metadata": {
                    "checked": True,
                    "refused": True,
                    "reason": refusal_reason,
                    "category": emergency_flag.category,
                    "emergency": flag_dict,
                },
            }

        # 2. Clinical Consent Gating (allow_clinical check)
        target_domain = state.get("target_domain") or state.get("domain")
        is_consented = state.get("allow_clinical") is True
        if target_domain == "clinical" and not is_consented:
            return {
                "is_refusal": True,
                "refused": True,
                "refusal_reason": "clinical_consent_required",
                "refusal_message": (
                    "Clinical assist features require explicit user consent (allow_clinical=True)."
                ),
                "next_step": "refusal",
                "tool_calls": [],  # Suppress pending tool calls on lack of consent
                "recalled_memories": [],
                "safety_metadata": {
                    "checked": True,
                    "refused": True,
                    "reason": "clinical_consent_required",
                    "category": "consent",
                },
            }

        # 3. Standard Clinical Safety Refusal (34 patterns in refusal_patterns.yaml)
        safety_check = check_safety_refusal(prompt_text)

        if safety_check.refused:
            reason = safety_check.reason or "forbidden_intent:medical_prohibited"
            return {
                "is_refusal": True,
                "refused": True,
                "refusal_reason": reason,
                "next_step": "refusal",
                "tool_calls": [],  # Suppress pending tool calls on safety refusal
                "recalled_memories": [],
                "safety_metadata": {
                    "checked": True,
                    "refused": True,
                    "reason": reason,
                    "category": reason.replace("forbidden_intent:", ""),
                },
            }

        # 4. Phase 1 Context Recall: Query BaseStore for previous episodic/semantic memories
        recalled_memories: List[Dict[str, Any]] = []
        memory_context: Optional[str] = None
        thread_id = state.get("thread_id")

        if store is not None and thread_id and prompt_text:
            try:
                # Query namespace ("memories", str(thread_id)) up to limit 5
                search_items = await store.asearch(
                    ("memories", str(thread_id)),
                    query=prompt_text,
                    limit=5,
                )
                for item in search_items:
                    item_created = (
                        item.created_at.isoformat()
                        if hasattr(getattr(item, "created_at", None), "isoformat")
                        else str(getattr(item, "created_at", "") or "")
                    )
                    recalled_memories.append({
                        "key": item.key,
                        "namespace": item.namespace,
                        "value": item.value,
                        "created_at": item_created,
                        "score": getattr(item, "score", None),
                    })

                if recalled_memories:
                    lines = ["### Relevant Patient Context & Previous Conversations:"]
                    for mem in recalled_memories:
                        val = mem.get("value")
                        if isinstance(val, dict):
                            uq = val.get("user_query") or val.get("query")
                            ar = val.get("agent_response") or val.get("response") or val.get("output")
                            if uq and ar:
                                lines.append(f"- Previous Query: {uq}\n  Previous Response: {ar}")
                            elif "text" in val and val["text"]:
                                lines.append(f"- {val['text']}")
                            else:
                                lines.append(f"- {json.dumps(val, ensure_ascii=False)}")
                        elif isinstance(val, str):
                            lines.append(f"- {val}")
                        else:
                            lines.append(f"- {val}")
                    memory_context = "\n".join(lines)
            except Exception as err:
                self.logger.warning("Phase 1 context recall failed gracefully: %s", err)

        # 5. Enrich state system_prompt with recalled memory context
        system_prompt = state.get("system_prompt")
        updated_system_prompt = system_prompt
        if memory_context:
            if system_prompt:
                if memory_context not in system_prompt:
                    updated_system_prompt = f"{system_prompt}\n\n{memory_context}"
            else:
                updated_system_prompt = memory_context

        output_state: Dict[str, Any] = {
            "is_refusal": False,
            "refused": False,
            "refusal_reason": None,
            "next_step": "supervisor",
            "recalled_memories": recalled_memories,
            "safety_metadata": {
                "checked": True,
                "refused": False,
                "reason": None,
            },
        }
        if memory_context:
            output_state["memory_context"] = memory_context
        if updated_system_prompt is not None:
            output_state["system_prompt"] = updated_system_prompt

        return output_state

    # Method alias for process requirement compatibility
    process = execute


__all__ = ["InputGuardrailNode"]
