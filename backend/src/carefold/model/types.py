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

"""Model client data types and streaming schemas."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Protocol
from pydantic import BaseModel, Field


class ModelMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ModelToolFunction(BaseModel):
    name: str = ""
    arguments: str = ""


class ModelToolCallChunk(BaseModel):
    index: int = 0
    id: Optional[str] = None
    type: str = "function"
    function: Optional[ModelToolFunction] = None


class StreamDelta(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[List[ModelToolCallChunk]] = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: StreamDelta = Field(default_factory=StreamDelta)
    finish_reason: Optional[str] = None


class ModelStreamChunk(BaseModel):
    id: Optional[str] = None
    choices: List[StreamChoice] = Field(default_factory=list)


class ModelClient(Protocol):
    def get_model_name(self) -> str:
        ...

    async def check_health(self) -> Dict[str, Any]:
        ...

    def stream_chat(
        self,
        messages: List[ModelMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[ModelStreamChunk]:
        ...
