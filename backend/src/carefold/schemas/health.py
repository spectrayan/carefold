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
