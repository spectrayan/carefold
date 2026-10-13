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

"""Closed Phase 0 tool: search_records (AU-26).

Executes profile-scoped cognitive hybrid search across patient medical records,
attachments, and clinical notes with monotone untrusted taint tracking.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from carefold.schemas.tool import ToolResult
from carefold.search.base import SearchIndex, SearchResult
from carefold.search.factory import get_search_index

logger = logging.getLogger("carefold.tools.search_records")

UNTRUSTED_SOURCES = frozenset({
    "external",
    "import",
    "connector",
    "email",
    "web",
    "patient_portal",
    "untrusted",
    "external_ehr",
    "third_party",
})

TRUSTED_SOURCES = frozenset({
    "clinical_note",
    "note",
    "internal",
    "clinical",
    "upload",
})


def is_hit_untrusted(hit: SearchResult) -> bool:
    """Evaluates whether a search hit originates from an external or untrusted source."""
    meta = hit.metadata if isinstance(hit.metadata, dict) else {}

    # 1. Explicit trust markers in metadata
    trust_val = str(meta.get("trust", "")).lower().strip()
    if trust_val == "untrusted" or meta.get("untrusted") is True or meta.get("is_trusted") is False:
        return True

    # 2. Source matching against untrusted taxonomy
    hit_source = str(hit.source or "").lower().strip()
    meta_source = str(meta.get("source", "")).lower().strip()

    if hit_source in UNTRUSTED_SOURCES or meta_source in UNTRUSTED_SOURCES:
        return True

    # 3. External indicators in metadata
    if meta.get("external") is True or meta.get("is_external") is True:
        return True
    if meta.get("connector_id") or meta.get("connector_type") or meta.get("origin") == "external":
        return True

    # 4. Strict provenance fallback: if source is non-empty and not in recognized trusted set
    if hit_source and hit_source not in TRUSTED_SOURCES and hit_source not in ("search",):
        return True
    if meta_source and meta_source not in TRUSTED_SOURCES and meta_source not in ("search",):
        return True

    return False


async def execute_search_records(args: Dict[str, Any], ctx: Any = None) -> Any:
    """Executes profile-scoped search with fail-closed security and taint escalation."""
    from carefold.engine.tool_exec import UntrustedResult

    # 1. Fail-closed profile verification
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("search_records rejected: invalid or missing profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed search.",
        )
    clean_profile_id = profile_id.strip()

    # 2. Parameter validation
    raw_query = args.get("query") if isinstance(args, dict) else None
    if not raw_query or not str(raw_query).strip():
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'query' must not be empty.",
        )
    query = str(raw_query).strip()

    # Limit validation with safe clamping [1, 50]
    limit_raw = args.get("limit", 5) if isinstance(args, dict) else 5
    try:
        limit = max(1, min(int(limit_raw), 50))
    except (TypeError, ValueError):
        limit = 5

    # Mode validation
    mode_raw = str(args.get("mode", "hybrid")).strip().lower() if isinstance(args, dict) else "hybrid"
    mode = mode_raw if mode_raw in ("hybrid", "lexical", "semantic") else "hybrid"

    # Source filter
    filters: Optional[Dict[str, Any]] = None
    source_filter = args.get("source") if isinstance(args, dict) else None
    if source_filter and str(source_filter).strip():
        filters = {"source": str(source_filter).strip()}

    # 3. Execution against hexagonal SearchIndex
    try:
        index: SearchIndex = get_search_index()
        hits: List[SearchResult] = await index.search(
            query=query,
            profile_id=clean_profile_id,
            limit=limit,
            mode=mode,
            filters=filters,
        )
    except Exception as exc:
        logger.warning(
            "search_records execution error for profile %s: %s",
            clean_profile_id,
            exc,
            exc_info=True,
        )
        return ToolResult(
            success=False,
            output=[],
            error=f"Search execution failed: {exc}",
        )

    serialized_hits: List[Dict[str, Any]] = [h.model_dump() for h in hits]

    # 4. Monotone Taint Tracking
    has_untrusted = any(is_hit_untrusted(h) for h in hits)

    if has_untrusted:
        # Monotone escalation on ToolContext taint flag
        if ctx is not None and getattr(ctx, "taint", None) is not None:
            if hasattr(ctx.taint, "set"):
                ctx.taint.set()

        wrapped_hits: List[Any] = []
        for h, data in zip(hits, serialized_hits):
            if is_hit_untrusted(h):
                wrapped_hits.append(
                    UntrustedResult(data=data, taint=True, source=h.source or "external")
                )
            else:
                wrapped_hits.append(data)

        return UntrustedResult(
            data=wrapped_hits,
            taint=True,
            source="external_record",
        )

    return serialized_hits


__all__ = [
    "UNTRUSTED_SOURCES",
    "TRUSTED_SOURCES",
    "is_hit_untrusted",
    "execute_search_records",
]
