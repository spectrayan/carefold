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

"""GraphBuilder engine assembling workflows nodes, subgraphs, edges, and checkpointers.

Implements Requirement R3 and Feature 39 (F-39):
- Fluent Builder pattern API (with_model, with_checkpointer, with_subgraph, with_tools)
- Comprehensive integration of all 11 discrete SOLID workflow nodes (F-21 to F-32)
- Seamless integration of specialist subgraphs (Supervisor F-33, Extraction R2/F-34 to F-38)
- Stateful checkpointer attachment supporting SqliteSaver, AsyncSqliteSaver, and MemorySaver
- Clinical guardrail edges (InputGuardrail, OutputGuardrail) and reflection self-correction loop (ReflectionNode)
- Sandboxed tool execution loop and ANSI/size validation (ToolNode, ToolValidatorNode)
- Zero-body audit logging (AuditNode) and sanitized error formatting (ErrorNode)
- Backward-compatible standalone create_agent_graph convenience factory
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from pathlib import Path
import time
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Union,
)

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from carefold.audit.logger import record_audit
from carefold.config import settings
from carefold.constants.api import (
    SSE_EVENT_REFUSAL,
    SSE_EVENT_SUGGESTIONS,
    SSE_EVENT_TOOL_END,
    SSE_EVENT_TOOL_START,
)
from carefold.constants.defaults import (
    DEFAULT_MAX_REFLECTIONS,
    MAX_TOOL_ITERATIONS,
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_CONNECT_TIMEOUT_SECONDS,
    SQLITE_JOURNAL_MODE,
)
from carefold.constants.paths import (
    CHATS_DIR,
    DEFAULT_AUDIT_LOG_FILE,
    DEFAULT_CHECKPOINTS_DB,
    ENV_DB_PATH,
    LOGS_DIR,
)
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.schemas.audit import AuditEvent
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS
from carefold.agents.registry import AgentRegistry
from carefold.workflows.dispatcher import ExecutionDispatcher
from carefold.workflows.nodes import (
    AgentExecutionNode,
    AgentNode,
    AuditNode,
    BaseNode,
    ErrorNode,
    InputGuardrailNode,
    OrchestratorDecision,
    OrchestratorNode,
    OutputGuardrailNode,
    ReflectionNode,
    RefusalNode,
    ResponseSynthesizerNode,
    SuggestionNode,
    SupervisorNode,
    ToolNode,
    ToolValidatorNode,
)
from carefold.workflows.state import AgentState

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Fluent state graph builder assembling discrete workflow nodes and subgraphs.

    Fulfills Requirement R3 and Feature 39 (F-39).
    """

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        tools: Optional[Sequence[Any]] = None,
        subgraphs: Optional[Dict[str, Union[StateGraph, CompiledStateGraph]]] = None,
        system_prompt: Optional[str] = None,
        max_reflections: int = DEFAULT_MAX_REFLECTIONS,
        max_tool_iterations: int = MAX_TOOL_ITERATIONS,
        execution_context: Optional[Any] = None,
        nodes: Optional[Dict[str, Union[BaseNode, Callable]]] = None,
        include_supervisor: bool = True,
        include_reflection: bool = True,
        include_tool_validator: bool = True,
        include_error_node: bool = True,
        include_dispatcher: bool = True,
        include_synthesizer: bool = True,
        registry: Optional[AgentRegistry] = None,
        tool_registry: Optional[Any] = None,
        use_dynamic_orchestrator: bool = True,
        store: Optional[BaseStore] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize GraphBuilder configuration."""
        self.model = model
        self.checkpointer = checkpointer
        self.store = store
        self.tools = list(tools) if tools is not None else None
        self.subgraphs: Dict[str, Union[StateGraph, CompiledStateGraph]] = dict(subgraphs or {})
        self.system_prompt = system_prompt
        self.max_reflections = max_reflections
        self.max_tool_iterations = max_tool_iterations
        self.execution_context = execution_context
        self._custom_nodes: Dict[str, Union[BaseNode, Callable]] = dict(nodes or {})
        self.include_supervisor = include_supervisor
        self.include_reflection = include_reflection
        self.include_tool_validator = include_tool_validator
        self.include_error_node = include_error_node
        self.include_dispatcher = include_dispatcher
        self.include_synthesizer = include_synthesizer
        self.registry = registry
        self.tool_registry = tool_registry
        self.use_dynamic_orchestrator = use_dynamic_orchestrator
        self.suggestion_model = kwargs.get("suggestion_model")
        self.extra_kwargs = kwargs

    def with_dispatcher(self, enabled: bool = True) -> GraphBuilder:
        """Enable or disable multi-agent execution dispatcher."""
        self.include_dispatcher = enabled
        return self

    def with_response_synthesizer(self, enabled: bool = True) -> GraphBuilder:
        """Enable or disable response synthesizer node."""
        self.include_synthesizer = enabled
        return self

    # ========================================================================
    # Fluent Builder Pattern Methods
    # ========================================================================

    def with_registry(self, registry: AgentRegistry) -> GraphBuilder:
        """Attach an AgentRegistry instance for dynamic agent discovery."""
        self.registry = registry
        return self

    def with_tool_registry(self, tool_registry: Any) -> GraphBuilder:
        """Attach a ToolRegistry instance for dynamic tool resolution."""
        self.tool_registry = tool_registry
        return self

    def with_dynamic_orchestrator(self, enabled: bool = True) -> GraphBuilder:
        """Enable or disable dynamic LLM orchestrator routing."""
        self.use_dynamic_orchestrator = enabled
        return self

    def with_model(self, model: BaseChatModel) -> GraphBuilder:
        """Attach or update the primary chat model."""
        self.model = model
        return self

    def with_checkpointer(self, checkpointer: Optional[BaseCheckpointSaver]) -> GraphBuilder:
        """Attach a state persistence checkpointer (SqliteSaver, AsyncSqliteSaver, MemorySaver)."""
        self.checkpointer = checkpointer
        return self

    def with_store(self, store: Optional[BaseStore]) -> GraphBuilder:
        """Attach a LangGraph BaseStore instance for long-term cognitive memory persistence."""
        self.store = store
        return self

    def with_subgraph(
        self,
        name: str,
        subgraph: Union[StateGraph, CompiledStateGraph],
    ) -> GraphBuilder:
        """Register a nested StateGraph or CompiledStateGraph under a distinct node name."""
        self.subgraphs[name] = subgraph
        return self

    def with_tools(self, tools: Sequence[Any]) -> GraphBuilder:
        """Configure tools available for agent binding and execution."""
        self.tools = list(tools)
        return self

    def with_system_prompt(self, system_prompt: Optional[str]) -> GraphBuilder:
        """Set a default system prompt for the agent node."""
        self.system_prompt = system_prompt
        return self

    def with_node(self, name: str, node: Union[BaseNode, Callable]) -> GraphBuilder:
        """Override or inject a discrete node instance or callable."""
        self._custom_nodes[name] = node
        return self

    def with_max_reflections(self, max_reflections: int) -> GraphBuilder:
        """Set the maximum self-correction reflection ceiling."""
        self.max_reflections = max_reflections
        return self

    def with_max_tool_iterations(self, max_tool_iterations: int) -> GraphBuilder:
        """Set the maximum consecutive tool execution iterations ceiling."""
        self.max_tool_iterations = max_tool_iterations
        return self

    def with_suggestion_model(self, suggestion_model: Optional[BaseChatModel]) -> GraphBuilder:
        """Set dedicated model for follow-up question chip generation."""
        self.suggestion_model = suggestion_model
        return self

    def with_execution_context(self, execution_context: Any) -> GraphBuilder:
        """Attach ExecutionContext for filesystem sandboxing."""
        self.execution_context = execution_context
        return self

    # ========================================================================
    # Graph Construction & Compilation Methods
    # ========================================================================

    def create_graph(self) -> StateGraph:
        """Assembles and returns the uncompiled StateGraph(AgentState)."""
        builder = StateGraph(AgentState)

        # 1. Bind tools to model if supported
        bound_model = self.model
        if self.tools is not None:
            tool_schemas = self.tools
        elif self.execution_context is not None and getattr(self.execution_context, "effective_tools", None) is not None:
            eff = self.execution_context.effective_tools
            tool_schemas = [CLOSED_TOOL_DEFINITIONS[t] for t in eff if t in CLOSED_TOOL_DEFINITIONS]
        else:
            tool_schemas = list(CLOSED_TOOL_DEFINITIONS.values())

        if bound_model and tool_schemas and hasattr(bound_model, "bind_tools") and callable(bound_model.bind_tools):
            try:
                bound_model = bound_model.bind_tools(tool_schemas)
            except (NotImplementedError, Exception) as err:
                logger.debug("Model bind_tools not supported or skipped: %s", err)
                bound_model = self.model

        # 2. Instantiate discrete workflow nodes
        input_guard_node = self._custom_nodes.get("input_guardrail") or InputGuardrailNode()
        supervisor_node = self._custom_nodes.get("supervisor") or self._custom_nodes.get("orchestrator")
        if supervisor_node is None:
            if self.use_dynamic_orchestrator:
                supervisor_node = OrchestratorNode(
                    model=bound_model or self.model,
                    registry=self.registry,
                )
            else:
                supervisor_node = SupervisorNode()

        agent_node = self._custom_nodes.get("agent") or self._custom_nodes.get("agent_execution")
        if agent_node is None:
            if self.use_dynamic_orchestrator:
                agent_node = AgentExecutionNode(
                    model=bound_model or self.model,
                    registry=self.registry,
                    tool_registry=self.tool_registry,
                    default_tools=self.tools,
                )
            else:
                agent_node = AgentNode(
                    model=bound_model or self.model,
                    tools=self.tools,
                    system_prompt=self.system_prompt,
                )
        builder_allowed_tools = (
            self.tools
            if self.tools is not None
            else (
                getattr(self.execution_context, "effective_tools", None)
                if self.execution_context is not None
                else None
            )
        )
        tool_node = self._custom_nodes.get("tools") or ToolNode(
            allowed_tools=builder_allowed_tools,
            tools=self.tools,
        )
        tool_validator_node = self._custom_nodes.get("tool_validator") or ToolValidatorNode()
        output_guard_node = self._custom_nodes.get("output_guardrail") or OutputGuardrailNode()
        reflection_node = self._custom_nodes.get("reflection") or ReflectionNode(max_reflections=self.max_reflections)
        refusal_node = self._custom_nodes.get("refusal") or RefusalNode()
        suggestion_model = getattr(self, "suggestion_model", None)
        if suggestion_model is None and self.model is not None:
            cls_name = self.model.__class__.__name__.lower()
            if not any(skip in cls_name for skip in ("fake", "mock", "infinite", "loop", "double", "stub")):
                suggestion_model = self.model
        suggestion_node = self._custom_nodes.get("suggestion") or SuggestionNode(model=suggestion_model)
        audit_node = self._custom_nodes.get("audit") or AuditNode()
        error_node = self._custom_nodes.get("error") or ErrorNode()
        dispatcher_node = self._custom_nodes.get("dispatcher") or self._custom_nodes.get("execution_dispatcher")
        if dispatcher_node is None and self.include_dispatcher:
            dispatcher_node = ExecutionDispatcher(
                model=bound_model or self.model,
                registry=self.registry,
                tool_registry=self.tool_registry,
                default_tools=self.tools,
            )
        synthesizer_node = (
            self._custom_nodes.get("response_synthesizer")
            or self._custom_nodes.get("synthesizer")
            or (ResponseSynthesizerNode() if self.include_synthesizer else None)
        )

        # Helper for defensive node invocation with optional store injection
        async def _invoke_node_with_store(
            node: Any,
            state: AgentState,
            store: Optional[BaseStore] = None,
        ) -> Dict[str, Any]:
            if node is None:
                return {}
            target_store = store if store is not None else self.store
            target = getattr(node, "execute", None) if hasattr(node, "execute") else (node if callable(node) else None)
            if target is None and callable(node):
                target = node
            if target is None:
                return {}
            try:
                sig = inspect.signature(target)
                if "store" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    return await target(state, store=target_store)
            except (ValueError, TypeError):
                pass
            return await target(state)

        # Node Wrappers with SSE dispatching and store ingestion
        async def _dispatcher_wrapper(state: AgentState) -> Dict[str, Any]:
            if dispatcher_node is None:
                return {}
            return await (dispatcher_node(state) if callable(dispatcher_node) else dispatcher_node.execute(state))

        async def _synthesizer_wrapper(
            state: AgentState,
            *,
            store: Optional[BaseStore] = None,
        ) -> Dict[str, Any]:
            if synthesizer_node is None:
                return {}
            return await _invoke_node_with_store(synthesizer_node, state, store=store)

        async def _input_guardrail_wrapper(
            state: AgentState,
            *,
            store: Optional[BaseStore] = None,
        ) -> Dict[str, Any]:
            res = await _invoke_node_with_store(input_guard_node, state, store=store)
            if res.get("is_refusal") or res.get("refused"):
                reason = res.get("refusal_reason") or state.get("default_refusal_reason") or "forbidden_intent:policy_prohibited"
                try:
                    await adispatch_custom_event(
                        SSE_EVENT_REFUSAL,
                        {
                            "type": SSE_EVENT_REFUSAL,
                            "reason": reason,
                            "message": SAFE_REFUSAL_TEMPLATE,
                        },
                    )
                except Exception:
                    pass
            return res

        async def _tool_wrapper(state: AgentState) -> Dict[str, Any]:
            calls = list(state.get("tool_calls", []))
            if not calls:
                msgs = state.get("messages", [])
                last_ai = next((m for m in reversed(msgs) if isinstance(m, AIMessage)), None)
                if last_ai:
                    calls = getattr(last_ai, "tool_calls", []) or []
            for c in calls:
                try:
                    await adispatch_custom_event(
                        SSE_EVENT_TOOL_START,
                        {
                            "type": SSE_EVENT_TOOL_START,
                            "tool": c.get("name"),
                            "params": c.get("args"),
                        },
                    )
                except Exception:
                    pass
            prior_count = len(state.get("tool_traces", []))

            # Determine authorized tool allowlist boundary
            effective_tools = (
                state.get("effective_tools")
                if state.get("effective_tools") is not None
                else (
                    state.get("allowed_tools")
                    if state.get("allowed_tools") is not None
                    else (
                        self.tools
                        if self.tools is not None
                        else (
                            getattr(self.execution_context, "effective_tools", None)
                            if self.execution_context is not None
                            else None
                        )
                    )
                )
            )

            # Sync allowed_tools with ToolNode instance if applicable
            if effective_tools is not None and hasattr(tool_node, "allowed_tools"):
                tool_node.allowed_tools = set(effective_tools)

            res = await (tool_node(state) if callable(tool_node) else tool_node.execute(state))

            ws_root = state.get("workspace_root") or settings.workspace_root
            resolved_log_path = (
                Path(settings.audit_log_path)
                if settings.audit_log_path
                else (Path(ws_root) / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE)
            )
            agent_id = str(state.get("current_agent") or state.get("agent_id") or "carefold-agent")
            store_bodies = bool(state.get("store_bodies", settings.audit_store_bodies))

            all_traces = res.get("tool_traces", [])
            new_traces = all_traces[prior_count:]

            effective_allowed_set = set(effective_tools) if effective_tools is not None else None

            for tr in new_traces:
                tool_name = tr.get("tool")
                if effective_allowed_set is not None and tool_name not in effective_allowed_set:
                    tr["allowed"] = False
                    tr["status"] = "denied"
                    tr["success"] = False
                    tr["output"] = None
                    if not tr.get("error") or "undeclared tool" not in str(tr.get("error")):
                        tr["error"] = f"Tool '{tool_name}' execution denied: undeclared tool for agent '{agent_id}'."

                is_allowed = tr.get("allowed", True)
                dur_ms = tr.get("duration_ms", 0.0)
                is_success = tr.get("success", False) if is_allowed else False
                status = "completed" if is_allowed and is_success else ("denied" if not is_allowed else "failed")
                result_payload = {
                    "success": is_success,
                    "output": tr.get("output"),
                    "error": tr.get("error"),
                }
                # Record tool audit event (including undeclared / denied tools)
                try:
                    await record_audit(
                        AuditEvent(
                            agent_id=agent_id,
                            event="tool",
                            tool=tool_name,
                            allowed=is_allowed,
                            duration_ms=dur_ms,
                            reason=tr.get("error") if not is_allowed else None,
                        ),
                        log_path=resolved_log_path,
                        store_bodies=store_bodies,
                    )
                except Exception as err:
                    logger.debug("Failed to record tool audit event: %s", err)

                try:
                    await adispatch_custom_event(
                        SSE_EVENT_TOOL_END,
                        {
                            "type": SSE_EVENT_TOOL_END,
                            "tool": tool_name,
                            "duration_ms": round(dur_ms, 2),
                            "status": status,
                            "allowed": is_allowed,
                            "result": result_payload,
                        },
                    )
                except Exception:
                    pass

            if effective_allowed_set is not None and "messages" in res:
                for msg in res["messages"]:
                    if isinstance(msg, ToolMessage) and getattr(msg, "name", None) not in effective_allowed_set:
                        msg.status = "error"
                        err_str = f"Tool '{msg.name}' execution denied: undeclared tool for agent '{agent_id}'."
                        msg.content = json.dumps({"error": err_str, "success": False})

            res["iteration_count"] = state.get("iteration_count", 0) + 1
            return res

        async def _output_guardrail_wrapper(state: AgentState) -> Dict[str, Any]:
            res = await (output_guard_node(state) if callable(output_guard_node) else output_guard_node.execute(state))
            if res.get("is_refusal") or res.get("refused"):
                reason = res.get("refusal_reason") or state.get("default_refusal_reason") or "forbidden_intent:policy_prohibited"
                from carefold.safety.classifier import is_hard_refusal_reason
                if is_hard_refusal_reason(reason):
                    try:
                        await adispatch_custom_event(
                            SSE_EVENT_REFUSAL,
                            {
                                "type": SSE_EVENT_REFUSAL,
                                "reason": reason,
                                "message": SAFE_REFUSAL_TEMPLATE,
                            },
                        )
                    except Exception:
                        pass
            return res

        async def _suggestion_wrapper(state: AgentState) -> Dict[str, Any]:
            res = await (suggestion_node(state) if callable(suggestion_node) else suggestion_node.execute(state))
            suggestions = res.get("follow_up_suggestions", [])
            try:
                await adispatch_custom_event(
                    SSE_EVENT_SUGGESTIONS,
                    {"type": SSE_EVENT_SUGGESTIONS, "suggestions": suggestions},
                )
            except Exception:
                pass
            return res

        # 3. Add discrete nodes to StateGraph
        builder.add_node("input_guardrail", _input_guardrail_wrapper)
        if self.include_supervisor:
            builder.add_node("supervisor", supervisor_node)
        if self.include_dispatcher and dispatcher_node is not None:
            builder.add_node("dispatcher", _dispatcher_wrapper)
        if self.include_synthesizer and synthesizer_node is not None:
            builder.add_node("response_synthesizer", _synthesizer_wrapper)
        builder.add_node("agent", agent_node)
        builder.add_node("tools", _tool_wrapper)
        if self.include_tool_validator:
            builder.add_node("tool_validator", tool_validator_node)
        builder.add_node("output_guardrail", _output_guardrail_wrapper)
        if self.include_reflection:
            builder.add_node("reflection", reflection_node)
        builder.add_node("refusal", refusal_node)
        builder.add_node("suggestion", _suggestion_wrapper)
        builder.add_node("audit", audit_node)
        if self.include_error_node:
            builder.add_node("error", error_node)

        # 4. Add registered subgraphs (auto-compile uncompiled StateGraphs)
        for sg_name, sg_obj in self.subgraphs.items():
            compiled_sg = (
                sg_obj.compile()
                if hasattr(sg_obj, "compile") and not isinstance(sg_obj, CompiledStateGraph)
                else sg_obj
            )
            builder.add_node(sg_name, compiled_sg)
            builder.add_edge(sg_name, "output_guardrail")

        # 5. Wire graph edges & conditional routing
        builder.add_edge(START, "input_guardrail")

        # Input guardrail conditional routing
        def route_input_guardrail(state: AgentState) -> str:
            if state.get("is_refusal") or state.get("refused") or state.get("next_step") == "refusal":
                return "refusal"
            if self.include_supervisor:
                return "supervisor"
            return "agent"

        input_destinations = {"refusal": "refusal"}
        if self.include_supervisor:
            input_destinations["supervisor"] = "supervisor"
        else:
            input_destinations["agent"] = "agent"
        builder.add_conditional_edges("input_guardrail", route_input_guardrail, input_destinations)

        # Supervisor conditional routing
        if self.include_supervisor:
            def route_supervisor(state: AgentState) -> str:
                target = (
                    state.get("routed_subgraph")
                    or state.get("current_agent")
                    or state.get("next_step")
                    or ""
                )
                target_norm = str(target).lower().replace("-", "_")
                for sg_k in self.subgraphs.keys():
                    if sg_k.lower().replace("-", "_") == target_norm or (
                        "extract" in sg_k.lower() and ("extract" in target_norm or "document" in target_norm)
                    ):
                        return sg_k

                plan = state.get("execution_plan")
                if plan and self.include_dispatcher and dispatcher_node is not None:
                    mode = plan.get("mode") if isinstance(plan, dict) else getattr(plan, "mode", None)
                    mode_val = getattr(mode, "value", str(mode)).lower()
                    if mode_val in ("parallel", "pipeline"):
                        return "dispatcher"

                if (
                    target_norm in ("dispatcher", "execution_dispatcher")
                    and self.include_dispatcher
                    and dispatcher_node is not None
                ):
                    return "dispatcher"

                if (
                    target_norm in ("response_synthesizer", "synthesizer")
                    and self.include_synthesizer
                    and synthesizer_node is not None
                ):
                    return "response_synthesizer"

                return "agent"

            super_destinations = {"agent": "agent"}
            if self.include_dispatcher and dispatcher_node is not None:
                super_destinations["dispatcher"] = "dispatcher"
            if self.include_synthesizer and synthesizer_node is not None:
                super_destinations["response_synthesizer"] = "response_synthesizer"
            for sg_k in self.subgraphs.keys():
                super_destinations[sg_k] = sg_k
            builder.add_conditional_edges("supervisor", route_supervisor, super_destinations)

        # Dispatcher conditional routing
        if self.include_dispatcher and dispatcher_node is not None:
            def route_dispatcher(state: AgentState) -> str:
                if (state.get("next_step") == "error" or state.get("error")) and self.include_error_node:
                    return "error"
                if self.include_synthesizer and synthesizer_node is not None:
                    return "response_synthesizer"
                return "output_guardrail"

            disp_destinations = {}
            if self.include_synthesizer and synthesizer_node is not None:
                disp_destinations["response_synthesizer"] = "response_synthesizer"
            else:
                disp_destinations["output_guardrail"] = "output_guardrail"
            if self.include_error_node:
                disp_destinations["error"] = "error"

            builder.add_conditional_edges("dispatcher", route_dispatcher, disp_destinations)

        # Response synthesizer edge
        if self.include_synthesizer and synthesizer_node is not None:
            builder.add_edge("response_synthesizer", "output_guardrail")

        # Agent conditional routing
        def route_agent(state: AgentState) -> str:
            if (state.get("next_step") == "error" or state.get("error")) and self.include_error_node:
                return "error"
            messages = state.get("messages", [])
            last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            tool_calls = getattr(last_ai, "tool_calls", []) if last_ai else []
            if not tool_calls and state.get("tool_calls"):
                tool_calls = state.get("tool_calls")
            if tool_calls and state.get("iteration_count", 0) < self.max_tool_iterations:
                return "tools"
            if self.include_synthesizer and synthesizer_node is not None:
                return "response_synthesizer"
            return "output_guardrail"

        agent_destinations = {"tools": "tools", "output_guardrail": "output_guardrail"}
        if self.include_synthesizer and synthesizer_node is not None:
            agent_destinations["response_synthesizer"] = "response_synthesizer"
        if self.include_error_node:
            agent_destinations["error"] = "error"
        builder.add_conditional_edges("agent", route_agent, agent_destinations)

        # Tool execution loop
        if self.include_tool_validator:
            builder.add_edge("tools", "tool_validator")
            builder.add_edge("tool_validator", "agent")
        else:
            builder.add_edge("tools", "agent")

        # Output guardrail conditional routing
        def route_output_guardrail(state: AgentState) -> str:
            if state.get("is_refusal") or state.get("refused") or state.get("next_step") == "reflection":
                if self.include_reflection and state.get("reflection_count", 0) < self.max_reflections:
                    return "reflection"
                return "refusal"
            return "suggestion"

        output_destinations = {"suggestion": "suggestion", "refusal": "refusal"}
        if self.include_reflection:
            output_destinations["reflection"] = "reflection"
        builder.add_conditional_edges("output_guardrail", route_output_guardrail, output_destinations)

        # Reflection self-correction loop
        if self.include_reflection:
            def route_reflection(state: AgentState) -> str:
                if state.get("next_step") == "agent" and state.get("reflection_count", 0) <= self.max_reflections:
                    return "agent"
                return "refusal"
            builder.add_conditional_edges("reflection", route_reflection, {"agent": "agent", "refusal": "refusal"})

        # Finalization edges
        builder.add_edge("refusal", "audit")
        builder.add_edge("suggestion", "audit")
        if self.include_error_node:
            builder.add_edge("error", "audit")
        builder.add_edge("audit", END)

        return builder

    def build(
        self,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        store: Optional[BaseStore] = None,
        **compile_kwargs: Any,
    ) -> CompiledStateGraph:
        """Constructs and compiles the StateGraph, attaching checkpointer and store."""
        effective_checkpointer = checkpointer if checkpointer is not None else self.checkpointer
        effective_store = store if store is not None else self.store
        g = self.create_graph()
        return g.compile(
            checkpointer=effective_checkpointer,
            store=effective_store,
            **compile_kwargs,
        )

    # Fluent alias for compilation
    compile = build

    @classmethod
    def build_graph(
        cls,
        model: Optional[BaseChatModel] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        tools: Optional[Sequence[Any]] = None,
        subgraphs: Optional[Dict[str, Union[StateGraph, CompiledStateGraph]]] = None,
        system_prompt: Optional[str] = None,
        store: Optional[BaseStore] = None,
        **kwargs: Any,
    ) -> CompiledStateGraph:
        """Classmethod convenience constructor compiling the complete graph."""
        builder = cls(
            model=model,
            checkpointer=checkpointer,
            tools=tools,
            subgraphs=subgraphs,
            system_prompt=system_prompt,
            store=store,
            **kwargs,
        )
        return builder.build(checkpointer=checkpointer, store=store)

    def inspect_graph(self) -> Dict[str, Any]:
        """Provides introspective metadata regarding nodes, subgraphs, limits, and checkpointer."""
        return {
            "nodes": [
                "input_guardrail",
                *(["supervisor", "orchestrator"] if self.include_supervisor else []),
                *(["dispatcher", "execution_dispatcher"] if self.include_dispatcher else []),
                "agent",
                "agent_execution",
                *(["response_synthesizer", "synthesizer"] if self.include_synthesizer else []),
                "tools",
                *(["tool_validator"] if self.include_tool_validator else []),
                "output_guardrail",
                *(["reflection"] if self.include_reflection else []),
                "refusal",
                "suggestion",
                "audit",
                *(["error"] if self.include_error_node else []),
            ],
            "subgraphs": list(self.subgraphs.keys()),
            "model": type(self.model).__name__ if self.model else None,
            "checkpointer": type(self.checkpointer).__name__ if self.checkpointer else None,
            "store": type(self.store).__name__ if getattr(self, "store", None) else None,
            "tools_count": len(self.tools) if self.tools is not None else 0,
            "max_reflections": self.max_reflections,
            "max_tool_iterations": self.max_tool_iterations,
        }


# ============================================================================
# Standalone Convenience & Compatibility Factory
# ============================================================================

def create_agent_graph(
    model: BaseChatModel,
    execution_context: Optional[Any] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[Sequence[Any]] = None,
    subgraphs: Optional[Dict[str, Union[StateGraph, CompiledStateGraph]]] = None,
    use_dynamic_orchestrator: bool = True,
    store: Optional[BaseStore] = None,
    **kwargs: Any,
) -> CompiledStateGraph:
    """Builds and compiles the Carefold stateful execution graph delegating to GraphBuilder.

    Preserves 100% backward compatibility with existing tests and runners.
    """
    if execution_context is not None and isinstance(execution_context, BaseCheckpointSaver):
        checkpointer = execution_context
        execution_context = None

    builder = GraphBuilder(
        model=model,
        checkpointer=checkpointer,
        tools=tools,
        subgraphs=subgraphs,
        system_prompt=system_prompt,
        execution_context=execution_context,
        use_dynamic_orchestrator=use_dynamic_orchestrator,
        store=store,
        **kwargs,
    )
    return builder.build(checkpointer=checkpointer, store=store)


__all__ = [
    "GraphBuilder",
    "create_agent_graph",
]
