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

"""Hermetic unit & integration test suite for Carefold REST Memory API endpoints.

Covers Requirement R4 & Milestone M4:
- GET /api/memory (Recall, tier filtering, namespace isolation, pagination limit, empty results)
- DELETE /api/memory/{key} (Deletion, non-existent key safety, namespace scoping, idempotency)
- GET /api/memory/status (Healthy state, degraded/fallback state, backend identification)
- Backend parity across SQLite FTS5 and Spector Cognitive Memory
- Zero-Mock compliance with test doubles strictly confined to backend/tests/
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, AsyncIterator, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# Ensure tests directory is importable for test doubles
_tests_dir = str(Path(__file__).resolve().parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from carefold.api.deps import get_current_memory_port
from carefold.config import settings
from carefold.main import app
from carefold.memory.adapters.spector.memory_adapter import SpectorMemoryAdapter
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import (
    create_memory_port,
    get_memory_port,
    reset_memory_ports,
    set_memory_port,
)
from carefold.memory.ports.memory_port import MemoryPort, MemoryTier

# Zero-Mock test doubles confined to backend/tests/
try:
    from tests.test_spector_store_adapter import SimulatedAsyncMemoryClient
except ImportError:
    from test_spector_store_adapter import SimulatedAsyncMemoryClient

try:
    from tests.test_memory_fallback import ControllableAsyncMemoryClient
except ImportError:
    from test_memory_fallback import ControllableAsyncMemoryClient


# =============================================================================
# Fixtures & Hermetic Test Environment
# =============================================================================

@pytest.fixture(autouse=True)
def clean_memory_env() -> None:
    """Guarantees complete memory singleton and dependency override isolation."""
    reset_memory_ports()
    app.dependency_overrides.clear()
    yield
    reset_memory_ports()
    app.dependency_overrides.clear()


@pytest.fixture
def sqlite_port(tmp_path: Path) -> SqliteMemoryAdapter:
    """Provides an isolated SQLite memory adapter using a temporary database."""
    db_file = tmp_path / "test_memory.db"
    port = SqliteMemoryAdapter(db_path=db_file)
    set_memory_port(port)
    return port


@pytest.fixture
def spector_port() -> SpectorMemoryAdapter:
    """Provides an isolated Spector memory adapter wired to an in-memory simulated client."""
    sim_client = SimulatedAsyncMemoryClient()
    port = SpectorMemoryAdapter(client=sim_client, fallback_to_sqlite=True)
    set_memory_port(port)
    return port


@pytest.fixture
def client(temp_workspace: Path) -> TestClient:
    """Standard synchronous FastAPI test client."""
    return TestClient(app)


@pytest.fixture
async def async_client(temp_workspace: Path) -> AsyncIterator[AsyncClient]:
    """Asynchronous HTTP test client using ASGITransport."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


# =============================================================================
# 1. GET /api/memory: Recall, Tier Filtering, Namespace & Pagination
# =============================================================================

