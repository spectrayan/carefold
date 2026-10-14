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

"""Audit logging schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

AuditEventType = Literal["run", "tool", "refuse", "error", "boundary_warning", "synthesis"]


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
    thread_id: Optional[str] = None
    profile_id: Optional[str] = None
    id: Optional[str] = None
    actor_user_id: Optional[str] = None
    principal: Optional[str] = None
    run_id: Optional[str] = None
    risk: Optional[str] = None
    decision: Optional[str] = None
    payload_hash: Optional[str] = None
    external_ref: Optional[str] = None


class AuditListResponse(BaseModel):
    total: int
    limit: int
    events: List[AuditEvent]
