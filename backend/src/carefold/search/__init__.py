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

"""Hexagonal cognitive search subsystem for Carefold: ports, chunkers, adapters, and factory."""

from __future__ import annotations

from carefold.search.adapters.spector import SpectorSearchIndex
from carefold.search.adapters.sqlite import SqliteSearchIndex
from carefold.search.base import SearchIndex, SearchResult
from carefold.search.chunker import ClinicalChunk, ClinicalChunker
from carefold.search.factory import (
    SEARCH_BACKEND_SPECTOR,
    SEARCH_BACKEND_SQLITE,
    SUPPORTED_SEARCH_BACKENDS,
    create_search_index,
    get_search_index,
    is_spector_reachable,
    reset_search_index,
    reset_search_indexes,
    set_search_index,
)

__all__ = [
    "ClinicalChunk",
    "ClinicalChunker",
    "SEARCH_BACKEND_SPECTOR",
    "SEARCH_BACKEND_SQLITE",
    "SUPPORTED_SEARCH_BACKENDS",
    "SearchIndex",
    "SearchResult",
    "SpectorSearchIndex",
    "SqliteSearchIndex",
    "create_search_index",
    "get_search_index",
    "is_spector_reachable",
    "reset_search_index",
    "reset_search_indexes",
    "set_search_index",
]