class TestMemoryRecallApi:
    """Test suite for GET /api/memory endpoint."""

    def test_recall_empty_store_returns_empty_list(self, client: TestClient, sqlite_port: MemoryPort):
        """Empty memory store returns 200 OK and an empty list []."""
        res = client.get("/api/memory")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_recall_with_valid_query_returns_matching_items(self, client: TestClient, sqlite_port: MemoryPort):
        """Recall with a search query returns matching memory items with 200 OK."""
        asyncio.run(sqlite_port.remember(
            key="med_metformin",
            value={"name": "Metformin", "dose": "500mg"},
            tier=MemoryTier.SEMANTIC,
            namespace="default",
            metadata={"source": "ehr"},
        ))
        asyncio.run(sqlite_port.remember(
            key="med_lisinopril",
            value={"name": "Lisinopril", "dose": "10mg"},
            tier=MemoryTier.SEMANTIC,
            namespace="default",
            metadata={"source": "ehr"},
        ))

        res = client.get("/api/memory?query=Metformin")
        assert res.status_code == 200
        items = res.json()
        assert isinstance(items, list)
        assert len(items) == 1
        assert items[0]["key"] == "med_metformin"
        assert items[0]["value"]["name"] == "Metformin"
        assert items[0]["tier"] == "semantic"
        assert items[0]["namespace"] == "default"
        assert items[0]["metadata"]["source"] == "ehr"
        assert "salience" in items[0]
        assert "created_at" in items[0]

    def test_recall_filtering_by_tier(self, client: TestClient, sqlite_port: MemoryPort):
        """Filtering by tier returns only memories belonging to that cognitive tier."""
        asyncio.run(sqlite_port.remember(
            key="scratch_1",
            value="Active task scratchpad note",
            tier=MemoryTier.WORKING,
            namespace="default",
        ))
        asyncio.run(sqlite_port.remember(
            key="turn_1",
            value="Patient mentioned shortness of breath on exertion",
            tier=MemoryTier.EPISODIC,
            namespace="default",
        ))
        asyncio.run(sqlite_port.remember(
            key="fact_1",
            value="Patient has penicillin allergy",
            tier=MemoryTier.SEMANTIC,
            namespace="default",
        ))
        asyncio.run(sqlite_port.remember(
            key="protocol_1",
            value="Hypertension Stage 2 guideline checklist",
            tier=MemoryTier.PROCEDURAL,
            namespace="default",
        ))

        # 1. Query tier=working
        res_working = client.get("/api/memory?tier=working")
        assert res_working.status_code == 200
        working_items = res_working.json()
        assert len(working_items) == 1
        assert working_items[0]["key"] == "scratch_1"
        assert working_items[0]["tier"] == "working"

        # 2. Query tier=episodic
        res_episodic = client.get("/api/memory?tier=episodic")
        assert res_episodic.status_code == 200
        episodic_items = res_episodic.json()
        assert len(episodic_items) == 1
        assert episodic_items[0]["key"] == "turn_1"
        assert episodic_items[0]["tier"] == "episodic"

        # 3. Query tier=semantic
        res_semantic = client.get("/api/memory?tier=semantic")
        assert res_semantic.status_code == 200
        semantic_items = res_semantic.json()
        assert len(semantic_items) == 1
        assert semantic_items[0]["key"] == "fact_1"
        assert semantic_items[0]["tier"] == "semantic"

        # 4. Query tier=procedural
        res_proc = client.get("/api/memory?tier=procedural")
        assert res_proc.status_code == 200
        proc_items = res_proc.json()
        assert len(proc_items) == 1
        assert proc_items[0]["key"] == "protocol_1"
        assert proc_items[0]["tier"] == "procedural"

    def test_recall_tier_case_insensitivity(self, client: TestClient, sqlite_port: MemoryPort):
        """Tier filter parameter is evaluated case-insensitively."""
        asyncio.run(sqlite_port.remember(
            key="k_upper",
            value="Case test item",
            tier=MemoryTier.EPISODIC,
            namespace="default",
        ))

        res_upper = client.get("/api/memory?tier=EPISODIC")
        assert res_upper.status_code == 200
        items = res_upper.json()
        assert len(items) == 1
        assert items[0]["key"] == "k_upper"

    def test_recall_invalid_tier_returns_400(self, client: TestClient, sqlite_port: MemoryPort):
        """Invalid tier returns HTTP 400 Bad Request."""
        res = client.get("/api/memory?tier=nonexistent_tier_xyz")
        assert res.status_code == 400
        assert "Invalid memory tier" in res.json()["detail"]

    def test_recall_custom_namespace_isolation(self, client: TestClient, sqlite_port: MemoryPort):
        """Memories stored in distinct namespaces are strictly isolated."""
        asyncio.run(sqlite_port.remember(
            key="note",
            value="Patient A notes",
            tier=MemoryTier.SEMANTIC,
            namespace="patient_a",
        ))
        asyncio.run(sqlite_port.remember(
            key="note",
            value="Patient B notes",
            tier=MemoryTier.SEMANTIC,
            namespace="patient_b",
        ))

        # Query patient_a
        res_a = client.get("/api/memory?namespace=patient_a")
        assert res_a.status_code == 200
        items_a = res_a.json()
        assert len(items_a) == 1
        assert items_a[0]["value"] == "Patient A notes"
        assert items_a[0]["namespace"] == "patient_a"

        # Query patient_b
        res_b = client.get("/api/memory?namespace=patient_b")
        assert res_b.status_code == 200
        items_b = res_b.json()
        assert len(items_b) == 1
        assert items_b[0]["value"] == "Patient B notes"
        assert items_b[0]["namespace"] == "patient_b"

        # Query default (unpopulated)
        res_def = client.get("/api/memory?namespace=default")
        assert res_def.status_code == 200
        assert len(res_def.json()) == 0

    def test_recall_pagination_limit(self, client: TestClient, sqlite_port: MemoryPort):
        """Limit parameter caps the number of returned records."""
        for i in range(5):
            asyncio.run(sqlite_port.remember(
                key=f"item_{i}",
                value=f"Memory record number {i}",
                tier=MemoryTier.SEMANTIC,
                namespace="default",
            ))

        res = client.get("/api/memory?limit=2")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 2

    def test_recall_invalid_limit_boundary(self, client: TestClient, sqlite_port: MemoryPort):
        """Limit values <= 0 return HTTP 422 Unprocessable Entity."""
        res_zero = client.get("/api/memory?limit=0")
        assert res_zero.status_code == 422

        res_neg = client.get("/api/memory?limit=-5")
        assert res_neg.status_code == 422

    def test_recall_complex_payload_fidelity(self, client: TestClient, sqlite_port: MemoryPort):
        """Nested dictionaries, lists, and numerical values retain exact types."""
        complex_value = {
            "lab_results": [
                {"test": "A1C", "value": 6.8, "unit": "%"},
                {"test": "eGFR", "value": 92, "unit": "mL/min"},
            ],
            "abnormal": True,
            "count": 2,
        }
        asyncio.run(sqlite_port.remember(
            key="labs_2026",
            value=complex_value,
            tier=MemoryTier.SEMANTIC,
            namespace="default",
        ))

        res = client.get("/api/memory?query=A1C")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        assert items[0]["value"] == complex_value


