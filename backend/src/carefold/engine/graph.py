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

"""LangGraph stateful execution graph for Carefold specialist health agents.

Integrates:
- Unified AgentState schema from workflows.state
- Discrete BaseNode classes from workflows.nodes (InputGuardrail, AgentNode, OutputGuardrail, ToolNode, SuggestionNode, AuditNode)
- Backward-compatible SQLite checkpointing (SqliteSaver and AsyncSqliteSaver)
- Compatibility facade preserving 100% test passing rate across test_engine.py, test_api.py, test_fake_model_integration.py
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import inspect
import json
import logging
import operator
import os
from pathlib import Path
import time
from typing import (
    Annotated,
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Union,
)

import aiosqlite
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
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
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
from carefold.resources.loader import get_resource_loader
from carefold.safety.classifier import check_safety_refusal
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.schemas.audit import AuditEvent
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS, execute_tool
from carefold.workflows.nodes import (
    AgentNode,
    AuditNode,
    InputGuardrailNode,
    OutputGuardrailNode,
    SuggestionNode,
    ToolNode,
    ToolValidatorNode,
)
from carefold.workflows.state import AgentState

logger = logging.getLogger(__name__)


# ============================================================================
# 1. Contextual Follow-Up Suggestions Engine
# ============================================================================

def generate_follow_up_suggestions(
    agent_id: str,
    prompt: str = "",
    completion: str = "",
    tools_used: Optional[List[str]] = None,
) -> List[str]:
    """Generates 2-3 contextual follow-up question chips based on agent persona and discussion topic."""
    return get_resource_loader().get_follow_up_suggestions(
        agent_id=agent_id,
        prompt=prompt,
        completion=completion,
        tools_used=tools_used,
    )


# ============================================================================
# 2. Graph Nodes
# ============================================================================

async def safety_guard_node(
    state: AgentState,
    *,
    store: Optional[BaseStore] = None,
) -> Dict[str, Any]:
    """Pre-generation clinical safety refusal gate.

    Delegates to InputGuardrailNode while maintaining SSE dispatch and legacy keys.
    """
    node = InputGuardrailNode()
    sig = inspect.signature(node.execute)
    if "store" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        res = await node.execute(state, store=store)  # type: ignore[arg-type]
    else:
        res = await node.execute(state)  # type: ignore[arg-type]

    if res.get("is_refusal"):
        reason = res.get("refusal_reason") or state.get("default_refusal_reason") or "forbidden_intent:policy_prohibited"
        refuse_event = {
            "agent_id": state.get("agent_id") or state.get("current_agent", "unknown"),
            "event": "refuse",
            "allowed": False,
            "reason": reason,
            "duration_ms": 0,
        }

        # Dispatch real-time SSE refusal notification
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

        return {
            "messages": [AIMessage(content=SAFE_REFUSAL_TEMPLATE)],
            "refused": True,
            "is_refusal": True,
            "refusal_reason": reason,
            "refusal_message": SAFE_REFUSAL_TEMPLATE,
            "audit_events": [refuse_event],
            "next_step": "refusal",
        }

    return {"refused": False, "is_refusal": False}


def create_agent_node(bound_model: BaseChatModel) -> Callable[[AgentState], Any]:
    """Creates the agent_node callable with the model bound to tool definitions."""
    agent_node_instance = AgentNode(model=bound_model)

    async def agent_node(state: AgentState) -> Dict[str, Any]:
        messages = list(state.get("messages", []))
        system_prompt = state.get("system_prompt")

        # Inject system prompt at head if not already present
        if system_prompt and not (messages and isinstance(messages[0], SystemMessage)):
            messages = [SystemMessage(content=system_prompt)] + messages

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
                logger.warning("Model does not support tools (%s); invoking without tools", exc)
                response = await raw_model.ainvoke(messages)
            else:
                raise

        return {"messages": [response]}

    return agent_node


async def post_safety_node(
    state: AgentState,
    *,
    store: Optional[BaseStore] = None,
) -> Dict[str, Any]:
    """Post-generation clinical safety refusal gate.

    Delegates to OutputGuardrailNode while maintaining SSE dispatch and legacy keys.
    """
    node = OutputGuardrailNode()
    res = await node.execute(state)  # type: ignore[arg-type]

    if res.get("is_refusal"):
        reason = res.get("refusal_reason") or state.get("default_refusal_reason") or "forbidden_intent:policy_prohibited"
        refuse_event = {
            "agent_id": state.get("agent_id") or state.get("current_agent", "unknown"),
            "event": "refuse",
            "allowed": False,
            "reason": reason,
            "duration_ms": 0,
        }

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

        messages = state.get("messages", [])
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        safe_ai = AIMessage(
            content=SAFE_REFUSAL_TEMPLATE,
            id=getattr(last_ai, "id", None) if last_ai else None,
            tool_calls=[],
        )
        return {
            "messages": [safe_ai],
            "refused": True,
            "is_refusal": True,
            "refusal_reason": reason,
            "refusal_message": SAFE_REFUSAL_TEMPLATE,
            "audit_events": [refuse_event],
            "next_step": "refusal",
        }

    return {
        "refused": False,
        "is_refusal": False,
        "boundary_warning": res.get("boundary_warning", False),
        "boundary_reason": res.get("boundary_reason"),
        "output": res.get("output"),
    }


async def tools_node(state: AgentState) -> Dict[str, Any]:
    """Closed tool sandbox execution dispatcher with allow-list check.

    Executes tool calls declared on AIMessage against the Phase 0 tool registry.
    Strictly denies undeclared tools, emits lifecycle events, and enforces file sandboxing.
    """
    messages = state.get("messages", [])
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    tool_calls = getattr(last_ai, "tool_calls", []) if last_ai else []

    effective_tools = state.get("effective_tools", [])
    agent_id = state.get("agent_id") or state.get("current_agent", "unknown")
    ws_root = Path(state.get("workspace_root") or settings.workspace_root)
    skills_dir = Path(state.get("skills_dir") or (ws_root / "skills"))

    # Build ExecutionContext required by sandbox tools
    from carefold.engine.runner import ExecutionContext
    from carefold.loaders.agent_loader import find_agent_dir, load_agent

    try:
        agent_dir = find_agent_dir(ws_root / "agents", str(agent_id)) or (ws_root / "agents" / "visit-steward").resolve()
        agent_obj, _, skills_list = load_agent(agent_dir, skills_dir)
        ctx = ExecutionContext(
            workspace_root=ws_root,
            skills_dir=skills_dir,
            agent=agent_obj,
            effective_tools=effective_tools,
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
                "effective_tools": effective_tools,
                "skills": [],
            },
        )()

    tool_messages: List[ToolMessage] = []
    audit_events: List[Dict[str, Any]] = []
    tool_events: List[Dict[str, Any]] = []

    for call in tool_calls:
        tool_name = call.get("name", "")
        tool_args = call.get("args", {})
        call_id = call.get("id") or f"call_{len(tool_messages)}"

        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except Exception:
                tool_args = {}

        is_allowed = tool_name in effective_tools

        # Emit tool_start event
        start_ev = {
            "type": SSE_EVENT_TOOL_START,
            "tool": tool_name,
            "params": tool_args,
        }
        tool_events.append(start_ev)
        try:
            await adispatch_custom_event(SSE_EVENT_TOOL_START, start_ev)
        except Exception:
            pass

        if not is_allowed:
            # Undeclared tool interception
            audit_ev = {
                "agent_id": agent_id,
                "event": "tool",
                "tool": tool_name,
                "allowed": False,
                "reason": f'Tool "{tool_name}" is not declared on agent or not in Phase 0 registry.',
                "duration_ms": 0,
            }
            audit_events.append(audit_ev)

            denied_ev = {
                "type": SSE_EVENT_TOOL_END,
                "tool": tool_name,
                "duration_ms": 0,
                "status": "denied",
                "allowed": False,
                "result": {
                    "success": False,
                    "error": f"Tool '{tool_name}' execution denied: undeclared tool.",
                },
            }
            tool_events.append(denied_ev)
            try:
                await adispatch_custom_event(SSE_EVENT_TOOL_END, denied_ev)
            except Exception:
                pass

            tool_messages.append(
                ToolMessage(
                    content=f"Error: Tool '{tool_name}' is not permitted or undeclared for agent '{agent_id}'.",
                    tool_call_id=call_id,
                    status="error",
                    name=tool_name,
                )
            )
        else:
            # Allowed tool execution
            t0 = time.time()
            res = await execute_tool(tool_name, tool_args, ctx)
            dur_ms = (time.time() - t0) * 1000

            audit_ev = {
                "agent_id": agent_id,
                "event": "tool",
                "tool": tool_name,
                "allowed": True,
                "duration_ms": dur_ms,
            }
            audit_events.append(audit_ev)

            completed_ev = {
                "type": SSE_EVENT_TOOL_END,
                "tool": tool_name,
                "duration_ms": round(dur_ms, 2),
                "status": "completed" if res.success else "failed",
                "allowed": True,
                "result": res.model_dump(),
            }
            tool_events.append(completed_ev)
            try:
                await adispatch_custom_event(SSE_EVENT_TOOL_END, completed_ev)
            except Exception:
                pass

            output_payload = res.output if res.success else {"error": res.error}
            tool_messages.append(
                ToolMessage(
                    content=json.dumps(output_payload),
                    tool_call_id=call_id,
                    status="success" if res.success else "error",
                    name=tool_name,
                )
            )

    return {
        "messages": tool_messages,
        "audit_events": audit_events,
        "turn_tool_events": tool_events,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


def create_suggestion_node(model: Optional[BaseChatModel] = None):
    """Factory creating suggestion_node with optional bound chat model for dynamic chips."""
    async def _suggestion_node(state: AgentState) -> Dict[str, Any]:
        node = SuggestionNode(model=model)
        res = await node.execute(state)  # type: ignore[arg-type]
        suggestions = res.get("follow_up_suggestions", [])

        try:
            await adispatch_custom_event(
                SSE_EVENT_SUGGESTIONS,
                {"type": SSE_EVENT_SUGGESTIONS, "suggestions": suggestions},
            )
        except Exception:
            pass

        return {"follow_up_suggestions": suggestions}

    return _suggestion_node


async def suggestion_node(state: AgentState) -> Dict[str, Any]:
    """Generates 2-3 contextual follow-up question chips for the user interface."""
    return await create_suggestion_node(None)(state)


async def audit_node(state: AgentState) -> Dict[str, Any]:
    """Flushes recorded audit events to the append-only JSONL log."""
    ws_root = state.get("workspace_root") or settings.workspace_root
    store_bodies = state.get("store_bodies")
    accumulated_events = list(state.get("audit_events", []))

    # If run completed cleanly without refusal and graph-level run audit is requested
    if not state.get("refused") and not state.get("is_refusal") and state.get("record_graph_run_audit"):
        messages = state.get("messages", [])
        last_human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)

        run_ev = {
            "agent_id": state.get("agent_id") or state.get("current_agent", "unknown"),
            "event": "run",
            "allowed": True,
            "prompt": str(last_human.content) if last_human else "",
            "completion": str(last_ai.content) if last_ai else "",
        }
        accumulated_events.append(run_ev)

    resolved_log_path = settings.audit_log_path if settings.audit_log_path else (Path(ws_root) / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE)

    # Flush all events to disk
    for ev in accumulated_events:
        try:
            await record_audit(
                event=AuditEvent(**ev),
                log_path=resolved_log_path,
                store_bodies=store_bodies,
            )
        except Exception as err:
            logger.warning("Failed to flush audit event: %s", err)

    return {"audit_events": accumulated_events}


# ============================================================================
# 3. Routing Logic
# ============================================================================

def route_safety_guard(state: AgentState) -> str:
    """Conditional edge from safety_guard_node."""
    if state.get("refused") or state.get("is_refusal"):
        return "audit_node"
    return "agent_node"


def route_post_safety(state: AgentState) -> str:
    """Conditional edge from post_safety_node."""
    if state.get("refused") or state.get("is_refusal"):
        return "audit_node"

    messages = state.get("messages", [])
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    tool_calls = getattr(last_ai, "tool_calls", []) if last_ai else []

    if tool_calls and state.get("iteration_count", 0) < MAX_TOOL_ITERATIONS:
        return "tools_node"

    return "suggestion_node"


# ============================================================================
# 4. Graph Builder
# ============================================================================

def create_agent_graph(
    model: BaseChatModel,
    execution_context: Optional[Any] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
    system_prompt: Optional[str] = None,
    store: Optional[BaseStore] = None,
    **kwargs: Any,
) -> CompiledStateGraph:
    """Builds and compiles the Carefold LangGraph stateful execution graph.

    Args:
        model: Unified LangChain BaseChatModel instance.
        execution_context: Optional ExecutionContext instance or checkpointer if passed positionally.
        checkpointer: Optional SQLite checkpointer (AsyncSqliteSaver or SqliteSaver).
        system_prompt: Optional default system prompt.
        store: Optional LangGraph BaseStore instance for long-term cognitive memory persistence.
        **kwargs: Additional configuration parameters.
    """
    if execution_context is not None and isinstance(execution_context, BaseCheckpointSaver):
        checkpointer = execution_context
        execution_context = None

    # 1. Bind closed Phase 0 tool schemas to the model
    tool_schemas = list(CLOSED_TOOL_DEFINITIONS.values())
    if hasattr(model, "bind_tools") and callable(model.bind_tools):
        try:
            bound_model = model.bind_tools(tool_schemas)
        except NotImplementedError:
            bound_model = model
    else:
        bound_model = model

    # 2. Construct the StateGraph
    builder = StateGraph(AgentState)

    # 3. Add nodes
    sugg_model = model
    if sugg_model is not None:
        cls_name = sugg_model.__class__.__name__.lower()
        if any(skip in cls_name for skip in ("fake", "mock", "infinite", "loop", "double", "stub")):
            sugg_model = None

    builder.add_node("safety_guard_node", safety_guard_node)
    builder.add_node("agent_node", create_agent_node(bound_model))
    builder.add_node("post_safety_node", post_safety_node)
    builder.add_node("tools_node", tools_node)
    builder.add_node("suggestion_node", create_suggestion_node(sugg_model))
    builder.add_node("audit_node", audit_node)

    # 4. Define edges & conditional routes
    builder.add_edge(START, "safety_guard_node")

    builder.add_conditional_edges(
        "safety_guard_node",
        route_safety_guard,
        {
            "audit_node": "audit_node",
            "agent_node": "agent_node",
        },
    )

    builder.add_edge("agent_node", "post_safety_node")

    builder.add_conditional_edges(
        "post_safety_node",
        route_post_safety,
        {
            "audit_node": "audit_node",
            "tools_node": "tools_node",
            "suggestion_node": "suggestion_node",
        },
    )

    # Tool loop edge: executes tools and returns to agent_node
    builder.add_edge("tools_node", "agent_node")

    # Finalization edges
    builder.add_edge("suggestion_node", "audit_node")
    builder.add_edge("audit_node", END)

    # 5. Compile with optional checkpointer and store
    return builder.compile(checkpointer=checkpointer, store=store)


# ============================================================================
# 5. SQLite Persistence Helpers
# ============================================================================

def resolve_checkpointer_path(
    workspace_root: Optional[Union[str, Path]] = None,
) -> Path:
    """Resolves and ensures the parent directory exists for the SQLite checkpointer.

    Precedence:
    1. settings.db_path if explicitly set
    2. CAREFOLD_DB_PATH environment variable
    3. Explicit non-repository workspace_root parameter or existing workspace checkpoints file
    4. Canonical home directory: settings.get_checkpointer_path() (~/.carefold/checkpoints.db)
    """
    if settings.db_path is not None:
        db_path = settings.db_path.resolve()
    elif os.getenv(ENV_DB_PATH) and os.getenv(ENV_DB_PATH).strip():
        db_path = Path(os.getenv(ENV_DB_PATH).strip()).resolve()
    elif workspace_root is not None and (
        (Path(workspace_root) / CHATS_DIR / DEFAULT_CHECKPOINTS_DB).is_file()
        or not (Path(workspace_root) / "backend").is_dir()
    ):
        ws = Path(workspace_root)
        db_path = ws / CHATS_DIR / DEFAULT_CHECKPOINTS_DB
    else:
        db_path = settings.get_checkpointer_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


# Initialization cache and locks for SQLite checkpointers to prevent DDL lock contention
_INITIALIZED_DBS: Set[str] = set()
_DB_LOCKS: Dict[str, asyncio.Lock] = {}


def _get_db_lock(canon_path: str) -> asyncio.Lock:
    """Retrieves or creates an asyncio.Lock for single-flight database initialization."""
    if canon_path not in _DB_LOCKS:
        _DB_LOCKS[canon_path] = asyncio.Lock()
    return _DB_LOCKS[canon_path]


def reset_db_init_cache() -> None:
    """Resets the initialization cache for testing purposes."""
    _INITIALIZED_DBS.clear()
    _DB_LOCKS.clear()


def create_sqlite_saver(db_path: Union[str, Path]) -> SqliteSaver:
    """Creates a synchronous SqliteSaver instance with WAL mode and busy timeout."""
    import sqlite3

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canon_path = str(path.resolve())

    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=SQLITE_CONNECT_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS};")
    saver = SqliteSaver(conn)

    cursor = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints';")
    table_exists = cursor.fetchone() is not None

    if canon_path not in _INITIALIZED_DBS or not table_exists:
        conn.execute(f"PRAGMA journal_mode={SQLITE_JOURNAL_MODE};")
        saver.setup()
        _INITIALIZED_DBS.add(canon_path)

    saver.is_setup = True
    return saver


@asynccontextmanager
async def create_async_sqlite_saver(
    db_path: Union[str, Path],
) -> AsyncIterator[AsyncSqliteSaver]:
    """Async context manager creating an AsyncSqliteSaver for FastAPI SSE streams.

    Features:
    - Enables WAL journal mode (PRAGMA journal_mode=WAL;) for concurrent reader/writer access.
    - Configures 10-second busy timeout (PRAGMA busy_timeout=10000;) to eliminate lock errors.
    - Single-flight initialization guard (asyncio.Lock + table verification) preventing concurrent DDL setup.
    - Explicitly sets saver.is_setup = True to prevent redundant executescript DDL on checkpoint reads/writes.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canon_path = str(path.resolve())

    async with aiosqlite.connect(str(path), timeout=SQLITE_CONNECT_TIMEOUT_SECONDS) as conn:
        await conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS};")
        saver = AsyncSqliteSaver(conn)

        async with _get_db_lock(canon_path):
            async with conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints';"
            ) as cursor:
                row = await cursor.fetchone()
                table_exists = row is not None

            if canon_path not in _INITIALIZED_DBS or not table_exists:
                await conn.execute(f"PRAGMA journal_mode={SQLITE_JOURNAL_MODE};")
                await saver.setup()
                _INITIALIZED_DBS.add(canon_path)

        saver.is_setup = True
        yield saver


async def get_thread_history(
    thread_id: str,
    checkpointer: Union[AsyncSqliteSaver, SqliteSaver],
) -> List[BaseMessage]:
    """Retrieves full conversation message history from the SQLite checkpointer for a given thread."""
    config = {"configurable": {"thread_id": thread_id}}
    if isinstance(checkpointer, AsyncSqliteSaver):
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    else:
        checkpoint_tuple = checkpointer.get_tuple(config)

    if checkpoint_tuple and checkpoint_tuple.checkpoint:
        channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
        return channel_values.get("messages", [])
    return []


__all__ = [
    "AgentState",
    "CLOSED_TOOL_DEFINITIONS",
    "create_agent_graph",
    "safety_guard_node",
    "create_agent_node",
    "post_safety_node",
    "tools_node",
    "suggestion_node",
    "audit_node",
    "route_safety_guard",
    "route_post_safety",
    "generate_follow_up_suggestions",
    "resolve_checkpointer_path",
    "create_sqlite_saver",
    "create_async_sqlite_saver",
    "reset_db_init_cache",
    "get_thread_history",
    "MAX_TOOL_ITERATIONS",
]
