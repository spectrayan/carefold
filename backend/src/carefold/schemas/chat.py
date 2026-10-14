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

"""Chat API request, message, and SSE payload schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ChatRequestBody(BaseModel):
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    prompt: str
    messages: List[ChatMessage] = Field(default_factory=list)
    attachments: List[str] = Field(default_factory=list)
    allow_clinical: bool = False

    # LangGraph state & session parameters
    threadId: Optional[str] = None
    thread_id: Optional[str] = None
    profileId: Optional[str] = None
    profile_id: Optional[str] = None

    # LangChain multi-provider parameters
    provider: Optional[str] = "ollama"
    model: Optional[str] = None
    apiKey: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Ignored by server; keys and endpoints resolve exclusively from server configuration.",
    )
    api_key: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Ignored by server; keys and endpoints resolve exclusively from server configuration.",
    )
    customEndpoint: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Ignored by server; keys and endpoints resolve exclusively from server configuration.",
    )
    baseUrl: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Ignored by server; keys and endpoints resolve exclusively from server configuration.",
    )
    base_url: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Ignored by server; keys and endpoints resolve exclusively from server configuration.",
    )

    def get_agent_id(self) -> str:
        aid = self.agentId or self.agent_id
        if not aid:
            raise ValueError("agentId or agent_id is required")
        return aid

    def get_thread_id(self) -> Optional[str]:
        return self.threadId or self.thread_id

    def get_profile_id(self) -> Optional[str]:
        return self.profileId or self.profile_id

    def get_provider(self) -> str:
        return self.provider or "ollama"

    def get_api_key(self) -> Optional[str]:
        """Strictly ignored by server; resolves exclusively from server configuration."""
        return None

    def get_custom_endpoint(self) -> Optional[str]:
        """Strictly ignored by server; resolves exclusively from server configuration."""
        return None



class SSETokenEvent(BaseModel):
    type: Literal["token"] = "token"
    delta: str


class SSEToolStartEvent(BaseModel):
    type: Literal["tool_start"] = "tool_start"
    tool: str
    params: Dict[str, Any] = Field(default_factory=dict)


class SSEToolEndEvent(BaseModel):
    type: Literal["tool_end"] = "tool_end"
    tool: str
    duration_ms: float
    status: Literal["completed", "failed", "denied"]
    allowed: bool
    result: Dict[str, Any] = Field(default_factory=dict)


class SSERefusalEvent(BaseModel):
    type: Literal["refusal"] = "refusal"
    reason: str
    message: str


class SSESuggestionsEvent(BaseModel):
    type: Literal["suggestions"] = "suggestions"
    suggestions: List[str] = Field(default_factory=list)


class SSEDoneEvent(BaseModel):
    type: Literal["done"] = "done"
    fullText: str
    auditEventId: Optional[str] = None
    refused: bool = False
    refusalReason: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)
    followUpSuggestions: List[str] = Field(default_factory=list)
    threadId: Optional[str] = None


class SSEErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