# =============================================================================
# 2. DELETE /api/memory/{key}: Removal, Safety, Scoping & Idempotency
# =============================================================================

class TestMemoryDeleteApi:
    """Test suite for DELETE /api/memory/{key} endpoint."""

    def test_delete_existing_key_returns_true(self, client: TestClient, sqlite_port: MemoryPort):
        """Deleting an existing memory returns {"deleted": true, "key": ..., "namespace": ...}."""
        asyncio.run(sqlite_port.remember(
            key="to_delete",
            value="Temporary memory",
            tier=MemoryTier.WORKING,
            namespace="default",
        ))

        res = client.delete("/api/memory/to_delete")
        assert res.status_code == 200
        data = res.json()
        assert data["deleted"] is True
        assert data["key"] == "to_delete"
        assert data["namespace"] == "default"

        # Verify removal via subsequent recall
        recall_res = client.get("/api/memory?query=Temporary")
        assert recall_res.status_code == 200
        assert len(recall_res.json()) == 0

    def test_delete_non_existent_key_returns_false_without_500(self, client: TestClient, sqlite_port: MemoryPort):
        """Deleting a non-existent key returns {"deleted": false, ...} with 200 OK (never 500)."""
        res = client.delete("/api/memory/definitely_missing_key_12345")
        assert res.status_code == 200
        data = res.json()
        assert data["deleted"] is False
        assert data["key"] == "definitely_missing_key_12345"
        assert data["namespace"] == "default"

    def test_delete_in_specific_namespace(self, client: TestClient, sqlite_port: MemoryPort):
        """Deletion in one namespace does not affect identical keys in other namespaces."""
        key = "shared_key_name"
        asyncio.run(sqlite_port.remember(
            key=key,
            value="Value in Scope 1",
            tier=MemoryTier.SEMANTIC,
            namespace="scope_1",
        ))
        asyncio.run(sqlite_port.remember(
            key=key,
            value="Value in Scope 2",
            tier=MemoryTier.SEMANTIC,
            namespace="scope_2",
        ))

        # Delete from scope_1
        res = client.delete(f"/api/memory/{key}?namespace=scope_1")
        assert res.status_code == 200
        assert res.json()["deleted"] is True
        assert res.json()["namespace"] == "scope_1"

        # Verify scope_1 is empty, but scope_2 persists
        res_scope1 = client.get("/api/memory?namespace=scope_1")
        assert len(res_scope1.json()) == 0

        res_scope2 = client.get("/api/memory?namespace=scope_2")
        assert len(res_scope2.json()) == 1
        assert res_scope2.json()[0]["value"] == "Value in Scope 2"

    def test_delete_idempotency(self, client: TestClient, sqlite_port: MemoryPort):
        """Consecutive deletes on the same key succeed with True on first and False on second."""
        asyncio.run(sqlite_port.remember(
            key="idempotent_key",
            value="Ephemeral",
            tier=MemoryTier.WORKING,
            namespace="default",
        ))

        res1 = client.delete("/api/memory/idempotent_key")
        assert res1.status_code == 200
        assert res1.json()["deleted"] is True

        res2 = client.delete("/api/memory/idempotent_key")
        assert res2.status_code == 200
        assert res2.json()["deleted"] is False

    def test_delete_special_characters_key(self, client: TestClient, sqlite_port: MemoryPort):
        """Keys containing hyphens and underscores delete without route error."""
        special_key = "session-123_turn-456"
        asyncio.run(sqlite_port.remember(
            key=special_key,
            value="Special key content",
            tier=MemoryTier.WORKING,
            namespace="default",
        ))

        res = client.delete(f"/api/memory/{special_key}")
        assert res.status_code == 200
        assert res.json()["deleted"] is True
        assert res.json()["key"] == special_key


