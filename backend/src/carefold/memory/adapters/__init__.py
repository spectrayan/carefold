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

"""Memory and Catalog storage adapters."""

from __future__ import annotations

from carefold.memory.adapters.spector import (
    SpectorMemoryAdapter,
    SpectorStore,
)
from carefold.memory.adapters.sqlite import (
    SqliteCatalogAdapter,
    SqliteMemoryAdapter,
    sanitize_fts_query,
)

__all__ = [
    "SqliteMemoryAdapter",
    "SqliteCatalogAdapter",
    "sanitize_fts_query",
    "SpectorMemoryAdapter",
    "SpectorStore",
]
