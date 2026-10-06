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

"""REST endpoints for Carefold cognitive memory management."""

from __future__ import annotations

import inspect
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from carefold.api.deps import get_current_memory_port
from carefold.config import settings
from carefold.constants.api import (
    HTTP_400_BAD_REQUEST,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from carefold.logging import sanitize_log_value
from carefold.memory.ports.memory_port import MemoryPort, MemoryTier
from carefold.schemas.memory import (
    MemoryDeleteResponse,
    MemoryRecordResponse,
    MemoryStatusResponse,
)

logger = logging.getLogger("carefold.api.memory")

router = APIRouter()


@router.get("", response_model=List[MemoryRecordResponse])
@router.get("/", response_model=List[MemoryRecordResponse], include_in_schema=False)
async def recall_memories(
    query: Optional[str] = Query(default="", description="Search query or keywords for memory recall"),
    tier: Optional[str] = Query(default=None, description="Optional cognitive memory tier filter (working, episodic, semantic, procedural)"),
    namespace: str = Query(default="default", description="Memory isolation namespace"),
    limit: int = Query(default=10, ge=1, le=100, description="Maximum number of memories to return"),
    port: MemoryPort = Depends(get_current_memory_port),
) -> List[MemoryRecordResponse]:
    """Recalls or lists cognitive memories matching query, tier filter, and namespace."""
    parsed_tier: Optional[MemoryTier] = None
    if tier is not None and tier.strip():
        tier_clean = tier.strip().lower()
        try:
            parsed_tier = MemoryTier(tier_clean)
        except ValueError:
            valid_tiers = [t.value for t in MemoryTier]
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=f"Invalid memory tier '{tier}'. Must be one of: {valid_tiers}",
            )

    try:
        res = port.recall(
            query=query or "",
            tier=parsed_tier,
            namespace=namespace,
            limit=limit,
        )
        if inspect.isawaitable(res):
            records = await res
        else:
            records = res
    except Exception as exc:
        logger.error("Failed to recall memories: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to recall memories: {str(exc)}",
        )

    return [MemoryRecordResponse.model_validate(r) for r in records]


@router.get("/status", response_model=MemoryStatusResponse)
async def get_memory_status(
    port: MemoryPort = Depends(get_current_memory_port),
) -> MemoryStatusResponse:
    """Returns active cognitive memory backend health, fallback state, and configuration."""
    backend_val = getattr(port, "backend", None)
    is_spector = (
        backend_val == "spector"
        or port.__class__.__name__ == "SpectorMemoryAdapter"
        or hasattr(port, "_store")
    )

    if is_spector:
        backend = "spector"
        fallback_active = bool(getattr(port, "fallback_active", getattr(port, "is_degraded", False)))
        healthy = not fallback_active
        store = getattr(port, "store", getattr(port, "_store", None))
        spector_url = str(getattr(store, "base_url", None) or settings.spector_url)
        cooldown_seconds = float(getattr(store, "cooldown_seconds", 30.0))
    else:
        backend = backend_val or (
            "sqlite" if port.__class__.__name__ == "SqliteMemoryAdapter" else settings.memory_backend
        )
        fallback_active = bool(getattr(port, "fallback_active", False))
        healthy = not fallback_active
        spector_url = settings.spector_url
        cooldown_seconds = float(getattr(port, "cooldown_seconds", 0.0))

    return MemoryStatusResponse(
        backend=backend,
        healthy=healthy,
        fallback_active=fallback_active,
        spector_url=spector_url,
        cooldown_seconds=cooldown_seconds,
    )


@router.delete("/{key}", response_model=MemoryDeleteResponse)
async def delete_memory(
    key: str = Path(..., description="Unique key of the memory record to forget"),
    namespace: str = Query(default="default", description="Memory isolation namespace"),
    port: MemoryPort = Depends(get_current_memory_port),
) -> MemoryDeleteResponse:
    """Forgets/deletes a memory record identified by key in the specified namespace."""
    if not key or not key.strip():
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Memory key must not be empty.",
        )

    try:
        res = port.forget(key=key.strip(), namespace=namespace)
        if inspect.isawaitable(res):
            deleted = await res
        else:
            deleted = res
    except Exception as exc:
        clean_key = sanitize_log_value(key)
        clean_namespace = sanitize_log_value(namespace)
        logger.error(
            "Failed to delete memory '%s' in namespace '%s': %s",
            clean_key,
            clean_namespace,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete memory record: {str(exc)}",
        )

    return MemoryDeleteResponse(
        deleted=bool(deleted),
        key=key.strip(),
        namespace=namespace,
    )


__all__ = ["router"]
