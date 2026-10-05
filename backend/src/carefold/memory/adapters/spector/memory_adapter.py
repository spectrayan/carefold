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

"""Spector cognitive memory adapter implementing Carefold MemoryPort interface.

Bridges Carefold hexagonal memory ports with LangGraph BaseStore, delegating operations
to SpectorStore (and through it to Spector Synapse or local fallback).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from langgraph.store.base import BaseStore, Item, SearchItem

from carefold.memory.ports.memory_port import MemoryPort, MemoryTier

if TYPE_CHECKING:
    from carefold.memory.adapters.spector.store import SpectorStore

logger = logging.getLogger(__name__)


class SpectorMemoryAdapter(MemoryPort):
    """Hexagonal memory adapter backed by Spector Cognitive Memory and LangGraph BaseStore.

    Implements MemoryPort (remember, recall, forget, reinforce, close) by delegating
    to an underlying SpectorStore instance. Exposes the `.store` property so the LangGraph
    compiler can natively bind the store to graph nodes.
    """

    def __init__(
        self,
        store: Optional[SpectorStore] = None,
        base_url: Optional[str] = None,
        fallback_to_sqlite: bool = True,
        timeout: float = 5.0,
        client: Optional[Any] = None,
        fallback_db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        """Initializes SpectorMemoryAdapter.

        Args:
            store: Optional pre-configured SpectorStore instance. If None, instantiates
                   a new SpectorStore using base_url and configuration parameters.
            base_url: Base URL of the Spector service (defaults to http://localhost:7070).
            fallback_to_sqlite: Whether to fall back to local storage when Spector is unreachable.
            timeout: Network timeout in seconds for Spector requests.
            client: Optional pre-configured client or test double.
            fallback_db_path: Optional path to SQLite fallback database.
        """
        if store is not None:
            self._store: BaseStore = store
        else:
            from carefold.memory.adapters.spector.store import SpectorStore
            self._store = SpectorStore(
                base_url=base_url or "http://localhost:7070",
                fallback_to_sqlite=fallback_to_sqlite,
                timeout=timeout,
                client=client,
                fallback_db_path=fallback_db_path,
            )
        self._lock = asyncio.Lock()

    @property
    def store(self) -> BaseStore:
        """Returns the underlying LangGraph BaseStore instance for engine compilation."""
        return self._store

    @property
    def fallback_to_sqlite(self) -> bool:
        """Returns True if the underlying store has fallback enabled."""
        return getattr(self._store, "fallback_to_sqlite", True)

    @property
    def is_degraded(self) -> bool:
        """Returns True if the underlying store is in degraded fallback state."""
        return getattr(self._store, "_is_degraded", False)

    @property
    def fallback_active(self) -> bool:
        """Returns True if fallback storage is actively serving requests."""
        return self.is_degraded

    async def remember(
        self,
        key: str,
        value: Any,
        tier: MemoryTier,
        namespace: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Stores or updates a memory record in the specified namespace and tier.

        Preserves exact payload type fidelity (dict, str, int, bool, float, list).
        Constructs an indexed text representation for cognitive embeddings while
        persisting full metadata and provenance attributes.

        Args:
            key: Unique identifier for the memory within the namespace.
            value: Memory payload.
            tier: Cognitive memory tier (WORKING, EPISODIC, SEMANTIC, PROCEDURAL).
            namespace: Isolation namespace (default 'default').
            metadata: Optional dictionary of attributes, tags, or provenance.
        """
        if not key or not str(key).strip():
            raise ValueError("Memory key must not be empty.")

        tier_val = tier.value if isinstance(tier, MemoryTier) else str(tier)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Build natural language text representation for cognitive indexing
        if isinstance(value, str):
            text_rep = f"{key}: {value}"
        elif isinstance(value, (dict, list)):
            try:
                text_rep = f"{key}: {json.dumps(value)}"
            except (TypeError, ValueError):
                text_rep = f"{key}: {value}"
        else:
            text_rep = f"{key}: {value}"

        # Construct structured payload preserving exact data types
        payload: Dict[str, Any] = {
            "key": key,
            "value": value,
            "tier": tier_val,
            "namespace": namespace,
            "metadata": metadata or {},
            "text": text_rep,
            "salience": 1.0,
            "access_count": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
            "last_accessed_at": None,
        }

        # Store via underlying BaseStore.aput into namespace tuple (namespace,)
        await self._store.aput(
            namespace=(namespace,),
            key=key,
            value=payload,
        )

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
                   retrieves recent or salient memories.
            tier: Optional tier filter. If None, searches across all tiers.
            namespace: Isolation namespace.
            limit: Maximum number of records to return (defaults to 10).

        Returns:
            List of memory record dictionaries ordered by relevance/salience descending.
        """
        clean_query = query.strip() if query and query.strip() else None
        tier_filter = (
            tier.value.lower()
            if isinstance(tier, MemoryTier)
            else (str(tier).lower() if tier else None)
        )

        filter_dict: Optional[Dict[str, Any]] = {"tier": tier_filter} if tier_filter else None

        # Execute search across namespace prefix via BaseStore.asearch
        items = await self._store.asearch(
            (namespace,),
            query=clean_query,
            filter=filter_dict,
            limit=limit,
        )

        results: List[Dict[str, Any]] = []
        for item in items:
            record = self._unpack_record(item, fallback_namespace=namespace)
            if tier_filter and str(record.get("tier", "")).lower() != tier_filter:
                continue
            results.append(record)

        # When query is empty, sort by salience DESC and updated_at DESC
        if not clean_query:
            results.sort(
                key=lambda r: (r.get("salience", 1.0), r.get("updated_at", "")),
                reverse=True,
            )

        return results[:limit]

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
        existing = await self._store.aget(namespace=(namespace,), key=key)
        if existing is None:
            return False

        await self._store.adelete(namespace=(namespace,), key=key)
        return True

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
            delta: Salience change delta (positive to boost, negative to decay).

        Raises:
            ValueError: If delta is not a finite float (NaN, +Inf, -Inf).
        """
        if not math.isfinite(delta):
            raise ValueError(f"delta must be a finite float, got: {delta}")

        async with self._lock:
            # Retrieve current item from store
            item = await self._store.aget(namespace=(namespace,), key=key)
            if item is not None and isinstance(item.value, dict):
                payload = dict(item.value)
                current_salience = float(payload.get("salience", 1.0))
                new_salience = max(0.0, current_salience + delta)
                payload["salience"] = new_salience
                payload["access_count"] = int(payload.get("access_count", 0)) + 1
                payload["last_accessed_at"] = datetime.now(timezone.utc).isoformat()
                await self._store.aput(namespace=item.namespace, key=item.key, value=payload)

        # Notify underlying store / client if custom reinforcement method is supported
        mem_id = f"{namespace}:{key}"
        valence = int(delta * 10) if int(delta * 10) != 0 else (1 if delta >= 0 else -1)
        if (
            not getattr(self._store, "_is_degraded", False)
            and hasattr(self._store, "_async_memory")
            and hasattr(self._store._async_memory, "reinforce")
        ):
            try:
                res = self._store._async_memory.reinforce(mem_id, valence=valence)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.debug("Spector memory reinforce notification failed: %s", exc)

    async def get(
        self,
        key: str,
        namespace: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """Retrieves a single memory record by key and namespace.

        Args:
            key: Memory key to look up.
            namespace: Isolation namespace.

        Returns:
            Dictionary matching MemoryPort return structure, or None if not found.
        """
        item = await self._store.aget(namespace=(namespace,), key=key)
        if item is None:
            return None
        return self._unpack_record(item, fallback_namespace=namespace)

    async def close(self) -> None:
        """Closes underlying store and client resources."""
        if hasattr(self._store, "aclose"):
            await self._store.aclose()
        elif hasattr(self._store, "close"):
            res = self._store.close()
            if asyncio.iscoroutine(res):
                await res

    def close_sync(self) -> None:
        """Synchronously closes underlying store and client resources."""
        if hasattr(self._store, "close"):
            res = self._store.close()
            if asyncio.iscoroutine(res):
                try:
                    asyncio.run(res)
                except Exception:
                    pass

    async def __aenter__(self) -> SpectorMemoryAdapter:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def _unpack_record(
        self,
        item: Union[Item, SearchItem],
        fallback_namespace: str = "default",
    ) -> Dict[str, Any]:
        """Unpacks a LangGraph Item or SearchItem into the canonical MemoryPort dictionary."""
        val_data = item.value if isinstance(item.value, dict) else {}

        # Unpack stored value while maintaining exact payload type fidelity
        if "value" in val_data and ("key" in val_data or "tier" in val_data):
            raw_value = val_data["value"]
            tier_val = val_data.get("tier", MemoryTier.SEMANTIC.value)
            metadata = val_data.get("metadata", {})
            salience = float(val_data.get("salience", 1.0))
            access_count = int(val_data.get("access_count", 0))
            last_accessed_at = val_data.get("last_accessed_at")
        else:
            # Item was written directly via store.aput
            raw_value = val_data
            tier_val = MemoryTier.SEMANTIC.value
            metadata = {}
            salience = 1.0
            access_count = 0
            last_accessed_at = None

        created_str = (
            item.created_at.isoformat()
            if hasattr(item.created_at, "isoformat")
            else str(item.created_at or datetime.now(timezone.utc).isoformat())
        )
        updated_str = (
            item.updated_at.isoformat()
            if hasattr(item.updated_at, "isoformat")
            else str(item.updated_at or datetime.now(timezone.utc).isoformat())
        )

        ns_str = (
            ":".join(item.namespace)
            if isinstance(item.namespace, tuple) and item.namespace
            else (str(item.namespace) if item.namespace else fallback_namespace)
        )

        score_val = getattr(item, "score", None)
        score = float(score_val) if score_val is not None else 1.0

        return {
            "key": item.key,
            "value": raw_value,
            "tier": tier_val,
            "namespace": ns_str,
            "metadata": metadata,
            "salience": salience,
            "access_count": access_count,
            "created_at": created_str,
            "updated_at": updated_str,
            "last_accessed_at": last_accessed_at,
            "score": score,
        }


__all__ = ["SpectorMemoryAdapter"]
