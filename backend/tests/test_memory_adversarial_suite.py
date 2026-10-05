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

"""Comprehensive Adversarial Test Suite for SqliteMemoryAdapter and memory/factory.py.
Target components:
- SqliteMemoryAdapter:
  1. Namespace collision & delimiter injection
  2. Extreme salience reinforcement & decay
  3. Unicode, binary, and primitive type mutability
  4. Recall limit edge conditions (0, negative, oversized)
  5. Recall tier filtering (None vs explicit vs string vs invalid)
- factory.py:
  6. Concurrency in singleton creation (threads and async tasks)
  7. Cache invalidation via reset_memory_ports()
  8. Overriding settings dynamically & explicit port overrides
  9. Env var overrides and backend validation semantics (invalid -> ValueError, spector/postgres -> NotImplementedError)
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from carefold.config import Settings
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import (
    create_catalog_port,
    create_memory_port,
    get_catalog_port,
    get_memory_port,
    reset_memory_ports,
    set_catalog_port,
    set_memory_port,
)
from carefold.memory.ports.catalog_port import CatalogPort
from carefold.memory.ports.memory_port import MemoryPort, MemoryTier


# ==============================================================================
# PART 1: SqliteMemoryAdapter Adversarial Tests
# ==============================================================================

class TestSqliteMemoryAdapterAdversarial:
    """Adversarial stress-tests targeting SqliteMemoryAdapter."""

    @pytest.fixture
    async def adapter(self, tmp_path: Path):
        """Creates an isolated SqliteMemoryAdapter with a temporary database."""
        db_path = tmp_path / "adversarial_memory.db"
        ad = SqliteMemoryAdapter(db_path=db_path)
        yield ad
        await ad.close()

    # --------------------------------------------------------------------------
    # 1. Namespace Collision Tests
    # --------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_same_key_in_different_namespaces_isolation(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies that identical keys in different namespaces maintain strict isolation."""
        namespaces = ["ns_alice", "ns_bob", "ns_carol", "tenant_1", "tenant_2"]
        key = "shared_config_key"

        # Write unique payload per namespace
        for ns in namespaces:
            await adapter.remember(
                key=key,
                value={"owner": ns, "payload": f"secret_data_for_{ns}"},
                tier=MemoryTier.SEMANTIC,
                namespace=ns,
                metadata={"ns_tag": ns},
            )

        # Recall and verify each namespace sees only its own data
        for ns in namespaces:
            results = await adapter.recall(query=key, namespace=ns)
            assert len(results) == 1, f"Expected exactly 1 record for namespace {ns}, got {len(results)}"
            record = results[0]
            assert record["key"] == key
            assert record["namespace"] == ns
            assert record["value"]["owner"] == ns
            assert record["value"]["payload"] == f"secret_data_for_{ns}"
            assert record["metadata"]["ns_tag"] == ns

        # Delete from ns_alice and verify other namespaces remain untouched
        deleted = await adapter.forget(key=key, namespace="ns_alice")
        assert deleted is True

        # ns_alice should now be empty
        alice_recall = await adapter.recall(query=key, namespace="ns_alice")
        assert len(alice_recall) == 0

        # All other namespaces must still retain their exact data
        for ns in namespaces[1:]:
            results = await adapter.recall(query=key, namespace=ns)
            assert len(results) == 1
            assert results[0]["value"]["owner"] == ns

    @pytest.mark.asyncio
    async def test_namespace_colon_delimiter_injection(self, adapter: SqliteMemoryAdapter) -> None:
        """Tests delimiter collision when namespace and key contain colons.
        
        mem_id is constructed as f"{namespace}:{key}".
        Case A: namespace="user:1", key="records" -> id="user:1:records"
        Case B: namespace="user", key="1:records" -> id="user:1:records"
        
        Adversarial check: Does Case B overwrite Case A?
        """
        await adapter.remember(
            key="records",
            value="User 1 Patient Records",
            tier=MemoryTier.SEMANTIC,
            namespace="user:1",
        )

        # Attempt to inject/collide via namespace="user" and key="1:records"
        await adapter.remember(
            key="1:records",
            value="Injected Malicious Value",
            tier=MemoryTier.WORKING,
            namespace="user",
        )

        # Inspect what is recalled under "user:1"
        rec_a = await adapter.recall("", namespace="user:1")
        # Inspect what is recalled under "user"
        rec_b = await adapter.recall("", namespace="user")

        # In a compound key f"{namespace}:{key}", both share the same primary key ID.
        # This allows cross-namespace overwrite:
        collision_detected = False
        if len(rec_a) > 0 and "Injected" in str(rec_a[0]["value"]):
            collision_detected = True

        assert not collision_detected, (
            "VULNERABILITY DETECTED: Colon in namespace/key allows ID collision across namespaces! "
            f"namespace='user:1', key='records' was overwritten by namespace='user', key='1:records'."
        )

    # --------------------------------------------------------------------------
    # 2. Extreme Salience Reinforcement and Decay Tests
    # --------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_extreme_salience_decay_clamped_at_zero(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies that extreme negative delta decay clamps salience to 0.0 without going negative."""
        key = "decay_target"
        ns = "salience_ns"
        await adapter.remember(key, "decayable memory", MemoryTier.EPISODIC, namespace=ns)

        # Moderate decay
        await adapter.reinforce(key, namespace=ns, delta=-0.5)
        item = await adapter.get(key, namespace=ns)
        assert item is not None
        assert item["salience"] == pytest.approx(0.5, abs=1e-5)
        assert item["access_count"] == 1

        # Massive negative decay (-1,000,000.0)
        await adapter.reinforce(key, namespace=ns, delta=-1_000_000.0)
        item = await adapter.get(key, namespace=ns)
        assert item is not None
        assert item["salience"] == 0.0, f"Expected 0.0 clamping, got {item['salience']}"
        assert item["access_count"] == 2

    @pytest.mark.asyncio
    async def test_extreme_positive_salience_reinforcement(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies large positive reinforcement deltas (up to 1e9) do not overflow SQLite REAL."""
        key = "boost_target"
        ns = "salience_ns"
        await adapter.remember(key, "boostable memory", MemoryTier.SEMANTIC, namespace=ns)

        # Huge boost
        await adapter.reinforce(key, namespace=ns, delta=1_000_000.0)
        item = await adapter.get(key, namespace=ns)
        assert item is not None
        assert item["salience"] >= 1_000_001.0

        # Further boost
        await adapter.reinforce(key, namespace=ns, delta=1e9)
        item2 = await adapter.get(key, namespace=ns)
        assert item2 is not None
        assert item2["salience"] >= 1e9

    @pytest.mark.asyncio
    async def test_zero_salience_recall_and_ranking(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies memories with 0.0 salience still recall but rank below high-salience items."""
        ns = "ranking_ns"
        await adapter.remember("item_low", "common symptom cough", MemoryTier.SEMANTIC, namespace=ns)
        await adapter.remember("item_high", "common symptom cough", MemoryTier.SEMANTIC, namespace=ns)

        # Decay item_low to 0.0, boost item_high to 50.0
        await adapter.reinforce("item_low", namespace=ns, delta=-10.0)
        await adapter.reinforce("item_high", namespace=ns, delta=49.0)

        results = await adapter.recall("cough", namespace=ns)
        assert len(results) == 2
        # Highest salience/score must be first
        assert results[0]["key"] == "item_high"
        assert results[0]["salience"] >= 50.0
        assert results[1]["key"] == "item_low"
        assert results[1]["salience"] == 0.0

    @pytest.mark.asyncio
    async def test_salience_non_existent_key_no_crash(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies reinforcing a non-existent key does not raise or corrupt state."""
        await adapter.reinforce("ghost_key", namespace="empty_ns", delta=5.0)
        recalled = await adapter.recall("", namespace="empty_ns")
        assert len(recalled) == 0

    # --------------------------------------------------------------------------
    # 3. Unicode and Binary Payload Handling Tests
    # --------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_unicode_multilingual_emojis_and_accents(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies full Unicode support: emojis, CJK, RTL, zero-width chars, and diacritics."""
        ns = "unicode_ns"
        unicode_payloads = {
            "emojis": "Patient status: 🩺 🥼 🏥 💊 🩸 Heart rate steady ❤️",
            "japanese": "患者はペニシリンに対してアレルギーがあります。処方箋が必要です。",
            "arabic": "المريض يعاني من ارتفاع ضغط الدم والسكري.",
            "accents": "Éléphant, déjà vu, façade, naïve, Schön, señor, tête-à-tête",
            "zwsp": "Token\u200bWith\u200cZero\u200dWidth\ufeffCharacters",
        }

        for key, text in unicode_payloads.items():
            await adapter.remember(key, text, MemoryTier.SEMANTIC, namespace=ns)

        for key, text in unicode_payloads.items():
            item = await adapter.get(key, namespace=ns)
            assert item is not None, f"Failed to retrieve unicode key {key}"
            assert item["value"] == text, f"Unicode mismatch for key {key}"

        # FTS recall on emojis and unicode text
        res_em = await adapter.recall("Heart", namespace=ns)
        assert len(res_em) >= 1
        assert res_em[0]["key"] == "emojis"

    @pytest.mark.asyncio
    async def test_binary_and_bytes_handling(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies handling of byte strings and non-string types in remember."""
        ns = "binary_ns"
        raw_bytes = b"header\x01\x02\x03\xfe\xfftail"
        
        # Storing bytes converts to string representation
        await adapter.remember("bytes_key", raw_bytes, MemoryTier.WORKING, namespace=ns)
        item = await adapter.get("bytes_key", namespace=ns)
        assert item is not None
        assert "b'header" in str(item["value"])

    @pytest.mark.asyncio
    async def test_json_string_type_mutation_vulnerability(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies whether storing a string that happens to be valid JSON mutates its type upon recall.
        
        Vulnerability: SqliteMemoryAdapter un-conditionally executes json.loads(val) on recall.
        If a user stores a JSON string e.g. '{"note": "text"}', the returned value becomes a dict,
        and storing '123' returns an int.
        """
        ns = "primitives_ns"
        str_json = '{"clinical_note": "Line 1"}'
        await adapter.remember("raw_json_str", str_json, MemoryTier.WORKING, namespace=ns)

        item = await adapter.get("raw_json_str", namespace=ns)
        assert item is not None
        # Check if the stored string mutated into a dict
        type_mutated = isinstance(item["value"], dict)
        assert not type_mutated, (
            "VULNERABILITY DETECTED: Stored string payload was auto-deserialized into dict, "
            "mutating caller's data type!"
        )

    # --------------------------------------------------------------------------
    # 4. Recall Limit Edge Conditions
    # --------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_recall_limit_zero(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies limit=0 returns an empty list without error."""
        ns = "limits_ns"
        for i in range(5):
            await adapter.remember(f"item_{i}", f"payload data {i}", MemoryTier.EPISODIC, namespace=ns)

        results = await adapter.recall("", namespace=ns, limit=0)
        assert isinstance(results, list)
        assert len(results) == 0

        # With query
        results_q = await adapter.recall("payload", namespace=ns, limit=0)
        assert isinstance(results_q, list)
        assert len(results_q) == 0

    @pytest.mark.asyncio
    async def test_recall_limit_negative(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies behavior when limit is negative (e.g. limit=-1).
        
        In SQLite, LIMIT -1 denotes no upper limit (returns all matched rows).
        """
        ns = "limits_ns_neg"
        for i in range(5):
            await adapter.remember(f"item_{i}", f"payload data {i}", MemoryTier.SEMANTIC, namespace=ns)

        results = await adapter.recall("", namespace=ns, limit=-1)
        # SQLite interprets LIMIT -1 as unbounded
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_recall_limit_greater_than_total_items(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies limit > total items returns all available items without error."""
        ns = "limits_ns_large"
        for i in range(3):
            await adapter.remember(f"k_{i}", f"data {i}", MemoryTier.WORKING, namespace=ns)

        results = await adapter.recall("", namespace=ns, limit=10_000)
        assert len(results) == 3

    # --------------------------------------------------------------------------
    # 5. Recall Tier Filtering
    # --------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_recall_tier_filtering_comprehensive(self, adapter: SqliteMemoryAdapter) -> None:
        """Verifies tier filtering: tier=None (all tiers), explicit tier, string tier, invalid tier."""
        ns = "tier_filter_ns"
        await adapter.remember("w1", "working note", MemoryTier.WORKING, namespace=ns)
        await adapter.remember("e1", "episodic note", MemoryTier.EPISODIC, namespace=ns)
        await adapter.remember("s1", "semantic note", MemoryTier.SEMANTIC, namespace=ns)
        await adapter.remember("p1", "procedural note", MemoryTier.PROCEDURAL, namespace=ns)

        # 1. tier=None must return all 4 tiers
        all_tiers = await adapter.recall("", tier=None, namespace=ns, limit=10)
        assert len(all_tiers) == 4
        recalled_keys = {r["key"] for r in all_tiers}
        assert recalled_keys == {"w1", "e1", "s1", "p1"}

        # 2. Explicit tier filtering
        for expected_tier in MemoryTier:
            res = await adapter.recall("", tier=expected_tier, namespace=ns)
            assert len(res) == 1, f"Expected 1 record for tier {expected_tier}, got {len(res)}"
            assert res[0]["tier"] == expected_tier.value

        # 3. String tier parameter instead of enum
        res_str = await adapter.recall("", tier="procedural", namespace=ns)  # type: ignore[arg-type]
        assert len(res_str) == 1
        assert res_str[0]["key"] == "p1"

        # 4. Invalid / non-existent tier returns empty list
        res_invalid = await adapter.recall("", tier="non_existent_tier", namespace=ns)  # type: ignore[arg-type]
        assert len(res_invalid) == 0


# ==============================================================================
# PART 2: Memory Factory Adversarial Tests
# ==============================================================================

class TestMemoryFactoryAdversarial:
    """Adversarial stress-tests targeting memory/factory.py."""

    def setup_method(self) -> None:
        reset_memory_ports()

    def teardown_method(self) -> None:
        reset_memory_ports()

    # --------------------------------------------------------------------------
    # 6. Concurrency in Singleton Creation
    # --------------------------------------------------------------------------

    def test_concurrent_singleton_creation_multithreaded(self, tmp_path: Path) -> None:
        """Verifies thread-safety of get_memory_port() under 20 concurrent threads."""
        db_path = tmp_path / "concurrent_factory.db"
        settings = Settings(catalog_db_path=db_path)

        def worker() -> MemoryPort:
            return get_memory_port(settings)

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(worker) for _ in range(40)]
            results = [f.result() for f in futures]

        # All threads must receive a valid MemoryPort instance
        for port in results:
            assert isinstance(port, MemoryPort)

        # All must refer to the exact same cached singleton
        first_port = results[0]
        for port in results[1:]:
            assert port is first_port, "Singleton mismatch: multiple distinct instances created under concurrent access"

    @pytest.mark.asyncio
    async def test_concurrent_singleton_creation_asyncio(self, tmp_path: Path) -> None:
        """Verifies async concurrency in get_memory_port() and get_catalog_port()."""
        db_path = tmp_path / "async_factory.db"
        settings = Settings(catalog_db_path=db_path)

        async def get_mem():
            await asyncio.sleep(0.001)
            return get_memory_port(settings)

        async def get_cat():
            await asyncio.sleep(0.001)
            return get_catalog_port(settings)

        mem_tasks = [get_mem() for _ in range(30)]
        cat_tasks = [get_cat() for _ in range(30)]

        mem_results = await asyncio.gather(*mem_tasks)
        cat_results = await asyncio.gather(*cat_tasks)

        mem_singleton = mem_results[0]
        for m in mem_results[1:]:
            assert m is mem_singleton

        cat_singleton = cat_results[0]
        for c in cat_results[1:]:
            assert c is cat_singleton

    # --------------------------------------------------------------------------
    # 7. Cache Invalidation via reset_memory_ports()
    # --------------------------------------------------------------------------

    def test_cache_invalidation_and_lifecycle(self, tmp_path: Path) -> None:
        """Verifies reset_memory_ports() clears cached singletons."""
        s1 = Settings(catalog_db_path=tmp_path / "db_1.db")
        m1 = get_memory_port(s1)
        c1 = get_catalog_port(s1)

        # Invalidate cache
        reset_memory_ports()

        s2 = Settings(catalog_db_path=tmp_path / "db_2.db")
        m2 = get_memory_port(s2)
        c2 = get_catalog_port(s2)

        # Must be distinct new objects
        assert m1 is not m2, "reset_memory_ports() failed to clear _CACHED_MEMORY_PORT"
        assert c1 is not c2, "reset_memory_ports() failed to clear _CACHED_CATALOG_PORT"

    # --------------------------------------------------------------------------
    # 8. Overriding Settings Dynamically & Explicit Overrides
    # --------------------------------------------------------------------------

    def test_explicit_port_overrides_and_clearing(self, tmp_path: Path) -> None:
        """Verifies set_memory_port and set_catalog_port inject custom adapters."""
        custom_mem = create_memory_port(db_path=tmp_path / "custom_m.db")
        custom_cat = create_catalog_port(db_path=tmp_path / "custom_c.db")

        set_memory_port(custom_mem)
        set_catalog_port(custom_cat)

        assert get_memory_port() is custom_mem
        assert get_catalog_port() is custom_cat

        # Clearing via None resets to default creation
        set_memory_port(None)
        set_catalog_port(None)

        assert get_memory_port() is not custom_mem
        assert get_catalog_port() is not custom_cat

    def test_create_memory_port_returns_independent_instances(self, tmp_path: Path) -> None:
        """Verifies create_memory_port produces fresh un-cached instances."""
        p1 = create_memory_port(db_path=tmp_path / "p1.db")
        p2 = create_memory_port(db_path=tmp_path / "p2.db")

        assert p1 is not p2
        assert get_memory_port() is not p1
        assert get_memory_port() is not p2

    # --------------------------------------------------------------------------
    # 9. Env Var Overrides and Backend Validation
    # --------------------------------------------------------------------------

    def test_env_var_override_invalid_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifies CAREFOLD_MEMORY_BACKEND='invalid' raises ValueError."""
        monkeypatch.setenv("CAREFOLD_MEMORY_BACKEND", "invalid_backend")
        settings = Settings()

        with pytest.raises(ValueError) as exc_mem:
            get_memory_port(settings)
        assert "unsupported" in str(exc_mem.value).lower()
        assert "invalid_backend" in str(exc_mem.value)

        with pytest.raises(ValueError) as exc_cat:
            get_catalog_port(settings)
        assert "unsupported" in str(exc_cat.value).lower()
        assert "invalid_backend" in str(exc_cat.value)

    def test_env_var_override_spector_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifies CAREFOLD_MEMORY_BACKEND='spector' returns MemoryPort with .store, CatalogPort raises NotImplementedError."""
        monkeypatch.setenv("CAREFOLD_MEMORY_BACKEND", "spector")
        monkeypatch.setenv("CAREFOLD_SPECTOR_URL", "http://spector-service:9000")
        settings = Settings()

        mem = get_memory_port(settings)
        assert isinstance(mem, MemoryPort)
        assert hasattr(mem, "store")
        assert mem.store is not None

        with pytest.raises(NotImplementedError) as exc_cat:
            get_catalog_port(settings)
        assert "spector" in str(exc_cat.value).lower()
        assert "http://spector-service:9000" in str(exc_cat.value)

    def test_env_var_override_postgres_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifies CAREFOLD_MEMORY_BACKEND='postgres' raises NotImplementedError."""
        monkeypatch.setenv("CAREFOLD_MEMORY_BACKEND", "postgres")
        settings = Settings()

        with pytest.raises(NotImplementedError) as exc_mem:
            get_memory_port(settings)
        assert "postgres" in str(exc_mem.value).lower()

        with pytest.raises(NotImplementedError) as exc_cat:
            get_catalog_port(settings)
        assert "postgres" in str(exc_cat.value).lower()

    def test_empty_string_backend_vulnerability_discovery(self) -> None:
        """Empirically test whether empty string backend='' properly raises ValueError.
        
        Bug finding: In factory.py, '(backend or cfg.memory_backend)' treats '' as falsy,
        causing create_memory_port(backend='') to fall back to 'sqlite' instead of raising ValueError.
        """
        # Testing explicit backend="" argument
        with pytest.raises(ValueError, match="Unsupported memory backend"):
            create_memory_port(backend="")

        with pytest.raises(ValueError, match="Unsupported catalog backend"):
            create_catalog_port(backend="")
