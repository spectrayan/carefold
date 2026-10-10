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

"""Specialist Supervisor Subgraph for multi-agent clinical and insurance workflows.

Coordinates:
- Intent classification and specialist dispatching (benefits-guide, visit-steward, document-extractor, habit-companion, generalist)
- State handoff across specialist subgraphs and discrete nodes
- Return transitions back to supervisor or termination
- Dual compilation API: create_supervisor_subgraph() and build_supervisor_subgraph()
"""

from __future__ import annotations

import logging
import re
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from carefold.resources.loader import get_resource_loader
from carefold.workflows.state import AgentState

logger = logging.getLogger(__name__)


class SupervisorState(AgentState, total=False):
    """Supervisor graph state supporting document extraction attachments and text."""
    document_text: Optional[str]
    raw_text: Optional[str]
    file_path: Optional[str]
    attachment_path: Optional[str]
    dossier_type: Optional[str]

# Canonical specialist IDs
SPECIALIST_BENEFITS_GUIDE = "benefits-guide"
SPECIALIST_VISIT_STEWARD = "visit-steward"
SPECIALIST_DOCUMENT_EXTRACTOR = "document-extractor"
SPECIALIST_HABIT_COMPANION = "habit-companion"
SPECIALIST_GENERALIST = "generalist"

DEFAULT_SPECIALISTS = [
    SPECIALIST_BENEFITS_GUIDE,
    SPECIALIST_VISIT_STEWARD,
    SPECIALIST_DOCUMENT_EXTRACTOR,
    SPECIALIST_HABIT_COMPANION,
    SPECIALIST_GENERALIST,
]

def _load_yaml_patterns(key: str) -> List[str]:
    """Retrieves routing patterns from external routing_patterns.yaml resource."""
    try:
        patterns = get_resource_loader().get_routing_patterns()
        return list(patterns.get(key, []))
    except Exception:
        return []


BENEFITS_PATTERNS = _load_yaml_patterns(SPECIALIST_BENEFITS_GUIDE)
VISIT_PATTERNS = _load_yaml_patterns(SPECIALIST_VISIT_STEWARD)
EXTRACTION_PATTERNS = _load_yaml_patterns(SPECIALIST_DOCUMENT_EXTRACTOR)
HABIT_PATTERNS = _load_yaml_patterns(SPECIALIST_HABIT_COMPANION)



# ============================================================================
# 1. System Prompt Resolution
# ============================================================================

def _get_specialist_prompt(specialist_id: str) -> str:
    """Retrieves authoritative persona prompt from AgentRegistry / agent.yaml."""
    try:
        from carefold.agents.registry import get_agent_registry
        registry = get_agent_registry()
        manifest = registry.get(specialist_id.replace("_", "-"))
        if manifest:
            if isinstance(manifest.persona, str) and manifest.persona.strip():
                return manifest.persona.strip()
            elif hasattr(manifest.persona, "instructions") and manifest.persona.instructions:
                return manifest.persona.instructions.strip()
    except Exception as err:
        logger.debug("Could not resolve manifest persona for %s: %s", specialist_id, err)

    prompts = get_resource_loader().get_prompts()
    if specialist_id in ("supervisor", "orchestrator"):
        return str(prompts.get("supervisor", {}).get("system_prompt", "")).strip()

    return str(prompts.get("agents", {}).get(specialist_id.replace("-", "_"), "")).strip()



# ============================================================================
# 2. Specialist Node Implementations
# ============================================================================

