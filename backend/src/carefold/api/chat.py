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

"""Server-Sent Events (SSE) chat streaming and session thread REST endpoints."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Literal, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, resolve_owner_user_id
from carefold.api.profiles import auto_provision_primary_me_profile, get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.db.models import Agent, ChatThread, Profile
from carefold.db.session import get_db
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
from carefold.engine.graph import create_async_sqlite_saver, resolve_checkpointer_path
from carefold.engine.runner import execute_agent_run
from carefold.engine.service import AgentExecutionService
from carefold.schemas.chat import ChatRequestBody

from carefold.logging import get_logger

logger = get_logger("carefold.api.chat")

router = APIRouter(tags=["Chat"])


@router.post(ROUTE_CHAT)
async def chat_stream(
    request: ChatRequestBody,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
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
            a_stmt = select(Agent).where(Agent.id == agent_id)
            a_res = await db.execute(a_stmt)
            if a_res.scalar_one_or_none() is None:
                raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Agent '{agent_id}' not found.")

    raw_profile_id = request.get_profile_id()
    profile_id = (raw_profile_id or "").strip()
    if not profile_id:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="profile_id is required")

    if profile_id.lower() == "me":
        profile_record = await auto_provision_primary_me_profile(user, db)
        profile_id = profile_record.id
    else:
        p_stmt = select(Profile).where(Profile.id == profile_id)
        p_res = await db.execute(p_stmt)
        profile_record = p_res.scalar_one_or_none()
        if profile_record is None:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Profile '{profile_id}' not found.")
    access = await get_user_profile_access(profile_record, user, db)
    if access is None:
        raise HTTPException(status_code=403, detail=f"Access denied to profile '{profile_id}'.")
    if access == "view_paperwork":
        raise HTTPException(status_code=403, detail="Access denied: clinical permissions required for chat.")

    # Resolve thread ID for session persistence
    thread_id = request.get_thread_id() or f"thread_{agent_id}_{uuid.uuid4().hex[:12]}"

    owner_id = resolve_owner_user_id(user)
    stmt = select(ChatThread).where(ChatThread.id == thread_id)
    res = await db.execute(stmt)
    existing_thread = res.scalar_one_or_none()
    if existing_thread is not None:
        if owner_id and getattr(user, "role", "member") != "admin":
            if existing_thread.user_id is not None and existing_thread.user_id != owner_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: conversation thread belongs to another user.",
                )
        if existing_thread.profile_id:
            p_stmt = select(Profile).where(Profile.id == existing_thread.profile_id)
            p_res = await db.execute(p_stmt)
            p_obj = p_res.scalar_one_or_none()
            if p_obj:
                p_acc = await get_user_profile_access(p_obj, user, db)
                if p_acc is None:
                    raise HTTPException(status_code=403, detail="Access denied to conversation thread profile.")
    else:
        new_thread = ChatThread(
            id=thread_id,
            user_id=owner_id,
            profile_id=profile_id,
            agent_id=agent_id,
            title=request.prompt.strip()[:50] or "New Consultation",
        )
        db.add(new_thread)
        await db.commit()

    # Resolve provider and model from request; keys and endpoints resolve exclusively server-side
    provider = request.get_provider()
    model = request.model

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
                api_key=None,
                base_url=None,
                user_id=owner_id,
                profile_id=profile_id,
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


@router.get("/chat/threads")
@router.get(ROUTE_CHAT_THREADS)
async def get_thread_history(
    thread_id: Optional[str] = None,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves conversation history and checkpoints for a given thread ID."""
    if not thread_id or not thread_id.strip():
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Parameter 'thread_id' is required.")

    clean_thread_id = thread_id.strip()
    owner_id = resolve_owner_user_id(user)

    stmt = select(ChatThread).where(ChatThread.id == clean_thread_id)
    res = await db.execute(stmt)
    thread_record = res.scalar_one_or_none()
    if thread_record is not None:
        if owner_id and getattr(user, "role", "member") != "admin":
            if thread_record.user_id is not None and thread_record.user_id != owner_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: conversation thread belongs to another user.",
                )
        if thread_record.profile_id:
            p_stmt = select(Profile).where(Profile.id == thread_record.profile_id)
            p_res = await db.execute(p_stmt)
            p_obj = p_res.scalar_one_or_none()
            if p_obj:
                p_acc = await get_user_profile_access(p_obj, user, db)
                if p_acc is None or p_acc == "view_paperwork":
                    raise HTTPException(status_code=403, detail="Access denied to conversation thread profile.")
            elif getattr(user, "role", "member") != "admin":
                raise HTTPException(status_code=403, detail="Access denied to conversation thread profile.")
    elif owner_id and getattr(user, "role", "member") != "admin":
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Thread '{clean_thread_id}' not found.",
        )

    db_path = resolve_checkpointer_path()
    if not db_path.is_file() and settings.workspace_root:
        ws_db = resolve_checkpointer_path(settings.workspace_root)
        if ws_db.is_file():
            db_path = ws_db

    if not db_path.is_file():
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"No checkpoints found for thread '{clean_thread_id}'.")

    try:
        async with create_async_sqlite_saver(db_path) as saver:
            config = {"configurable": {"thread_id": clean_thread_id}}
            checkpoint_tuple = await saver.aget_tuple(config)

            if not checkpoint_tuple or not checkpoint_tuple.checkpoint:
                raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Thread '{clean_thread_id}' not found.")

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
                "threadId": clean_thread_id,
                "profileId": thread_record.profile_id if thread_record else None,
                "messages": serialized_messages,
                "followUpSuggestions": channel_values.get("follow_up_suggestions", []),
                "count": len(serialized_messages),
            }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to load thread history")
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load thread history.")


