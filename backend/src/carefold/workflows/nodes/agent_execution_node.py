# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Unified agent execution node for all specialist agents (F-48).

Loads agent persona, forbidden constraints, and tool allowlists dynamically from
AgentRegistry, binds resolved tools via ToolRegistry, invokes the model, and
routes conditionally to 'tools' or 'output_guardrail'.
"""

from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Union
import uuid

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
from carefold.constants.agents import (
    WORKSPACE_NOTE_MCP_TOOLS,
    expand_workspace_note_tools,
)
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS
from carefold.workflows.nodes.base import BaseNode
from carefold.workflows.state import AgentState

logger = logging.getLogger(__name__)

_FENCED_JSON_RE = re.compile(r"```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```", re.IGNORECASE)
_FALLBACK_ENVELOPE_KEYS = frozenset({
    "name",
    "tool",
    "tool_name",
    "function",
    "args",
    "arguments",
    "params",
    "parameters",
    "input",
    "id",
    "call_id",
    "type",
    "tool_calls",
})


def _extract_tool_name(tool_obj: Any) -> str:
    """Extracts a canonical tool name from a ToolSpec, OpenAI dict, BaseTool, or string."""
    if hasattr(tool_obj, "name") and getattr(tool_obj, "name", None):
        return str(tool_obj.name)
    if isinstance(tool_obj, dict):
        fn = tool_obj.get("function")
        if isinstance(fn, dict) and fn.get("name"):
            return str(fn["name"])
        if tool_obj.get("name"):
            return str(tool_obj["name"])
        return ""
    return str(tool_obj)


def _serialize_tool_for_binding(tool_obj: Any) -> Any:
    """Serializes ToolSpec objects into OpenAI function definitions for model.bind_tools()."""
    to_def = getattr(tool_obj, "to_tool_definition", None)
    if callable(to_def):
        return to_def()
    return tool_obj


def _describe_tool_for_fallback(tool_obj: Any) -> Dict[str, Any]:
    """Builds a minimal JSON schema descriptor for models without native tool calling."""
    serialized = _serialize_tool_for_binding(tool_obj)
    if isinstance(serialized, dict):
        fn = serialized.get("function") if isinstance(serialized.get("function"), dict) else serialized
        return {
            "name": str(fn.get("name") or ""),
            "description": str(fn.get("description") or ""),
            "parameters": fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {},
        }
    name = _extract_tool_name(serialized)
    description = str(getattr(serialized, "description", "") or "")
    parameters: Dict[str, Any] = {}
    args_schema = getattr(serialized, "args_schema", None)
    if args_schema is not None and hasattr(args_schema, "model_json_schema"):
        try:
            parameters = args_schema.model_json_schema()
        except Exception:
            parameters = {}
    elif isinstance(getattr(serialized, "parameters", None), dict):
        parameters = dict(serialized.parameters)
    return {"name": name, "description": description, "parameters": parameters}


def _format_fallback_tool_instructions(tools: Sequence[Any], *, after_tool_result: bool) -> str:
    """Builds JSON tool invocation instructions for models without native bind_tools."""
    catalog = [
        desc
        for desc in (_describe_tool_for_fallback(t) for t in tools)
        if desc.get("name")
    ]
    serialized_catalog = json.dumps(catalog, indent=2, ensure_ascii=False)
    if after_tool_result:
        mode_guidance = (
            "A tool call has already executed above and its result is in the latest tool message. "
            "Never repeat a failed tool call or retry a missing file path; if a tool returned 'File not found' or an error, "
            "or if the tool result completes the user request, reply directly in clear plain language using the context already in the conversation WITHOUT outputting JSON. "
            "Only if a different follow-up tool call is genuinely required, respond ONLY with a JSON object matching the schema below."
        )
    else:
        mode_guidance = (
            "When you need to inspect records, search workspace files, or create, read, list, update, "
            "or delete a workspace note or record, respond ONLY with a JSON object matching the schema below "
            "and NO surrounding prose. Never invent or guess file paths (for example in `attach-read`) when no attachment filename or path was explicitly provided; "
            "if the user already included text inline or no tool call is needed, answer normally in plain language."
        )
    return (
        "# TOOL INVOCATION FALLBACK PROTOCOL\n"
        f"{mode_guidance}\n"
        "JSON format (put all tool arguments inside `args` using exact parameter names from Available tools):\n"
        '{"tool_calls": [{"name": "<tool_name>", "args": {<parameter_key>: <parameter_value>}}]}\n\n'
        "Available tools:\n"
        f"{serialized_catalog}"
    )


def _accepts_config_kwarg(fn: Any) -> bool:
    """Returns True when a callable accepts a `config` keyword or **kwargs parameter."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return any(
        p.name == "config" or p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )


async def _invoke_unbound_no_stream(raw_model: Any, messages: List[BaseMessage]) -> Any:
    """Invokes an unbound model while tagging LangChain chat models with `no_stream`."""
    use_tag = isinstance(raw_model, BaseChatModel)
    if hasattr(raw_model, "ainvoke"):
        if use_tag and _accepts_config_kwarg(raw_model.ainvoke):
            return await raw_model.ainvoke(messages, config={"tags": ["no_stream"]})
        return await raw_model.ainvoke(messages)
    if use_tag and _accepts_config_kwarg(raw_model.invoke):
        return raw_model.invoke(messages, config={"tags": ["no_stream"]})
    return raw_model.invoke(messages)


def _normalize_fallback_call_entry(entry: Any, allowed_names: set[str]) -> Optional[Dict[str, Any]]:
    """Validates and normalizes a single parsed JSON tool call entry."""
    if not isinstance(entry, dict):
        return None
    fn_obj = entry.get("function")
    fn_dict = fn_obj if isinstance(fn_obj, dict) else None
    raw_name = (
        entry.get("name")
        or entry.get("tool")
        or entry.get("tool_name")
        or (fn_dict.get("name") if fn_dict else None)
        or (fn_obj if isinstance(fn_obj, str) else None)
    )
    if not isinstance(raw_name, str) or raw_name not in allowed_names:
        return None

    raw_args: Any = None
    for key in ("args", "arguments", "params", "parameters", "input"):
        if key in entry and entry[key] is not None:
            raw_args = entry[key]
            break
    if raw_args is None and fn_dict is not None and fn_dict.get("arguments") is not None:
        raw_args = fn_dict["arguments"]
    if raw_args is None:
        raw_args = {k: v for k, v in entry.items() if k not in _FALLBACK_ENVELOPE_KEYS}

    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw_args, dict):
        return None
    return {
        "name": raw_name,
        "args": raw_args,
        "id": f"fallback_{uuid.uuid4().hex[:12]}",
        "type": "tool_call",
    }