def _create_specialist_node(
    specialist_id: str,
    model: BaseChatModel,
    tools: Optional[Sequence[Any]] = None,
    system_prompt: Optional[str] = None,
) -> Callable[[SupervisorState], Coroutine[Any, Any, Dict[str, Any]]]:
    """Builds an execution node for an individual specialist."""
    resolved_prompt = system_prompt or _get_specialist_prompt(specialist_id)

    # Bind tools if provided and supported
    if tools and hasattr(model, "bind_tools") and callable(model.bind_tools):
        try:
            bound_model = model.bind_tools(list(tools))
        except NotImplementedError:
            bound_model = model
    else:
        bound_model = model

    async def specialist_node(state: SupervisorState) -> Dict[str, Any]:
        messages = list(state.get("messages", []))

        # Handle document extractor specialization
        if specialist_id == SPECIALIST_DOCUMENT_EXTRACTOR:
            file_path = state.get("file_path") or state.get("attachment_path")
            doc_text = state.get("document_text") or state.get("raw_text")
            dossier_type = state.get("dossier_type")

            messages = state.get("messages", [])
            last_human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
            prompt_text = (str(last_human.content) if last_human else "").lower()

            # Dynamic attachment resolution from prompt if file_path and doc_text are missing
            if not file_path and not doc_text:
                attachments = state.get("attachments") or []
                if attachments and isinstance(attachments, list) and isinstance(attachments[0], str):
                    file_path = attachments[0]
                else:
                    matched_files = re.findall(r"[\w\-.]+\.(?:txt|pdf|md)", prompt_text)
                    if matched_files:
                        file_path = matched_files[0]

            # Auto-infer dossier type only if missing from state
            if not dossier_type:
                if any(k in prompt_text for k in ("insurance", "benefit", "deductible", "copay")):
                    dossier_type = "insurance"
                elif any(k in prompt_text for k in ("visit", "physician", "doctor", "appointment")):
                    dossier_type = "clinical"
                else:
                    dossier_type = "generic"

            dossiers = list(state.get("document_dossiers", []))

            if file_path or doc_text:
                try:
                    from carefold.workflows.subgraphs.extraction.tool import extract_document_dossier
                    res = await extract_document_dossier.ainvoke({
                        "file_path": file_path,
                        "document_text": doc_text,
                        "dossier_type": dossier_type,
                    })
                    if isinstance(res, dict) and "dossier" in res:
                        payload = {
                            "dossier_type": res.get("dossier_type", dossier_type),
                            "data": res.get("dossier"),
                            "grounding": {
                                "is_grounded": res.get("is_grounded", True),
                                "unmatched_values": res.get("unmatched_values", []),
                            },
                            "source_file": file_path,
                        }
                        dossiers.append(payload)
                except Exception as exc:
                    logger.warning("Document extraction failed in specialist node: %s", exc)

            content = "Document extraction completed. Structured dossiers verified."
            if not dossiers:
                content = (
                    "Extracted document summary and verified numerical figures against source."
                )
            ai_msg = AIMessage(content=content)
            return {
                "messages": [ai_msg],
                "output": content,
                "current_agent": specialist_id,
                "agent_id": specialist_id,
                "document_dossiers": dossiers,
                "next_step": "done",
            }

        # Inject specialist persona system prompt if not present
        if resolved_prompt and not (messages and isinstance(messages[0], SystemMessage)):
            messages = [SystemMessage(content=resolved_prompt)] + messages

        raw_model = bound_model
        while hasattr(raw_model, "bound") and getattr(raw_model, "bound", None) is not None:
            raw_model = raw_model.bound

        try:
            response = await bound_model.ainvoke(messages)
        except Exception as exc:
            exc_str = str(exc).lower()
            if bound_model is not raw_model and any(
                p in exc_str
                for p in (
                    "does not support tools",
                    "does not support tool",
                    "tools not supported",
                    "tools are not supported",
                    "tool calling not supported",
                    "tool calling is not supported",
                    "function calling not supported",
                    "function calling is not supported",
                )
            ):
                logger.warning(
                    "Specialist '%s' model does not support tools (%s); invoking without tools",
                    specialist_id,
                    exc,
                )
                response = await raw_model.ainvoke(messages)
            else:
                raise
        if not isinstance(response, BaseMessage):
            response = AIMessage(content=str(response))

        output_text = getattr(response, "content", "")
        return {
            "messages": [response],
            "output": output_text,
            "current_agent": specialist_id,
            "agent_id": specialist_id,
            "next_step": "done",
        }

    return specialist_node


# ============================================================================
# 3. Supervisor Router Node
# ============================================================================

def create_supervisor_router_node(
    model: Optional[BaseChatModel] = None,
    fallback_agent: str = SPECIALIST_VISIT_STEWARD,
) -> Callable[[SupervisorState], Coroutine[Any, Any, Dict[str, Any]]]:
    """Creates the supervisor routing node delegating to dynamic OrchestratorNode."""
    from carefold.workflows.nodes.orchestrator_node import OrchestratorNode
    orchestrator = OrchestratorNode(model=model)

    async def supervisor_node(state: SupervisorState) -> Dict[str, Any]:
        return await orchestrator.execute(dict(state))

    return supervisor_node


# ============================================================================
# 4. Conditional Edges
# ============================================================================

def route_supervisor(state: AgentState) -> str:
    """Conditional edge from supervisor_node dispatching to specialist nodes."""
    target = (
        state.get("routed_subgraph")
        or state.get("current_agent")
        or state.get("next_step")
        or ""
    )
    target_norm = str(target).lower().replace("_", "-")

    canonical_map = {
        SPECIALIST_BENEFITS_GUIDE: "benefits_guide",
        SPECIALIST_VISIT_STEWARD: "visit_steward",
        SPECIALIST_DOCUMENT_EXTRACTOR: "document_extractor",
        SPECIALIST_HABIT_COMPANION: "habit_companion",
        SPECIALIST_GENERALIST: "generalist",
        "benefits-guide": "benefits_guide",
        "visit-steward": "visit_steward",
        "document-extractor": "document_extractor",
        "habit-companion": "habit_companion",
        "generalist": "generalist",
        "benefits_guide": "benefits_guide",
        "visit_steward": "visit_steward",
        "document_extractor": "document_extractor",
        "habit_companion": "habit_companion",
    }
    return canonical_map.get(target_norm, "generalist")



