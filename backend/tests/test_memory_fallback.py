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

"""Comprehensive test suite for Spector Memory resilient fallback engine and configuration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional
import urllib.error

from langgraph.store.base import (
    GetOp,
    PutOp,
)
from langgraph.store.memory import InMemoryStore
import pytest
from spector_client.exceptions import (
    MemoryNotFoundError,
    SpectorServerError,
    TransportError,
)
from spector_client.models import (
    MemoryRecord,
    MemoryTier as SpectorTier,
    RecallRecord,
)

from carefold.config import Settings
from carefold.memory.adapters.spector.memory_adapter import SpectorMemoryAdapter
from carefold.memory.adapters.spector.store import SpectorStore
from carefold.memory.factory import (
    create_memory_port,
    get_memory_port,
    reset_memory_ports,
)
from carefold.memory.ports.memory_port import MemoryTier


# =============================================================================
# Zero-Mock Test Doubles (strictly confined to backend/tests/)
# =============================================================================


class ControllableAsyncMemoryClient:
    """Deterministic, stateful test double of AsyncMemoryClient for hermetic CI testing."""

    def __init__(
        self,
        healthy: bool = True,
        exc_to_raise: Optional[Exception] = None,
    ) -> None:
        self.healthy: bool = healthy
        self.exc_to_raise: Exception = exc_to_raise or TransportError("Connection refused")
        self.records: Dict[str, MemoryRecord] = {}
        self.primary_remember_calls: int = 0
        self.primary_find_calls: int = 0
        self.primary_recall_calls: int = 0
        self.primary_forget_calls: int = 0
        self.health_check_calls: int = 0
        self.closed: bool = False

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
        if not self.healthy:
            raise self.exc_to_raise
        self.primary_remember_calls += 1
        meta = metadata or {}
        key = meta.get("key", "default_key")
        ns = meta.get("namespace", "default")
        ns_str = ":".join(ns) if isinstance(ns, list) else str(ns)
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

    async def find(self, memory_id: str) -> Optional[MemoryRecord]:
        if not self.healthy:
            raise self.exc_to_raise
        self.primary_find_calls += 1
        return self.records.get(memory_id)

    async def get(self, memory_id: str) -> MemoryRecord:
        if not self.healthy:
            raise self.exc_to_raise
        if memory_id not in self.records:
            raise MemoryNotFoundError(f"Memory {memory_id} not found")
        return self.records[memory_id]

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[RecallRecord]:
        if not self.healthy:
            raise self.exc_to_raise
        self.primary_recall_calls += 1
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
        if not self.healthy:
            raise self.exc_to_raise
        self.primary_forget_calls += 1
        self.records.pop(memory_id, None)

    async def status(self) -> Dict[str, Any]:
        self.health_check_calls += 1
        if not self.healthy:
            raise self.exc_to_raise
        return {"status": "ok", "total_records": len(self.records)}

    async def close(self) -> None:
        self.closed = True


class ControllableSyncMemoryClient:
    """Deterministic, stateful synchronous test double of MemoryClient for hermetic CI testing."""

    def __init__(
        self,
        healthy: bool = True,
        exc_to_raise: Optional[Exception] = None,
    ) -> None:
        self.healthy: bool = healthy
        self.exc_to_raise: Exception = exc_to_raise or TransportError("Connection refused")
        self.records: Dict[str, MemoryRecord] = {}
        self.primary_remember_calls: int = 0
        self.primary_find_calls: int = 0
        self.primary_recall_calls: int = 0
        self.primary_forget_calls: int = 0
        self.health_check_calls: int = 0
        self.closed: bool = False

    def remember(
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
        if not self.healthy:
            raise self.exc_to_raise
        self.primary_remember_calls += 1
        meta = metadata or {}
        key = meta.get("key", "default_key")
        ns = meta.get("namespace", "default")
        ns_str = ":".join(ns) if isinstance(ns, list) else str(ns)
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

    def find(self, memory_id: str) -> Optional[MemoryRecord]:
        if not self.healthy:
            raise self.exc_to_raise
        self.primary_find_calls += 1
        return self.records.get(memory_id)

    def get(self, memory_id: str) -> MemoryRecord:
        if not self.healthy:
            raise self.exc_to_raise
        if memory_id not in self.records:
            raise MemoryNotFoundError(f"Memory {memory_id} not found")
        return self.records[memory_id]

    def recall(
        self,
        query: str,
        top_k: int = 5,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[RecallRecord]:
        if not self.healthy:
            raise self.exc_to_raise
        self.primary_recall_calls += 1
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

    def forget(self, memory_id: str, reason: Optional[str] = None) -> None:
        if not self.healthy:
            raise self.exc_to_raise
        self.primary_forget_calls += 1
        self.records.pop(memory_id, None)

    def status(self) -> Dict[str, Any]:
        self.health_check_calls += 1
        if not self.healthy:
            raise self.exc_to_raise
        return {"status": "ok", "total_records": len(self.records)}

    def close(self) -> None:
        self.closed = True


# =============================================================================
# Group 1: Unreachable Spector Port with Fallback Enabled (fallback_to_sqlite=True)
# =============================================================================


@pytest.mark.asyncio
async def test_unreachable_spector_port_store_aput() -> None:
    """Verifies aput falls back to in-memory store when Spector is unreachable."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        await store.aput(("test",), "k1", {"text": "fallback_val"})
        assert store._is_degraded is True
        assert store._cooldown_until > time.time()
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_unreachable_spector_port_store_aget() -> None:
    """Verifies aget reads from fallback store when Spector is unreachable."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        await store.aput(("test",), "k1", {"text": "fallback_val"})
        item = await store.aget(("test",), "k1")
        assert item is not None
        assert item.value == {"text": "fallback_val"}
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_unreachable_spector_port_store_asearch() -> None:
    """Verifies asearch queries fallback store when Spector is unreachable."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        await store.aput(("test",), "k1", {"text": "fallback_val"})
        results = await store.asearch(("test",), query="fallback_val")
        assert len(results) >= 1
        assert results[0].key == "k1"
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_unreachable_spector_port_store_adelete() -> None:
    """Verifies adelete removes items from fallback store when Spector is unreachable."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        await store.aput(("test",), "k1", {"text": "fallback_val"})
        await store.adelete(("test",), "k1")
        item = await store.aget(("test",), "k1")
        assert item is None
    finally:
        await store.aclose()


def test_unreachable_spector_port_store_batch_sync() -> None:
    """Verifies synchronous batch operations fall back cleanly on unreachable port."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        res = store.batch([PutOp(("sync",), "k1", {"text": "sync_val"})])
        assert res == [None]
        items = store.batch([GetOp(("sync",), "k1")])
        assert len(items) == 1
        assert items[0] is not None
        assert items[0].value == {"text": "sync_val"}
    finally:
        store.close()


