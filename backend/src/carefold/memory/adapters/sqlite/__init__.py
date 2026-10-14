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

"""SQLite adapter package implementing MemoryPort and CatalogPort."""

from __future__ import annotations

from carefold.memory.adapters.sqlite.catalog_adapter import (
    CANONICAL_DOMAINS,
    SqliteCatalogAdapter,
    build_category_tree_from_rows,
    sanitize_fts_query,
)
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter

__all__ = [
    "SqliteMemoryAdapter",
    "SqliteCatalogAdapter",
    "sanitize_fts_query",
    "build_category_tree_from_rows",
    "CANONICAL_DOMAINS",
]
