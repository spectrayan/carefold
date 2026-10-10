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

"""Pluggable adapter factory for MemoryPort and CatalogPort."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional, Union

from carefold.config import Settings, settings as global_settings
from carefold.memory.ports.catalog_port import CatalogPort
from carefold.memory.ports.memory_port import MemoryPort

logger = logging.getLogger(__name__)

MEMORY_BACKEND_SQLITE: str = "sqlite"
MEMORY_BACKEND_SPECTOR: str = "spector"
MEMORY_BACKEND_POSTGRES: str = "postgres"

SUPPORTED_MEMORY_BACKENDS = frozenset({
    MEMORY_BACKEND_SQLITE,
    MEMORY_BACKEND_SPECTOR,
    MEMORY_BACKEND_POSTGRES,
})

_CACHED_MEMORY_PORT: Optional[MemoryPort] = None
_CACHED_CATALOG_PORT: Optional[CatalogPort] = None
_memory_ports: Dict[str, MemoryPort] = {}


def create_memory_port(
    settings: Optional[Settings] = None,
    backend: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
    spector_url: Optional[str] = None,
    fallback_to_sqlite: Optional[bool] = None,
) -> MemoryPort:
    """Instantiates a new MemoryPort adapter based on configured backend.
    
    Args:
        settings: Optional Settings instance. Defaults to global settings.
        backend: Optional backend override ('sqlite', 'spector', 'postgres').
        db_path: Optional database path override for SQLite adapter.
        spector_url: Optional Spector service URL override.
        fallback_to_sqlite: Optional fallback toggle override for Spector adapter.
        
    Returns:
        Instance implementing MemoryPort.
        
    Raises:
        NotImplementedError: If requested backend is 'postgres'.
        ValueError: If requested backend is unrecognized.
    """
    cfg = settings or global_settings
    raw_backend = cfg.memory_backend if backend is None else backend
    selected_backend = (raw_backend or "").lower().strip()
    if not selected_backend or selected_backend not in SUPPORTED_MEMORY_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_MEMORY_BACKENDS))
        raise ValueError(
            f"Unsupported memory backend: '{raw_backend}'. Supported backends: {supported}."
        )

    if selected_backend == MEMORY_BACKEND_SQLITE:
        from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
        resolved_db_path = db_path or cfg.get_catalog_db_path()
        return SqliteMemoryAdapter(db_path=resolved_db_path)

    elif selected_backend == MEMORY_BACKEND_SPECTOR:
        from carefold.memory.adapters.spector.memory_adapter import SpectorMemoryAdapter
        url = spector_url or cfg.spector_url
        fallback_enabled = (
            fallback_to_sqlite
            if fallback_to_sqlite is not None
            else getattr(cfg, "memory_fallback_to_sqlite", True)
        )
        fallback_db = db_path or cfg.get_catalog_db_path()
        return SpectorMemoryAdapter(
            base_url=url,
            fallback_to_sqlite=fallback_enabled,
            fallback_db_path=fallback_db,
        )

    elif selected_backend == MEMORY_BACKEND_POSTGRES:
        raise NotImplementedError(
            "Backend 'postgres' is not yet implemented. "
            "PostgreSQL memory adapter is not yet implemented. Set CAREFOLD_MEMORY_BACKEND='sqlite'."
        )

    else:
        supported = ", ".join(sorted(SUPPORTED_MEMORY_BACKENDS))
        raise ValueError(
            f"Unsupported memory backend: '{selected_backend}'. Supported backends: {supported}."
        )


def create_catalog_port(
    settings: Optional[Settings] = None,
    backend: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
    spector_url: Optional[str] = None,
) -> CatalogPort:
    """Instantiates a new CatalogPort adapter based on configured backend.
    
    Args:
        settings: Optional Settings instance. Defaults to global settings.
        backend: Optional backend override ('sqlite', 'spector', 'postgres').
        db_path: Optional database path override for SQLite adapter.
        spector_url: Optional Spector service URL override.
        
    Returns:
        Instance implementing CatalogPort.
        
    Raises:
        NotImplementedError: If requested backend is 'spector' or 'postgres'.
        ValueError: If requested backend is unrecognized.
    """
    cfg = settings or global_settings
    raw_backend = cfg.memory_backend if backend is None else backend
    selected_backend = (raw_backend or "").lower().strip()
    if not selected_backend or selected_backend not in SUPPORTED_MEMORY_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_MEMORY_BACKENDS))
        raise ValueError(
            f"Unsupported catalog backend: '{raw_backend}'. Supported backends: {supported}."
        )

    if selected_backend == MEMORY_BACKEND_SQLITE:
        from carefold.memory.adapters.sqlite.catalog_adapter import SqliteCatalogAdapter
        resolved_db_path = db_path or cfg.get_catalog_db_path()
        return SqliteCatalogAdapter(db_path=resolved_db_path)

    elif selected_backend == MEMORY_BACKEND_SPECTOR:
        url = spector_url or cfg.spector_url
        raise NotImplementedError(
            f"Backend 'spector' is not yet implemented (configured URL: '{url}'). "
            "Spector catalog adapter is not yet implemented. Set CAREFOLD_MEMORY_BACKEND='sqlite'."
        )

    elif selected_backend == MEMORY_BACKEND_POSTGRES:
        raise NotImplementedError(
            "Backend 'postgres' is not yet implemented. "
            "PostgreSQL catalog adapter is not yet implemented. Set CAREFOLD_MEMORY_BACKEND='sqlite'."
        )

    else:
        supported = ", ".join(sorted(SUPPORTED_MEMORY_BACKENDS))
        raise ValueError(
            f"Unsupported catalog backend: '{selected_backend}'. Supported backends: {supported}."
        )


def get_memory_port(settings: Optional[Settings] = None) -> MemoryPort:
    """Provides a singleton/shared MemoryPort instance for the runtime.
    
    If settings is provided and cached singleton is None, configures the singleton.
    Preserves singleton caching for both SQLite and Spector backends.
    """
    global _CACHED_MEMORY_PORT, _memory_ports
    if settings is None:
        if _CACHED_MEMORY_PORT is None:
            _CACHED_MEMORY_PORT = create_memory_port()
            backend = (global_settings.memory_backend or MEMORY_BACKEND_SQLITE).lower().strip()
            _memory_ports[backend] = _CACHED_MEMORY_PORT
        return _CACHED_MEMORY_PORT

    target_backend = (settings.memory_backend or MEMORY_BACKEND_SQLITE).lower().strip()
    if target_backend in _memory_ports:
        _CACHED_MEMORY_PORT = _memory_ports[target_backend]
        return _CACHED_MEMORY_PORT

    if _CACHED_MEMORY_PORT is not None:
        is_spector = _CACHED_MEMORY_PORT.__class__.__name__ == "SpectorMemoryAdapter"
        if target_backend == MEMORY_BACKEND_SPECTOR and is_spector:
            _memory_ports[MEMORY_BACKEND_SPECTOR] = _CACHED_MEMORY_PORT
            return _CACHED_MEMORY_PORT
        if target_backend == MEMORY_BACKEND_SQLITE and not is_spector:
            _memory_ports[MEMORY_BACKEND_SQLITE] = _CACHED_MEMORY_PORT
            return _CACHED_MEMORY_PORT

    port = create_memory_port(settings=settings)
    _CACHED_MEMORY_PORT = port
    _memory_ports[target_backend] = port
    return port


def get_catalog_port(settings: Optional[Settings] = None) -> CatalogPort:
    """Provides a singleton/shared CatalogPort instance for the runtime.
    
    If settings is provided and cached singleton is None, configures the singleton.
    If cached singleton already exists and settings specifies a different backend,
    creates and returns an adapter for those settings.
    """
    global _CACHED_CATALOG_PORT
    if settings is not None:
        if _CACHED_CATALOG_PORT is None:
            _CACHED_CATALOG_PORT = create_catalog_port(settings=settings)
            return _CACHED_CATALOG_PORT
        if settings.memory_backend != MEMORY_BACKEND_SQLITE:
            return create_catalog_port(settings=settings)
    if _CACHED_CATALOG_PORT is None:
        _CACHED_CATALOG_PORT = create_catalog_port()
    return _CACHED_CATALOG_PORT


def reset_memory_ports() -> None:
    """Resets cached adapter singletons for test cleanup."""
    global _CACHED_MEMORY_PORT, _CACHED_CATALOG_PORT, _memory_ports
    ports_to_close = list(_memory_ports.values())
    if _CACHED_MEMORY_PORT and _CACHED_MEMORY_PORT not in ports_to_close:
        ports_to_close.append(_CACHED_MEMORY_PORT)
    for p in ports_to_close:
        try:
            if hasattr(p, "_conn") and getattr(p, "_conn") is not None:
                p._conn.stop()
            elif hasattr(p, "close"):
                res = p.close()
                if hasattr(res, "__await__"):
                    import asyncio
                    try:
                        asyncio.run(res)
                    except Exception:
                        pass
        except Exception:
            pass
    _CACHED_MEMORY_PORT = None
    _CACHED_CATALOG_PORT = None
    _memory_ports.clear()


def set_memory_port(port: Optional[MemoryPort]) -> None:
    """Explicitly sets or overrides the cached MemoryPort singleton."""
    global _CACHED_MEMORY_PORT, _memory_ports
    _CACHED_MEMORY_PORT = port
    _memory_ports.clear()
    if port is not None:
        backend_key = "spector" if port.__class__.__name__ == "SpectorMemoryAdapter" else "sqlite"
        _memory_ports[backend_key] = port


def set_catalog_port(port: Optional[CatalogPort]) -> None:
    """Explicitly sets or overrides the cached CatalogPort singleton."""
    global _CACHED_CATALOG_PORT
    _CACHED_CATALOG_PORT = port


reset_memory_port = reset_memory_ports
