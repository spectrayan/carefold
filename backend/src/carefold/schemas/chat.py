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
    apiKey: Optional[str] = None
    api_key: Optional[str] = None
    customEndpoint: Optional[str] = None
    baseUrl: Optional[str] = None
    base_url: Optional[str] = None

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
        return self.apiKey or self.api_key

    def get_custom_endpoint(self) -> Optional[str]:
        return self.customEndpoint or self.baseUrl or self.base_url


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
