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

"""AI follow-up question chip generator node (F-30).

Generates 2-4 contextual follow-up question chips dynamically via model invocation
using prompts/suggestions/generation.md, with offline fallback to curated chips.
Strictly suppresses chip generation if a safety refusal occurred (`is_refusal=True`).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from carefold.resources.loader import get_resource_loader
from carefold.workflows.nodes.base import BaseNode

logger = logging.getLogger(__name__)


class SuggestionNode(BaseNode):
    """AI follow-up next question generator supporting dynamic LLM generation and curated fallbacks."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        name: str = "suggestion",
    ) -> None:
        super().__init__(name=name)
        self.model = model

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generates up to 4 follow-up suggestion chips."""
        # Strictly suppress suggestion chips on safety refusal
        if state.get("is_refusal") or state.get("refused"):
            return {
                "follow_up_suggestions": [],
                "next_step": "done",
            }

        agent_id = str(state.get("current_agent") or state.get("agent_id") or "visit-steward")
        messages: List[Any] = state.get("messages", [])

        user_queries: List[str] = []
        for m in messages:
            if isinstance(m, HumanMessage):
                q = str(m.content or "").strip()
                if q:
                    user_queries.append(q)
            elif isinstance(m, dict) and m.get("role") in ("user", "human"):
                q = str(m.get("content", "")).strip()
                if q:
                    user_queries.append(q)

        prompt_text = user_queries[-1] if user_queries else ""
        completion_text = str(state.get("output", ""))

        if not completion_text:
            for m in reversed(messages):
                if isinstance(m, AIMessage) or (isinstance(m, dict) and m.get("role") in ("assistant", "ai")):
                    completion_text = str(getattr(m, "content", "") if isinstance(m, AIMessage) else m.get("content", ""))
                    break

        tools_used = [t.get("tool") for t in state.get("tool_traces", []) if t.get("allowed")]

        chips: List[str] = []

        # 1. Dynamic LLM generation if model is present and context exists
        if self.model is not None and (prompt_text or completion_text):
            try:
                import asyncio
                loader = get_resource_loader()
                prompt_tmpl = loader.get_prompt_text("suggestions/generation")
                # Keep prompt compact to avoid high TTFT on local models
                clean_assistant_resp = (completion_text or "")[:400]
                clean_user_prompt = (prompt_text or "")[:200]
                rendered_prompt = prompt_tmpl.format(
                    agent_title=agent_id.replace("-", " ").title(),
                    user_prompt=clean_user_prompt or "(none)",
                    assistant_response=clean_assistant_resp or "(none)",
                    tools_used=", ".join(tools_used) if tools_used else "None",
                )
                resp = await asyncio.wait_for(
                    self.model.ainvoke(
                        [SystemMessage(content=rendered_prompt)],
                        config={"tags": ["internal", "suggestion", "no_stream"]},
                    ),
                    timeout=2.0,
                )
                content = str(getattr(resp, "content", "") or "").strip()

                raw_extracted: List[str] = []
                parsed = None
                try:
                    parsed = json.loads(content)
                except Exception:
                    match = re.search(r"\[.*\]", content, re.DOTALL)
                    if match:
                        try:
                            parsed = json.loads(match.group(0))
                        except Exception:
                            parsed = None

                if isinstance(parsed, list):
                    raw_extracted = [str(c).strip() for c in parsed if isinstance(c, str) and c.strip()]
                else:
                    lines = [re.sub(r"^[\d\.\-\*\•\s]+", "", l).strip(' "\'') for l in content.splitlines()]
                    raw_extracted = [l for l in lines if l and len(l) > 6 and l.endswith("?")]

                # Filter out questions already asked by the user in this conversation
                lower_prior = {q.lower().strip() for q in user_queries}
                filtered_chips: List[str] = []
                for c in raw_extracted:
                    c_clean = c.strip()
                    c_low = c_clean.lower()
                    if c_low not in lower_prior and not any(c_low in q or q in c_low for q in lower_prior if len(q) > 12):
                        filtered_chips.append(c_clean)

                chips = filtered_chips[:3]
            except Exception as err:
                logger.debug("Dynamic suggestion generation timed out or failed: %s; falling back to curated chips", err)

        # 2. Offline / parameterless fallback to curated chips from ResourceLoader
        if not chips:
            raw_chips = get_resource_loader().get_follow_up_suggestions(
                agent_id=agent_id,
                prompt=prompt_text,
                completion=completion_text,
                tools_used=tools_used,
                user_queries=user_queries,
            )
            chips = list(raw_chips)[:3]

        # 3. Emit SSE custom event immediately so stream consumers receive it promptly
        try:
            from langchain_core.callbacks.manager import adispatch_custom_event
            from carefold.constants.api import SSE_EVENT_SUGGESTIONS
            await adispatch_custom_event(
                SSE_EVENT_SUGGESTIONS,
                {"type": SSE_EVENT_SUGGESTIONS, "suggestions": chips},
            )
        except Exception:
            pass

        return {
            "follow_up_suggestions": chips,
            "next_step": "done",
        }


__all__ = ["SuggestionNode"]
