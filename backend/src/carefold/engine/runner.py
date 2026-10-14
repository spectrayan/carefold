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

"""Agent execution runtime backward-compatibility delegation facade.

Delegates execution runs to AgentExecutionService and GraphBuilder, eliminating
legacy monolithic pre/post guardrails and tool loops.
Satisfies Requirement R3 and Feature F-41.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Union
import uuid

from langchain_core.language_models.chat_models import BaseChatModel

from carefold.engine.service import AgentExecutionService
from carefold.model.factory import create_chat_model
from carefold.schemas.chat import ChatMessage
from carefold.schemas.manifest import AgentManifest, SkillManifest

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Lightweight execution context passed to sandbox tools and tests."""

    workspace_root: Path
    skills_dir: Path
    agent: AgentManifest
    effective_tools: List[str]
    skills: List[SkillManifest]


async def execute_agent_run(
    agent_id: str,
    prompt: str,
    messages: Optional[List[ChatMessage]] = None,
    attachments: Optional[List[str]] = None,
    allow_clinical: bool = True,
    model_client: Optional[Any] = None,
    workspace_root: Optional[Union[Path, str]] = None,
    store_bodies: Optional[bool] = None,
    thread_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    checkpointer_db_path: Optional[Union[Path, str]] = None,
    **kwargs: Any,
) -> AsyncIterator[Dict[str, Any]]:
    """Delegates agent execution runs to AgentExecutionService.

    Preserves 100% backward compatibility for all existing callers while
    eliminating monolithic pre/post safety guardrails and manual tool loops.
    """
    resolved_thread_id = thread_id or f"thread_{agent_id}_{uuid.uuid4().hex[:12]}"

    # Resolve chat model if specified or use factory (respects test monkeypatching)
    chat_model = model_client if model_client is not None else create_chat_model(
        provider=provider or "ollama", model=model, api_key=api_key, base_url=base_url
    )

    service = AgentExecutionService(
        model=chat_model if isinstance(chat_model, BaseChatModel) else None,
        workspace_root=workspace_root, db_path=checkpointer_db_path, store_bodies=store_bodies,
    )

    async for event in service.execute_turn(
        thread_id=resolved_thread_id, prompt=prompt, agent_id=agent_id,
        messages=messages, attachments=attachments, allow_clinical=allow_clinical,
        model=chat_model, provider=provider, model_name=model,
        api_key=api_key, base_url=base_url, store_bodies=store_bodies, **kwargs,
    ):
        yield event


__all__ = ["ExecutionContext", "execute_agent_run", "create_chat_model"]
