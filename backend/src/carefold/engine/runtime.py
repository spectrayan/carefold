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

"""Carefold production execution service on yarvelle-core's Deep Agents runtime.

Constructs core ``AgentExecutionService`` with the pack's orchestration
spec and ``HealthSafetyPolicy``. Acute emergencies hard-refuse first in the
input guardrail with the vetted referral (no agent, no model call); the
pack's document-intake fixed route resolves before any model router call.
There is no legacy runtime feature flag.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import weakref
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Optional, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from yarvelle_core.engine.builder import GraphBuilder
from yarvelle_core.engine.graph import create_async_sqlite_saver, resolve_checkpointer_path
from yarvelle_core.engine.safety_policy import SafetyPolicy
from yarvelle_core.engine.service import AgentExecutionService as CoreAgentExecutionService

from carefold.engine.refusal_node import CarefoldRefusalNode
from carefold.engine.response_synthesizer import CarefoldResponseSynthesizerNode
from carefold.safety.policy import (
    CarefoldHealthSafetyPolicy,
    adapt_legacy_core_chat_request,
    adapt_legacy_core_turn_kwargs,
)
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE

logger = logging.getLogger(__name__)


def _load_pack_orchestration() -> Any:
    from carefold import get_pack

    return get_pack().orchestration


def _load_pack_safety_policy() -> SafetyPolicy:
    from yarvelle_core.engine.guards import build_guarded_policy

    from carefold import get_pack

    pack = get_pack()
    base = pack.safety_policy or CarefoldHealthSafetyPolicy()
    return build_guarded_policy(base, pack=pack)


# Per event loop, per checkpoint file: one asyncio lock that queues in-process
# checkpoint writes. Concurrent turns each open their own SQLite connection;
# queueing their commits here is fair (FIFO) instead of leaving them to race
# SQLite's busy-timeout backoff, which starves writers under load.
_CHECKPOINT_WRITE_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)
_SERIALIZED_WRITE_METHODS = ("aput", "aput_writes", "adelete_thread")


def _checkpoint_write_lock(db_path: Union[str, Path]) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    locks = _CHECKPOINT_WRITE_LOCKS.setdefault(loop, {})
    key = str(Path(db_path).resolve())
    lock = locks.get(key)
    if lock is None:
        lock = locks[key] = asyncio.Lock()
    return lock


def _serialize_checkpoint_writes(saver: Any, lock: asyncio.Lock) -> Any:
    """Route the saver's async write methods through ``lock``; reads stay concurrent."""
    for name in _SERIALIZED_WRITE_METHODS:
        original = getattr(saver, name, None)
        if original is None:
            continue

        async def _locked(*args: Any, __original: Any = original, **kwargs: Any) -> Any:
            async with lock:
                return await __original(*args, **kwargs)

        setattr(saver, name, _locked)
    return saver


@asynccontextmanager
async def serialized_sqlite_saver(db_path: Union[str, Path]) -> AsyncIterator[Any]:
    """Core's async SQLite checkpointer with in-process write queueing."""
    async with create_async_sqlite_saver(db_path) as saver:
        yield _serialize_checkpoint_writes(saver, _checkpoint_write_lock(db_path))


