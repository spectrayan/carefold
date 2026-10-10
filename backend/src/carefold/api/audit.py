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

"""Audit log retrieval and inspection endpoints."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query

from carefold.api.deps import get_current_user
from carefold.audit.logger import get_recent_audit_events
from carefold.auth.ports import UserProfile
from carefold.constants.api import ROUTE_AUDIT
from carefold.constants.defaults import (
    DEFAULT_AUDIT_LIMIT,
    MAX_AUDIT_LIMIT,
    MIN_AUDIT_LIMIT,
)
from carefold.schemas.audit import AuditListResponse

router = APIRouter(tags=["Audit"])


@router.get(ROUTE_AUDIT, response_model=AuditListResponse)
async def list_audit_events(
    limit: int = Query(
        DEFAULT_AUDIT_LIMIT,
        ge=MIN_AUDIT_LIMIT,
        le=MAX_AUDIT_LIMIT,
        description="Max number of recent events to return",
    ),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    event: Optional[str] = Query(None, description="Filter by event type (run, tool, refuse, error)"),
    full: bool = Query(False, description="Include message bodies if stored"),
    profile_id: Optional[str] = Query(None, description="Filter by profile ID"),
    user: UserProfile = Depends(get_current_user),
) -> AuditListResponse:
    """Retrieves recent audit log events, newest first, with privacy redaction by default."""
    total, events = await get_recent_audit_events(
        limit=limit,
        agent_id=agent_id,
        event=event,
        full=full,
        profile_id=profile_id,
    )

    return AuditListResponse(
        total=total,
        limit=limit,
        events=events,
    )
