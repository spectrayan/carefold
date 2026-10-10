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

"""AgentExecutionService for Carefold streaming engine and thread lifecycle management.

Handles LangGraph stateful workflow execution, real-time SSE event streaming,
checkpoint persistence, thread state inspection, and graceful disconnect recovery.
Satisfies Requirement R3 and Feature F-40.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import inspect
import json
import logging
from pathlib import Path
import time
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
)
import uuid

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCallChunk,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from carefold.audit.logger import record_audit
from carefold.config import settings
from carefold.constants.api import (
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_MESSAGE,
    SSE_EVENT_REFUSAL,
    SSE_EVENT_SUGGESTIONS,
    SSE_EVENT_TOKEN,
    SSE_EVENT_TOOL_END,
    SSE_EVENT_TOOL_START,
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
)
from carefold.constants.models import PROVIDER_OLLAMA
from carefold.constants.paths import AGENTS_DIR, DEFAULT_AUDIT_LOG_FILE, LOGS_DIR, SKILLS_DIR, SYSTEM_AGENTS_DIR
from carefold.engine.graph import (
    create_agent_graph,
    create_async_sqlite_saver,
    generate_follow_up_suggestions,
    resolve_checkpointer_path,
)
from carefold.engine.prompt_builder import build_system_prompt
from carefold.loaders.agent_loader import find_agent_dir, load_agent
from carefold.model.factory import create_chat_model
from carefold.safety.classifier import check_safety_refusal, is_hard_refusal_reason
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.schemas.audit import AuditEvent
from carefold.schemas.chat import ChatMessage, ChatRequestBody
from carefold.schemas.manifest import AgentManifest, AgentPersonaObject, RiskClass, SkillManifest, SLUG_REGEX
from carefold.logging import get_logger
from carefold.workflows.nodes.base import sanitize_log_message
from carefold.workflows.state import AgentState

logger = get_logger("carefold.engine.service")

# Nodes whose chat model invocations are internal/structural and must never stream tokens to the user chat UI
NON_STREAMING_NODES: set[str] = {
    "suggestion",
    "suggestion_node",
    "supervisor",
    "orchestrator",
    "dispatcher",
    "input_guardrail",
    "safety_guard_node",
    "output_guardrail",
    "post_safety_node",
    "tools",
    "tools_node",
    "tool_validator",
    "reflection",
    "refusal",
    "audit",
    "audit_node",
    "error",
    "skill_generator",
    "document_extractor",
    "triage_auditor",
    "quality_reviewer",
}


# ============================================================================
# Generic Stream Chat Adapter for Non-BaseChatModel Callers
# ============================================================================

class _StreamChatModelAdapter(BaseChatModel):
    """Internal adapter wrapping any stream_chat callable into a BaseChatModel.

    Guarantees backward compatibility for tests passing custom streaming clients
    without introducing mock references into production code.
    """

    client: Any
    bound_tools: Optional[List[Any]] = None

    @property
    def _llm_type(self) -> str:
        return "carefold-stream-chat-adapter"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("Use async astream / ainvoke.")

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], type, Any]],
        **kwargs: Any,
    ) -> Any:
        return self.__class__(client=self.client, bound_tools=list(tools))

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        # Convert LangChain messages to role/content objects
        converted_messages: List[Any] = []
        for m in messages:
            role = "user"
            tool_calls = None
            tool_call_id = None
            msg_type = getattr(m, "type", "")

            if isinstance(m, HumanMessage) or msg_type in ("human", "user"):
                role = "user"
            elif isinstance(m, AIMessage) or msg_type in ("ai", "assistant"):
                role = "assistant"
                if getattr(m, "tool_calls", None):
                    tool_calls = [
                        {
                            "id": tc.get("id"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name"),
                                "arguments": json.dumps(tc.get("args", {}))
                                if isinstance(tc.get("args"), dict)
                                else str(tc.get("args") or "{}"),
                            },
                        }
                        for tc in m.tool_calls
                    ]
            elif isinstance(m, ToolMessage) or msg_type == "tool":
                role = "tool"
                tool_call_id = getattr(m, "tool_call_id", None)
            elif isinstance(m, SystemMessage) or msg_type == "system":
                role = "system"

            content_str = str(m.content) if m.content is not None else ""
            msg_obj = type(
                "GenericModelMessage",
                (),
                {
                    "role": role,
                    "content": content_str or None,
                    "tool_calls": tool_calls,
                    "tool_call_id": tool_call_id,
                },
            )()
            converted_messages.append(msg_obj)

        tools = self.bound_tools or kwargs.get("tools")
        async for chunk in self.client.stream_chat(converted_messages, tools=tools):
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                yield ChatGenerationChunk(message=AIMessageChunk(content=delta.content))
            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    func_args = getattr(tc.function, "arguments", "{}") or "{}"
                    func_name = getattr(tc.function, "name", "") or ""
                    tc_id = getattr(tc, "id", None) or f"call_{getattr(tc, 'index', 0)}"
                    tc_index = getattr(tc, "index", 0)
                    yield ChatGenerationChunk(
                        message=AIMessageChunk(
                            content="",
                            tool_call_chunks=[
                                ToolCallChunk(
                                    name=func_name,
                                    args=func_args,
                                    id=tc_id,
                                    index=tc_index,
                                )
                            ],
                        )
                    )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        gen_chunk: Optional[ChatGenerationChunk] = None
        async for chunk in self._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            if gen_chunk is None:
                gen_chunk = chunk
            else:
                gen_chunk += chunk
        if gen_chunk is None:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])
        return ChatResult(generations=[ChatGeneration(message=gen_chunk.message)])


def strip_internal_suggestion_leakage(text: str) -> str:
    """Strips accidental suggestion generator preamble or raw JSON question blocks."""
    if not text:
        return text
    import re
    has_leakage = False

    def _replace_preamble(m: Any) -> str:
        nonlocal has_leakage
        has_leakage = True
        return m.group(1) or ""

    def _replace_json(m: Any) -> str:
        nonlocal has_leakage
        has_leakage = True
        return ""

    cleaned = re.sub(
        r"(\.|\?|\!)?\s*(?:assistant\s*\n+|\n|^)Here are \d+ concise follow-up questions.*$",
        _replace_preamble,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"(?:\n|^)\[\s*\"[^\"]+\?\s*\"(?:\s*,\s*\"[^\"]+\?\s*\")*\s*\]\s*$",
        _replace_json,
        cleaned,
        flags=re.DOTALL,
    )
    return cleaned.rstrip() if has_leakage else cleaned


def strip_reference_doc_preamble(text: str) -> str:
    """Strips robotic 'Based on the provided reference document/guide...' opening phrases."""
    if not text:
        return text
    import re
    pattern = r"^(?:(?:\*|_){0,2}(?:(?:Based on|According to|From) (?:the )?(?:provided )?reference (?:document|guide|material|checklist|information|docs?)(?: provided)?)[,:]?(?:\*|_){0,2}[,:]?\s*)"
    cleaned = re.sub(pattern, "", text.lstrip(), flags=re.IGNORECASE).lstrip("*_ \t")
    if cleaned and cleaned != text:
        cleaned = cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper()
    return cleaned


# ============================================================================
# AgentExecutionService
# ============================================================================

class AgentExecutionService:
    """Execution engine and thread session manager for Carefold specialist agents.

    Provides streaming turn execution, thread persistence inspection, and SSE
    protocol wire formatting.
    """

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        graph: Optional[CompiledStateGraph] = None,
        graph_builder: Optional[Any] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        store: Optional[BaseStore] = None,
        memory_adapter: Optional[Any] = None,
        db_path: Optional[Union[str, Path]] = None,
        workspace_root: Optional[Union[str, Path]] = None,
        store_bodies: Optional[bool] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the execution service with model, graph, checkpointer, and memory settings."""
        self.model = model
        self.graph = graph
        self.graph_builder = graph_builder
        self.checkpointer = checkpointer
        self.store = store if store is not None else kwargs.get("store")
        self.memory_adapter = memory_adapter if memory_adapter is not None else kwargs.get("memory_adapter")
        if self.memory_adapter is None and self.store is None:
            try:
                from carefold.memory.factory import get_memory_port
                self.memory_adapter = get_memory_port()
            except Exception as exc:
                logger.debug("Default MemoryPort could not be initialized: %s", exc)
                self.memory_adapter = None

        self.workspace_root = Path(workspace_root) if workspace_root else settings.workspace_root
        self.db_path = Path(db_path) if db_path else None
        self.store_bodies = store_bodies if store_bodies is not None else settings.audit_store_bodies
        self.extra_kwargs = kwargs

    # ------------------------------------------------------------------------
    # Event Formatting Helpers
    # ------------------------------------------------------------------------

    @staticmethod
    def format_token_event(delta: str) -> Dict[str, Any]:
        """Formats a token streaming event."""
        return {"type": SSE_EVENT_TOKEN, "delta": delta}

    @staticmethod
    def format_tool_start_event(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Formats a tool invocation start event."""
        return {"type": SSE_EVENT_TOOL_START, "tool": tool, "params": params}

    @staticmethod
    def format_tool_end_event(
        tool: str,
        duration_ms: float,
        status: str,
        allowed: bool,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Formats a tool execution completion event."""
        return {
            "type": SSE_EVENT_TOOL_END,
            "tool": tool,
            "duration_ms": duration_ms,
            "status": status,
            "allowed": allowed,
            "result": result,
        }

    @staticmethod
    def format_refusal_event(
        reason: str,
        message: str = SAFE_REFUSAL_TEMPLATE,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Formats a clinical safety refusal event."""
        payload: Dict[str, Any] = {"type": SSE_EVENT_REFUSAL, "reason": reason, "message": message}
        if category:
            payload["category"] = category
        return payload

    @staticmethod
    def format_suggestions_event(suggestions: List[str]) -> Dict[str, Any]:
        """Formats an AI follow-up suggestion chips event."""
        return {"type": SSE_EVENT_SUGGESTIONS, "suggestions": suggestions}

    @staticmethod
    def format_done_event(
        full_text: str,
        thread_id: str,
        audit_event_id: Optional[str] = None,
        refused: bool = False,
        refusal_reason: Optional[str] = None,
        boundary_warning: bool = False,
        boundary_reason: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        citations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Formats the terminal completion event."""
        chips = suggestions or []
        payload: Dict[str, Any] = {
            "type": SSE_EVENT_DONE,
            "fullText": strip_reference_doc_preamble(strip_internal_suggestion_leakage(full_text)),
            "auditEventId": audit_event_id,
            "refused": refused,
            "refusalReason": refusal_reason,
            "boundaryWarning": boundary_warning,
            "boundaryReason": boundary_reason,
            "suggestions": chips,
            "followUpSuggestions": chips,
            "threadId": thread_id,
        }
        if citations:
            payload["citations"] = citations
        return payload

    @staticmethod
    def format_error_event(message: str) -> Dict[str, Any]:
        """Formats a sanitized error event."""
        return {"type": SSE_EVENT_ERROR, "message": sanitize_log_message(message)}

    @staticmethod
    def format_sse_wire_event(event: Dict[str, Any]) -> str:
        """Encodes an event dictionary into the Server-Sent Events wire format."""
        event_type = event.get("type", SSE_EVENT_MESSAGE)
        data_str = json.dumps(event)
        return f"event: {event_type}\ndata: {data_str}\n\n"

    # ------------------------------------------------------------------------
    # Execution Methods
    # ------------------------------------------------------------------------

    async def execute_turn(
        self,
        thread_id: str,
        prompt: str,
        user_id: str = "default_user",
        profile_id: Optional[str] = None,
        attachments: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
        messages: Optional[List[Union[ChatMessage, BaseMessage, Dict[str, Any]]]] = None,
        allow_clinical: bool = True,
        model: Optional[Any] = None,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        store_bodies: Optional[bool] = None,
        store: Optional[BaseStore] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Executes a single conversation turn through the LangGraph agent graph.

        Yields real-time event dictionaries for tokens, tool calls, refusals,
        suggestions, and terminal completion records.
        """
        start_time = time.time()
        raw_agent_id = str(agent_id or "visit-steward").strip()
        effective_agent_id = raw_agent_id if SLUG_REGEX.match(raw_agent_id) and not raw_agent_id.startswith(".") else "visit-steward"
        ws_root = self.workspace_root.resolve()
        agents_dir = (ws_root / AGENTS_DIR).resolve()
        skills_dir = (ws_root / SKILLS_DIR).resolve()
        agent_dir = (
            find_agent_dir(agents_dir, effective_agent_id)
            or find_agent_dir(agents_dir, "visit-steward")
            or (agents_dir / "visit-steward").resolve()
        )

        effective_store_bodies = store_bodies if store_bodies is not None else self.store_bodies
        resolved_log_path = (
            Path(settings.audit_log_path)
            if settings.audit_log_path
            else (ws_root / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE)
        )

        # 1. Load agent and verify clinical risk class gating
        try:
            agent, effective_tools, skills = load_agent(agent_dir, skills_dir)
        except Exception as err:
            logger.warning("Failed to load agent '%s': %s. Using default agent manifest.", effective_agent_id, err)
            agent = AgentManifest(
                id=effective_agent_id,
                title=effective_agent_id,
                risk_class=RiskClass.WELLNESS,
                model="carefold-default",
                persona=AgentPersonaObject(role="Care navigation assistant"),
            )
            effective_tools = []
            skills = []

        if agent.risk_class == RiskClass.CLINICAL_ASSIST and not allow_clinical:
            err_msg = (
                f"Agent '{effective_agent_id}' is classified as clinical_assist. "
                "Execution is forbidden without explicit clinical consent (allow_clinical=True)."
            )
            await record_audit(
                AuditEvent(
                    agent_id=agent.id,
                    event="refuse",
                    allowed=False,
                    reason="forbidden_risk_class:clinical_assist_unauthorized",
                    duration_ms=(time.time() - start_time) * 1000,
                ),
                log_path=resolved_log_path,
                store_bodies=effective_store_bodies,
            )
            yield self.format_error_event(err_msg)
            return

        # 2. Resolve Chat Model
        active_model = model or self.model
        if active_model is None:
            req_provider = provider or PROVIDER_OLLAMA
            req_model = model_name

            if not req_model:
                if isinstance(agent.model, str):
                    req_model = agent.model
                elif hasattr(agent.model, "name") and agent.model.name:
                    req_model = agent.model.name
                if hasattr(agent.model, "provider") and agent.model.provider and not provider:
                    req_provider = agent.model.provider

            active_model = create_chat_model(
                provider=req_provider,
                model=req_model,
                api_key=api_key,
                base_url=base_url,
            )
        elif not isinstance(active_model, BaseChatModel) and hasattr(active_model, "stream_chat"):
            active_model = _StreamChatModelAdapter(client=active_model)

        # 3. Build Execution Context
        from carefold.engine.runner import ExecutionContext

        execution_context = ExecutionContext(
            workspace_root=ws_root,
            skills_dir=skills_dir,
            agent=agent,
            effective_tools=effective_tools,
            skills=skills,
        )

        logger.info(
            "workflow_turn_started",
            engine="LANGGRAPH_WORKFLOW",
            agent_id=effective_agent_id,
            thread_id=thread_id,
            provider=provider or PROVIDER_OLLAMA,
            model=model_name or getattr(active_model, "model_name", None) or "default",
            tools=effective_tools,
        )

        # 4. Format Input Messages
        system_prompt = build_system_prompt(agent, skills, effective_tools)
        initial_messages: List[BaseMessage] = []

        if messages:
            for msg in messages:
                if isinstance(msg, BaseMessage):
                    initial_messages.append(msg)
                elif isinstance(msg, dict):
                    role = msg.get("role", "user")
                    content = str(msg.get("content", ""))
                    if role == "system":
                        initial_messages.append(SystemMessage(content=content))
                    elif role in ("user", "human"):
                        initial_messages.append(HumanMessage(content=content))
                    elif role in ("assistant", "ai"):
                        initial_messages.append(AIMessage(content=content))
                    elif role == "tool":
                        initial_messages.append(
                            ToolMessage(content=content, tool_call_id=msg.get("tool_call_id", "call_0"))
                        )
                elif hasattr(msg, "role"):
                    r = msg.role
                    c = getattr(msg, "content", "") or ""
                    if r == "system":
                        initial_messages.append(SystemMessage(content=c))
                    elif r in ("user", "human"):
                        initial_messages.append(HumanMessage(content=c))
                    elif r in ("assistant", "ai"):
                        initial_messages.append(AIMessage(content=c))
                    elif r == "tool":
                        initial_messages.append(
                            ToolMessage(content=c, tool_call_id=getattr(msg, "tool_call_id", "call_0") or "call_0")
                        )

        user_content = prompt
        if attachments:
            user_content += f"\n\n[Attached files: {', '.join(attachments)}]"
        initial_messages.append(HumanMessage(content=user_content))

        # 5. Resolve Checkpointer Database Path
        db_path = self.db_path or resolve_checkpointer_path(ws_root)

        accumulated_text = ""
        refusal_triggered = False
        refusal_reason: Optional[str] = None
        suggestions: List[str] = []
        citations: List[Dict[str, Any]] = []

        initial_input: Dict[str, Any] = {
            "messages": initial_messages,
            "thread_id": thread_id,
            "user_id": user_id,
            "profile_id": profile_id or kwargs.get("profile_id"),
            "agent_id": agent.id,
            "current_agent": agent.id,
            "explicit_agent": agent_id,
            "effective_tools": effective_tools,
            "workspace_root": str(ws_root),
            "skills_dir": str(skills_dir),
            "system_prompt": system_prompt,
            "refused": False,
            "is_refusal": False,
            "refusal_reason": None,
            "follow_up_suggestions": [],
            "document_dossiers": [],
            "store_bodies": effective_store_bodies,
            "allow_clinical": allow_clinical,
            "attachments": attachments or [],
            "notes": [],
            "emergency_red_flags": None,
            "execution_plan": None,
            "provisioned_references": {},
            "specialist_outputs": {},
        }
        # Ingest multi-source context (attachments, notes, catalog summary)
        from carefold.loaders.context_loader import ContextLoader
        initial_input = ContextLoader.load_context(initial_input, ws_root)

        graph_config = {"configurable": {"thread_id": thread_id}}

        # Helper context manager supporting both self.checkpointer and default AsyncSqliteSaver
        @asynccontextmanager
        async def _resolve_checkpointer():
            if self.checkpointer is not None:
                yield self.checkpointer
            else:
                async with create_async_sqlite_saver(db_path) as saver:
                    yield saver

        # 6. Stream Execution Events
        try:
            async with _resolve_checkpointer() as checkpointer:
                # Retrieve BaseStore from explicit parameter, self.memory_adapter, self.store, or kwargs
                effective_store = (
                    store
                    if store is not None
                    else (
                        getattr(self.memory_adapter, "store", None)
                        or getattr(self, "store", None)
                        or kwargs.get("store")
                    )
                )

                # Resolve compiled graph
                if self.graph is not None:
                    compiled_graph = self.graph
                elif self.graph_builder is not None:
                    if hasattr(self.graph_builder, "build"):
                        compiled_graph = self.graph_builder.build(checkpointer=checkpointer, store=effective_store)
                    elif hasattr(self.graph_builder, "build_graph"):
                        compiled_graph = self.graph_builder.build_graph(active_model, checkpointer=checkpointer, store=effective_store)
                    elif callable(self.graph_builder):
                        sig = inspect.signature(self.graph_builder)
                        b_kwargs = {"execution_context": execution_context, "checkpointer": checkpointer}
                        if "store" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                            b_kwargs["store"] = effective_store
                        compiled_graph = self.graph_builder(active_model, **b_kwargs)
                    else:
                        compiled_graph = create_agent_graph(active_model, execution_context=execution_context, checkpointer=checkpointer, store=effective_store)
                else:
                    # Attempt import from builder.py, fallback to graph.py
                    try:
                        from carefold.engine.builder import GraphBuilder
                        builder_instance = (
                            GraphBuilder()
                            .with_model(active_model)
                            .with_checkpointer(checkpointer)
                            .with_execution_context(execution_context)
                            .with_tools(effective_tools)
                        )
                        if effective_store is not None:
                            builder_instance = builder_instance.with_store(effective_store)
                        compiled_graph = builder_instance.build(checkpointer=checkpointer, store=effective_store)
                    except (ImportError, AttributeError):
                        compiled_graph = create_agent_graph(active_model, execution_context=execution_context, checkpointer=checkpointer, store=effective_store)

                async for event in compiled_graph.astream_events(initial_input, config=graph_config, version="v2"):
                    ev_kind = event.get("event")

                    # Stream model token chunks
                    if ev_kind == "on_chat_model_stream":
                        node_name = event.get("metadata", {}).get("langgraph_node")
                        tags = event.get("tags") or []
                        if (
                            (node_name and node_name in NON_STREAMING_NODES)
                            or "internal" in tags
                            or "no_stream" in tags
                            or "suggestion" in tags
                        ):
                            continue

                        chunk = event.get("data", {}).get("chunk")
                        if chunk and getattr(chunk, "content", None):
                            content_str = chunk.content
                            if isinstance(content_str, str) and content_str:
                                accumulated_text += content_str
                                yield self.format_token_event(content_str)

                    # Forward custom node events (tools, refusals, suggestions)
                    elif ev_kind == "on_custom_event":
                        name = event.get("name")
                        data = event.get("data", {})
                        if name == SSE_EVENT_TOOL_START:
                            logger.info("tool_invoked", tool=data.get("tool"), thread_id=thread_id)
                            yield data
                        elif name == SSE_EVENT_TOOL_END:
                            logger.info(
                                "tool_completed",
                                tool=data.get("tool"),
                                duration_ms=data.get("duration_ms"),
                                allowed=data.get("allowed"),
                                thread_id=thread_id,
                            )
                            yield data
                        elif name == SSE_EVENT_REFUSAL:
                            refusal_triggered = True
                            refusal_reason = data.get("reason")
                            logger.warning("safety_refusal_triggered", reason=refusal_reason, thread_id=thread_id)
                            yield data
                        elif name == SSE_EVENT_SUGGESTIONS:
                            suggestions = data.get("suggestions", [])
                            logger.info(
                                "suggestions_emitted",
                                count=len(suggestions),
                                suggestions=suggestions,
                                thread_id=thread_id,
                            )
                            yield data
                        elif name == "synthesis":
                            synth_text = data.get("output") or data.get("text") or ""
                            if synth_text and not accumulated_text:
                                accumulated_text = synth_text
                                yield self.format_token_event(synth_text)
                            logger.info(
                                "response_synthesis_emitted",
                                thread_id=thread_id,
                                text_length=len(synth_text),
                            )
                            yield {"type": "synthesis", **data}
                        elif name in ("citations", "extraction"):
                            cits = data.get("citations") or data.get("dossiers", [])
                            if cits:
                                citations.extend(cits)
                                yield {"type": "citations", "citations": cits}

                    elif ev_kind == "on_chain_end":
                        if not refusal_triggered and not accumulated_text:
                            chain_out = event.get("data", {}).get("output", {})
                            if isinstance(chain_out, dict):
                                out_text = chain_out.get("output")
                                if out_text and isinstance(out_text, str):
                                    accumulated_text = out_text
                                    yield self.format_token_event(out_text)

        except asyncio.CancelledError:
            logger.info("turn_cancelled", thread_id=thread_id)
            raise
        except Exception as err:
            logger.exception("turn_stream_error", error=str(err), thread_id=thread_id)
            err_str = str(err).lower()
            if "file is not a database" in err_str:
                yield self.format_error_event("Database error: file is not a database")
            else:
                yield self.format_error_event("An error occurred during turn execution.")
            return

        # 7. Post-Execution Safety Verification and Done Event
        total_dur_ms = (time.time() - start_time) * 1000
        accumulated_text = strip_reference_doc_preamble(strip_internal_suggestion_leakage(accumulated_text))

        # Verify output against safety boundaries if not already flagged
        output_safety = check_safety_refusal(accumulated_text)
        is_refusal_candidate = refusal_triggered or output_safety.refused
        reason = refusal_reason or (output_safety.reason if output_safety.refused else None) or "forbidden_intent:medical_prohibited"
        is_hard = refusal_triggered or (output_safety.refused and is_hard_refusal_reason(reason))

        if is_refusal_candidate and is_hard:
            logger.warning(
                "workflow_turn_refused",
                engine="LANGGRAPH_WORKFLOW",
                agent_id=agent.id,
                thread_id=thread_id,
                reason=reason,
                duration_ms=round(total_dur_ms, 2),
            )
            refuse_event = None
            try:
                refuse_event = await record_audit(
                    AuditEvent(
                        agent_id=agent.id,
                        event="refuse",
                        allowed=False,
                        reason=reason,
                        duration_ms=total_dur_ms,
                    ),
                    log_path=resolved_log_path,
                    store_bodies=effective_store_bodies,
                )
            except Exception as audit_err:
                logger.warning("Failed to record refuse audit event: %s", audit_err)

            if not refusal_triggered:
                yield self.format_refusal_event(reason=reason, message=SAFE_REFUSAL_TEMPLATE)

            yield self.format_done_event(
                full_text=SAFE_REFUSAL_TEMPLATE,
                thread_id=thread_id,
                audit_event_id=getattr(refuse_event, "ts", None),
                refused=True,
                refusal_reason=reason,
                boundary_warning=False,
                boundary_reason=None,
                suggestions=[],
                citations=citations if citations else None,
            )
        else:
            is_soft_boundary = is_refusal_candidate and not is_hard
            if is_soft_boundary:
                logger.info(
                    "workflow_turn_boundary_warning",
                    engine="LANGGRAPH_WORKFLOW",
                    agent_id=agent.id,
                    thread_id=thread_id,
                    reason=reason,
                    duration_ms=round(total_dur_ms, 2),
                )
                try:
                    await record_audit(
                        AuditEvent(
                            agent_id=agent.id,
                            event="boundary_warning",
                            allowed=True,
                            reason=reason,
                            duration_ms=total_dur_ms,
                        ),
                        log_path=resolved_log_path,
                        store_bodies=effective_store_bodies,
                    )
                except Exception as audit_err:
                    logger.warning("Failed to record boundary_warning audit event: %s", audit_err)

            if not suggestions:
                suggestions = generate_follow_up_suggestions(
                    agent_id=agent.id,
                    prompt=prompt,
                    completion=accumulated_text,
                )

            logger.info(
                "workflow_turn_completed",
                engine="LANGGRAPH_WORKFLOW",
                agent_id=agent.id,
                thread_id=thread_id,
                duration_ms=round(total_dur_ms, 2),
                tokens_count=len(accumulated_text),
                suggestions_count=len(suggestions),
                suggestions=suggestions,
            )

            run_event = None
            try:
                run_event = await record_audit(
                    AuditEvent(
                        agent_id=agent.id,
                        event="run",
                        allowed=True,
                        duration_ms=total_dur_ms,
                        prompt=prompt,
                        completion=accumulated_text,
                    ),
                    log_path=resolved_log_path,
                    store_bodies=effective_store_bodies,
                )
            except Exception as audit_err:
                logger.warning("Failed to record run audit event: %s", audit_err)


            yield self.format_done_event(
                full_text=accumulated_text,
                thread_id=thread_id,
                audit_event_id=getattr(run_event, "ts", None),
                refused=False,
                refusal_reason=None,
                boundary_warning=is_soft_boundary,
                boundary_reason=reason if is_soft_boundary else None,
                suggestions=suggestions,
                citations=citations if citations else None,
            )

    async def execute_chat(
        self,
        request: Union[ChatRequestBody, Dict[str, Any]],
        raw_events: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[Union[str, Dict[str, Any]]]:
        """Streams events for a chat request.

        If raw_events=False (default for HTTP), yields wire-formatted SSE strings:
            event: <type>\\ndata: <json>\\n\\n
        If raw_events=True, yields dictionary payloads directly.
        """
        if isinstance(request, ChatRequestBody):
            agent_id = request.get_agent_id()
            prompt = request.prompt
            messages = request.messages
            attachments = request.attachments
            allow_clinical = request.allow_clinical
            thread_id = request.get_thread_id() or f"thread_{agent_id}_{uuid.uuid4().hex[:12]}"
            provider = request.get_provider()
            model_name = request.model
            api_key = request.get_api_key()
            base_url = request.get_custom_endpoint()
        else:
            agent_id = request.get("agent_id") or request.get("agentId") or "visit-steward"
            prompt = request.get("prompt", "")
            messages = request.get("messages", [])
            attachments = request.get("attachments", [])
            allow_clinical = bool(request.get("allow_clinical", False))
            thread_id = request.get("thread_id") or request.get("threadId") or f"thread_{agent_id}_{uuid.uuid4().hex[:12]}"
            provider = request.get("provider", "ollama")
            model_name = request.get("model")
            api_key = request.get("api_key") or request.get("apiKey")
            base_url = request.get("base_url") or request.get("customEndpoint")

        async for event in self.execute_turn(
            thread_id=thread_id,
            prompt=prompt,
            user_id=kwargs.get("user_id", "default_user"),
            attachments=attachments,
            agent_id=agent_id,
            messages=messages,
            allow_clinical=allow_clinical,
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        ):
            if raw_events:
                yield event
            else:
                yield self.format_sse_wire_event(event)

    # ------------------------------------------------------------------------
    # Thread Lifecycle Management
    # ------------------------------------------------------------------------

    async def get_thread_state(self, thread_id: str) -> Optional[AgentState]:
        """Retrieves the current AgentState mapping for a given thread ID."""
        db_path = self.db_path or resolve_checkpointer_path(self.workspace_root)
        config = {"configurable": {"thread_id": thread_id}}

        if self.checkpointer is not None:
            if isinstance(self.checkpointer, AsyncSqliteSaver):
                tup = await self.checkpointer.aget_tuple(config)
            else:
                tup = self.checkpointer.get_tuple(config)
            if tup and tup.checkpoint:
                return tup.checkpoint.get("channel_values")
            return None

        if not Path(db_path).is_file():
            return None

        try:
            async with create_async_sqlite_saver(db_path) as saver:
                tup = await saver.aget_tuple(config)
                if tup and tup.checkpoint:
                    return tup.checkpoint.get("channel_values")
        except Exception as err:
            logger.warning("Failed to retrieve thread state for thread '%s': %s", thread_id, err)

        return None

    async def get_thread_history(self, thread_id: str) -> Dict[str, Any]:
        """Retrieves serialized message history and follow-up suggestions for REST API."""
        state = await self.get_thread_state(thread_id)
        if state is None:
            return {
                "threadId": thread_id,
                "messages": [],
                "followUpSuggestions": [],
                "count": 0,
            }

        raw_messages = state.get("messages", [])
        serialized_messages: List[Dict[str, Any]] = []

        for msg in raw_messages:
            msg_role = "user"
            msg_type = getattr(msg, "type", "")
            if msg_type in ("human", "user"):
                msg_role = "user"
            elif msg_type in ("ai", "assistant"):
                msg_role = "assistant"
            elif msg_type == "tool":
                msg_role = "tool"
            elif msg_type == "system":
                msg_role = "system"
            elif isinstance(msg, dict):
                msg_role = msg.get("role", "user")

            serialized_messages.append({
                "role": msg_role,
                "content": getattr(msg, "content", "") if not isinstance(msg, dict) else msg.get("content", ""),
                "tool_calls": getattr(msg, "tool_calls", None) if not isinstance(msg, dict) else msg.get("tool_calls"),
            })

        return {
            "threadId": thread_id,
            "messages": serialized_messages,
            "followUpSuggestions": state.get("follow_up_suggestions", []),
            "count": len(serialized_messages),
        }

    async def clear_thread_state(self, thread_id: str) -> bool:
        """Clears or resets checkpoint records for a given thread ID."""
        state = await self.get_thread_state(thread_id)
        return state is not None


__all__ = [
    "AgentExecutionService",
]