# =============================================================================
# 3. GET /api/memory/status: Backend Identification & Resilient Fallback
# =============================================================================

class TestMemoryStatusApi:
    """Test suite for GET /api/memory/status endpoint."""

    def test_status_sqlite_healthy(self, client: TestClient, sqlite_port: MemoryPort):
        """Status endpoint reports healthy SQLite backend when SQLite adapter is active."""
        res = client.get("/api/memory/status")
        assert res.status_code == 200
        data = res.json()
        assert data["backend"] == "sqlite"
        assert data["healthy"] is True
        assert data["fallback_active"] is False
        assert "spector_url" in data
        assert data["cooldown_seconds"] >= 0.0

    def test_status_spector_healthy(self, client: TestClient, spector_port: MemoryPort):
        """Status endpoint reports healthy Spector backend when Spector adapter is active."""
        res = client.get("/api/memory/status")
        assert res.status_code == 200
        data = res.json()
        assert data["backend"] == "spector"
        assert data["healthy"] is True
        assert data["fallback_active"] is False
        assert "spector_url" in data
        assert "7070" in str(data["spector_url"])
        assert data["cooldown_seconds"] == 30.0

    def test_status_spector_degraded_fallback_active(self, client: TestClient):
        """When Spector is unreachable and fallback is triggered, status reports fallback_active=True."""
        unhealthy_client = ControllableAsyncMemoryClient(healthy=False)
        adapter = SpectorMemoryAdapter(client=unhealthy_client, fallback_to_sqlite=True)
        set_memory_port(adapter)

        # Trigger a memory write to cause circuit breaker trip to fallback
        asyncio.run(adapter.remember(
            key="fallback_trigger",
            value="Triggering fallback",
            tier=MemoryTier.WORKING,
            namespace="default",
        ))
        assert adapter.fallback_active is True

        res = client.get("/api/memory/status")
        assert res.status_code == 200
        data = res.json()
        assert data["backend"] == "spector"
        assert data["fallback_active"] is True
        assert data["healthy"] is False
        assert "spector_url" in data