def _parse_fallback_tool_calls(content: str, allowed_names: set[str]) -> List[Dict[str, Any]]:
    """Extracts validated tool_calls from a plain-text fallback response."""
    if not content or "{" not in content or not allowed_names:
        return []
    candidates: List[str] = [content.strip()]
    for match in _FENCED_JSON_RE.finditer(content):
        block = match.group(1).strip()
        if block:
            candidates.append(block)
    first_brace = content.find("{")
    last_brace = content.rfind("}")
    if 0 <= first_brace < last_brace:
        candidates.append(content[first_brace : last_brace + 1].strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        if isinstance(parsed.get("tool_calls"), list):
            normalized = [
                call
                for item in parsed["tool_calls"]
                if (call := _normalize_fallback_call_entry(item, allowed_names)) is not None
            ]
            if normalized:
                return normalized
        single = _normalize_fallback_call_entry(parsed, allowed_names)
        if single is not None:
            return [single]
    return []


def _render_messages_for_non_tool_model(
    messages: Sequence[BaseMessage],
    *,
    force_plain_text: bool = False,
) -> List[BaseMessage]:
    """Converts AIMessage(tool_calls) and ToolMessage history into user/assistant text turns.

    Chat templates without native tool support drop ``role='tool'`` messages and render
    empty ``AIMessage(content='')`` turns. Rendering tool calls and tool outputs into plain
    assistant/user messages preserves multi-turn visibility and strict role alternation.
    """
    rendered: List[BaseMessage] = []
    ended_with_tool = bool(messages and isinstance(messages[-1], ToolMessage))

    def _append_human(text_part: str) -> None:
        if not text_part:
            return
        if rendered and isinstance(rendered[-1], HumanMessage):
            prev = str(rendered[-1].content or "")
            rendered[-1] = HumanMessage(content=f"{prev}\n\n{text_part}" if prev else text_part)
        else:
            rendered.append(HumanMessage(content=text_part))

    def _append_ai(text_part: str) -> None:
        if rendered and isinstance(rendered[-1], AIMessage):
            prev = str(rendered[-1].content or "")
            rendered[-1] = AIMessage(content=f"{prev}\n\n{text_part}" if prev else text_part)
        else:
            rendered.append(AIMessage(content=text_part))

    for msg in messages:
        if isinstance(msg, SystemMessage):
            rendered.append(msg)
        elif isinstance(msg, AIMessage):
            raw_calls = getattr(msg, "tool_calls", None) or []
            raw_text = str(getattr(msg, "content", "") or "").strip()
            if raw_calls:
                calls_payload = json.dumps(
                    {
                        "tool_calls": [
                            {"name": tc.get("name"), "args": tc.get("args", {})}
                            for tc in raw_calls
                        ]
                    },
                    ensure_ascii=False,
                )
                combined = f"{raw_text}\n{calls_payload}" if raw_text else calls_payload
                _append_ai(combined)
            elif raw_text:
                _append_ai(raw_text)
        elif isinstance(msg, ToolMessage):
            t_name = str(getattr(msg, "name", None) or "tool").strip() or "tool"
            t_content = str(getattr(msg, "content", "") or "").strip()
            _append_human(f"[Tool Execution Result — {t_name}]\n{t_content}")
        elif isinstance(msg, HumanMessage):
            _append_human(str(getattr(msg, "content", "") or ""))
        else:
            rendered.append(msg)

    if force_plain_text:
        _append_human(
            "Tool execution limit reached for this turn. Using the tool execution results above, "
            "reply directly to the user in clear plain language WITHOUT outputting JSON or code fences."
        )
    elif ended_with_tool:
        _append_human(
            "Using the tool execution result above, if the user's request is fulfilled "
            "(or if an error cannot be fixed with different valid parameters), reply directly "
            "to the user in clear plain language WITHOUT outputting JSON or code fences. "
            "Only output a JSON tool call if a distinct follow-up tool step is genuinely required."
        )

    return rendered


def _completed_turn_tool_signatures(messages: Sequence[BaseMessage]) -> set[tuple[str, str]]:
    """Returns (tool_name, canonical_args_json) signatures that succeeded in the active turn."""
    last_user_idx = -1
    for idx, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            last_user_idx = idx
    turn_slice = messages[last_user_idx + 1 :] if last_user_idx >= 0 else messages

    tm_by_id: Dict[str, ToolMessage] = {}
    for msg in turn_slice:
        if isinstance(msg, ToolMessage):
            tid = str(getattr(msg, "tool_call_id", "") or "")
            if tid:
                tm_by_id[tid] = msg

    completed: set[tuple[str, str]] = set()
    for idx, msg in enumerate(turn_slice):
        if not isinstance(msg, AIMessage):
            continue
        for tc in (getattr(msg, "tool_calls", None) or []):
            tc_name = str(tc.get("name") or "")
            if not tc_name:
                continue
            tc_id = str(tc.get("id") or "")
            tm = tm_by_id.get(tc_id)
            if tm is None and idx + 1 < len(turn_slice) and isinstance(turn_slice[idx + 1], ToolMessage):
                tm = turn_slice[idx + 1]  # type: ignore[assignment]
            if tm is None:
                continue
            tm_status = str(getattr(tm, "status", "") or "").lower()
            tm_body = str(getattr(tm, "content", "") or "")
            if tm_status == "error" or '"error":' in tm_body:
                continue
            canonical_args = json.dumps(tc.get("args") or {}, sort_keys=True, default=str)
            completed.add((tc_name, canonical_args))
    return completed


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

    def _resolve_system_prompt(
        self,
        manifest: Any,
        state: Dict[str, Any],
        effective_tools: Optional[Sequence[str]] = None,
    ) -> str:
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

        effective_list = list(effective_tools or ())
        has_note_tools = any(
            t == "workspace-note" or t in WORKSPACE_NOTE_MCP_TOOLS
            for t in effective_list
        )
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
            "effective_tools": effective_list,
            "tools_summary": ", ".join(effective_list),
            "has_note_tools": has_note_tools,
        }

        from carefold.templates.engine import render_template
        return render_template("agent_execution_prompt", context)

    def _resolve_effective_tool_names(
        self, agent_id: str, manifest: Any, state: Dict[str, Any]
    ) -> List[str]:
        """Resolves deduplicated effective tool names and expands DB-backed note tools."""
        effective_tool_names: List[str] = []
        if state.get("effective_tools") is not None:
            effective_tool_names = list(state["effective_tools"])
        elif hasattr(self.registry, "get_effective_tools") and self.registry.get(agent_id) is not None:
            effective_tool_names = list(self.registry.get_effective_tools(agent_id))
        elif hasattr(self.registry, "_effective_tools") and agent_id in self.registry._effective_tools:
            effective_tool_names = list(self.registry._effective_tools[agent_id])
        elif manifest is not None and getattr(manifest, "tools", None) is not None:
            effective_tool_names = list(manifest.tools)
        elif self.default_tools is not None:
            effective_tool_names = [
                name for name in (_extract_tool_name(t) for t in self.default_tools) if name
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

        # Expand declarative MCP database toolset if requested in state
        db_toolset_name = state.get("db_toolset")
        if db_toolset_name:
            try:
                from carefold.tools.mcp_db_toolbox import get_db_toolbox

                toolbox = get_db_toolbox()
                if str(db_toolset_name) == "auto":
                    dom = str(getattr(manifest, "domain", "clinical") or "clinical")
                    rc = str(getattr(manifest, "risk_class", "assist") or "assist")
                    toolset_tools = toolbox.get_toolset_for_domain(dom, rc)
                else:
                    toolset_tools = toolbox.get_toolset(str(db_toolset_name))
                for t_name in toolset_tools:
                    if t_name not in effective_tool_names:
                        effective_tool_names.append(t_name)
            except Exception as err:
                logger.debug("MCP DB toolset expansion skipped: %s", err)

        return expand_workspace_note_tools(effective_tool_names)

    def _resolve_tools(
        self,
        agent_id: str,
        manifest: Any,
        state: Dict[str, Any],
        effective_tool_names: Optional[Sequence[str]] = None,
    ) -> List[Any]:
        """Resolves tool definitions or instances authorized for this agent."""
        names = (
            list(effective_tool_names)
            if effective_tool_names is not None
            else self._resolve_effective_tool_names(agent_id, manifest, state)
        )

        if self.tool_registry is not None and hasattr(self.tool_registry, "resolve"):
            return [_serialize_tool_for_binding(t) for t in self.tool_registry.resolve(names)]

        default_reg = None
        default_map = (
            {_extract_tool_name(t): t for t in self.default_tools}
            if self.default_tools is not None
            else {}
        )
        resolved: List[Any] = []
        for t_name in names:
            if t_name in CLOSED_TOOL_DEFINITIONS:
                resolved.append(CLOSED_TOOL_DEFINITIONS[t_name])
                continue
            if self.tool_registry and hasattr(self.tool_registry, "get"):
                t_obj = self.tool_registry.get(t_name)
                if t_obj is not None:
                    resolved.append(_serialize_tool_for_binding(t_obj))
                    continue
            if default_reg is None:
                from carefold.engine.tool_registry import create_default_registry

                default_reg = create_default_registry()
            spec = default_reg.get(t_name)
            if spec is not None:
                resolved.append(_serialize_tool_for_binding(spec))
            elif t_name in default_map:
                resolved.append(_serialize_tool_for_binding(default_map[t_name]))
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

        # 1. Resolve authorized tools before rendering prompt so tool instructions match allowlist
        effective_tool_names = self._resolve_effective_tool_names(agent_id, manifest, state)
        tools = self._resolve_tools(
            agent_id,
            manifest,
            state,
            effective_tool_names=effective_tool_names,
        )
        for t in tools:
            t_name = _extract_tool_name(t)
            if t_name and t_name not in effective_tool_names:
                effective_tool_names.append(t_name)

        # 2. Assemble system prompt
        system_prompt = self._resolve_system_prompt(
            manifest, state, effective_tools=effective_tool_names
        )

        # 3. Build messages list
        raw_messages = list(state.get("messages", []))
        parsed_messages: List[BaseMessage] = []
        for m in raw_messages:
            if isinstance(m, BaseMessage):
                parsed_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "")
                content = str(m.get("content", ""))
                if role == "system":
                    parsed_messages.append(SystemMessage(content=content))
                elif role in ("assistant", "ai"):
                    parsed_messages.append(AIMessage(content=content, tool_calls=m.get("tool_calls", [])))
                elif role == "tool":
                    parsed_messages.append(
                        ToolMessage(content=content, tool_call_id=m.get("tool_call_id", "call_0"))
                    )
                else:
                    parsed_messages.append(HumanMessage(content=content))

        # Strip orphan AIMessage tool_calls that were never followed by a ToolMessage
        lc_messages: List[BaseMessage] = []
        for idx, msg in enumerate(parsed_messages):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                next_is_tool = (idx + 1 < len(parsed_messages)) and isinstance(parsed_messages[idx + 1], ToolMessage)
                if not next_is_tool:
                    txt = str(getattr(msg, "content", "") or "").strip()
                    if txt:
                        lc_messages.append(AIMessage(content=txt))
                    continue
            lc_messages.append(msg)

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

        # Resolve raw underlying model if wrapped in RunnableBinding
        raw_model = model
        while hasattr(raw_model, "bound") and getattr(raw_model, "bound", None) is not None:
            raw_model = raw_model.bound

        iteration_count = int(state.get("iteration_count", 0) or 0)
        max_tool_iterations = int(state.get("max_tool_iterations", 3) or 3)

        bound_model = raw_model
        if (
            tools
            and iteration_count < max_tool_iterations
            and hasattr(raw_model, "bind_tools")
            and callable(raw_model.bind_tools)
        ):
            try:
                bound_model = raw_model.bind_tools(tools)
            except (NotImplementedError, Exception) as err:
                logger.debug("Model bind_tools not supported or skipped: %s", err)
                bound_model = raw_model

        has_fallback_tool_history = any(
            isinstance(m, AIMessage)
            and any(
                str(tc.get("id") or "").startswith("fallback_")
                for tc in (getattr(m, "tool_calls", None) or [])
            )
            for m in lc_messages
        )

        # 5. Invoke model
        if iteration_count >= max_tool_iterations and has_fallback_tool_history:
            try:
                response = await _invoke_unbound_no_stream(
                    raw_model,
                    _render_messages_for_non_tool_model(lc_messages, force_plain_text=True),
                )
            except Exception as fallback_exc:
                logger.error("AgentExecutionNode fallback model invocation failed: %s", fallback_exc)
                return {
                    "error": str(fallback_exc),
                    "error_exception": fallback_exc,
                    "next_step": "error",
                }
        else:
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
                        "Model does not support tools (%s); falling back to unbound model invocation for agent '%s'",
                        exc,
                        agent_id,
                    )
                    fallback_messages = list(lc_messages)
                    after_tool_result = bool(
                        fallback_messages and isinstance(fallback_messages[-1], ToolMessage)
                    )
                    use_json_tool_fallback = bool(tools and iteration_count < max_tool_iterations)
                    if use_json_tool_fallback:
                        fallback_instructions = _format_fallback_tool_instructions(
                            tools, after_tool_result=after_tool_result
                        )
                        if fallback_messages and isinstance(fallback_messages[0], SystemMessage):
                            base_sys = str(fallback_messages[0].content or "")
                            fallback_messages[0] = SystemMessage(
                                content=(
                                    f"{base_sys}\n\n{fallback_instructions}"
                                    if base_sys
                                    else fallback_instructions
                                )
                            )
                        else:
                            fallback_messages.insert(0, SystemMessage(content=fallback_instructions))
                    rendered_fallback = _render_messages_for_non_tool_model(
                        fallback_messages, force_plain_text=False
                    )
                    try:
                        response = await _invoke_unbound_no_stream(raw_model, rendered_fallback)
                    except Exception as fallback_exc:
                        logger.error("AgentExecutionNode fallback model invocation failed: %s", fallback_exc)
                        return {
                            "error": str(fallback_exc),
                            "error_exception": fallback_exc,
                            "next_step": "error",
                        }
                    if use_json_tool_fallback:
                        allowed_names = set(effective_tool_names)
                        raw_text = str(getattr(response, "content", response) or "")
                        parsed_calls = _parse_fallback_tool_calls(raw_text, allowed_names)
                        if parsed_calls:
                            novel_calls = parsed_calls
                            if after_tool_result:
                                done_sigs = _completed_turn_tool_signatures(lc_messages)
                                novel_calls = [
                                    c
                                    for c in parsed_calls
                                    if (
                                        c["name"],
                                        json.dumps(c.get("args") or {}, sort_keys=True, default=str),
                                    )
                                    not in done_sigs
                                ]
                            if novel_calls:
                                response = AIMessage(content="", tool_calls=novel_calls)
                            else:
                                try:
                                    response = await _invoke_unbound_no_stream(
                                        raw_model,
                                        _render_messages_for_non_tool_model(
                                            lc_messages, force_plain_text=True
                                        ),
                                    )
                                except Exception as rewrite_exc:
                                    logger.error(
                                        "AgentExecutionNode duplicate-tool fallback rewrite failed: %s",
                                        rewrite_exc,
                                    )
                                    return {
                                        "error": str(rewrite_exc),
                                        "error_exception": rewrite_exc,
                                        "next_step": "error",
                                    }
                else:
                    logger.error("AgentExecutionNode model invocation failed: %s", exc)
                    return {
                        "error": str(exc),
                        "error_exception": exc,
                        "next_step": "error",
                    }

        if not isinstance(response, BaseMessage):
            response = AIMessage(content=str(response))

        tool_calls = getattr(response, "tool_calls", []) or []
        if tool_calls and iteration_count >= max_tool_iterations:
            tool_calls = []
            if not str(getattr(response, "content", "") or "").strip():
                try:
                    final_ctx = (
                        _render_messages_for_non_tool_model(lc_messages, force_plain_text=True)
                        if has_fallback_tool_history
                        else lc_messages
                    )
                    response = await _invoke_unbound_no_stream(raw_model, final_ctx)
                    if not isinstance(response, BaseMessage):
                        response = AIMessage(content=str(response))
                except Exception as err:
                    logger.debug("Final-turn unbound fallback failed: %s", err)

        if not tool_calls and effective_tool_names:
            raw_reply = str(getattr(response, "content", "") or "")
            if _parse_fallback_tool_calls(raw_reply, set(effective_tool_names)):
                stripped_reply = _FENCED_JSON_RE.sub("", raw_reply).strip()
                if stripped_reply and not _parse_fallback_tool_calls(
                    stripped_reply, set(effective_tool_names)
                ):
                    response = AIMessage(content=stripped_reply)
                else:
                    try:
                        rewrite_msgs = _render_messages_for_non_tool_model(
                            lc_messages, force_plain_text=True
                        )
                        rewritten = await _invoke_unbound_no_stream(raw_model, rewrite_msgs)
                        rewritten_text = _FENCED_JSON_RE.sub(
                            "", str(getattr(rewritten, "content", rewritten) or "")
                        ).strip()
                        if rewritten_text:
                            response = AIMessage(content=rewritten_text)
                    except Exception as err:
                        logger.debug("Final-turn fallback plain-text rewrite failed: %s", err)

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
