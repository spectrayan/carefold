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
    ) -> None:
        super().__init__(name=name)
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None
        self.tools = tools or []

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Executes tool calls declared in state or on latest AIMessage."""
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

        ws_root = Path(state.get("workspace_root") or settings.workspace_root)
        skills_dir = Path(state.get("skills_dir") or (ws_root / "skills"))
        agent_id = str(state.get("current_agent") or state.get("agent_id") or "carefold-agent")

        from carefold.engine.runner import ExecutionContext
        from carefold.loaders.agent_loader import find_agent_dir, load_agent

        try:
            agent_dir = find_agent_dir(ws_root / "agents", str(agent_id)) or (ws_root / "agents" / "visit-steward").resolve()
            agent_obj, _, skills_list = load_agent(agent_dir, skills_dir)
            ctx = ExecutionContext(
                workspace_root=ws_root,
                skills_dir=skills_dir,
                agent=agent_obj,
                effective_tools=list(allowed),
                skills=skills_list,
            )
        except Exception:
            agent_fallback = type("Agent", (), {"id": agent_id, "skills": []})()
            ctx = type(
                "FallbackExecutionContext",
                (),
                {
                    "workspace_root": ws_root,
                    "skills_dir": skills_dir,
                    "agent": agent_fallback,
                    "effective_tools": list(allowed),
                    "skills": [],
                },
            )()

        tool_messages: List[ToolMessage] = []
        tool_traces: List[Dict[str, Any]] = list(state.get("tool_traces", []))
        last_tool_output: Any = ""

        for call in tool_calls:
            call_id = call.get("id") or f"call_{len(tool_messages)}"
            name = call.get("name", "")
            raw_args = call.get("args", {})
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
            else:
                args = dict(raw_args) if isinstance(raw_args, dict) else {}

            is_allowed = name in allowed

            if not is_allowed:
                error_msg = f"Tool '{name}' execution denied: undeclared tool for agent '{agent_id}'."
                tool_traces.append({
                    "tool": name,
                    "allowed": False,
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
                t0 = time.time()
                res = await execute_tool(name, args, ctx)
                dur_ms = round((time.time() - t0) * 1000, 2)

                tool_traces.append({
                    "tool": name,
                    "allowed": True,
                    "success": res.success,
                    "duration_ms": dur_ms,
                    "output": res.output if res.success else {"error": res.error},
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
