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

"""Agent prompt assembly and model invocation node (F-24).

Assembles system prompt with safety preamble, binds authorized tools,
invokes the chat model, updates message state, and captures tool calls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from carefold.resources.loader import get_resource_loader
from carefold.workflows.nodes.base import BaseNode

logger = logging.getLogger(__name__)


class AgentNode(BaseNode):
    """Manages agent prompt assembly and model invocation."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        tools: Optional[Sequence[Any]] = None,
        system_prompt: Optional[str] = None,
        name: str = "agent",
    ) -> None:
        super().__init__(name=name)
        self.model = model
        self.tools = tools or []
        self.system_prompt = system_prompt

    def assemble_system_prompt(self, state: Dict[str, Any]) -> str:
        """Assembles the system prompt including safety preamble and agent instructions."""
        if state.get("system_prompt"):
            return str(state["system_prompt"])
        if self.system_prompt:
            return self.system_prompt

        raw_aid = state.get("current_agent") or state.get("agent_id") or ""
        agent_manifest = None
        if raw_aid:
            try:
                from carefold.agents.registry import get_agent_registry
                agent_manifest = get_agent_registry().get(raw_aid)
            except Exception:
                pass

        if agent_manifest is not None:
            from carefold.engine.prompt_builder import build_system_prompt
            return build_system_prompt(agent_manifest)

        loader = get_resource_loader()
        prompts = loader.get_prompts()
        agent_id = raw_aid.replace("-", "_") if raw_aid else "agent"
        agent_instructions = prompts.get("agents", {}).get(agent_id, "")

        forbidden_rules = state.get("forbidden") or loader.get_refusal_patterns().get("default_forbidden_intents", [])
        forbidden_str = ", ".join(forbidden_rules) if forbidden_rules else "policy prohibited actions"

        preamble = loader.get_safety_preamble_template().format(
            forbidden_str=forbidden_str
        )
        if agent_instructions:
            return f"{preamble}\n\n# AGENT INSTRUCTIONS\n{agent_instructions}"
        return preamble

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Assembles prompt, calls model, updates messages, and captures tool_calls."""
        system_prompt = self.assemble_system_prompt(state)
        raw_messages: List[Any] = list(state.get("messages", []))

        # Convert dictionary messages to LangChain message instances if needed
        lc_messages: List[BaseMessage] = []
        for m in raw_messages:
            if isinstance(m, BaseMessage):
                lc_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "")
                content = str(m.get("content", ""))
                if role in ("system",):
                    lc_messages.append(SystemMessage(content=content))
                elif role in ("assistant", "ai"):
                    lc_messages.append(AIMessage(content=content, tool_calls=m.get("tool_calls", [])))
                else:
                    lc_messages.append(HumanMessage(content=content))

        # Inject system prompt at index 0 if not already present
        if system_prompt and not (lc_messages and isinstance(lc_messages[0], SystemMessage)):
            lc_messages = [SystemMessage(content=system_prompt)] + lc_messages

        # Resolve model
        model = self.model or state.get("model")
        if model is None:
            return {
                "messages": [AIMessage(content="I am ready to assist with your healthcare administration.")],
                "output": "I am ready to assist with your healthcare administration.",
                "tool_calls": [],
                "next_step": "output_guardrail",
            }

        # Bind tools if provided and supported
        effective_tools = self.tools or state.get("tools") or []
        raw_model = model
        while hasattr(raw_model, "bound") and getattr(raw_model, "bound", None) is not None:
            raw_model = raw_model.bound

        bound_model = raw_model
        if effective_tools and hasattr(raw_model, "bind_tools"):
            try:
                bound_model = raw_model.bind_tools(effective_tools)
            except (NotImplementedError, Exception) as err:
                logger.debug("Model bind_tools not supported or skipped: %s", err)
                bound_model = raw_model

        try:
            if hasattr(bound_model, "ainvoke"):
                response = await bound_model.ainvoke(lc_messages)
            else:
                response = bound_model.invoke(lc_messages)
        except Exception as exc:
            exc_str = str(exc).lower()
            is_unsupported_tools = (
                bound_model is not raw_model
                and any(
                    phrase in exc_str
                    for phrase in (
                        "does not support tools",
                        "does not support tool",
                        "tools not supported",
                        "tools are not supported",
                        "tool calling not supported",
                        "tool calling is not supported",
                        "function calling not supported",
                        "function calling is not supported",
                        "does not support function",
                        "does not support functions",
                    )
                )
            )
            if is_unsupported_tools:
                logger.warning(
                    "Model does not support tools (%s); falling back to unbound model invocation",
                    exc,
                )
                try:
                    if hasattr(raw_model, "ainvoke"):
                        response = await raw_model.ainvoke(lc_messages)
                    else:
                        response = raw_model.invoke(lc_messages)
                except Exception as fallback_exc:
                    logger.error("AgentNode fallback invocation failed: %s", fallback_exc)
                    return {
                        "error": str(fallback_exc),
                        "error_exception": fallback_exc,
                        "next_step": "error",
                    }
            else:
                logger.error("AgentNode model invocation failed: %s", exc)
                return {
                    "error": str(exc),
                    "error_exception": exc,
                    "next_step": "error",
                }

        tool_calls = getattr(response, "tool_calls", []) or []
        next_step = "tools" if tool_calls else "output_guardrail"

        return {
            "messages": [response],
            "output": getattr(response, "content", ""),
            "tool_calls": tool_calls,
            "next_step": next_step,
        }


__all__ = ["AgentNode"]