@router.delete("/chat/threads")
@router.delete("/chat/threads/{thread_id}")
@router.delete(ROUTE_CHAT_THREADS)
async def delete_thread_history(
    thread_id: Optional[str] = None,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes conversation thread tracking entity."""
    clean_thread_id = (thread_id or "").strip()
    if not clean_thread_id:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Parameter 'thread_id' is required.")

    owner_id = resolve_owner_user_id(user)
    stmt = select(ChatThread).where(ChatThread.id == clean_thread_id)
    res = await db.execute(stmt)
    thread_record = res.scalar_one_or_none()

    if thread_record is not None:
        if owner_id and getattr(user, "role", "member") != "admin":
            if thread_record.user_id is not None and thread_record.user_id != owner_id:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: conversation thread belongs to another user.",
                )
        if thread_record.profile_id:
            p_stmt = select(Profile).where(Profile.id == thread_record.profile_id)
            p_res = await db.execute(p_stmt)
            p_obj = p_res.scalar_one_or_none()
            if p_obj:
                p_acc = await get_user_profile_access(p_obj, user, db)
                if p_acc != "manage" and getattr(user, "role", "member") != "admin":
                    raise HTTPException(status_code=403, detail="Access denied: manage permissions required to delete conversation thread.")
            elif getattr(user, "role", "member") != "admin":
                raise HTTPException(status_code=403, detail="Access denied to conversation thread profile.")
        await db.delete(thread_record)
        await db.commit()

    return {"success": True, "threadId": clean_thread_id, "deleted": True}


class ChatResumeRequestBody(BaseModel):
    thread_id: str = Field(..., description="Conversation thread identifier to resume")
    approval_id: str = Field(..., description="Approval record identifier")
    decision: Literal["approved", "rejected"] = Field("approved", description="Decision outcome")
    edited_args: Optional[Dict[str, Any]] = Field(None, description="Optional edited tool arguments")
    profile_id: Optional[str] = Field(None, description="Target profile ID")


@router.post("/chat/resume")
@router.post("/v1/chat/resume")
async def chat_resume_stream(
    request: ChatResumeRequestBody,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Resumes an interrupted conversation thread after human steward approval or rejection."""
    owner_id = resolve_owner_user_id(user)
    service = AgentExecutionService()

    async def sse_resume_generator() -> AsyncIterator[str]:
        try:
            async for event in service.execute_resume_turn(
                thread_id=request.thread_id,
                approval_id=request.approval_id,
                decision=request.decision,
                edited_args=request.edited_args,
                user_id=owner_id,
                profile_id=request.profile_id,
            ):
                event_type = event.get("type", SSE_EVENT_MESSAGE)
                data_str = json.dumps(event)
                yield f"event: {event_type}\ndata: {data_str}\n\n"
        except Exception:
            logger.exception("Unexpected error in chat resume stream")
            err_data = json.dumps({
                "type": SSE_EVENT_ERROR,
                "message": "An unexpected error occurred during chat resumption.",
            })
            yield f"event: {SSE_EVENT_ERROR}\ndata: {err_data}\n\n"

    return StreamingResponse(
        sse_resume_generator(),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )

