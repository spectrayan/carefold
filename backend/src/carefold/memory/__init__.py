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
