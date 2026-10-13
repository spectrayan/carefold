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

"""Pydantic schemas for Activity Timeline and Single-Click Undo (AU-40)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class ActivityItemResponse(BaseModel):
    """Single chronological activity timeline event card."""

    id: str = Field(..., description="Unique audit event UUID")
    event_id: Optional[str] = Field(None, description="Referenced AuditEventRecord UUID")
    ts: datetime = Field(..., description="Event issuance UTC timestamp")
    profile_id: str = Field(..., description="Associated patient profile identifier")
    actor_user_id: Optional[str] = Field(None, description="Authenticated user ID who triggered action")
    principal: str = Field("user", description="Execution principal: user, agent, orchestrator")
    actor: str = Field("user", description="Normalized actor principal: user, agent, system")
    event: str = Field(..., description="Event type classification: tool, run, refuse, undo, create")
    action: Optional[str] = Field(None, description="Action classification: create, update, delete, undo, tool, refuse")
    tool: Optional[str] = Field(None, description="Invoked tool or system module identifier")
    risk: Optional[str] = Field(None, description="Risk tier: write_local, read, write_network, none")
    external_ref: Optional[str] = Field(None, description="Target entity locator: <entity_type>:<entity_id>")
    summary: str = Field(..., description="Patient-friendly summary headline")
    description: str = Field(..., description="Human-readable clinical activity description")
    undoable: bool = Field(False, description="True if action is write_local, within 7 days, and not undone")
    undone: bool = Field(False, description="True if this specific action has already been reverted")
    details: Dict[str, Any] = Field(default_factory=dict, description="Sanitized metadata and execution details")

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "id" in data and not data.get("event_id"):
                data["event_id"] = data["id"]
            elif "event_id" in data and not data.get("id"):
                data["id"] = data["event_id"]
            if "principal" in data and not data.get("actor"):
                data["actor"] = data["principal"]
            elif "actor" in data and not data.get("principal"):
                data["principal"] = data["actor"]
            if "event" in data and not data.get("action"):
                data["action"] = data["event"]
            elif "action" in data and not data.get("event"):
                data["event"] = data["action"]
        return data


# Alias for backward compatibility with domain models
ActivityItem = ActivityItemResponse


class ActivityTimelineResponse(BaseModel):
    """Paginated collection of activity timeline items for a patient profile."""

    items: List[ActivityItemResponse] = Field(..., description="Chronological activity items (newest first)")
    total: int = Field(..., ge=0, description="Total matching activity events in store")
    limit: int = Field(..., ge=1, description="Requested page size limit")
    offset: int = Field(..., ge=0, description="Requested pagination offset")
    profile_id: str = Field(..., description="Scoped patient profile identifier")
    has_more: bool = Field(False, description="True if additional pages are available")


class ActivityUndoResponse(BaseModel):
    """Confirmation payload returned after single-click undo execution."""

    status: Literal["undone"] = Field("undone", description="Status confirmation indicating successful rollback")
    event_id: str = Field(..., description="Original audit event UUID that was reverted")
    undo_event_id: Optional[str] = Field(None, description="Audited reversal event UUID logged in audit_events")
    external_ref: Optional[str] = Field(None, description="Rolled back target entity reference")
    reverted_summary: Optional[str] = Field(None, description="Human-readable summary of the action that was undone")
    message: Optional[str] = Field("Action successfully undone.", description="Human-readable success message")
