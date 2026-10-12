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

"""Sandboxed tool execution node enforcing authorized tool unions (F-25).

Executes tools declaring adherence to `union(agent.tools, skill.tools)`.
Intercepts and rejects unauthorized tool calls, emits traces, and formats
standard ToolMessages.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Sequence
from langchain_core.messages import AIMessage, ToolMessage

from carefold.config import settings
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS, execute_tool
from carefold.workflows.nodes.base import BaseNode


class ToolNode(BaseNode):
    """Executes tools adhering to the sandboxed permission boundary."""

    def __init__(
        self,
        allowed_tools: Optional[Sequence[str]] = None,
        tools: Optional[Sequence[Any]] = None,
        name: str = "tools",
        tool_context: Optional[Any] = None,
    ) -> None:
        super().__init__(name=name)
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None
        self.tools = tools or []
        self.tool_context = tool_context

    async def execute(
        self,
        state: Dict[str, Any],
        *,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Executes tool calls declared in state or on latest AIMessage through execute_tool_call."""
        from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS, TOOL_EXECUTORS
        from carefold.engine.tool_exec import ToolContext, ToolSpec, execute_tool_call
        from carefold.loaders.agent_loader import find_agent_dir, load_agent

        # Determine allowed tools boundary
        if self.allowed_tools is not None:
            allowed = self.allowed_tools
        elif state.get("effective_tools") is not None:
            allowed = set(state["effective_tools"])
        elif state.get("allowed_tools") is not None:
            allowed = set(state["allowed_tools"])
        else:
            allowed = set(CLOSED_TOOL_DEFINITIONS.keys())

        # Extract tool calls
        tool_calls = list(state.get("tool_calls", []))
        if not tool_calls:
            messages = state.get("messages", [])
            last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            if last_ai:
                tool_calls = getattr(last_ai, "tool_calls", []) or []

        if not tool_calls:
            return {
                "messages": [],
                "tool_messages": [],
                "tool_traces": list(state.get("tool_traces", [])),
                "tool_output": "",
                "next_step": "tool_validator",
            }

        ws_root = Path(state.get("workspace_root") or settings.workspace_root)
        skills_dir = Path(state.get("skills_dir") or (ws_root / "skills"))
        agent_id = str(state.get("current_agent") or state.get("agent_id") or "carefold-agent")

        agent_obj = None
        skills_list = []
        try:
            agent_dir = find_agent_dir(ws_root / "agents", str(agent_id)) or (ws_root / "agents" / "visit-steward").resolve()
            agent_obj, _, skills_list = load_agent(agent_dir, skills_dir)
        except Exception:
            agent_obj = type("Agent", (), {"id": agent_id, "skills": []})()

        configurable = (config or {}).get("configurable", {})
        raw_ctx = (
            configurable.get("tool_context")
            or getattr(self, "tool_context", None)
            or state.get("tool_context")
        )

        # Check if any tool call is allowed and requires execution
        has_allowed_calls = any(c.get("name") in allowed for c in tool_calls)

        ctx: Optional[ToolContext] = None
        if has_allowed_calls:
            if isinstance(raw_ctx, ToolContext):
                if not raw_ctx.profile_id or not str(raw_ctx.profile_id).strip():
                    raise ValueError(
                        "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed."
                    )
                ctx = raw_ctx
            else:
                has_pid_key = "profile_id" in configurable or "profile_id" in state
                p_val = configurable.get("profile_id") if "profile_id" in configurable else state.get("profile_id")
                u_val = configurable.get("user_id") if "user_id" in configurable else state.get("user_id")

                if has_pid_key:
                    if p_val is None or not str(p_val).strip():
                        raise ValueError(
                            "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed."
                        )
                    p_id = str(p_val).strip()
                else:
                    p_id = "default_profile"

                u_id = str(u_val or "default_user").strip()
                if not u_id:
                    raise ValueError(
                        "Security invariant violation: ToolContext requires a non-empty 'profile_id'. Fail-closed."
                    )

                ctx = ToolContext(
                    user_id=u_id,
                    profile_id=p_id,
                    run_id=str(configurable.get("run_id") or configurable.get("thread_id") or state.get("thread_id") or ""),
                    workspace_root=ws_root,
                    skills_dir=skills_dir,
                    agent=agent_obj,
                    effective_tools=tuple(allowed),
                    skills=tuple(skills_list),
                )

        tool_messages: List[ToolMessage] = []
        tool_traces: List[Dict[str, Any]] = list(state.get("tool_traces", []))
        last_tool_output: Any = ""

        for call in tool_calls:
            call_id = call.get("id") or f"call_{len(tool_messages)}"
            name = call.get("name", "")
            raw_args = call.get("args")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
            else:
                args = dict(raw_args) if isinstance(raw_args, dict) else {}

            is_allowed = name in allowed

            if not is_allowed:
                error_msg = f"Tool '{name}' execution denied: undeclared tool for agent '{agent_id}'. Tool '{name}' is not permitted or undeclared for agent '{agent_id}'."
                tool_traces.append({
                    "tool": name,
                    "allowed": False,
                    "status": "denied",
                    "error": error_msg,
                    "duration_ms": 0.0,
                })
                tool_messages.append(
                    ToolMessage(
                        content=json.dumps({"error": error_msg, "success": False}),
                        tool_call_id=call_id,
                        status="error",
                        name=name,
                    )
                )
                last_tool_output = {"error": error_msg}
            else:
                executor = TOOL_EXECUTORS.get(name)
                tool_def = CLOSED_TOOL_DEFINITIONS.get(name, {})
                spec = ToolSpec(
                    name=name,
                    description=tool_def.get("description", ""),
                    parameters=tool_def.get("parameters", {}),
                    executor=executor,
                )

                t0 = time.time()
                res = await execute_tool_call(ctx, spec, args)
                dur_ms = round((time.time() - t0) * 1000, 2)

                tool_traces.append({
                    "tool": name,
                    "allowed": True,
                    "success": res.success,
                    "duration_ms": dur_ms,
                    "output": res.output if res.success else {"error": res.error},
                    "audit_logged": True,
                })

                output_val = res.output if res.success else {"error": res.error}
                tool_messages.append(
                    ToolMessage(
                        content=json.dumps(output_val) if not isinstance(output_val, str) else output_val,
                        tool_call_id=call_id,
                        status="success" if res.success else "error",
                        name=name,
                    )
                )
                last_tool_output = output_val

        return {
            "messages": tool_messages,
            "tool_messages": tool_messages,
            "tool_traces": tool_traces,
            "tool_output": last_tool_output,
            "next_step": "tool_validator",
        }


__all__ = ["ToolNode"]