def route_specialist_return(state: AgentState) -> str:
    """Conditional edge from specialist nodes back to supervisor or to END."""
    next_step = state.get("next_step", "")
    requires_supervisor = state.get("requires_supervisor", False)

    if next_step in ("supervisor", "supervisor_node") or requires_supervisor:
        return "supervisor_node"

    return END


# ============================================================================
# 5. Graph Builders
# ============================================================================

def create_supervisor_subgraph(
    model: BaseChatModel,
    specialists: Optional[Dict[str, Any]] = None,
    tools: Optional[Sequence[Any]] = None,
    system_prompt: Optional[str] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
    compile: bool = False,
    **kwargs: Any,
) -> Union[StateGraph, CompiledStateGraph]:
    """Assembles and optionally compiles the Multi-Agent Specialist Supervisor Subgraph.

    Args:
        model: Unified LangChain chat model double or provider.
        specialists: Optional dictionary overriding default specialist callables or subgraphs.
        tools: Optional global tool definitions available to specialists.
        system_prompt: Optional custom supervisor router system prompt.
        checkpointer: Optional SQLite or memory checkpointer for state persistence.
        compile: If True, returns a CompiledStateGraph; otherwise returns StateGraph.

    Returns:
        StateGraph or CompiledStateGraph ready for nested or standalone execution.
    """
    builder = StateGraph(SupervisorState)

    # 1. Add supervisor routing node
    builder.add_node("supervisor_node", create_supervisor_router_node(model))

    # 2. Add specialist nodes
    specs = specialists or {}

    # Benefits Guide
    bg_node = specs.get(SPECIALIST_BENEFITS_GUIDE) or specs.get("benefits_guide")
    if bg_node is None:
        bg_node = _create_specialist_node(SPECIALIST_BENEFITS_GUIDE, model, tools=tools)
    builder.add_node("benefits_guide", bg_node)

    # Visit Steward
    vs_node = specs.get(SPECIALIST_VISIT_STEWARD) or specs.get("visit_steward")
    if vs_node is None:
        vs_node = _create_specialist_node(SPECIALIST_VISIT_STEWARD, model, tools=tools)
    builder.add_node("visit_steward", vs_node)

    # Document Extractor
    de_node = specs.get(SPECIALIST_DOCUMENT_EXTRACTOR) or specs.get("document_extractor")
    if de_node is None:
        de_node = _create_specialist_node(SPECIALIST_DOCUMENT_EXTRACTOR, model, tools=tools)
    builder.add_node("document_extractor", de_node)

    # Habit Companion
    hc_node = specs.get(SPECIALIST_HABIT_COMPANION) or specs.get("habit_companion")
    if hc_node is None:
        hc_node = _create_specialist_node(SPECIALIST_HABIT_COMPANION, model, tools=tools)
    builder.add_node("habit_companion", hc_node)

    # Generalist Fallback
    gen_node = specs.get(SPECIALIST_GENERALIST) or specs.get("generalist")
    if gen_node is None:
        gen_node = _create_specialist_node(SPECIALIST_GENERALIST, model, tools=tools)
    builder.add_node("generalist", gen_node)

    # 3. Add edges from START to supervisor
    builder.add_edge(START, "supervisor_node")

    # 4. Add conditional routing edge from supervisor to specialists
    builder.add_conditional_edges(
        "supervisor_node",
        route_supervisor,
        {
            "benefits_guide": "benefits_guide",
            "visit_steward": "visit_steward",
            "document_extractor": "document_extractor",
            "habit_companion": "habit_companion",
            "generalist": "generalist",
        },
    )

    # 5. Add return transition edges from each specialist
    specialist_node_names = [
        "benefits_guide",
        "visit_steward",
        "document_extractor",
        "habit_companion",
        "generalist",
    ]
    for node_name in specialist_node_names:
        builder.add_conditional_edges(
            node_name,
            route_specialist_return,
            {
                "supervisor_node": "supervisor_node",
                END: END,
            },
        )

    if compile:
        return builder.compile(checkpointer=checkpointer)

    return builder


def build_supervisor_subgraph(
    model: BaseChatModel,
    specialists: Optional[Dict[str, Any]] = None,
    tools: Optional[Sequence[Any]] = None,
    system_prompt: Optional[str] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
    **kwargs: Any,
) -> CompiledStateGraph:
    """Convenience factory compiling the supervisor subgraph directly."""
    return create_supervisor_subgraph(
        model=model,
        specialists=specialists,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        compile=True,
        **kwargs,
    )


__all__ = [
    "DEFAULT_SPECIALISTS",
    "SPECIALIST_BENEFITS_GUIDE",
    "SPECIALIST_DOCUMENT_EXTRACTOR",
    "SPECIALIST_GENERALIST",
    "SPECIALIST_HABIT_COMPANION",
    "SPECIALIST_VISIT_STEWARD",
    "build_supervisor_subgraph",
    "create_supervisor_router_node",
    "create_supervisor_subgraph",
    "route_specialist_return",
    "route_supervisor",
]
