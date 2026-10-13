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

"""REST API endpoints for profile-scoped cognitive record and document search."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user
from carefold.api.profiles import auto_provision_primary_me_profile, get_user_profile_access
from carefold.auth.ports import UserProfile
from carefold.db.models import Profile
from carefold.db.session import get_db
from carefold.logging import get_logger
from carefold.search.base import SearchResult
from carefold.search.factory import get_search_index

logger = get_logger("carefold.api.search")

router = APIRouter(tags=["search"])
search_router = router

VALID_SEARCH_MODES = frozenset({"hybrid", "lexical", "semantic"})


@router.get("/profiles/{profile_id}/search", response_model=List[SearchResult])
@router.get("/profiles/{profile_id}/search/", response_model=List[SearchResult], include_in_schema=False)
@router.get("/{profile_id}/search", response_model=List[SearchResult], include_in_schema=False)
@router.get("/{profile_id}/search/", response_model=List[SearchResult], include_in_schema=False)
async def search_profile_records(
    profile_id: str,
    q: Optional[str] = Query(default=None, description="Search query string or keywords"),
    query: Optional[str] = Query(default=None, description="Alias for query parameter"),
    limit: int = Query(default=10, ge=1, le=100, description="Maximum number of search results to retrieve"),
    mode: str = Query(default="hybrid", description="Retrieval mode: 'hybrid', 'lexical', or 'semantic'"),
    source: Optional[str] = Query(default=None, description="Optional filter by record source"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[SearchResult]:
    """Searches clinical notes, uploaded attachments, and extracted records for a specific profile.

    Enforces fail-closed multi-profile isolation and permissions via get_user_profile_access.
    """
    # 1. Validate profile_id parameter
    clean_profile_id = (profile_id or "").strip() if isinstance(profile_id, str) else ""
    if not clean_profile_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile not found",
        )

    # 2. Validate query string (accepts both ?q= and ?query=)
    raw_query = q if q is not None else query
    clean_query = (raw_query or "").strip()
    if not clean_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query cannot be empty",
        )

    # 3. Validate retrieval mode
    clean_mode = (mode or "hybrid").lower().strip()
    if clean_mode not in VALID_SEARCH_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid search mode",
        )

    # 4. Resolve Profile from database
    if clean_profile_id.lower() == "me":
        prof = await auto_provision_primary_me_profile(user, db)
    else:
        p_stmt = select(Profile).where(Profile.id == clean_profile_id)
        p_res = await db.execute(p_stmt)
        prof = p_res.scalar_one_or_none()

    if prof is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile not found",
        )

    # 5. Verify user access
    access = await get_user_profile_access(prof, user, db)
    if access is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: profile access denied",
        )

    # 6. Filters
    filters: Optional[Dict[str, Any]] = None
    if source and source.strip():
        filters = {"source": source.strip()}

    # 7. Execute search against hexagonal SearchIndex
    search_index = get_search_index()
    results = await search_index.search(
        query=clean_query,
        profile_id=prof.id,
        limit=limit,
        mode=clean_mode,
        filters=filters,
    )

    logger.info(
        "profile_search_completed",
        profile_id=prof.id,
        query=clean_query,
        limit=limit,
        mode=clean_mode,
        hits=len(results),
    )

    return results


__all__ = ["router", "search_router", "search_profile_records"]
