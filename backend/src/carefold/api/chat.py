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

"""Server-Sent Events (SSE) chat streaming and session thread REST endpoints."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from carefold.config import settings
from carefold.constants.api import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
    ROUTE_CHAT,
    ROUTE_CHAT_THREADS,
    SSE_EVENT_ERROR,
    SSE_EVENT_MESSAGE,
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
)
from carefold.constants.paths import CHATS_DIR, DEFAULT_CHECKPOINTS_DB, SYSTEM_AGENTS_DIR
from carefold.engine.graph import create_async_sqlite_saver
from carefold.engine.runner import execute_agent_run
from carefold.schemas.chat import ChatRequestBody

from carefold.logging import get_logger

logger = get_logger("carefold.api.chat")

router = APIRouter(tags=["Chat"])


@router.post(ROUTE_CHAT)
async def chat_stream(request: ChatRequestBody) -> StreamingResponse:
    """Streams token chunks, tool traces, refusals, suggestions, and completion records via SSE.
    
    Supports:
    - Multi-provider model switching (Ollama, Gemini, Claude, OpenAI, custom endpoints)
    - Client-supplied API keys strictly overriding server environment variables
    - Conversation session continuity via SQLite thread checkpointing
    - AI-suggested next question chips emitted upon assistant turn completion
    """
    try:
        agent_id = request.get_agent_id()
    except ValueError as val_err:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(val_err))

    if not request.prompt or not request.prompt.strip():
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Parameter 'prompt' must not be empty.")

    agent_dir = settings.get_agents_dir() / agent_id
    if not agent_dir.is_dir():
        system_candidate = settings.get_agents_dir() / SYSTEM_AGENTS_DIR / agent_id
        if system_candidate.is_dir():
            agent_dir = system_candidate
        else:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Agent '{agent_id}' not found.")

    # Resolve thread ID for session persistence
    thread_id = request.get_thread_id() or f"thread_{agent_id}_{uuid.uuid4().hex[:12]}"

    # Resolve provider and custom endpoint parameters
    provider = request.get_provider()
    model = request.model
    api_key = request.get_api_key()
    custom_endpoint = request.get_custom_endpoint()

    logger.info(
        "chat_stream_initiated",
        agent_id=agent_id,
        thread_id=thread_id,
        provider=provider or "ollama",
        model=model or settings.default_model,
        prompt_preview=request.prompt[:60] + "..." if len(request.prompt) > 60 else request.prompt,
    )

    async def sse_generator() -> AsyncIterator[str]:
        try:
            async for event in execute_agent_run(
                agent_id=agent_id,
                prompt=request.prompt,
                messages=request.messages,
                attachments=request.attachments,
                allow_clinical=request.allow_clinical,
                thread_id=thread_id,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=custom_endpoint,
            ):
                event_type = event.get("type", SSE_EVENT_MESSAGE)
                data_str = json.dumps(event)
                yield f"event: {event_type}\ndata: {data_str}\n\n"
        except Exception:
            logger.exception("Unexpected error in chat stream")
            err_data = json.dumps({
                "type": SSE_EVENT_ERROR,
                "message": "An unexpected error occurred during chat execution.",
            })
            yield f"event: {SSE_EVENT_ERROR}\ndata: {err_data}\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


@router.get(ROUTE_CHAT_THREADS)
async def get_thread_history(thread_id: str) -> Dict[str, Any]:
    """Retrieves conversation history and checkpoints for a given thread ID."""
    chats_dir = settings.workspace_root / CHATS_DIR
    db_path = chats_dir / DEFAULT_CHECKPOINTS_DB

    if not db_path.is_file():
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"No checkpoints found for thread '{thread_id}'.")

    try:
        async with create_async_sqlite_saver(db_path) as saver:
            config = {"configurable": {"thread_id": thread_id}}
            checkpoint_tuple = await saver.aget_tuple(config)

            if not checkpoint_tuple or not checkpoint_tuple.checkpoint:
                raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Thread '{thread_id}' not found.")

            channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
            raw_messages = channel_values.get("messages", [])

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

                serialized_messages.append({
                    "role": msg_role,
                    "content": getattr(msg, "content", ""),
                    "tool_calls": getattr(msg, "tool_calls", None),
                })

            return {
                "threadId": thread_id,
                "messages": serialized_messages,
                "followUpSuggestions": channel_values.get("follow_up_suggestions", []),
                "count": len(serialized_messages),
            }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to load thread history")
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load thread history.")