# =============================================================================
# 4. Backend Parity Tests: SQLite vs Spector Seamless Equivalence
# =============================================================================

class TestMemoryApiBackendParity:
    """Verifies that both SQLite and Spector adapters yield identical observable API behavior."""

    @pytest.mark.parametrize("adapter_type", ["sqlite", "spector"])
    def test_parity_remember_recall_and_delete(
        self,
        client: TestClient,
        tmp_path: Path,
        adapter_type: str,
    ):
        """Verifies full roundtrip lifecycle parity between SQLite and Spector adapters."""
        if adapter_type == "sqlite":
            adapter = SqliteMemoryAdapter(db_path=tmp_path / f"{adapter_type}.db")
        else:
            adapter = SpectorMemoryAdapter(client=SimulatedAsyncMemoryClient())
        set_memory_port(adapter)

        # 1. Initially empty
        res_empty = client.get("/api/memory")
        assert res_empty.status_code == 200
        assert res_empty.json() == []

        # 2. Add item via adapter
        asyncio.run(adapter.remember(
            key="parity_item",
            value={"diagnosis": "Hypertension"},
            tier=MemoryTier.SEMANTIC,
            namespace="clinical",
        ))

        # 3. Recall item
        res_recall = client.get("/api/memory?query=Hypertension&namespace=clinical")
        assert res_recall.status_code == 200
        items = res_recall.json()
        assert len(items) == 1
        assert items[0]["key"] == "parity_item"
        assert items[0]["value"]["diagnosis"] == "Hypertension"
        assert items[0]["namespace"] == "clinical"

        # 4. Delete item
        res_del = client.delete("/api/memory/parity_item?namespace=clinical")
        assert res_del.status_code == 200
        assert res_del.json()["deleted"] is True

        # 5. Verify deleted
        res_after = client.get("/api/memory?namespace=clinical")
        assert res_after.status_code == 200
        assert res_after.json() == []


# =============================================================================
# 5. Dependency Injection Override & AsyncClient Transport Tests
# =============================================================================

class TestMemoryApiAdvancedTransports:
    """Tests dependency injection overrides and asynchronous client transports."""

    def test_dependency_override_custom_memory_port(self, client: TestClient, tmp_path: Path):
        """Verifies that app.dependency_overrides[get_current_memory_port] properly overrides resolution."""
        custom_port = SqliteMemoryAdapter(db_path=tmp_path / "custom_override.db")
        asyncio.run(custom_port.remember(
            key="override_key",
            value="Overridden memory value",
            tier=MemoryTier.WORKING,
            namespace="override_ns",
        ))

        # Override dependency explicitly
        app.dependency_overrides[get_current_memory_port] = lambda: custom_port

        res = client.get("/api/memory?namespace=override_ns")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        assert items[0]["key"] == "override_key"
        assert items[0]["value"] == "Overridden memory value"

    @pytest.mark.asyncio
    async def test_async_client_memory_api_roundtrip(
        self,
        async_client: AsyncClient,
        tmp_path: Path,
    ):
        """Verifies non-blocking asynchronous execution over ASGITransport."""
        port = SqliteMemoryAdapter(db_path=tmp_path / "async_test.db")
        set_memory_port(port)

        await port.remember(
            key="async_key",
            value="Async test payload",
            tier=MemoryTier.EPISODIC,
            namespace="default",
        )

        # Async GET recall
        res_get = await async_client.get("/api/memory?query=Async")
        assert res_get.status_code == 200
        data = res_get.json()
        assert len(data) == 1
        assert data[0]["key"] == "async_key"

        # Async GET status
        res_status = await async_client.get("/api/memory/status")
        assert res_status.status_code == 200
        assert res_status.json()["backend"] == "sqlite"

        # Async DELETE
        res_del = await async_client.delete("/api/memory/async_key")
        assert res_del.status_code == 200
        assert res_del.json()["deleted"] is True
