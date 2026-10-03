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

"""Clinical Safety Middleware running in Slot 7 of Deep Agents pipeline.

Enforces:
1. Closed Phase 0 tool registry (PHASE_0_REGISTRY) validation.
2. ToolValidationError on unauthorized or forbidden tools.
3. Dynamic risk class elevation to 'clinical_assist' when clinical skills load.
4. Intended-use clinical disclaimer enforcement.
"""

from __future__ import annotations

import ast
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from carefold.loaders.frontmatter import check_mandatory_intended_use
from carefold.loaders.union import ToolValidationError
from carefold.resources.loader import get_resource_loader
from carefold.schemas.manifest import PHASE_0_REGISTRY, RiskClass

logger = logging.getLogger(__name__)

# Support graceful import across Deep Agents and standalone execution environments
try:
    from deepagents.middleware import SkillsState
    from langchain.agents.middleware import AgentMiddleware  # type: ignore
except ImportError:
    SkillsState = dict  # type: ignore

    class AgentMiddleware:  # type: ignore
        """Fallback base class when deepagents or langchain is not installed."""
        pass


def _parse_declared_tools(tools_val: Any) -> List[str]:
    """Defensively parses declared tools from lists, tuples, or stringified sequences."""
    if not tools_val:
        return []
    if isinstance(tools_val, str):
        s = tools_val.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, (list, tuple, set)):
                    return [str(t).strip() for t in parsed if str(t).strip()]
            except Exception:
                return [t.strip().strip("'\"") for t in s[1:-1].split(",") if t.strip()]
        if "," in s:
            return [t.strip().strip("'\"") for t in s.split(",") if t.strip()]
        return [t.strip().strip("'\"") for t in s.split() if t.strip()]
    if isinstance(tools_val, (list, tuple, set)):
        return [str(t).strip() for t in tools_val if str(t).strip()]
    return []


class ClinicalSafetyMiddleware(AgentMiddleware):
    """Slot 7 Clinical Safety Middleware in Deep Agents pipeline."""

    slot: int = 7
    name: str = "clinical_safety"
    state_schema: Any = SkillsState

    def before_agent(
        self,
        state: Dict[str, Any],
        runtime: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Pre-execution hook executed before the agent reasoning loop.

        Validates declared tools in state and skills metadata against PHASE_0_REGISTRY,
        and dynamically elevates risk class to 'clinical_assist' if clinical skills load.
        """
        skills_metadata = state.get("skills_metadata") or []
        max_risk: str = RiskClass.ADMIN.value

        # 1. Validate agent-level tools if present (union all declared tool fields)
        agent_tools: List[str] = []
        agent_tools.extend(_parse_declared_tools(state.get("tools")))
        agent_tools.extend(_parse_declared_tools(state.get("declared_tools")))
        for tool in agent_tools:
            if tool not in PHASE_0_REGISTRY:
                raise ToolValidationError(
                    f"Agent declares unauthorized tool: '{tool}'. "
                    f"Allowed tools: {sorted(list(PHASE_0_REGISTRY))}"
                )

        # 2. Inspect skill metadata and validate tools per skill
        for skill in skills_metadata:
            skill_name = skill.get("name") or skill.get("id") or "unnamed_skill"
            meta = skill.get("metadata", {}) or {}

            # Evaluate risk class (case-insensitive)
            raw_risk = meta.get("risk_class") or skill.get("risk_class", RiskClass.ADMIN.value)
            risk_val = raw_risk.value if isinstance(raw_risk, RiskClass) else str(raw_risk).strip().lower()
            if risk_val in (RiskClass.CLINICAL_ASSIST.value, "clinical_assist"):
                max_risk = RiskClass.CLINICAL_ASSIST.value

            # Validate tools (union across all declared tool fields)
            declared_tools: List[str] = []
            declared_tools.extend(_parse_declared_tools(meta.get("tools")))
            declared_tools.extend(_parse_declared_tools(skill.get("tools")))
            declared_tools.extend(_parse_declared_tools(meta.get("allowed-tools")))
            declared_tools.extend(_parse_declared_tools(skill.get("allowed-tools")))

            for tool in declared_tools:
                if tool not in PHASE_0_REGISTRY:
                    raise ToolValidationError(
                        f"Skill '{skill_name}' declares unauthorized tool: '{tool}'. "
                        f"Allowed tools: {sorted(list(PHASE_0_REGISTRY))}"
                    )

        # 3. Dynamic elevation to clinical_assist
        updates: Dict[str, Any] = {}
        if max_risk == RiskClass.CLINICAL_ASSIST.value:
            updates["carefold_risk_class"] = max_risk
            if isinstance(state, dict):
                state["carefold_risk_class"] = max_risk

        return updates if updates else None

    def before_tool(
        self,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]] = None,
        state: Optional[Dict[str, Any]] = None,
        runtime: Any = None,
    ) -> None:
        """Validates tool execution at invocation time against PHASE_0_REGISTRY."""
        if tool_name not in PHASE_0_REGISTRY:
            raise ToolValidationError(
                f"Tool invocation denied: '{tool_name}' is not in Phase 0 closed registry."
            )

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        """Intercepts Deep Agents runtime tool calls to enforce PHASE_0_REGISTRY."""
        tool_name = (
            getattr(request, "tool_name", None)
            or getattr(request, "name", None)
            or (request.get("name") if isinstance(request, dict) else None)
        )
        if not tool_name or tool_name not in PHASE_0_REGISTRY:
            raise ToolValidationError(
                f"Tool invocation denied: '{tool_name}' is not in Phase 0 closed registry."
            )
        return handler(request)

    def after_agent(
        self,
        state: Dict[str, Any],
        runtime: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Post-execution hook executed after agent response generation.

        Enforces mandatory clinical disclaimers if thread is elevated to clinical_assist.
        """
        risk_class = state.get("carefold_risk_class")
        risk_str = (risk_class.value if isinstance(risk_class, RiskClass) else str(risk_class)).strip().lower() if risk_class else ""
        if risk_str not in (RiskClass.CLINICAL_ASSIST.value, "clinical_assist"):
            return None

        output = state.get("output", "")
        messages = state.get("messages") or []
        last_msg = messages[-1] if messages else None
        if not output and last_msg is not None:
            if hasattr(last_msg, "content") and isinstance(last_msg.content, str):
                output = last_msg.content
            elif isinstance(last_msg, dict) and isinstance(last_msg.get("content"), str):
                output = last_msg.get("content", "")

        if not output:
            return None

        valid, _ = check_mandatory_intended_use(output)
        if not valid:
            disclaimer_text = self.get_canonical_disclaimer()
            appended_output = f"{output}\n\n{disclaimer_text}"
            updates: Dict[str, Any] = {
                "output": appended_output,
                "disclaimer": disclaimer_text,
            }
            if isinstance(state, dict):
                state["output"] = appended_output
                state["disclaimer"] = disclaimer_text

            if messages and last_msg is not None:
                if hasattr(last_msg, "content"):
                    last_msg.content = appended_output
                elif isinstance(last_msg, dict):
                    last_msg["content"] = appended_output
                updates["messages"] = list(messages)

            return updates
        return None

    @staticmethod
    def get_canonical_disclaimer() -> str:
        """Retrieves canonical intended-use disclaimer text from resource loader."""
        lines = get_resource_loader().get_mandatory_intended_use_lines()
        return ". ".join(lines) + "."


__all__ = [
    "ClinicalSafetyMiddleware",
]
