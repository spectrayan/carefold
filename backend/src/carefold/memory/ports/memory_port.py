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

"""MemoryPort interface and MemoryTier enumeration for hexagonal cognitive memory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional


class MemoryTier(str, Enum):
    """Cognitive tiers for hierarchical agent memory.
    
    Tiers categorize memories based on temporal longevity, mutability, and cognitive role:
    - WORKING: Ephemeral scratchpad, active task execution state, and session context.
    - EPISODIC: Autobiographical turn interactions, event logs, chronological history with timestamps.
    - SEMANTIC: Consolidated factual healthcare knowledge, patient profile, preferences, extracted concepts.
    - PROCEDURAL: Clinical guidelines, step-by-step SOP execution rules, protocols, skill action steps.
    """

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryPort(ABC):
    """Abstract port interface for cognitive memory operations across agent tiers.
    
    Provides isolation across namespaces (e.g., agent ID, user ID, session ID)
    and supports salience reinforcement/decay and multi-tier cognitive recall.
    """

    @abstractmethod
    async def remember(
        self,
        key: str,
        value: Any,
        tier: MemoryTier,
        namespace: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Stores or updates a memory record in the specified namespace and tier.
        
        Args:
            key: Unique identifier for the memory within the namespace.
            value: Memory payload (string, dict, or serializable structure).
            tier: Cognitive memory tier (WORKING, EPISODIC, SEMANTIC, PROCEDURAL).
            namespace: Isolation namespace (e.g. 'agent:visit-steward', 'user:patient_1').
            metadata: Optional dictionary of attributes, tags, or provenance.
        """
        ...

    @abstractmethod
    async def recall(
        self,
        query: str,
        tier: Optional[MemoryTier] = None,
        namespace: str = "default",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Recalls memory records relevant to the query in the namespace.
        
        Args:
            query: Natural language query string or search keywords. If empty,
                   retrieves recent/salient memories.
            tier: Optional tier filter. If None, searches across all tiers in the namespace.
            namespace: Isolation namespace.
            limit: Maximum number of records to return (defaults to 10).
            
        Returns:
            List of memory record dictionaries ordered by relevance/salience descending.
            Each dictionary contains: 'key', 'value', 'tier', 'namespace', 'metadata',
            'salience', 'created_at', 'updated_at', and optionally 'score'.
        """
        ...

    @abstractmethod
    async def forget(
        self,
        key: str,
        namespace: str = "default",
    ) -> bool:
        """Deletes a memory record identified by key in the specified namespace.
        
        Args:
            key: Memory key to delete.
            namespace: Isolation namespace.
            
        Returns:
            True if the record existed and was deleted, False otherwise.
        """
        ...

    @abstractmethod
    async def reinforce(
        self,
        key: str,
        namespace: str = "default",
        delta: float = 0.1,
    ) -> None:
        """Adjusts the salience / retrieval weight of a memory record.
        
        Args:
            key: Memory key to reinforce.
            namespace: Isolation namespace.
            delta: Salience change delta (positive to boost, negative to decay; defaults to 0.1).
        """
        ...

    @abstractmethod
    async def get(
        self,
        key: str,
        namespace: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """Retrieves a single memory record by key in the specified namespace.
        
        Args:
            key: Memory key to retrieve.
            namespace: Isolation namespace.
            
        Returns:
            Dictionary of memory record if found, None otherwise.
        """
        ...

    @abstractmethod
    async def forget_all(
        self,
        namespace: str = "default",
    ) -> int:
        """Deletes all memory records within the specified namespace.
        
        Args:
            namespace: Isolation namespace.
            
        Returns:
            Number of deleted memory records.
        """
        ...

    async def close(self) -> None:
        """Closes any underlying resources (database connections, network sessions).
        
        Default implementation is a no-op; adapters override if cleanup is needed.
        """
        pass


__all__ = [
    "MemoryPort",
    "MemoryTier",
]