@pytest.mark.asyncio
async def test_unreachable_spector_warning_log_captured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verifies structured warning log is emitted when fallback is activated."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        with caplog.at_level(logging.WARNING, logger="carefold.memory.adapters.spector.store"):
            await store.aput(("log_test",), "k1", {"text": "val"})
        matching = [
            r
            for r in caplog.records
            if "Spector operation failed:" in r.message and "Activating resilient fallback." in r.message
        ]
        assert len(matching) >= 1
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_unreachable_spector_adapter_remember() -> None:
    """Verifies SpectorMemoryAdapter.remember falls back without error on unreachable port."""
    adapter = SpectorMemoryAdapter(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        await adapter.remember("k1", "patient note", MemoryTier.SEMANTIC, namespace="clin")
        assert adapter.is_degraded is True
        assert adapter.fallback_active is True
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_unreachable_spector_adapter_recall() -> None:
    """Verifies SpectorMemoryAdapter.recall retrieves from fallback on unreachable port."""
    adapter = SpectorMemoryAdapter(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        await adapter.remember("k1", "patient note", MemoryTier.SEMANTIC, namespace="clin")
        recalled = await adapter.recall("patient", tier=MemoryTier.SEMANTIC, namespace="clin")
        assert len(recalled) == 1
        assert recalled[0]["key"] == "k1"
        assert recalled[0]["value"] == "patient note"
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_unreachable_spector_adapter_get() -> None:
    """Verifies SpectorMemoryAdapter.get reads from fallback on unreachable port."""
    adapter = SpectorMemoryAdapter(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        await adapter.remember("k1", "patient note", MemoryTier.SEMANTIC, namespace="clin")
        rec = await adapter.get("k1", namespace="clin")
        assert rec is not None
        assert rec["value"] == "patient note"
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_unreachable_spector_adapter_reinforce() -> None:
    """Verifies SpectorMemoryAdapter.reinforce updates salience in fallback on unreachable port."""
    adapter = SpectorMemoryAdapter(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        await adapter.remember("k1", "patient note", MemoryTier.SEMANTIC, namespace="clin")
        await adapter.reinforce("k1", namespace="clin", delta=0.5)
        rec = await adapter.get("k1", namespace="clin")
        assert rec is not None
        assert rec["salience"] == 1.5
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_unreachable_spector_adapter_forget() -> None:
    """Verifies SpectorMemoryAdapter.forget deletes from fallback on unreachable port."""
    adapter = SpectorMemoryAdapter(base_url="http://127.0.0.1:59999", fallback_to_sqlite=True, timeout=0.2)
    try:
        await adapter.remember("k1", "patient note", MemoryTier.SEMANTIC, namespace="clin")
        deleted = await adapter.forget("k1", namespace="clin")
        assert deleted is True
        assert await adapter.get("k1", namespace="clin") is None
    finally:
        await adapter.close()


# =============================================================================
# Group 2: Unreachable Spector Port with Fallback Disabled (fallback_to_sqlite=False)
# =============================================================================


@pytest.mark.asyncio
async def test_unreachable_spector_disabled_store_aput_raises() -> None:
    """Verifies aput raises connection exception when fallback is disabled."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=False, timeout=0.2)
    try:
        with pytest.raises((TransportError, ConnectionError, OSError)):
            await store.aput(("test",), "k1", {"text": "val"})
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_unreachable_spector_disabled_store_aget_raises() -> None:
    """Verifies aget raises connection exception when fallback is disabled."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=False, timeout=0.2)
    try:
        with pytest.raises((TransportError, ConnectionError, OSError)):
            await store.aget(("test",), "k1")
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_unreachable_spector_disabled_store_asearch_raises() -> None:
    """Verifies asearch raises connection exception when fallback is disabled."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=False, timeout=0.2)
    try:
        with pytest.raises((TransportError, ConnectionError, OSError)):
            await store.asearch(("test",), query="val")
    finally:
        await store.aclose()


def test_unreachable_spector_disabled_store_batch_raises() -> None:
    """Verifies synchronous batch raises connection exception when fallback is disabled."""
    store = SpectorStore(base_url="http://127.0.0.1:59999", fallback_to_sqlite=False, timeout=0.2)
    try:
        with pytest.raises((TransportError, ConnectionError, OSError)):
            store.batch([PutOp(("test",), "k1", {"text": "val"})])
    finally:
        store.close()


@pytest.mark.asyncio
async def test_unreachable_spector_disabled_adapter_operations_raise() -> None:
    """Verifies SpectorMemoryAdapter operations cleanly raise when fallback is disabled."""
    adapter = SpectorMemoryAdapter(base_url="http://127.0.0.1:59999", fallback_to_sqlite=False, timeout=0.2)
    try:
        with pytest.raises((TransportError, ConnectionError, OSError)):
            await adapter.remember("k1", "val", MemoryTier.SEMANTIC)
        with pytest.raises((TransportError, ConnectionError, OSError)):
            await adapter.recall("val")
        with pytest.raises((TransportError, ConnectionError, OSError)):
            await adapter.get("k1")
        with pytest.raises((TransportError, ConnectionError, OSError)):
            await adapter.reinforce("k1", delta=0.5)
    finally:
        await adapter.close()


# =============================================================================
# Group 3: Runtime Request Exceptions & Circuit Breaker Cooldown
# =============================================================================


@pytest.mark.asyncio
async def test_mid_session_network_drop_trips_circuit_breaker() -> None:
    """Verifies mid-session network drop trips circuit breaker into degraded state."""
    client = ControllableAsyncMemoryClient(healthy=True)
    store = SpectorStore(client=client, fallback_to_sqlite=True, cooldown_seconds=30.0)
    try:
        await store.aput(("test",), "k1", {"text": "initial"})
        assert client.primary_remember_calls == 1
        assert store._is_degraded is False

        client.healthy = False
        await store.aput(("test",), "k2", {"text": "during_drop"})
        assert store._is_degraded is True
        assert store._cooldown_until > time.time()

        item = await store.aget(("test",), "k2")
        assert item is not None
        assert item.value == {"text": "during_drop"}
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_mid_cooldown_requests_routed_immediately_without_latency() -> None:
    """Verifies operations during cooldown window route to fallback with 0ms fast-path."""
    client = ControllableAsyncMemoryClient(healthy=False)
    store = SpectorStore(client=client, fallback_to_sqlite=True, cooldown_seconds=30.0)
    try:
        await store.aput(("test",), "k0", {"text": "initial"})
        assert store._is_degraded is True
        remember_calls_before = client.primary_remember_calls

        start_time = time.perf_counter()
        for i in range(10):
            await store.aput(("test",), f"k_{i}", {"text": f"val_{i}"})
            item = await store.aget(("test",), f"k_{i}")
            assert item is not None
        elapsed = time.perf_counter() - start_time

        assert elapsed < 0.1
        assert client.primary_remember_calls == remember_calls_before
        assert client.health_check_calls == 0
    finally:
        await store.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        TransportError("net down"),
        SpectorServerError(500, "internal error"),
        urllib.error.URLError("timeout"),
        TimeoutError("timeout"),
        OSError("network unreachable"),
        ConnectionError("connection reset"),
    ],
)
async def test_various_exceptions_trigger_circuit_breaker(exc: Exception) -> None:
    """Verifies transport, server, and network exceptions trip the circuit breaker."""
    client = ControllableAsyncMemoryClient(healthy=False, exc_to_raise=exc)
    store = SpectorStore(client=client, fallback_to_sqlite=True, cooldown_seconds=30.0)
    try:
        await store.aput(("test",), "k1", {"text": "val"})
        assert store._is_degraded is True
        item = await store.aget(("test",), "k1")
        assert item is not None
        assert item.value == {"text": "val"}
    finally:
        await store.aclose()


# =============================================================================
# Group 4: Service Recovery After Cooldown
# =============================================================================


@pytest.mark.asyncio
async def test_recovery_after_cooldown_resumes_primary_operations(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verifies service recovery after cooldown restores primary execution path."""
    client = ControllableAsyncMemoryClient(healthy=False)
    store = SpectorStore(client=client, fallback_to_sqlite=True, cooldown_seconds=0.05)
    try:
        await store.aput(("test",), "k1", {"text": "drop"})
        assert store._is_degraded is True

        client.healthy = True
        await asyncio.sleep(0.07)

        with caplog.at_level(logging.INFO, logger="carefold.memory.adapters.spector.store"):
            await store.aput(("test",), "k_rec", {"text": "recovered"})

        assert store._is_degraded is False
        assert client.primary_remember_calls == 1
        assert "Spector service reconnected. Exiting degraded fallback state." in caplog.text
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_recovery_failure_extends_cooldown() -> None:
    """Verifies failed health probe upon cooldown expiry extends the cooldown period."""
    client = ControllableAsyncMemoryClient(healthy=False)
    store = SpectorStore(client=client, fallback_to_sqlite=True, cooldown_seconds=0.05)
    try:
        await store.aput(("test",), "k1", {"text": "drop"})
        assert store._is_degraded is True
        old_cooldown = store._cooldown_until

        await asyncio.sleep(0.07)
        # client is still unhealthy
        await store.aput(("test",), "k_fail", {"text": "still down"})

        assert store._is_degraded is True
        assert client.health_check_calls == 1
        assert store._cooldown_until > old_cooldown
    finally:
        await store.aclose()


def test_sync_recovery_after_cooldown(caplog: pytest.LogCaptureFixture) -> None:
    """Verifies service recovery on synchronous batch path after cooldown."""
    sync_client = ControllableSyncMemoryClient(healthy=False)
    store = SpectorStore(sync_client=sync_client, fallback_to_sqlite=True, cooldown_seconds=0.05)
    try:
        store.batch([PutOp(("sync",), "k1", {"text": "sync_drop"})])
        assert store._is_degraded is True

        sync_client.healthy = True
        time.sleep(0.07)

        with caplog.at_level(logging.INFO, logger="carefold.memory.adapters.spector.store"):
            store.batch([PutOp(("sync",), "k_rec", {"text": "sync_rec"})])

        assert store._is_degraded is False
        assert sync_client.primary_remember_calls == 1
        assert "Spector service reconnected. Exiting degraded fallback state." in caplog.text
    finally:
        store.close()


# =============================================================================
# Group 5: Settings & Factory Integration
# =============================================================================


def test_settings_default_fallback_to_sqlite() -> None:
    """Verifies Settings defaults memory_fallback_to_sqlite to True."""
    s = Settings()
    assert s.memory_fallback_to_sqlite is True


def test_settings_env_var_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies CAREFOLD_MEMORY_FALLBACK_TO_SQLITE environment variable resolution."""
    monkeypatch.setenv("CAREFOLD_MEMORY_FALLBACK_TO_SQLITE", "false")
    s = Settings()
    assert s.memory_fallback_to_sqlite is False

    monkeypatch.setenv("CAREFOLD_MEMORY_FALLBACK_TO_SQLITE", "true")
    s2 = Settings()
    assert s2.memory_fallback_to_sqlite is True


def test_factory_honors_fallback_setting() -> None:
    """Verifies create_memory_port honors memory_fallback_to_sqlite in Settings."""
    s_false = Settings(memory_backend="spector", memory_fallback_to_sqlite=False)
    port_false = create_memory_port(settings=s_false)
    assert isinstance(port_false, SpectorMemoryAdapter)
    assert port_false.fallback_to_sqlite is False
    assert getattr(port_false.store, "fallback_to_sqlite", True) is False

    s_true = Settings(memory_backend="spector", memory_fallback_to_sqlite=True)
    port_true = create_memory_port(settings=s_true)
    assert isinstance(port_true, SpectorMemoryAdapter)
    assert port_true.fallback_to_sqlite is True
    assert getattr(port_true.store, "fallback_to_sqlite", False) is True


# =============================================================================
# Group 6: Edge Cases & Integrity
# =============================================================================


@pytest.mark.asyncio
async def test_custom_fallback_store_injection() -> None:
    """Verifies custom fallback store injection is honored when fallback occurs."""
    custom_store = InMemoryStore()
    client = ControllableAsyncMemoryClient(healthy=False)
    store = SpectorStore(client=client, fallback_to_sqlite=True, fallback_store=custom_store)
    try:
        await store.aput(("custom",), "ck1", {"text": "injected"})
        item = await custom_store.aget(("custom",), "ck1")
        assert item is not None
        assert item.value == {"text": "injected"}
    finally:
        await store.aclose()


def test_factory_spector_singleton_caching() -> None:
    """Verifies get_memory_port caches singleton instance across calls for Spector backend."""
    reset_memory_ports()
    s = Settings(memory_backend="spector")
    p1 = get_memory_port(s)
    p2 = get_memory_port(s)
    assert p1 is p2
    reset_memory_ports()
    p3 = get_memory_port(s)
    assert p1 is not p3
    reset_memory_ports()
