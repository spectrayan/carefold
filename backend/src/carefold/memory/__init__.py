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

"""Hexagonal memory and catalog architecture for Carefold.

Exports port interfaces (MemoryPort, CatalogPort, MemoryTier), concrete SQLite adapters
(SqliteMemoryAdapter, SqliteCatalogAdapter), and dynamic factory functions for cognitive
agent memory and catalog indexing.
"""

from carefold.memory.adapters.spector import (
    SpectorMemoryAdapter,
    SpectorStore,
)
from carefold.memory.adapters.sqlite import (
    SqliteCatalogAdapter,
    SqliteMemoryAdapter,
)
from carefold.memory.factory import (
    create_catalog_port,
    create_memory_port,
    get_catalog_port,
    get_memory_port,
    reset_memory_ports,
    set_catalog_port,
    set_memory_port,
)
from carefold.memory.ports import (
    CatalogPort,
    MemoryPort,
    MemoryTier,
)

__all__ = [
    "CatalogPort",
    "MemoryPort",
    "MemoryTier",
    "SqliteCatalogAdapter",
    "SqliteMemoryAdapter",
    "SpectorMemoryAdapter",
    "SpectorStore",
    "create_catalog_port",
    "create_memory_port",
    "get_catalog_port",
    "get_memory_port",
    "reset_memory_ports",
    "set_catalog_port",
    "set_memory_port",
]
