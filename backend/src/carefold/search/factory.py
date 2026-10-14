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

"""Search index factory with automatic reachability detection and fallback."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import socket
from typing import Any, Dict, Optional, Union
import urllib.parse

from carefold.config import Settings, settings as global_settings
from carefold.search.base import SearchIndex

logger = logging.getLogger("carefold.search.factory")

SEARCH_BACKEND_SPECTOR: str = "spector"
SEARCH_BACKEND_SQLITE: str = "sqlite"

SUPPORTED_SEARCH_BACKENDS = frozenset({
    SEARCH_BACKEND_SPECTOR,
    SEARCH_BACKEND_SQLITE,
})

_CACHED_SEARCH_INDEX: Optional[SearchIndex] = None
_search_indexes: Dict[str, SearchIndex] = {}


def is_spector_reachable(url: str, timeout: float = 0.5) -> bool:
    """Non-blocking socket check to verify if the Spector service is reachable."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (OSError, socket.error, socket.timeout):
        return False


def create_search_index(
    settings: Optional[Settings] = None,
    backend: Optional[str] = None,
    spector_url: Optional[str] = None,
    fallback_to_sqlite: Optional[bool] = None,
    db_path: Optional[Union[str, Path]] = None,
    client: Optional[Any] = None,
) -> SearchIndex:
    """Creates a new SearchIndex adapter based on reachability and configuration.

    Resolution Priority:
    1. Explicit `backend` argument.
    2. Environment variable `CAREFOLD_SEARCH_BACKEND`.
    3. Auto-detection: If Spector is configured and reachable via socket check, selects 'spector'.
       Otherwise transparently falls back to 'sqlite'.
    """
    cfg = settings or global_settings

    raw_backend = backend or os.getenv("CAREFOLD_SEARCH_BACKEND")
    selected_backend: Optional[str] = raw_backend.lower().strip() if raw_backend else None

    target_url = (spector_url or getattr(cfg, "spector_url", "http://localhost:7070")).rstrip("/")
    fallback_enabled = fallback_to_sqlite if fallback_to_sqlite is not None else True

    # Auto-detection when not explicitly set
    if not selected_backend:
        if is_spector_reachable(target_url, timeout=0.5):
            selected_backend = SEARCH_BACKEND_SPECTOR
            logger.info("Spector service detected at %s. Selecting SpectorSearchIndex.", target_url)
        else:
            selected_backend = SEARCH_BACKEND_SQLITE
            logger.info("Spector service unreachable at %s. Falling back to SqliteSearchIndex.", target_url)

    if selected_backend not in SUPPORTED_SEARCH_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_SEARCH_BACKENDS))
        raise ValueError(
            f"Unsupported search backend: '{selected_backend}'. Supported backends: {supported}."
        )

    if selected_backend == SEARCH_BACKEND_SPECTOR:
        from carefold.search.adapters.spector import SpectorSearchIndex
        return SpectorSearchIndex(
            base_url=target_url,
            fallback_to_sqlite=fallback_enabled,
            client=client,
        )
    else:  # sqlite
        from carefold.search.adapters.sqlite import SqliteSearchIndex
        resolved_db_path = db_path
        if resolved_db_path is None:
            if hasattr(cfg, "get_catalog_db_path"):
                resolved_db_path = cfg.get_catalog_db_path()
            elif hasattr(cfg, "workspace_root"):
                resolved_db_path = cfg.workspace_root / "catalog.db"
            else:
                resolved_db_path = Path("catalog.db")
        return SqliteSearchIndex(db_path=resolved_db_path)


def get_search_index(
    settings: Optional[Settings] = None,
    use_spector: Optional[bool] = None,
    spector_client: Optional[Any] = None,
    backend: Optional[str] = None,
) -> SearchIndex:
    """Returns singleton SearchIndex instance with caching and lifecycle management."""
    global _CACHED_SEARCH_INDEX, _search_indexes

    # Direct resolution override for test doubles
    if use_spector is True or spector_client is not None:
        from carefold.search.adapters.spector import SpectorSearchIndex
        return SpectorSearchIndex(client=spector_client, fallback_to_sqlite=True)
    if use_spector is False:
        from carefold.search.adapters.sqlite import SqliteSearchIndex
        return SqliteSearchIndex()

    if backend is not None:
        return create_search_index(settings=settings, backend=backend)

    if settings is None:
        if _CACHED_SEARCH_INDEX is None:
            _CACHED_SEARCH_INDEX = create_search_index()
            _search_indexes[_CACHED_SEARCH_INDEX.__class__.__name__] = _CACHED_SEARCH_INDEX
        return _CACHED_SEARCH_INDEX

    target_backend = (os.getenv("CAREFOLD_SEARCH_BACKEND") or "").lower().strip()
    if _CACHED_SEARCH_INDEX is not None:
        is_spector = _CACHED_SEARCH_INDEX.__class__.__name__ == "SpectorSearchIndex"
        if target_backend == SEARCH_BACKEND_SPECTOR and is_spector:
            return _CACHED_SEARCH_INDEX
        if target_backend == SEARCH_BACKEND_SQLITE and not is_spector:
            return _CACHED_SEARCH_INDEX
        if not target_backend:
            return _CACHED_SEARCH_INDEX

    index = create_search_index(settings=settings)
    _CACHED_SEARCH_INDEX = index
    _search_indexes[index.__class__.__name__] = index
    return index


def reset_search_indexes() -> None:
    """Closes all cached search indexes and resets singleton state for test teardown."""
    global _CACHED_SEARCH_INDEX, _search_indexes
    indexes_to_close = list(_search_indexes.values())
    if _CACHED_SEARCH_INDEX and _CACHED_SEARCH_INDEX not in indexes_to_close:
        indexes_to_close.append(_CACHED_SEARCH_INDEX)

    for idx in indexes_to_close:
        if hasattr(idx, "close"):
            try:
                res = idx.close()
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        try:
                            asyncio.run(res)
                        except Exception:
                            pass
            except Exception:
                pass

    _CACHED_SEARCH_INDEX = None
    _search_indexes.clear()


def set_search_index(index: Optional[SearchIndex]) -> None:
    """Injects a custom SearchIndex or mock test double into the singleton slot."""
    global _CACHED_SEARCH_INDEX, _search_indexes
    _CACHED_SEARCH_INDEX = index
    _search_indexes.clear()
    if index is not None:
        _search_indexes[index.__class__.__name__] = index


reset_search_index = reset_search_indexes

__all__ = [
    "create_search_index",
    "get_search_index",
    "reset_search_indexes",
    "reset_search_index",
    "set_search_index",
    "is_spector_reachable",
    "SEARCH_BACKEND_SPECTOR",
    "SEARCH_BACKEND_SQLITE",
    "SUPPORTED_SEARCH_BACKENDS",
]
