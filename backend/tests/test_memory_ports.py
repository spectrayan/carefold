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

"""Unit tests for MemoryPort contract and SqliteMemoryAdapter."""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from carefold.memory import CatalogPort, MemoryPort, MemoryTier
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.ports import (
    CatalogPort as SubCatalogPort,
    MemoryPort as SubMemoryPort,
    MemoryTier as SubMemoryTier,
)


class TestMemoryTierEnum:
    """Verifies MemoryTier enum definitions and values."""

    def test_enum_values(self) -> None:
        assert MemoryTier.WORKING.value == "working"
        assert MemoryTier.EPISODIC.value == "episodic"
        assert MemoryTier.SEMANTIC.value == "semantic"
        assert MemoryTier.PROCEDURAL.value == "procedural"

    def test_enum_subclass_string(self) -> None:
        assert issubclass(MemoryTier, str)
        assert issubclass(MemoryTier, Enum)
        assert isinstance(MemoryTier.WORKING, str)
        assert MemoryTier("working") == MemoryTier.WORKING

    def test_reexports(self) -> None:
        assert MemoryTier is SubMemoryTier
        assert MemoryPort is SubMemoryPort
        assert CatalogPort is SubCatalogPort


class TestMemoryPortContract:
    """Verifies that MemoryPort enforces its abstract interface."""

    def test_cannot_instantiate_abstract_memory_port(self) -> None:
        with pytest.raises(TypeError) as exc_info:
            MemoryPort()  # type: ignore[abstract]
        error_msg = str(exc_info.value)
        assert "Can't instantiate abstract class" in error_msg
        for method in ("remember", "recall", "forget", "reinforce"):
            assert method in error_msg

    @pytest.mark.asyncio
    async def test_concrete_mock_implementation(self) -> None:
        class InMemoryMemoryAdapter(MemoryPort):
            def __init__(self) -> None:
                self.storage: Dict[str, Dict[str, Any]] = {}

            async def remember(
                self,
                key: str,
                value: Any,
                tier: MemoryTier,
                namespace: str = "default",
                metadata: Optional[Dict[str, Any]] = None,
            ) -> None:
                ns_key = f"{namespace}:{key}"
                self.storage[ns_key] = {
                    "key": key,
                    "value": value,
                    "tier": tier,
                    "namespace": namespace,
                    "metadata": metadata or {},
                    "salience": 1.0,
                }

            async def recall(
                self,
                query: str,
                tier: Optional[MemoryTier] = None,
                namespace: str = "default",
                limit: int = 10,
            ) -> List[Dict[str, Any]]:
                results = []
                for item in self.storage.values():
                    if item["namespace"] != namespace:
                        continue
                    if tier is not None and item["tier"] != tier:
                        continue
                    if query and query.lower() not in str(item["value"]).lower():
                        continue
                    results.append(item)
                return results[:limit]

            async def forget(self, key: str, namespace: str = "default") -> bool:
                ns_key = f"{namespace}:{key}"
                if ns_key in self.storage:
                    del self.storage[ns_key]
                    return True
                return False

            async def reinforce(
                self,
                key: str,
                namespace: str = "default",
                delta: float = 0.1,
            ) -> None:
                ns_key = f"{namespace}:{key}"
                if ns_key in self.storage:
                    self.storage[ns_key]["salience"] = max(0.0, self.storage[ns_key]["salience"] + delta)

            async def get(self, key: str, namespace: str = "default") -> Optional[Dict[str, Any]]:
                ns_key = f"{namespace}:{key}"
                return self.storage.get(ns_key)

            async def forget_all(self, namespace: str = "default") -> int:
                to_del = [k for k, v in self.storage.items() if v["namespace"] == namespace]
                for k in to_del:
                    del self.storage[k]
                return len(to_del)

        adapter = InMemoryMemoryAdapter()
        await adapter.remember("note_1", "Patient has penicillin allergy", MemoryTier.SEMANTIC, namespace="user:42")
        await adapter.remember("note_2", "Follow up next week", MemoryTier.EPISODIC, namespace="user:42")
        await adapter.remember("scratch", "Draft calculation", MemoryTier.WORKING, namespace="user:42")

        # Cross-namespace isolation
        await adapter.remember("note_1", "Other user data", MemoryTier.SEMANTIC, namespace="user:99")

        # Recall all in user:42
        recalled = await adapter.recall("", namespace="user:42")
        assert len(recalled) == 3

        # Recall by tier
        semantic = await adapter.recall("", tier=MemoryTier.SEMANTIC, namespace="user:42")
        assert len(semantic) == 1
        assert semantic[0]["key"] == "note_1"
        assert semantic[0]["value"] == "Patient has penicillin allergy"

        # Recall by query
        queried = await adapter.recall("penicillin", namespace="user:42")
        assert len(queried) == 1
        assert queried[0]["key"] == "note_1"

        # Reinforce
        await adapter.reinforce("note_1", namespace="user:42", delta=0.5)
        recalled_boost = await adapter.recall("penicillin", namespace="user:42")
        assert recalled_boost[0]["salience"] == 1.5

        # Forget
        assert await adapter.forget("note_1", namespace="user:42") is True
        assert await adapter.forget("note_1", namespace="user:42") is False
        assert len(await adapter.recall("penicillin", namespace="user:42")) == 0

        # Close no-op
        await adapter.close()


