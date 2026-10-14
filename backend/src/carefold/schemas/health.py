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

"""Health status schemas."""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class OllamaHealthStatus(BaseModel):
    status: Literal["connected", "unreachable", "error"]
    endpoint: str
    reachable: bool
    activeModel: Optional[str] = None
    availableModels: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class WorkspaceInfo(BaseModel):
    root: str
    agentsCount: int
    skillsCount: int


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "error"]
    version: str = "0.1.0"
    uptime: float
    timestamp: str
    modelReachable: bool
    workspace: WorkspaceInfo
    ollama: OllamaHealthStatus
    backendReachable: bool = True
