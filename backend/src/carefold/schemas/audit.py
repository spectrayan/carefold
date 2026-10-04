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

"""Audit logging schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

AuditEventType = Literal["run", "tool", "refuse", "error", "boundary_warning"]


class AuditEvent(BaseModel):
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    agent_id: str
    skill_id: Optional[str] = None
    skill_version: Optional[str] = None
    event: AuditEventType
    tool: Optional[str] = None
    allowed: Optional[bool] = None
    reason: Optional[str] = None
    duration_ms: Optional[float] = None
    prompt: Optional[str] = None      # Redacted unless store_bodies=True
    completion: Optional[str] = None  # Redacted unless store_bodies=True


class AuditListResponse(BaseModel):
    total: int
    limit: int
    events: List[AuditEvent]
