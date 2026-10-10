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
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from carefold.api.deps import (
    get_current_memory_port,
    get_current_user,
    resolve_owner_user_id,
)
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.constants.api import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from carefold.logging import sanitize_log_value
from carefold.memory.ports.memory_port import MemoryPort, MemoryTier
from carefold.schemas.memory import (
    MemoryBulkDeleteResponse,
    MemoryDeleteResponse,
    MemoryRecordResponse,
    MemoryStatusResponse,
    MemoryUpdateRequest,
)

logger = logging.getLogger("carefold.api.memory")

router = APIRouter()


def _validate_memory_key(key: str) -> str:
    """Validates and cleans a memory key against empty, path traversal, or null bytes."""
    if not key or not key.strip():
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Memory key must not be empty.",
        )
    clean_key = key.strip()
    if any(seq in clean_key for seq in ("\x00", "..", "/", "\\")):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Memory key contains invalid characters or path traversal sequences.",
        )
    return clean_key


def _validate_namespace(namespace: Optional[str]) -> str:
    """Validates and cleans an isolation namespace."""
    if not namespace or not namespace.strip():
        return "default"
    clean_ns = namespace.strip()
    if any(seq in clean_ns for seq in ("\x00", "..", "/", "\\")):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Memory namespace contains invalid characters or path traversal sequences.",
        )
    return clean_ns


def resolve_effective_namespace(
    user: Optional[UserProfile],
    client_namespace: Optional[str] = "default",
    profile_id: Optional[str] = None,
) -> str:
    """Derives isolated memory namespace server-side based on user ownership and profile.

    In disabled auth mode:
    - if profile_id: returns f"profile_{profile_id}" or f"profile_{profile_id}:{clean_ns}"
    - else: returns clean_ns
    In authenticated mode:
    - if profile_id: returns f"user_{owner_id}_profile_{profile_id}" or f"user_{owner_id}_profile_{profile_id}:{clean_ns}"
    - else: returns f"user_{owner_id}" or f"user_{owner_id}:{clean_ns}"
    """
    clean_ns = _validate_namespace(client_namespace)
    owner_id = resolve_owner_user_id(user)
    if not owner_id:
        if profile_id:
            return f"profile_{profile_id}" if clean_ns in ("default", "", None) else f"profile_{profile_id}:{clean_ns}"
        return clean_ns

    # Administrative override: admin can inspect specific user namespaces
    if getattr(user, "role", "member") == "admin" and clean_ns.startswith("user_"):
        return clean_ns

    if profile_id:
        base = f"user_{owner_id}_profile_{profile_id}"
        if clean_ns in ("default", "", None) or clean_ns == base:
            return base
        return f"{base}:{clean_ns}"

    if clean_ns == f"user_{owner_id}":
        return clean_ns
    if clean_ns in ("default", "", None):
        return f"user_{owner_id}"
    return f"user_{owner_id}:{clean_ns}"


@router.get("", response_model=List[MemoryRecordResponse])
@router.get("/", response_model=List[MemoryRecordResponse], include_in_schema=False)
@router.get("/recall", response_model=List[MemoryRecordResponse], include_in_schema=False)
async def recall_memories(
    query: Optional[str] = Query(default="", description="Search query or keywords for memory recall"),
    q: Optional[str] = Query(default=None, description="Alias for query parameter"),
    tier: Optional[str] = Query(default=None, description="Optional cognitive memory tier filter (working, episodic, semantic, procedural)"),
    namespace: str = Query(default="default", description="Memory isolation namespace"),
    profile_id: Optional[str] = Query(default=None, description="Optional care profile ID for memory scoping"),
    limit: int = Query(default=10, ge=1, le=100, description="Maximum number of memories to return"),
    port: MemoryPort = Depends(get_current_memory_port),
    user: UserProfile = Depends(get_current_user),
) -> List[MemoryRecordResponse]:
    """Recalls or lists cognitive memories matching query, tier filter, namespace, and profile."""
    effective_ns = resolve_effective_namespace(user, namespace, profile_id)
    search_query = (q if q is not None else query) or ""
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
            query=search_query,
            tier=parsed_tier,
            namespace=effective_ns,
            limit=limit,
        )
        if inspect.isawaitable(res):
            records = await res
        else:
            records = res
    except Exception as exc:
        clean_q = sanitize_log_value(query or "")
        clean_ns_log = sanitize_log_value(effective_ns)
        logger.error(
            "Failed to recall memories (query='%s', ns='%s'): %s",
            clean_q,
            clean_ns_log,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to recall memories: {str(exc)}",
        )

    return [MemoryRecordResponse.model_validate(r) for r in records]


