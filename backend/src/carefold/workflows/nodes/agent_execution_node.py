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

"""Unified agent execution node for all specialist agents (F-48).

Loads agent persona, forbidden constraints, and tool allowlists dynamically from
AgentRegistry, binds resolved tools via ToolRegistry, invokes the model, and
routes conditionally to 'tools' or 'output_guardrail'.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from carefold.agents.registry import AgentRegistry, get_agent_registry
from carefold.config import settings
from carefold.constants.agents import DEFAULT_ROUTING_FALLBACK_AGENT
from carefold.constants.paths import AGENTS_DIR, SKILLS_DIR
from carefold.loaders.agent_loader import load_agent
from carefold.resources.loader import get_resource_loader
from carefold.schemas.manifest import AgentManifest
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS
from carefold.workflows.nodes.base import BaseNode
from carefold.workflows.state import AgentState

logger = logging.getLogger(__name__)


class AgentExecutionNode(BaseNode):
    """Unified execution node handling all specialist agents discovered in AgentRegistry."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        registry: Optional[AgentRegistry] = None,
        tool_registry: Optional[Any] = None,
        default_tools: Optional[Sequence[Any]] = None,
        name: str = "agent_execution",
    ) -> None:
        super().__init__(name=name)
        self.model = model
        self._registry = registry
        self.tool_registry = tool_registry
        self.default_tools = list(default_tools) if default_tools is not None else None

    @property
    def registry(self) -> AgentRegistry:
        """Lazily resolves AgentRegistry from workspace root if not explicitly injected."""
        if self._registry is None:
            self._registry = get_agent_registry()
        return self._registry

    def _resolve_system_prompt(self, manifest: Any, state: Dict[str, Any]) -> str:
        """Assembles the agent persona and safety contract prompt using Handlebars."""
        persona = ""
        if isinstance(manifest.persona, str):
            persona = manifest.persona
        elif hasattr(manifest.persona, "instructions") and manifest.persona.instructions:
            persona = manifest.persona.instructions
        elif hasattr(manifest.persona, "role") and manifest.persona.role:
            persona = manifest.persona.role
        elif isinstance(manifest.persona, dict):
            persona = manifest.persona.get("instructions") or manifest.persona.get("role") or ""

        loader = get_resource_loader()
        forbidden_rules = getattr(manifest, "forbidden", []) or []
        if not forbidden_rules:
            forbidden_rules = loader.get_refusal_patterns().get("default_forbidden_intents", [])

        forbidden_str = ", ".join(forbidden_rules) if forbidden_rules else "policy prohibited actions"
        safety_preamble = loader.get_safety_preamble_template().format(
            forbidden_str=forbidden_str
        )

        orchestrator_instructions = state.get("orchestrator_instructions", "")

        # Extract companion skills declared in manifest.skills
        declared_skills: List[Dict[str, Any]] = []
        skill_ids = list(getattr(manifest, "skills", []) or [])
        agent_manifest_id = getattr(manifest, "id", "") or str(state.get("current_agent") or state.get("agent_id") or "")
        loaded_skills = self.registry.get_loaded_skills(agent_manifest_id) if agent_manifest_id else []
        loaded_map = {sk.id: sk for sk in loaded_skills}

        seen_skill_ids = set()
        for s_item in skill_ids:
            if isinstance(s_item, str):
                sk_id = s_item
                sk_obj = loaded_map.get(sk_id) or self.registry.get_skill(sk_id)
                if sk_obj is not None:
                    desc = sk_obj.description or ""
                    tier1_summary = (
                        f"Summary: {desc}\n(Instructions available on-demand via skill-docs)"
                        if desc
                        else "(Instructions available on-demand via skill-docs)"
                    )
                    declared_skills.append({
                        "name": sk_obj.name,
                        "id": sk_obj.id,
                        "instructions": tier1_summary,
                        "description": desc,
                    })
                else:
                    declared_skills.append({
                        "name": sk_id.replace("-", " ").title(),
                        "id": sk_id,
                        "instructions": "(Instructions available on-demand via skill-docs)",
                        "description": "",
                    })
                seen_skill_ids.add(sk_id)
            elif hasattr(s_item, "id"):
                sk_id = getattr(s_item, "id")
                desc = getattr(s_item, "description", "") or ""
                tier1_summary = (
                    f"Summary: {desc}\n(Instructions available on-demand via skill-docs)"
                    if desc
                    else "(Instructions available on-demand via skill-docs)"
                )
                declared_skills.append({
                    "name": getattr(s_item, "name", sk_id),
                    "id": sk_id,
                    "instructions": tier1_summary,
                    "description": desc,
                })
                seen_skill_ids.add(sk_id)
            elif isinstance(s_item, dict):
                sk_id = s_item.get("id", "skill")
                desc = s_item.get("description", "") or ""
                tier1_summary = (
                    f"Summary: {desc}\n(Instructions available on-demand via skill-docs)"
                    if desc
                    else "(Instructions available on-demand via skill-docs)"
                )
                declared_skills.append({
                    "name": s_item.get("name") or sk_id,
                    "id": sk_id,
                    "instructions": tier1_summary,
                    "description": desc,
                })
                seen_skill_ids.add(sk_id)

        for sk in loaded_skills:
            if sk.id not in seen_skill_ids:
                desc = sk.description or ""
                tier1_summary = (
                    f"Summary: {desc}\n(Instructions available on-demand via skill-docs)"
                    if desc
                    else "(Instructions available on-demand via skill-docs)"
                )
                declared_skills.append({
                    "name": sk.name,
                    "id": sk.id,
                    "instructions": tier1_summary,
                    "description": desc,
                })
                seen_skill_ids.add(sk.id)

        # Extract provisioned references
        provisioned_references_raw = state.get("provisioned_references")
        provisioned_references_list: List[Dict[str, Any]] = []
        if isinstance(provisioned_references_raw, dict):
            for doc_name, doc_data in provisioned_references_raw.items():
                if isinstance(doc_data, dict):
                    provisioned_references_list.append({
                        "name": doc_name,
                        "title": doc_data.get("title", doc_name),
                        "content": doc_data.get("content", ""),
                        "skill_id": doc_data.get("skill_id", ""),
                    })
                elif isinstance(doc_data, str):
                    provisioned_references_list.append({
                        "name": doc_name,
                        "title": doc_name,
                        "content": doc_data,
                        "skill_id": "",
                    })
        elif isinstance(provisioned_references_raw, list):
            for item in provisioned_references_raw:
                if isinstance(item, dict):
                    provisioned_references_list.append({
                        "name": item.get("name") or item.get("title") or "Reference",
                        "title": item.get("title", ""),
                        "content": item.get("content", ""),
                        "skill_id": item.get("skill_id", ""),
                    })
                elif isinstance(item, str):
                    provisioned_references_list.append({
                        "name": item,
                        "title": item,
                        "content": item,
                        "skill_id": "",
                    })

        # Inject dynamically generated skills passed from orchestrator
        generated_skills_raw = list(state.get("generated_skills") or [])
        single_gen = state.get("generated_skill")
        if single_gen and single_gen not in generated_skills_raw:
            generated_skills_raw.append(single_gen)

        processed_skills = []
        for gs in generated_skills_raw:
            if isinstance(gs, dict):
                refs = gs.get("references", {})
                ref_text = ""
                if isinstance(refs, dict) and refs:
                    ref_text = "\n".join(f"### {fname}\n{fbody}" for fname, fbody in refs.items())
                processed_skills.append({
                    "name": gs.get("name") or gs.get("id") or "Dynamic Skill",
                    "id": gs.get("id") or "dynamic_skill",
                    "description": gs.get("description", ""),
                    "instructions": gs.get("instructions", ""),
                    "ref_text": ref_text,
                })
            elif isinstance(gs, str):
                processed_skills.append({
                    "name": "Dynamic Skill",
                    "id": "dynamic_skill",
                    "description": "",
                    "instructions": gs,
                    "ref_text": "",
                })

        context = {
            "safety_preamble": safety_preamble,
            "manifest": manifest,
            "persona": persona.strip(),
            "orchestrator_instructions": orchestrator_instructions.strip() if orchestrator_instructions else "",
            "skills": declared_skills,
            "has_skills": bool(declared_skills),
            "provisioned_references": provisioned_references_list,
            "has_provisioned_references": bool(provisioned_references_list),
            "generated_skills": processed_skills,
            "has_generated_skills": bool(processed_skills),
        }

        from carefold.templates.engine import render_template
        return render_template("agent_execution_prompt", context)

    def _resolve_tools(self, agent_id: str, manifest: Any, state: Dict[str, Any]) -> List[Any]:
        """Resolves tool definitions or instances authorized for this agent."""
        effective_tool_names: List[str] = []
        if state.get("effective_tools") is not None:
            effective_tool_names = list(state["effective_tools"])
        elif hasattr(self.registry, "get_effective_tools") and self.registry.get(agent_id) is not None:
            effective_tool_names = self.registry.get_effective_tools(agent_id)
        elif hasattr(self.registry, "_effective_tools") and agent_id in self.registry._effective_tools:
            effective_tool_names = list(self.registry._effective_tools[agent_id])
        elif manifest is not None and getattr(manifest, "tools", None) is not None:
            effective_tool_names = list(manifest.tools)
        elif self.default_tools is not None:
            effective_tool_names = [
                t.name if hasattr(t, "name") else (t.get("name") if isinstance(t, dict) else str(t))
                for t in self.default_tools
            ]

        # Add tools from generated skills if present
        generated_skills = list(state.get("generated_skills") or [])
        if state.get("generated_skill") and state.get("generated_skill") not in generated_skills:
            generated_skills.append(state.get("generated_skill"))
        for gs in generated_skills:
            if isinstance(gs, dict) and gs.get("tools"):
                for t in gs["tools"]:
                    if t not in effective_tool_names:
                        effective_tool_names.append(t)

        if self.tool_registry is not None and hasattr(self.tool_registry, "resolve"):
            return self.tool_registry.resolve(effective_tool_names)

        resolved: List[Any] = []
        for t_name in effective_tool_names:
            if t_name in CLOSED_TOOL_DEFINITIONS:
                resolved.append(CLOSED_TOOL_DEFINITIONS[t_name])
            elif self.tool_registry and hasattr(self.tool_registry, "get"):
                t_obj = self.tool_registry.get(t_name)
                if t_obj is not None:
                    resolved.append(t_obj)
        return resolved

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the active agent's prompt, binds tools, and triggers model invocation."""
        raw_agent_id = str(
            state.get("current_agent")
            or state.get("agent_id")
            or DEFAULT_ROUTING_FALLBACK_AGENT
        ).strip()

        # Check raw ID first (preserves leading underscores like _template)
        agent_id = raw_agent_id
        manifest = self.registry.get(agent_id)

        if manifest is None:
            # Try normalized (lowercase, replace _ with - only if not leading _)
            if not raw_agent_id.startswith("_"):
                normalized_id = raw_agent_id.lower().replace("_", "-")
            else:
                normalized_id = raw_agent_id.lower()
            manifest = self.registry.get(normalized_id)
            if manifest is not None:
                agent_id = normalized_id

        # Check workspace_root from state if manifest still not found
        if manifest is None and state.get("workspace_root"):
            ws_agent_dir = Path(state["workspace_root"]) / "agents" / agent_id
            if ws_agent_dir.is_dir():
                try:
                    ws_skills_dir = Path(state["workspace_root"]) / "skills"
                    manifest, eff_tools, _ = load_agent(
                        ws_agent_dir, ws_skills_dir if ws_skills_dir.is_dir() else None
                    )
                    if hasattr(self.registry, "_agents"):
                        self.registry._agents[agent_id] = manifest
                        self.registry._effective_tools[agent_id] = eff_tools
                except Exception as err:
                    logger.debug("Failed loading agent '%s' from state workspace_root: %s", agent_id, err)

        # Fallback synthesis for dynamically configured / test agents
        if manifest is None:
            if (
                state.get("messages")
                or state.get("effective_tools") is not None
                or self.default_tools is not None
                or self.model is not None
                or state.get("model") is not None
            ):
                fallback_tools = (
                    list(state["effective_tools"])
                    if state.get("effective_tools") is not None
                    else (
                        [
                            t.name if hasattr(t, "name") else (t.get("name") if isinstance(t, dict) else str(t))
                            for t in self.default_tools
                        ]
                        if self.default_tools is not None
                        else []
                    )
                )
                manifest = AgentManifest(
                    id=agent_id,
                    title=agent_id.replace("-", " ").title(),
                    version="0.1.0",
                    risk_class="wellness",
                    skills=[],
                    tools=fallback_tools,
                    persona={"role": f"Assistant ({agent_id})", "instructions": ""},
                )
            else:
                err_msg = f"Unknown or unregistered agent ID: '{agent_id}'"
                logger.error(err_msg)
                return {
                    "error": err_msg,
                    "next_step": "error",
                }

        # 1. Assemble system prompt
        system_prompt = self._resolve_system_prompt(manifest, state)

        # 2. Resolve tools
        tools = self._resolve_tools(agent_id, manifest, state)
        if state.get("effective_tools") is not None:
            effective_tool_names = list(state["effective_tools"])
        elif hasattr(self.registry, "get_effective_tools") and self.registry.get(agent_id) is not None:
            effective_tool_names = self.registry.get_effective_tools(agent_id)
        elif manifest is not None and getattr(manifest, "tools", None) is not None:
            effective_tool_names = list(manifest.tools)
        elif self.default_tools is not None:
            effective_tool_names = [
                t.name if hasattr(t, "name") else (t.get("name") if isinstance(t, dict) else str(t))
                for t in self.default_tools
            ]
        else:
            effective_tool_names = [
                t.name if hasattr(t, "name") else (t.get("name") if isinstance(t, dict) else str(t))
                for t in tools
            ]

        # 3. Build messages list
        raw_messages = list(state.get("messages", []))
        lc_messages: List[BaseMessage] = []
        for m in raw_messages:
            if isinstance(m, BaseMessage):
                lc_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "")
                content = str(m.get("content", ""))
                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                elif role in ("assistant", "ai"):
                    lc_messages.append(AIMessage(content=content, tool_calls=m.get("tool_calls", [])))
                elif role == "tool":
                    lc_messages.append(
                        ToolMessage(content=content, tool_call_id=m.get("tool_call_id", "call_0"))
                    )
                else:
                    lc_messages.append(HumanMessage(content=content))

        # Prepend system prompt if not already present
        if system_prompt and not (lc_messages and isinstance(lc_messages[0], SystemMessage)):
            lc_messages = [SystemMessage(content=system_prompt)] + lc_messages

        # 4. Resolve and bind model
        model = self.model or state.get("model")
        if model is None:
            fallback_msg = AIMessage(content="I am ready to assist with your healthcare administration.")
            return {
                "messages": [fallback_msg],
                "output": fallback_msg.content,
                "tool_calls": [],
                "current_agent": agent_id,
                "agent_id": agent_id,
                "effective_tools": effective_tool_names,
                "next_step": "output_guardrail",
            }

        bound_model = model
        if tools and hasattr(model, "bind_tools") and callable(model.bind_tools):
            try:
                bound_model = model.bind_tools(tools)
            except (NotImplementedError, Exception) as err:
                logger.debug("Model bind_tools not supported or skipped: %s", err)
                bound_model = model

        # 5. Invoke model
        try:
            if hasattr(bound_model, "ainvoke"):
                response = await bound_model.ainvoke(lc_messages)
            else:
                response = bound_model.invoke(lc_messages)
        except Exception as exc:
            logger.error("AgentExecutionNode model invocation failed: %s", exc)
            return {
                "error": str(exc),
                "error_exception": exc,
                "next_step": "error",
            }

        if not isinstance(response, BaseMessage):
            response = AIMessage(content=str(response))

        tool_calls = getattr(response, "tool_calls", []) or []
        next_step = "tools" if tool_calls else "output_guardrail"

        return {
            "messages": [response],
            "output": getattr(response, "content", ""),
            "tool_calls": tool_calls,
            "current_agent": agent_id,
            "agent_id": agent_id,
            "effective_tools": effective_tool_names,
            "next_step": next_step,
        }


__all__ = ["AgentExecutionNode"]
