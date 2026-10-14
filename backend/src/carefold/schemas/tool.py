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

"""Tool and execution context schemas."""

from __future__ import annotations

from typing import Any, Callable, Dict, Literal, Optional
from pydantic import BaseModel, Field

ClosedToolName = Literal["attach-read", "workspace-note", "skill-docs"]


class ToolResult(BaseModel):
    success: bool
    output: Any = None
    error: Optional[str] = None


class ToolCallRecord(BaseModel):
    tool: str
    input: Dict[str, Any] = Field(default_factory=dict)
    allowed: bool = True
    duration_ms: float = 0.0
    success: bool = True
    output: Any = None
    error: Optional[str] = None
