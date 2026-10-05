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

"""Comprehensive unit test suite for SpectorStore and SpectorMemoryAdapter."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    MatchCondition,
    PutOp,
    SearchItem,
    SearchOp,
)

from carefold.config import Settings
from carefold.memory.adapters.spector.memory_adapter import SpectorMemoryAdapter
from carefold.memory.adapters.spector.store import SpectorStore
from carefold.memory.factory import (
    create_memory_port,
    get_memory_port,
    reset_memory_ports,
)
from carefold.memory.ports.memory_port import MemoryPort, MemoryTier
from spector_client.exceptions import MemoryNotFoundError, TransportError
from spector_client.models import MemoryRecord, MemoryTier as SpectorTier, RecallRecord


class SimulatedAsyncMemoryClient:
    """Deterministic in-memory test double of AsyncMemoryClient for hermetic CI testing."""

    def __init__(self) -> None:
        self.records: Dict[str, MemoryRecord] = {}
        self.closed: bool = False
        self.reinforce_calls: List[Dict[str, Any]] = []

    async def remember(
        self,
        text: str,
        tier: Any = SpectorTier.SEMANTIC,
        tags: Optional[List[str]] = None,
        interest: float = 0.0,
        urgency: float = 0.0,
        challenge: float = 0.0,
        valence: int = 0,
        arousal: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        meta = metadata or {}
        key = meta.get("key", "default_key")
        ns = meta.get("namespace", "default")
        if isinstance(ns, list):
            ns_str = ":".join(ns)
        else:
            ns_str = str(ns)
        memory_id = meta.get("_id") or meta.get("id") or (f"{ns_str}:{key}" if ns_str else key)

        now_str = datetime.now(timezone.utc).isoformat()
        tier_enum = SpectorTier(tier) if isinstance(tier, str) else tier

        rec = MemoryRecord(
            id=memory_id,
            text=text,
            tier=tier_enum,
            tags=tags or [],
            valence=valence,
            arousal=arousal,
            metadata=meta,
            created_at=meta.get("created_at", now_str),
            updated_at=meta.get("updated_at", now_str),
        )
        self.records[memory_id] = rec
        return {"id": memory_id, "status": "stored"}

    async def get(self, memory_id: str) -> MemoryRecord:
        if memory_id not in self.records:
            raise MemoryNotFoundError(f"Memory {memory_id} not found")
        return self.records[memory_id]

    async def find(self, memory_id: str) -> Optional[MemoryRecord]:
        return self.records.get(memory_id)

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[RecallRecord]:
        results: List[RecallRecord] = []
        for mem_id, rec in self.records.items():
            if rec.tombstoned:
                continue
            if tags and not any(t in rec.tags for t in tags):
                continue
            score = 1.0 if not query or query.lower() in rec.text.lower() else 0.1
            results.append(
                RecallRecord(
                    id=rec.id,
                    text=rec.text,
                    score=score,
                    tier=rec.tier,
                    tags=rec.tags,
                    metadata=rec.metadata,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    async def forget(self, memory_id: str, reason: Optional[str] = None) -> None:
        self.records.pop(memory_id, None)

    async def reinforce(self, memory_id: str, valence: int = 1) -> None:
        self.reinforce_calls.append({"id": memory_id, "valence": valence})

    async def status(self) -> Dict[str, Any]:
        return {"status": "ok", "total_records": len(self.records)}

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def simulated_client() -> SimulatedAsyncMemoryClient:
    """Fixture providing a fresh simulated in-memory Spector client."""
    return SimulatedAsyncMemoryClient()


@pytest.fixture
def spector_store(simulated_client: SimulatedAsyncMemoryClient) -> SpectorStore:
    """Fixture providing a SpectorStore wired to the simulated client."""
    return SpectorStore(client=simulated_client)


@pytest.fixture
def spector_adapter(simulated_client: SimulatedAsyncMemoryClient) -> SpectorMemoryAdapter:
    """Fixture providing a SpectorMemoryAdapter wired to the simulated client."""
    return SpectorMemoryAdapter(client=simulated_client)


# ==============================================================================
# 1. Tests for SpectorStore (LangGraph BaseStore Contract)
# ==============================================================================

class TestSpectorStoreContract:
    """Verifies that SpectorStore conforms to LangGraph BaseStore specifications."""

    def test_spector_store_inheritance(self, spector_store: SpectorStore) -> None:
        """Confirms that SpectorStore is a subclass and instance of BaseStore."""
        assert isinstance(spector_store, BaseStore)
        assert issubclass(SpectorStore, BaseStore)

    @pytest.mark.asyncio
    async def test_abatch_put_and_get(self, spector_store: SpectorStore) -> None:
        """Verifies abatch with PutOp and subsequent GetOp returns matching Item."""
        namespace = ("memories", "thread_1")
        key = "turn_1"
        value = {"text": "Patient has mild chest pain on exertion", "speaker": "patient"}

        put_results = await spector_store.abatch([PutOp(namespace, key, value)])
        assert len(put_results) == 1
        assert put_results[0] is None

        get_results = await spector_store.abatch([GetOp(namespace, key)])
        assert len(get_results) == 1
        item = get_results[0]
        assert isinstance(item, Item)
        assert item.key == key
        assert item.namespace == namespace
        assert item.value == value
        assert isinstance(item.created_at, datetime)
        assert isinstance(item.updated_at, datetime)

    @pytest.mark.asyncio
    async def test_abatch_search(self, spector_store: SpectorStore) -> None:
        """Verifies abatch with SearchOp returns correctly populated SearchItem list."""
        namespace = ("memories", "thread_2")
        await spector_store.abatch([
            PutOp(namespace, "turn_1", {"text": "Cardiology consult requested"}),
            PutOp(namespace, "turn_2", {"text": "Prescribed atorvastatin 20mg"}),
        ])

        search_results = await spector_store.abatch([
            SearchOp(namespace_prefix=namespace, query="atorvastatin", limit=5)
        ])
        assert len(search_results) == 1
        items = search_results[0]
        assert isinstance(items, list)
        assert len(items) >= 1
        search_item = items[0]
        assert isinstance(search_item, SearchItem)
        assert search_item.key == "turn_2"
        assert search_item.namespace == namespace
        assert "atorvastatin" in str(search_item.value)
        assert search_item.score is not None

    @pytest.mark.asyncio
    async def test_abatch_put_none_deletes_item(self, spector_store: SpectorStore) -> None:
        """Verifies abatch with PutOp(value=None) removes item from store."""
        namespace = ("notes", "patient_101")
        key = "scratchpad"
        await spector_store.abatch([PutOp(namespace, key, {"text": "Temporary note"})])

        items = await spector_store.abatch([GetOp(namespace, key)])
        assert items[0] is not None

        del_results = await spector_store.abatch([PutOp(namespace, key, None)])
        assert del_results[0] is None

        items_after = await spector_store.abatch([GetOp(namespace, key)])
        assert items_after[0] is None

    @pytest.mark.asyncio
    async def test_abatch_missing_key_returns_none(self, spector_store: SpectorStore) -> None:
        """Verifies abatch with GetOp for non-existent key returns None without raising."""
        results = await spector_store.abatch([GetOp(("nonexistent", "ns"), "missing_key")])
        assert len(results) == 1
        assert results[0] is None

    def test_batch_synchronous_operations(self, spector_store: SpectorStore) -> None:
        """Verifies synchronous batch operation executes PutOp, GetOp, and SearchOp."""
        namespace = ("sync", "session_1")
        key = "item_1"
        value = {"text": "Synchronous persistence check"}

        put_res = spector_store.batch([PutOp(namespace, key, value)])
        assert put_res == [None]

        get_res = spector_store.batch([GetOp(namespace, key)])
        assert len(get_res) == 1
        item = get_res[0]
        assert isinstance(item, Item)
        assert item.key == key
        assert item.value == value

        search_res = spector_store.batch([SearchOp(namespace_prefix=namespace, query="persistence", limit=5)])
        assert len(search_res) == 1
        items = search_res[0]
        assert len(items) == 1
        assert isinstance(items[0], SearchItem)

    @pytest.mark.asyncio
    async def test_convenience_methods(self, spector_store: SpectorStore) -> None:
        """Verifies convenience methods: aput, aget, asearch, adelete."""
        ns = ("memories", "convenience")
        await spector_store.aput(ns, "k1", {"text": "hello"})
        item = await spector_store.aget(ns, "k1")
        assert item is not None
        assert item.value == {"text": "hello"}

        results = await spector_store.asearch(ns, query="hello")
        assert len(results) >= 1

        await spector_store.adelete(ns, "k1")
        item_del = await spector_store.aget(ns, "k1")
        assert item_del is None

    @pytest.mark.asyncio
    async def test_list_namespaces_op(self, spector_store: SpectorStore) -> None:
        """Verifies list_namespaces with prefix matching and max_depth filtering."""
        await spector_store.aput(("patients", "101", "vitals"), "bp", {"val": "120/80"})
        await spector_store.aput(("patients", "101", "labs"), "hba1c", {"val": "5.6"})
        await spector_store.aput(("patients", "202", "vitals"), "bp", {"val": "130/85"})
        await spector_store.aput(("admin", "logs"), "log1", {"msg": "audit"})

        # List all namespaces
        ns_all = await spector_store.alist_namespaces()
        assert ("patients", "101", "vitals") in ns_all
        assert ("admin", "logs") in ns_all

        # Match with prefix condition
        match_pref = MatchCondition(match_type="prefix", path=("patients", "101"))
        res_pref = await spector_store.abatch([
            ListNamespacesOp(match_conditions=(match_pref,), max_depth=None, limit=10, offset=0)
        ])
        assert len(res_pref[0]) == 2
        assert ("patients", "101", "vitals") in res_pref[0]
        assert ("patients", "101", "labs") in res_pref[0]

        # Max depth truncation
        res_depth = await spector_store.abatch([
            ListNamespacesOp(match_conditions=None, max_depth=1, limit=10, offset=0)
        ])
        assert ("patients",) in res_depth[0]
        assert ("admin",) in res_depth[0]

    @pytest.mark.asyncio
    async def test_fallback_on_unreachable_spector(self) -> None:
        """Verifies resilient fallback to fallback store when Spector raises connection error."""
        class FailingAsyncMemoryClient:
            async def find(self, memory_id: str) -> Any:
                raise TransportError("Connection refused")

            async def remember(self, **kwargs: Any) -> Any:
                raise TransportError("Connection refused")

            async def recall(self, **kwargs: Any) -> Any:
                raise TransportError("Connection refused")

            async def forget(self, memory_id: str, **kwargs: Any) -> Any:
                raise TransportError("Connection refused")

            async def status(self) -> Any:
                raise TransportError("Connection refused")

        failing_client = FailingAsyncMemoryClient()
        store = SpectorStore(client=failing_client, fallback_to_sqlite=True, cooldown_seconds=60.0)

        # Write to store - should fall back to fallback store without raising
        await store.aput(("fallback", "ns"), "k1", {"text": "saved via fallback"})
        assert store._is_degraded is True

        # Read back from store - should read from fallback store
        item = await store.aget(("fallback", "ns"), "k1")
        assert item is not None
        assert item.value == {"text": "saved via fallback"}


# ==============================================================================
# 2. Tests for SpectorMemoryAdapter (Carefold MemoryPort Contract)
# ==============================================================================

class TestSpectorMemoryAdapterContract:
    """Verifies that SpectorMemoryAdapter conforms to Carefold MemoryPort specifications."""

    def test_spector_memory_adapter_inheritance(self, spector_adapter: SpectorMemoryAdapter) -> None:
        """Confirms that SpectorMemoryAdapter implements MemoryPort."""
        assert isinstance(spector_adapter, MemoryPort)
        assert issubclass(SpectorMemoryAdapter, MemoryPort)

    def test_store_property_returns_spector_store(self, spector_adapter: SpectorMemoryAdapter) -> None:
        """Confirms that adapter.store property returns the underlying SpectorStore."""
        store = spector_adapter.store
        assert isinstance(store, BaseStore)
        assert isinstance(store, SpectorStore)

    @pytest.mark.asyncio
    async def test_remember_and_recall(self, spector_adapter: SpectorMemoryAdapter) -> None:
        """Verifies remember stores memory and recall retrieves formatted dictionaries."""
        await spector_adapter.remember(
            key="allergy_penicillin",
            value="Severe penicillin allergy, anaphylaxis risk",
            tier=MemoryTier.SEMANTIC,
            namespace="patient_101",
            metadata={"source": "EHR", "verified": True},
        )

        recalled = await spector_adapter.recall(
            query="penicillin allergy",
            tier=MemoryTier.SEMANTIC,
            namespace="patient_101",
            limit=5,
        )

        assert len(recalled) == 1
        rec = recalled[0]
        assert rec["key"] == "allergy_penicillin"
        assert "penicillin" in str(rec["value"])
        assert rec["tier"] in (MemoryTier.SEMANTIC, "semantic")
        assert rec["namespace"] == "patient_101"
        assert rec["metadata"]["source"] == "EHR"
        assert "salience" in rec or "score" in rec

    @pytest.mark.asyncio
    async def test_remember_validation(self, spector_adapter: SpectorMemoryAdapter) -> None:
        """Verifies empty key raises ValueError."""
        with pytest.raises(ValueError):
            await spector_adapter.remember("", "value", MemoryTier.SEMANTIC)

    @pytest.mark.asyncio
    async def test_forget(self, spector_adapter: SpectorMemoryAdapter) -> None:
        """Verifies forget deletes memory and returns True, subsequent forget returns False."""
        await spector_adapter.remember(
            key="temp_key",
            value="To be deleted",
            tier=MemoryTier.WORKING,
            namespace="session_1",
        )

        deleted = await spector_adapter.forget(key="temp_key", namespace="session_1")
        assert deleted is True

        deleted_again = await spector_adapter.forget(key="temp_key", namespace="session_1")
        assert deleted_again is False

    @pytest.mark.asyncio
    async def test_reinforce(
        self,
        spector_adapter: SpectorMemoryAdapter,
        simulated_client: SimulatedAsyncMemoryClient,
    ) -> None:
        """Verifies reinforce invokes client.reinforce with delta."""
        await spector_adapter.remember(
            key="guideline_asthma",
            value="Asthma step-up therapy protocol",
            tier=MemoryTier.PROCEDURAL,
            namespace="clinical",
        )

        await spector_adapter.reinforce(key="guideline_asthma", namespace="clinical", delta=0.2)
        assert len(simulated_client.reinforce_calls) == 1
        assert "guideline_asthma" in simulated_client.reinforce_calls[0]["id"]

    @pytest.mark.asyncio
    async def test_get_by_key(self, spector_adapter: SpectorMemoryAdapter) -> None:
        """Verifies get retrieves single memory record or None."""
        await spector_adapter.remember("k_single", "single val", MemoryTier.SEMANTIC, "test_ns")
        rec = await spector_adapter.get("k_single", "test_ns")
        assert rec is not None
        assert rec["key"] == "k_single"
        assert rec["value"] == "single val"

        missing = await spector_adapter.get("nonexistent", "test_ns")
        assert missing is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self, simulated_client: SimulatedAsyncMemoryClient) -> None:
        """Verifies async context manager cleanup."""
        async with SpectorMemoryAdapter(client=simulated_client) as adapter:
            await adapter.remember("ctx_k", "ctx_val", MemoryTier.WORKING)
            rec = await adapter.get("ctx_k")
            assert rec is not None

        assert simulated_client.closed is True

    @pytest.mark.asyncio
    async def test_close(
        self,
        spector_adapter: SpectorMemoryAdapter,
        simulated_client: SimulatedAsyncMemoryClient,
    ) -> None:
        """Verifies close terminates client resources."""
        await spector_adapter.close()
        assert simulated_client.closed is True


# ==============================================================================
# 3. Tests for Factory Integration (carefold.memory.factory.py)
# ==============================================================================

class TestMemoryFactorySpectorIntegration:
    """Verifies factory instantiation and singleton management for Spector backend."""

    def setup_method(self) -> None:
        reset_memory_ports()

    def teardown_method(self) -> None:
        reset_memory_ports()

    def test_factory_creates_spector_memory_adapter(self) -> None:
        """Verifies create_memory_port(backend='spector') instantiates SpectorMemoryAdapter."""
        test_settings = Settings(
            memory_backend="spector",
            spector_url="http://localhost:7070",
        )

        with patch("carefold.memory.adapters.spector.store.AsyncSpectorClient") as mock_async_cls, \
             patch("carefold.memory.adapters.spector.store.SpectorClient") as mock_sync_cls:
            mock_async_cls.builder.return_value.with_rest.return_value.build.return_value.memory = SimulatedAsyncMemoryClient()
            mock_sync_cls.builder.return_value.with_rest.return_value.build.return_value.memory = None

            port = create_memory_port(settings=test_settings)
            assert isinstance(port, SpectorMemoryAdapter)
            assert isinstance(port, MemoryPort)
            assert isinstance(port.store, BaseStore)

    def test_get_memory_port_caches_spector_singleton(self) -> None:
        """Verifies get_memory_port returns cached singleton when CAREFOLD_MEMORY_BACKEND=spector."""
        test_settings = Settings(
            memory_backend="spector",
            spector_url="http://localhost:7070",
        )

        with patch("carefold.memory.adapters.spector.store.AsyncSpectorClient") as mock_async_cls, \
             patch("carefold.memory.adapters.spector.store.SpectorClient") as mock_sync_cls:
            mock_async_cls.builder.return_value.with_rest.return_value.build.return_value.memory = SimulatedAsyncMemoryClient()
            mock_sync_cls.builder.return_value.with_rest.return_value.build.return_value.memory = None

            p1 = get_memory_port(test_settings)
            p2 = get_memory_port()
            assert p1 is p2
            assert isinstance(p1, SpectorMemoryAdapter)

            reset_memory_ports()
            p3 = get_memory_port(test_settings)
            assert p1 is not p3