class CarefoldAgentExecutionService(CoreAgentExecutionService):
    """Core execution service pre-wired for the Carefold pack."""

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
        safety_policy: Optional[SafetyPolicy] = None,
        default_agent_id: Optional[str] = None,
        orchestration: Optional[Any] = None,
        registry: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        if orchestration is None and graph is None and graph_builder is None:
            orchestration = _load_pack_orchestration()
        if safety_policy is None:
            safety_policy = _load_pack_safety_policy()
        if default_agent_id is None and orchestration is not None:
            default_agent_id = getattr(orchestration, "default_agent", None)
        super().__init__(
            model=model,
            graph=graph,
            graph_builder=graph_builder,
            checkpointer=checkpointer,
            store=store,
            memory_adapter=memory_adapter,
            db_path=db_path,
            workspace_root=workspace_root,
            store_bodies=store_bodies,
            safety_policy=safety_policy,
            default_agent_id=default_agent_id,
            orchestration=orchestration,
            registry=registry,
            **kwargs,
        )

    @staticmethod
    def format_refusal_event(
        reason: str,
        message: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Prefer Carefold's safe-refusal template for API compatibility."""
        from yarvelle_core.constants.api import SSE_EVENT_REFUSAL

        payload: Dict[str, Any] = {
            "type": SSE_EVENT_REFUSAL,
            "reason": reason,
            "message": message or SAFE_REFUSAL_TEMPLATE,
        }
        if category:
            payload["category"] = category
        return payload

    async def _open_serialized_saver(self, stack: AsyncExitStack) -> Optional[Any]:
        """Open the turn's write-queued checkpointer, or None to leave it to core.

        Uses the same checkpoint file core resolves. When it cannot be opened
        (for example a corrupted file), core's own path runs and reports the
        error exactly as it would without this wrapper.
        """
        try:
            db_path = self.db_path or resolve_checkpointer_path(self.workspace_root.resolve())
            return await stack.enter_async_context(serialized_sqlite_saver(db_path))
        except Exception as err:
            logger.debug("write-queued checkpointer unavailable, using core default: %s", err)
            return None

    async def _order_buffered_events(
        self, stream: AsyncGenerator[Dict[str, Any], None]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Keep suggestions after the buffered answer token (and drop them on refusal)."""
        try:
            if not getattr(self, "_buffer_answer", False):
                async for event in stream:
                    yield event
                return
            held_suggestions: list[Dict[str, Any]] = []
            refused = False
            async for event in stream:
                ev_type = event.get("type")
                if ev_type == "suggestions":
                    held_suggestions.append(event)
                    continue
                if ev_type == "refusal":
                    refused = True
                    held_suggestions.clear()
                if ev_type == "token":
                    yield event
                    for sug in held_suggestions:
                        yield sug
                    held_suggestions.clear()
                    continue
                if ev_type == "done" and not refused and not event.get("refused"):
                    for sug in held_suggestions:
                        yield sug
                    held_suggestions.clear()
                yield event
        finally:
            await stream.aclose()

    async def execute_chat(self, request: Any, *args: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
        """Normalizes dict request payloads across yarvelle-core versions."""
        adapted_req = adapt_legacy_core_chat_request(request, CoreAgentExecutionService)
        async for item in super().execute_chat(adapted_req, *args, **kwargs):
            yield item

    async def execute_turn(self, *args: Any, **kwargs: Any) -> AsyncGenerator[Dict[str, Any], None]:
        """Run core's turn with a write-queued checkpointer when none was injected."""
        kwargs, blocked_events = adapt_legacy_core_turn_kwargs(
            self, args, kwargs, CoreAgentExecutionService
        )
        if blocked_events is not None:
            for ev in blocked_events:
                yield ev
            return
        async with AsyncExitStack() as stack:
            saver = None if self.checkpointer is not None else await self._open_serialized_saver(stack)
            if saver is None:
                async for event in self._order_buffered_events(super().execute_turn(*args, **kwargs)):
                    yield event
                return
            # Shallow per-turn copy so concurrent turns on one service never
            # share or overwrite each other's checkpointer.
            turn_service = copy.copy(self)
            turn_service.checkpointer = saver
            async for event in self._order_buffered_events(
                CoreAgentExecutionService.execute_turn(turn_service, *args, **kwargs)
            ):
                yield event

    async def execute_resume_turn(
        self, *args: Any, **kwargs: Any
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Resume with a write-queued checkpointer when none was injected."""
        async with AsyncExitStack() as stack:
            saver = None
            if kwargs.get("checkpointer") is None and self.checkpointer is None:
                saver = await self._open_serialized_saver(stack)
            if saver is not None:
                kwargs["checkpointer"] = saver
            async for event in super().execute_resume_turn(*args, **kwargs):
                yield event

    async def _soft_orchestration_audit(self, event: Any) -> None:
        """Best-effort orchestration audit; never abort the turn when DB write fails."""
        try:
            from yarvelle_core.engine.builder import _record_orchestration_audit

            await _record_orchestration_audit(event)
        except Exception as err:
            logger.warning("orchestration audit skipped: %s", err)

    def _build_orchestrated_graph(
        self,
        active_model: BaseChatModel,
        checkpointer: Optional[Any],
        effective_store: Optional[Any],
    ) -> Any:
        """Built-in routed graph with Carefold's refusal and synthesizer nodes."""
        registry = self._agent_registry()
        builder = GraphBuilder(
            model=active_model,
            registry=registry,
            orchestration=self.orchestration,
            default_agent=self.default_agent_id,
            safety_policy=self.safety_policy,
            checkpointer=checkpointer,
            orchestration_audit_sink=self._soft_orchestration_audit,
        )
        builder = builder.with_node("refusal", CarefoldRefusalNode()).with_node(
            "response_synthesizer",
            CarefoldResponseSynthesizerNode(
                model=active_model,
                agent_titles=builder._agent_titles(),
            ),
        )
        if effective_store is not None:
            builder = builder.with_store(effective_store)
        return builder.build(checkpointer=checkpointer, store=effective_store)


def create_execution_service(**kwargs: Any) -> CarefoldAgentExecutionService:
    """Factory used by chat APIs and tests for the production runtime."""
    return CarefoldAgentExecutionService(**kwargs)


__all__ = [
    "CarefoldAgentExecutionService",
    "create_execution_service",
    "serialized_sqlite_saver",
]