@router.get("/status", response_model=MemoryStatusResponse)
async def get_memory_status(
    port: MemoryPort = Depends(get_current_memory_port),
    user: UserProfile = Depends(get_current_user),
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


@router.delete("", response_model=MemoryBulkDeleteResponse)
@router.delete("/", response_model=MemoryBulkDeleteResponse, include_in_schema=False)
async def delete_all_memories(
    namespace: str = Query(default="default", description="Memory isolation namespace"),
    profile_id: Optional[str] = Query(default=None, description="Optional care profile ID for memory scoping"),
    port: MemoryPort = Depends(get_current_memory_port),
    user: UserProfile = Depends(get_current_user),
) -> MemoryBulkDeleteResponse:
    """Bulk forgets/deletes all memories within the specified namespace."""
    effective_ns = resolve_effective_namespace(user, namespace, profile_id)
    try:
        res = port.forget_all(namespace=effective_ns)
        if inspect.isawaitable(res):
            deleted_count = await res
        else:
            deleted_count = res
    except Exception as exc:
        clean_ns_log = sanitize_log_value(effective_ns)
        logger.error(
            "Failed to bulk delete memories in namespace '%s': %s",
            clean_ns_log,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk delete memories: {str(exc)}",
        )

    return MemoryBulkDeleteResponse(
        deleted=True,
        deleted_count=int(deleted_count),
        namespace=effective_ns,
    )


@router.get("/{key}", response_model=MemoryRecordResponse)
async def get_memory(
    key: str = Path(..., description="Unique key of the memory record to retrieve"),
    namespace: str = Query(default="default", description="Memory isolation namespace"),
    profile_id: Optional[str] = Query(default=None, description="Optional care profile ID for memory scoping"),
    port: MemoryPort = Depends(get_current_memory_port),
    user: UserProfile = Depends(get_current_user),
) -> MemoryRecordResponse:
    """Retrieves a single memory record by key in the specified namespace."""
    clean_key = _validate_memory_key(key)
    effective_ns = resolve_effective_namespace(user, namespace, profile_id)

    try:
        res = port.get(key=clean_key, namespace=effective_ns)
        if inspect.isawaitable(res):
            record = await res
        else:
            record = res
    except Exception as exc:
        clean_key_log = sanitize_log_value(clean_key)
        clean_ns_log = sanitize_log_value(effective_ns)
        logger.error(
            "Failed to retrieve memory '%s' in namespace '%s': %s",
            clean_key_log,
            clean_ns_log,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve memory: {str(exc)}",
        )

    if record is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Memory record '{clean_key}' not found in namespace '{effective_ns}'.",
        )

    return MemoryRecordResponse.model_validate(record)


@router.put("/{key}", response_model=MemoryRecordResponse)
async def update_memory(
    key: str = Path(..., description="Unique key of the memory record to update"),
    body: MemoryUpdateRequest = Body(..., description="Updated memory record payload"),
    namespace: Optional[str] = Query(default=None, description="Memory isolation namespace override"),
    profile_id: Optional[str] = Query(default=None, description="Optional care profile ID for memory scoping"),
    port: MemoryPort = Depends(get_current_memory_port),
    user: UserProfile = Depends(get_current_user),
) -> MemoryRecordResponse:
    """Updates or upserts a memory record in the specified namespace."""
    clean_key = _validate_memory_key(key)
    raw_ns = body.namespace if body.namespace is not None else namespace
    effective_profile_id = body.profile_id or profile_id
    effective_ns = resolve_effective_namespace(user, raw_ns, effective_profile_id)

    parsed_tier: Optional[MemoryTier] = None
    if body.tier is not None and body.tier.strip():
        tier_clean = body.tier.strip().lower()
        try:
            parsed_tier = MemoryTier(tier_clean)
        except ValueError:
            valid_tiers = [t.value for t in MemoryTier]
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=f"Invalid memory tier '{body.tier}'. Must be one of: {valid_tiers}",
            )

    try:
        # If tier was not specified in update, try preserving existing tier
        if parsed_tier is None:
            existing = port.get(key=clean_key, namespace=effective_ns)
            if inspect.isawaitable(existing):
                existing_record = await existing
            else:
                existing_record = existing
            if existing_record and existing_record.get("tier"):
                try:
                    parsed_tier = MemoryTier(existing_record["tier"])
                except Exception:
                    parsed_tier = MemoryTier.EPISODIC
            else:
                parsed_tier = MemoryTier.EPISODIC

        # Upsert via remember
        rem = port.remember(
            key=clean_key,
            value=body.value,
            tier=parsed_tier,
            namespace=effective_ns,
            metadata=body.metadata,
        )
        if inspect.isawaitable(rem):
            await rem

        # Retrieve updated record
        updated = port.get(key=clean_key, namespace=effective_ns)
        if inspect.isawaitable(updated):
            record = await updated
        else:
            record = updated
    except HTTPException:
        raise
    except Exception as exc:
        clean_key_log = sanitize_log_value(clean_key)
        clean_ns_log = sanitize_log_value(effective_ns)
        logger.error(
            "Failed to update memory '%s' in namespace '%s': %s",
            clean_key_log,
            clean_ns_log,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update memory record: {str(exc)}",
        )

    if record is None:
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Memory record was not found after update.",
        )

    return MemoryRecordResponse.model_validate(record)


@router.delete("/{key}", response_model=MemoryDeleteResponse)
async def delete_memory(
    key: str = Path(..., description="Unique key of the memory record to forget"),
    namespace: str = Query(default="default", description="Memory isolation namespace"),
    profile_id: Optional[str] = Query(default=None, description="Optional care profile ID for memory scoping"),
    port: MemoryPort = Depends(get_current_memory_port),
    user: UserProfile = Depends(get_current_user),
) -> MemoryDeleteResponse:
    """Forgets/deletes a memory record identified by key in the specified namespace."""
    clean_key = _validate_memory_key(key)
    effective_ns = resolve_effective_namespace(user, namespace, profile_id)

    try:
        res = port.forget(key=clean_key, namespace=effective_ns)
        if inspect.isawaitable(res):
            deleted = await res
        else:
            deleted = res
    except Exception as exc:
        clean_key_log = sanitize_log_value(clean_key)
        clean_ns_log = sanitize_log_value(effective_ns)
        logger.error(
            "Failed to delete memory '%s' in namespace '%s': %s",
            clean_key_log,
            clean_ns_log,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete memory record: {str(exc)}",
        )

    return MemoryDeleteResponse(
        deleted=bool(deleted),
        key=clean_key,
        namespace=effective_ns,
    )


__all__ = ["router"]