class TestSqliteMemoryAdapterCRUD:
    """Verifies SQLite memory adapter CRUD, tiers, salience, and isolation."""

    @pytest.fixture
    async def memory_adapter(self, tmp_path: Path):
        """Creates an isolated SqliteMemoryAdapter with a temporary database."""
        db_file = tmp_path / "test_memory.db"
        adapter = SqliteMemoryAdapter(db_path=db_file)
        yield adapter
        await adapter.close()

    @pytest.mark.asyncio
    async def test_remember_and_recall_basic(self, memory_adapter: SqliteMemoryAdapter) -> None:
        await memory_adapter.remember(
            key="allergy_penicillin",
            value="Patient reported severe rash and hives from Penicillin in 2021",
            tier=MemoryTier.SEMANTIC,
            namespace="user_101",
            metadata={"source": "intake_form"},
        )

        results = await memory_adapter.recall(
            query="Penicillin",
            namespace="user_101",
        )

        assert len(results) >= 1
        item = results[0]
        assert item["key"] == "allergy_penicillin"
        assert "Penicillin" in str(item["value"])
        assert item["tier"] == MemoryTier.SEMANTIC or item["tier"] == "semantic"
        assert item["namespace"] == "user_101"
        assert item["metadata"].get("source") == "intake_form"
        assert item["salience"] == 1.0
        assert "created_at" in item
        assert "updated_at" in item

    @pytest.mark.asyncio
    async def test_remember_upsert_behavior(self, memory_adapter: SqliteMemoryAdapter) -> None:
        # Initial insertion
        await memory_adapter.remember(
            key="bp_reading",
            value="120/80 mmHg",
            tier=MemoryTier.EPISODIC,
            namespace="user_101",
        )
        # Update same key
        await memory_adapter.remember(
            key="bp_reading",
            value="135/88 mmHg (elevated on retake)",
            tier=MemoryTier.EPISODIC,
            namespace="user_101",
        )

        results = await memory_adapter.recall(query="elevated", namespace="user_101")
        assert len(results) == 1
        assert results[0]["key"] == "bp_reading"
        assert "135/88" in str(results[0]["value"])

    @pytest.mark.asyncio
    async def test_cognitive_memory_tiers_filtering(self, memory_adapter: SqliteMemoryAdapter) -> None:
        await memory_adapter.remember("scratch", "Calculate deductible $1500", MemoryTier.WORKING, "user_101")
        await memory_adapter.remember("visit", "Attended cardiology appointment", MemoryTier.EPISODIC, "user_101")
        await memory_adapter.remember("profile", "Hypertension diagnosed 2020", MemoryTier.SEMANTIC, "user_101")
        await memory_adapter.remember("sop", "Step 1: check copay before booking", MemoryTier.PROCEDURAL, "user_101")

        # Specific tier search
        working = await memory_adapter.recall("", tier=MemoryTier.WORKING, namespace="user_101")
        assert len(working) == 1
        assert working[0]["key"] == "scratch"

        semantic = await memory_adapter.recall("", tier=MemoryTier.SEMANTIC, namespace="user_101")
        assert len(semantic) == 1
        assert semantic[0]["key"] == "profile"

        procedural = await memory_adapter.recall("", tier=MemoryTier.PROCEDURAL, namespace="user_101")
        assert len(procedural) == 1
        assert procedural[0]["key"] == "sop"

        # Search across all tiers
        all_records = await memory_adapter.recall("", tier=None, namespace="user_101", limit=10)
        assert len(all_records) == 4

    @pytest.mark.asyncio
    async def test_namespace_isolation(self, memory_adapter: SqliteMemoryAdapter) -> None:
        await memory_adapter.remember("secret_ssn", "SSN: 000-11-2222", MemoryTier.SEMANTIC, "tenant_alice")
        await memory_adapter.remember("secret_ssn", "SSN: 999-88-7777", MemoryTier.SEMANTIC, "tenant_bob")

        # Alice should never see Bob's data
        alice_data = await memory_adapter.recall("SSN", namespace="tenant_alice")
        assert len(alice_data) == 1
        assert "000-11-2222" in str(alice_data[0]["value"])
        assert "999-88-7777" not in str(alice_data[0]["value"])

        # Charlie (empty namespace) sees nothing
        charlie_data = await memory_adapter.recall("SSN", namespace="tenant_charlie")
        assert len(charlie_data) == 0

        # Deleting Alice's record does not affect Bob
        deleted = await memory_adapter.forget("secret_ssn", namespace="tenant_alice")
        assert deleted is True

        bob_data = await memory_adapter.recall("SSN", namespace="tenant_bob")
        assert len(bob_data) == 1
        assert "999-88-7777" in str(bob_data[0]["value"])

    @pytest.mark.asyncio
    async def test_forget_behavior(self, memory_adapter: SqliteMemoryAdapter) -> None:
        await memory_adapter.remember("note_to_delete", "Temporary memo", MemoryTier.WORKING, "user_101")

        # First delete should succeed
        assert await memory_adapter.forget("note_to_delete", namespace="user_101") is True
        # Second delete of non-existent key returns False
        assert await memory_adapter.forget("note_to_delete", namespace="user_101") is False

        remaining = await memory_adapter.recall("Temporary", namespace="user_101")
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_reinforce_salience(self, memory_adapter: SqliteMemoryAdapter) -> None:
        await memory_adapter.remember("priority_note", "Crucial medical instruction", MemoryTier.SEMANTIC, "user_101")

        # Reinforce with positive delta
        await memory_adapter.reinforce("priority_note", namespace="user_101", delta=0.5)
        results = await memory_adapter.recall("Crucial", namespace="user_101")
        assert len(results) == 1
        assert results[0]["salience"] > 1.0

        # Decay with negative delta clamped at 0.0
        await memory_adapter.reinforce("priority_note", namespace="user_101", delta=-5.0)
        decayed = await memory_adapter.recall("Crucial", namespace="user_101")
        assert len(decayed) == 1
        assert decayed[0]["salience"] == 0.0

        # Reinforce non-existent key completes without crashing
        await memory_adapter.reinforce("non_existent_key", namespace="user_101", delta=0.5)

    @pytest.mark.asyncio
    async def test_structured_dictionary_value(self, memory_adapter: SqliteMemoryAdapter) -> None:
        vitals = {"systolic": 118, "diastolic": 76, "pulse": 72, "spo2": 99}
        await memory_adapter.remember("vitals_today", vitals, MemoryTier.EPISODIC, "user_101")

        results = await memory_adapter.recall("118", namespace="user_101")
        assert len(results) == 1
        retrieved_val = results[0]["value"]
        assert isinstance(retrieved_val, dict)
        assert retrieved_val["systolic"] == 118
        assert retrieved_val["diastolic"] == 76

    @pytest.mark.asyncio
    async def test_get_by_key(self, memory_adapter: SqliteMemoryAdapter) -> None:
        await memory_adapter.remember("item_k", "Direct fetch content", MemoryTier.SEMANTIC, "user_101")
        fetched = await memory_adapter.get("item_k", "user_101")
        assert fetched is not None
        assert fetched["key"] == "item_k"
        assert fetched["value"] == "Direct fetch content"

        missing = await memory_adapter.get("missing_key", "user_101")
        assert missing is None

    @pytest.mark.asyncio
    async def test_in_memory_persistence_across_calls(self) -> None:
        adapter = SqliteMemoryAdapter(db_path=":memory:")
        try:
            await adapter.remember("key1", "val1", MemoryTier.WORKING, "ns")
            res = await adapter.recall("val1", namespace="ns")
            assert len(res) == 1
            assert res[0]["value"] == "val1"

            await adapter.remember("key2", "val2", MemoryTier.WORKING, "ns")
            res2 = await adapter.recall("", namespace="ns")
            assert len(res2) == 2
        finally:
            await adapter.close()

    @pytest.mark.asyncio
    async def test_async_context_manager(self, tmp_path: Path) -> None:
        db_file = tmp_path / "ctx_memory.db"
        async with SqliteMemoryAdapter(db_path=db_file) as adapter:
            await adapter.remember("key_ctx", "val_ctx", MemoryTier.SEMANTIC)
            res = await adapter.recall("val_ctx")
            assert len(res) == 1
