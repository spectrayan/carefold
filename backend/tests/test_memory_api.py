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

"""Hermetic unit & integration test suite for Carefold REST Memory API endpoints.

Covers Requirement R4 & Milestone Phase4:
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
from carefold.api.memory import resolve_effective_namespace
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
def sqlite_port(tmp_path: Path):
    """Provides an isolated SQLite memory adapter using a temporary database."""
    db_file = tmp_path / "test_memory.db"
    port = SqliteMemoryAdapter(db_path=db_file)
    set_memory_port(port)
    try:
        yield port
    finally:
        try:
            if hasattr(port, "_conn") and port._conn is not None:
                port._conn.stop()
        except Exception:
            pass


@pytest.fixture
def spector_port():
    """Provides an isolated Spector memory adapter wired to an in-memory simulated client."""
    sim_client = SimulatedAsyncMemoryClient()
    port = SpectorMemoryAdapter(client=sim_client, fallback_to_sqlite=True)
    set_memory_port(port)
    try:
        yield port
    finally:
        try:
            if hasattr(port, "close_sync"):
                port.close_sync()
            elif hasattr(port, "close"):
                res = port.close()
                if hasattr(res, "__await__"):
                    asyncio.run(res)
        except Exception:
            pass


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


@pytest.fixture
def test_profile(client: TestClient) -> str:
    """Provides a valid care profile for deep entity scoping."""
    from carefold.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
    from carefold.db.models import User
    from carefold.db.session import get_session_factory

    async def _ensure_steward():
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, DEFAULT_STEWARD_USER.id)
            if not user:
                user = User(
                    id=DEFAULT_STEWARD_USER.id,
                    email="steward@carefold.ai",
                    username="steward",
                    hashed_password="mock",
                    role="steward",
                    status="active",
                    auth_provider="disabled",
                )
                session.add(user)
                await session.commit()

    asyncio.run(_ensure_steward())
    res = client.post("/api/profiles", json={"name": "Test Memory Patient", "relationship": "self"})
    assert res.status_code == 201
    return res.json()["id"]


# =============================================================================
# 1. GET /api/memory: Recall, Tier Filtering, Namespace & Pagination
# =============================================================================

class TestMemoryRecallApi:
    """Test suite for GET /api/memory endpoint."""

    def test_recall_empty_store_returns_empty_list(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Empty memory store returns 200 OK and an empty list []."""
        res = client.get(f"/api/memory?profile_id={test_profile}")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_recall_with_valid_query_returns_matching_items(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Recall with a search query returns matching memory items with 200 OK."""
        eff_ns = resolve_effective_namespace(None, "default", test_profile)
        asyncio.run(sqlite_port.remember(
            key="med_metformin",
            value={"name": "Metformin", "dose": "500mg"},
            tier=MemoryTier.SEMANTIC,
            namespace=eff_ns,
            metadata={"source": "ehr"},
        ))
        asyncio.run(sqlite_port.remember(
            key="med_lisinopril",
            value={"name": "Lisinopril", "dose": "10mg"},
            tier=MemoryTier.SEMANTIC,
            namespace=eff_ns,
            metadata={"source": "ehr"},
        ))

        res = client.get(f"/api/memory?query=Metformin&profile_id={test_profile}")
        assert res.status_code == 200
        items = res.json()
        assert isinstance(items, list)
        assert len(items) == 1
        assert items[0]["key"] == "med_metformin"
        assert items[0]["value"]["name"] == "Metformin"
        assert items[0]["tier"] == "semantic"
        assert items[0]["namespace"] == eff_ns
        assert items[0]["metadata"]["source"] == "ehr"
        assert "salience" in items[0]
        assert "created_at" in items[0]

    def test_recall_filtering_by_tier(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Filtering by tier returns only memories belonging to that cognitive tier."""
        eff_ns = resolve_effective_namespace(None, "default", test_profile)
        asyncio.run(sqlite_port.remember(
            key="scratch_1",
            value="Active task scratchpad note",
            tier=MemoryTier.WORKING,
            namespace=eff_ns,
        ))
        asyncio.run(sqlite_port.remember(
            key="turn_1",
            value="Patient mentioned shortness of breath on exertion",
            tier=MemoryTier.EPISODIC,
            namespace=eff_ns,
        ))
        asyncio.run(sqlite_port.remember(
            key="fact_1",
            value="Patient has penicillin allergy",
            tier=MemoryTier.SEMANTIC,
            namespace=eff_ns,
        ))
        asyncio.run(sqlite_port.remember(
            key="protocol_1",
            value="Hypertension Stage 2 guideline checklist",
            tier=MemoryTier.PROCEDURAL,
            namespace=eff_ns,
        ))

        # 1. Query tier=working
        res_working = client.get(f"/api/memory?tier=working&profile_id={test_profile}")
        assert res_working.status_code == 200
        working_items = res_working.json()
        assert len(working_items) == 1
        assert working_items[0]["key"] == "scratch_1"
        assert working_items[0]["tier"] == "working"

        # 2. Query tier=episodic
        res_episodic = client.get(f"/api/memory?tier=episodic&profile_id={test_profile}")
        assert res_episodic.status_code == 200
        episodic_items = res_episodic.json()
        assert len(episodic_items) == 1
        assert episodic_items[0]["key"] == "turn_1"
        assert episodic_items[0]["tier"] == "episodic"

        # 3. Query tier=semantic
        res_semantic = client.get(f"/api/memory?tier=semantic&profile_id={test_profile}")
        assert res_semantic.status_code == 200
        semantic_items = res_semantic.json()
        assert len(semantic_items) == 1
        assert semantic_items[0]["key"] == "fact_1"
        assert semantic_items[0]["tier"] == "semantic"

        # 4. Query tier=procedural
        res_proc = client.get(f"/api/memory?tier=procedural&profile_id={test_profile}")
        assert res_proc.status_code == 200
        proc_items = res_proc.json()
        assert len(proc_items) == 1
        assert proc_items[0]["key"] == "protocol_1"
        assert proc_items[0]["tier"] == "procedural"

    def test_recall_tier_case_insensitivity(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Tier filter parameter is evaluated case-insensitively."""
        eff_ns = resolve_effective_namespace(None, "default", test_profile)
        asyncio.run(sqlite_port.remember(
            key="k_upper",
            value="Case test item",
            tier=MemoryTier.EPISODIC,
            namespace=eff_ns,
        ))

        res_upper = client.get(f"/api/memory?tier=EPISODIC&profile_id={test_profile}")
        assert res_upper.status_code == 200
        items = res_upper.json()
        assert len(items) == 1
        assert items[0]["key"] == "k_upper"

    def test_recall_invalid_tier_returns_400(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Invalid tier returns HTTP 400 Bad Request."""
        res = client.get(f"/api/memory?tier=nonexistent_tier_xyz&profile_id={test_profile}")
        assert res.status_code == 400
        assert "Invalid memory tier" in res.json()["detail"]

    def test_recall_custom_namespace_isolation(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Memories stored in distinct namespaces are strictly isolated."""
        ns_a = resolve_effective_namespace(None, "patient_a", test_profile)
        ns_b = resolve_effective_namespace(None, "patient_b", test_profile)
        asyncio.run(sqlite_port.remember(
            key="note",
            value="Patient A notes",
            tier=MemoryTier.SEMANTIC,
            namespace=ns_a,
        ))
        asyncio.run(sqlite_port.remember(
            key="note",
            value="Patient B notes",
            tier=MemoryTier.SEMANTIC,
            namespace=ns_b,
        ))

        # Query patient_a
        res_a = client.get(f"/api/memory?namespace=patient_a&profile_id={test_profile}")
        assert res_a.status_code == 200
        items_a = res_a.json()
        assert len(items_a) == 1
        assert items_a[0]["value"] == "Patient A notes"
        assert items_a[0]["namespace"] == ns_a

        # Query patient_b
        res_b = client.get(f"/api/memory?namespace=patient_b&profile_id={test_profile}")
        assert res_b.status_code == 200
        items_b = res_b.json()
        assert len(items_b) == 1
        assert items_b[0]["value"] == "Patient B notes"
        assert items_b[0]["namespace"] == ns_b

        # Query default (unpopulated)
        res_def = client.get(f"/api/memory?namespace=default&profile_id={test_profile}")
        assert res_def.status_code == 200
        assert len(res_def.json()) == 0

    def test_recall_pagination_limit(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Limit parameter caps the number of returned records."""
        eff_ns = resolve_effective_namespace(None, "default", test_profile)
        for i in range(5):
            asyncio.run(sqlite_port.remember(
                key=f"item_{i}",
                value=f"Memory record number {i}",
                tier=MemoryTier.SEMANTIC,
                namespace=eff_ns,
            ))

        res = client.get(f"/api/memory?limit=2&profile_id={test_profile}")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 2

    def test_recall_invalid_limit_boundary(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Limit values <= 0 return HTTP 422 Unprocessable Entity."""
        res_zero = client.get(f"/api/memory?limit=0&profile_id={test_profile}")
        assert res_zero.status_code == 422

        res_neg = client.get(f"/api/memory?limit=-5&profile_id={test_profile}")
        assert res_neg.status_code == 422

    def test_recall_complex_payload_fidelity(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Nested dictionaries, lists, and numerical values retain exact types."""
        eff_ns = resolve_effective_namespace(None, "default", test_profile)
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
            namespace=eff_ns,
        ))

        res = client.get(f"/api/memory?query=A1C&profile_id={test_profile}")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        assert items[0]["value"] == complex_value


# =============================================================================
# 2. DELETE /api/memory/{key}: Removal, Safety, Scoping & Idempotency
# =============================================================================

class TestMemoryDeleteApi:
    """Test suite for DELETE /api/memory/{key} endpoint."""

    def test_delete_existing_key_returns_true(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Deleting an existing memory returns {"deleted": true, "key": ..., "namespace": ...}."""
        eff_ns = resolve_effective_namespace(None, "default", test_profile)
        asyncio.run(sqlite_port.remember(
            key="to_delete",
            value="Temporary memory",
            tier=MemoryTier.WORKING,
            namespace=eff_ns,
        ))

        res = client.delete(f"/api/memory/to_delete?profile_id={test_profile}")
        assert res.status_code == 200
        data = res.json()
        assert data["deleted"] is True
        assert data["key"] == "to_delete"
        assert data["namespace"] == eff_ns

        # Verify removal via subsequent recall
        recall_res = client.get(f"/api/memory?query=Temporary&profile_id={test_profile}")
        assert recall_res.status_code == 200
        assert len(recall_res.json()) == 0

    def test_delete_non_existent_key_returns_false_without_500(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Deleting a non-existent key returns {"deleted": false, ...} with 200 OK (never 500)."""
        eff_ns = resolve_effective_namespace(None, "default", test_profile)
        res = client.delete(f"/api/memory/definitely_missing_key_12345?profile_id={test_profile}")
        assert res.status_code == 200
        data = res.json()
        assert data["deleted"] is False
        assert data["key"] == "definitely_missing_key_12345"
        assert data["namespace"] == eff_ns

    def test_delete_in_specific_namespace(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Deletion in one namespace does not affect identical keys in other namespaces."""
        key = "shared_key_name"
        ns_1 = resolve_effective_namespace(None, "scope_1", test_profile)
        ns_2 = resolve_effective_namespace(None, "scope_2", test_profile)
        asyncio.run(sqlite_port.remember(
            key=key,
            value="Value in Scope 1",
            tier=MemoryTier.SEMANTIC,
            namespace=ns_1,
        ))
        asyncio.run(sqlite_port.remember(
            key=key,
            value="Value in Scope 2",
            tier=MemoryTier.SEMANTIC,
            namespace=ns_2,
        ))

        # Delete from scope_1
        res = client.delete(f"/api/memory/{key}?namespace=scope_1&profile_id={test_profile}")
        assert res.status_code == 200
        assert res.json()["deleted"] is True
        assert res.json()["namespace"] == ns_1

        # Verify scope_1 is empty, but scope_2 persists
        res_scope1 = client.get(f"/api/memory?namespace=scope_1&profile_id={test_profile}")
        assert len(res_scope1.json()) == 0

        res_scope2 = client.get(f"/api/memory?namespace=scope_2&profile_id={test_profile}")
        assert len(res_scope2.json()) == 1
        assert res_scope2.json()[0]["value"] == "Value in Scope 2"

    def test_delete_idempotency(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Consecutive deletes on the same key succeed with True on first and False on second."""
        eff_ns = resolve_effective_namespace(None, "default", test_profile)
        asyncio.run(sqlite_port.remember(
            key="idempotent_key",
            value="Ephemeral",
            tier=MemoryTier.WORKING,
            namespace=eff_ns,
        ))

        res1 = client.delete(f"/api/memory/idempotent_key?profile_id={test_profile}")
        assert res1.status_code == 200
        assert res1.json()["deleted"] is True

        res2 = client.delete(f"/api/memory/idempotent_key?profile_id={test_profile}")
        assert res2.status_code == 200
        assert res2.json()["deleted"] is False

    def test_delete_special_characters_key(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str):
        """Keys containing hyphens and underscores delete without route error."""
        eff_ns = resolve_effective_namespace(None, "default", test_profile)
        special_key = "session-123_turn-456"
        asyncio.run(sqlite_port.remember(
            key=special_key,
            value="Special key content",
            tier=MemoryTier.WORKING,
            namespace=eff_ns,
        ))

        res = client.delete(f"/api/memory/{special_key}?profile_id={test_profile}")
        assert res.status_code == 200
        assert res.json()["deleted"] is True
        assert res.json()["key"] == special_key

    def test_delete_memory_error_log_injection_sanitization(
        self,
        client: TestClient,
        sqlite_port: MemoryPort,
        test_profile: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Guards against CRLF log injection (CWE-117 / py/log-injection) during delete errors.

        Fails on pre-fix code where raw key and namespace parameters containing CRLF
        sequences are logged directly, and passes when values are sanitized before logging.
        """
        import logging
        from unittest.mock import patch
        from urllib.parse import quote

        injected_key = "record123\r\n[CRITICAL] Forged log entry from attacker"
        injected_namespace = "patient_scope\r\n[CRITICAL] Second forged log line"
        encoded_key = quote(injected_key, safe="")
        encoded_ns = quote(injected_namespace, safe="")

        with patch.object(
            sqlite_port,
            "forget",
            side_effect=RuntimeError("Simulated backend store failure during delete"),
        ):
            with caplog.at_level(logging.ERROR, logger="carefold.api.memory"):
                res = client.delete(f"/api/memory/{encoded_key}?namespace={encoded_ns}&profile_id={test_profile}")

            assert res.status_code == 500
            assert "Simulated backend store failure" in res.json()["detail"]

            # Filter records emitted by carefold.api.memory
            matching_records = [
                r for r in caplog.records if r.name == "carefold.api.memory" and r.levelno == logging.ERROR
            ]
            assert len(matching_records) >= 1
            record = matching_records[0]

            # In pre-fix code, record.message contains raw '\r' and '\n', causing log injection.
            # In post-fix code, carriage return and newline characters are neutralized.
            assert "\r" not in record.message, "Log message contains raw carriage return (\\r)"
            assert "\n" not in record.message, "Log message contains raw newline (\\n)"
            assert "\r\n" not in record.message, "Log message contains raw CRLF sequence (\\r\\n)"
            assert len(record.message.splitlines()) == 1, "Log message must not split into multiple lines"



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

        try:
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
        finally:
            if hasattr(adapter, "close_sync"):
                adapter.close_sync()


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
        test_profile: str,
    ):
        """Verifies full roundtrip lifecycle parity between SQLite and Spector adapters."""
        if adapter_type == "sqlite":
            adapter = SqliteMemoryAdapter(db_path=tmp_path / f"{adapter_type}.db")
        else:
            adapter = SpectorMemoryAdapter(client=SimulatedAsyncMemoryClient())
        set_memory_port(adapter)

        try:
            # 1. Initially empty
            res_empty = client.get(f"/api/memory?profile_id={test_profile}")
            assert res_empty.status_code == 200
            assert res_empty.json() == []

            # 2. Add item via adapter
            eff_ns = resolve_effective_namespace(None, "clinical", test_profile)
            asyncio.run(adapter.remember(
                key="parity_item",
                value={"diagnosis": "Hypertension"},
                tier=MemoryTier.SEMANTIC,
                namespace=eff_ns,
            ))

            # 3. Recall item
            res_recall = client.get(f"/api/memory?query=Hypertension&namespace=clinical&profile_id={test_profile}")
            assert res_recall.status_code == 200
            items = res_recall.json()
            assert len(items) == 1
            assert items[0]["key"] == "parity_item"
            assert items[0]["value"]["diagnosis"] == "Hypertension"
            assert items[0]["namespace"] == eff_ns

            # 4. Delete item
            res_del = client.delete(f"/api/memory/parity_item?namespace=clinical&profile_id={test_profile}")
            assert res_del.status_code == 200
            assert res_del.json()["deleted"] is True

            # 5. Verify deleted
            res_after = client.get(f"/api/memory?namespace=clinical&profile_id={test_profile}")
            assert res_after.status_code == 200
            assert res_after.json() == []
        finally:
            try:
                if hasattr(adapter, "_conn") and adapter._conn is not None:
                    adapter._conn.stop()
                elif hasattr(adapter, "close_sync"):
                    adapter.close_sync()
                elif hasattr(adapter, "close"):
                    res = adapter.close()
                    if hasattr(res, "__await__"):
                        asyncio.run(res)
            except Exception:
                pass


# =============================================================================
# 5. Dependency Injection Override & AsyncClient Transport Tests
# =============================================================================

class TestMemoryApiAdvancedTransports:
    """Tests dependency injection overrides and asynchronous client transports."""

    def test_dependency_override_custom_memory_port(self, client: TestClient, tmp_path: Path, test_profile: str):
        """Verifies that app.dependency_overrides[get_current_memory_port] properly overrides resolution."""
        custom_port = SqliteMemoryAdapter(db_path=tmp_path / "custom_override.db")
        try:
            eff_ns = resolve_effective_namespace(None, "override_ns", test_profile)
            asyncio.run(custom_port.remember(
                key="override_key",
                value="Overridden memory value",
                tier=MemoryTier.WORKING,
                namespace=eff_ns,
            ))

            # Override dependency explicitly
            app.dependency_overrides[get_current_memory_port] = lambda: custom_port

            res = client.get(f"/api/memory?namespace=override_ns&profile_id={test_profile}")
            assert res.status_code == 200
            items = res.json()
            assert len(items) == 1
            assert items[0]["key"] == "override_key"
            assert items[0]["value"] == "Overridden memory value"
        finally:
            try:
                if hasattr(custom_port, "_conn") and custom_port._conn is not None:
                    custom_port._conn.stop()
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_async_client_memory_api_roundtrip(
        self,
        async_client: AsyncClient,
        tmp_path: Path,
    ):
        """Verifies non-blocking asynchronous execution over ASGITransport."""
        from carefold.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
        from carefold.db.models import User
        from carefold.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, DEFAULT_STEWARD_USER.id)
            if not user:
                user = User(
                    id=DEFAULT_STEWARD_USER.id,
                    email="steward@carefold.ai",
                    username="steward",
                    hashed_password="mock",
                    role="steward",
                    status="active",
                    auth_provider="disabled",
                )
                session.add(user)
                await session.commit()

        prof_res = await async_client.post("/api/profiles", json={"name": "Async Patient", "relationship": "self"})
        assert prof_res.status_code == 201
        pid = prof_res.json()["id"]

        port = SqliteMemoryAdapter(db_path=tmp_path / "async_test.db")
        set_memory_port(port)

        try:
            eff_ns = resolve_effective_namespace(None, "default", pid)
            await port.remember(
                key="async_key",
                value="Async test payload",
                tier=MemoryTier.EPISODIC,
                namespace=eff_ns,
            )

            # Async GET recall
            res_get = await async_client.get(f"/api/memory?query=Async&profile_id={pid}")
            assert res_get.status_code == 200
            data = res_get.json()
            assert len(data) == 1
            assert data[0]["key"] == "async_key"

            # Async GET status
            res_status = await async_client.get("/api/memory/status")
            assert res_status.status_code == 200
            assert res_status.json()["backend"] == "sqlite"

            # Async DELETE
            res_del = await async_client.delete(f"/api/memory/async_key?profile_id={pid}")
            assert res_del.status_code == 200
            assert res_del.json()["deleted"] is True
        finally:
            await port.close()


# =============================================================================
# 6. Log Injection Sanitization Unit Tests
# =============================================================================

class TestLogSanitization:
    """Unit tests for sanitize_log_value helper function."""

    def test_sanitize_log_value_strips_crlf(self) -> None:
        """Strips carriage return and newline characters to prevent log forging."""
        from carefold.logging import sanitize_log_value

        assert sanitize_log_value("safe_string") == "safe_string"
        assert sanitize_log_value("line1\r\nline2") == "line1line2"
        assert sanitize_log_value("line1\nline2") == "line1line2"
        assert sanitize_log_value("line1\rline2") == "line1line2"
        assert sanitize_log_value(None) == ""
        assert sanitize_log_value(12345) == "12345"
        assert sanitize_log_value("") == ""

    def test_sanitize_log_value_complex_payloads(self) -> None:
        """Neutralizes complex multiline forgery attack vectors."""
        from carefold.logging import sanitize_log_value

        attack_payload = (
            "valid_key\r\n"
            "2026-10-06 12:00:00 [ERROR] Forged Admin Event\r\n"
            "data: {\"compromised\": true}\n"
        )
        sanitized = sanitize_log_value(attack_payload)
        assert "\r" not in sanitized
        assert "\n" not in sanitized
        assert "\r\n" not in sanitized
        assert len(sanitized.splitlines()) == 1
        assert "valid_key2026-10-06" in sanitized


# =============================================================================
# 7. Milestone 5: Memory Inspection & Controls (Issue #102)
# =============================================================================

class TestMemoryInspectionAndControlsAPI:
    """Test suite for Milestone 5 memory inspection, editing, and bulk deletion controls."""

    def test_get_memory_by_key_success(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str) -> None:
        """GET /api/memory/{key} returns the memory record when it exists."""
        ns = resolve_effective_namespace(None, "patient_1", test_profile)
        asyncio.run(
            sqlite_port.remember(
                key="allergy_penicillin",
                value="Severe rash with penicillin",
                tier=MemoryTier.SEMANTIC,
                namespace=ns,
                metadata={"source": "intake_form"},
            )
        )

        res = client.get(f"/api/memory/allergy_penicillin?namespace=patient_1&profile_id={test_profile}")
        assert res.status_code == 200
        data = res.json()
        assert data["key"] == "allergy_penicillin"
        assert data["value"] == "Severe rash with penicillin"
        assert data["tier"] == "semantic"
        assert data["namespace"] == ns
        assert data["metadata"]["source"] == "intake_form"

    def test_get_memory_by_key_not_found(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str) -> None:
        """GET /api/memory/{key} returns 404 when key does not exist."""
        res = client.get(f"/api/memory/nonexistent_key?namespace=default&profile_id={test_profile}")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_get_memory_invalid_key_path_traversal(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str) -> None:
        """GET /api/memory/{key} rejects path traversal sequences with 400 or 404."""
        # Key containing traversal characters
        res = client.get(f"/api/memory/evil..key?profile_id={test_profile}")
        assert res.status_code == 400
        assert "invalid characters" in res.json()["detail"].lower()

        res_traversal = client.get(f"/api/memory/..%2Fsecret?profile_id={test_profile}")
        assert res_traversal.status_code in (400, 404)

    def test_put_memory_creates_new_record(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str) -> None:
        """PUT /api/memory/{key} creates a new memory record with provided tier and metadata."""
        expected_ns = resolve_effective_namespace(None, "vitals", test_profile)
        payload = {
            "value": "BP reading 120/80 mmHg",
            "tier": "episodic",
            "namespace": "vitals",
            "metadata": {"device": "omron_cuff"},
            "profile_id": test_profile,
        }
        res = client.put(f"/api/memory/bp_reading_1?profile_id={test_profile}", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["key"] == "bp_reading_1"
        assert data["value"] == "BP reading 120/80 mmHg"
        assert data["tier"] == "episodic"
        assert data["namespace"] == expected_ns
        assert data["metadata"]["device"] == "omron_cuff"

        # Verify persisted record
        persisted = asyncio.run(sqlite_port.get("bp_reading_1", namespace=expected_ns))
        assert persisted is not None
        assert persisted["value"] == "BP reading 120/80 mmHg"

    def test_put_memory_updates_existing_record_and_preserves_tier(
        self, client: TestClient, sqlite_port: MemoryPort, test_profile: str
    ) -> None:
        """PUT /api/memory/{key} updates value and preserves tier if tier is omitted."""
        ns = resolve_effective_namespace(None, "default", test_profile)
        asyncio.run(
            sqlite_port.remember(
                key="diet_pref",
                value="Low sodium diet",
                tier=MemoryTier.SEMANTIC,
                namespace=ns,
            )
        )

        # Update without specifying tier
        update_payload = {
            "value": "Strict low sodium (under 1500mg) diet",
            "metadata": {"updated_by": "patient"},
            "profile_id": test_profile,
        }
        res = client.put(f"/api/memory/diet_pref?profile_id={test_profile}", json=update_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["value"] == "Strict low sodium (under 1500mg) diet"
        assert data["tier"] == "semantic"  # preserved
        assert data["namespace"] == ns
        assert data["metadata"]["updated_by"] == "patient"

    def test_put_memory_invalid_tier_returns_400(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str) -> None:
        """PUT /api/memory/{key} with invalid tier returns 400 Bad Request."""
        payload = {
            "value": "Sample data",
            "tier": "invalid_tier_name",
            "profile_id": test_profile,
        }
        res = client.put(f"/api/memory/some_key?profile_id={test_profile}", json=payload)
        assert res.status_code == 400
        assert "invalid memory tier" in res.json()["detail"].lower()

    def test_put_memory_invalid_key_returns_400(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str) -> None:
        """PUT /api/memory/{key} with path traversal key returns 400 Bad Request or 404."""
        payload = {"value": "Malicious payload", "profile_id": test_profile}
        res = client.put(f"/api/memory/evil..key?profile_id={test_profile}", json=payload)
        assert res.status_code == 400
        assert "invalid characters" in res.json()["detail"].lower()

        res_traversal = client.put(f"/api/memory/..%2Fhack?profile_id={test_profile}", json=payload)
        assert res_traversal.status_code in (400, 404)

    def test_bulk_delete_memories_clears_namespace(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str) -> None:
        """DELETE /api/memory clears all records in the given namespace."""
        ns_a = resolve_effective_namespace(None, "session_a", test_profile)
        ns_b = resolve_effective_namespace(None, "session_b", test_profile)
        asyncio.run(
            sqlite_port.remember(
                key="rec_1",
                value="Fact 1",
                tier=MemoryTier.EPISODIC,
                namespace=ns_a,
            )
        )
        asyncio.run(
            sqlite_port.remember(
                key="rec_2",
                value="Fact 2",
                tier=MemoryTier.EPISODIC,
                namespace=ns_a,
            )
        )
        asyncio.run(
            sqlite_port.remember(
                key="rec_3",
                value="Fact 3",
                tier=MemoryTier.SEMANTIC,
                namespace=ns_b,
            )
        )

        # Bulk delete session_a
        res = client.delete(f"/api/memory?namespace=session_a&profile_id={test_profile}")
        assert res.status_code == 200
        data = res.json()
        assert data["deleted"] is True
        assert data["deleted_count"] == 2
        assert data["namespace"] == ns_a

        # Verify session_a memories are gone
        recalled_a = asyncio.run(sqlite_port.recall(query="", namespace=ns_a))
        assert len(recalled_a) == 0

        # Verify session_b memory is untouched
        recalled_b = asyncio.run(sqlite_port.recall(query="", namespace=ns_b))
        assert len(recalled_b) == 1

    def test_plural_route_alias_memories(self, client: TestClient, sqlite_port: MemoryPort, test_profile: str) -> None:
        """Verifies that /api/memories functions identically to /api/memory."""
        ns = resolve_effective_namespace(None, "plural_ns", test_profile)
        # 1. PUT via /api/memories/{key}
        put_res = client.put(
            f"/api/memories/plural_key?profile_id={test_profile}",
            json={"value": "Plural test fact", "tier": "episodic", "namespace": "plural_ns", "profile_id": test_profile},
        )
        assert put_res.status_code == 200
        assert put_res.json()["key"] == "plural_key"
        assert put_res.json()["namespace"] == ns

        # 2. GET single via /api/memories/{key}
        get_single = client.get(f"/api/memories/plural_key?namespace=plural_ns&profile_id={test_profile}")
        assert get_single.status_code == 200
        assert get_single.json()["value"] == "Plural test fact"

        # 3. GET list via /api/memories
        get_list = client.get(f"/api/memories?namespace=plural_ns&profile_id={test_profile}")
        assert get_list.status_code == 200
        assert len(get_list.json()) == 1

        # 4. DELETE single via /api/memories/{key}
        del_single = client.delete(f"/api/memories/plural_key?namespace=plural_ns&profile_id={test_profile}")
        assert del_single.status_code == 200
        assert del_single.json()["deleted"] is True

        # 5. Bulk DELETE via /api/memories
        bulk_del = client.delete(f"/api/memories?namespace=plural_ns&profile_id={test_profile}")
        assert bulk_del.status_code == 200
        assert bulk_del.json()["deleted_count"] == 0

    def test_spector_forget_all_parity(self, client: TestClient, spector_port: MemoryPort, test_profile: str) -> None:
        """Verifies bulk forget_all parity when running on SpectorMemoryAdapter."""
        ns = resolve_effective_namespace(None, "spector_ns", test_profile)
        asyncio.run(
            spector_port.remember(
                key="sp_1",
                value="Spector episodic 1",
                tier=MemoryTier.EPISODIC,
                namespace=ns,
            )
        )
        asyncio.run(
            spector_port.remember(
                key="sp_2",
                value="Spector episodic 2",
                tier=MemoryTier.EPISODIC,
                namespace=ns,
            )
        )

        res = client.delete(f"/api/memory?namespace=spector_ns&profile_id={test_profile}")
        assert res.status_code == 200
        assert res.json()["deleted_count"] == 2

        recalled = asyncio.run(spector_port.recall(query="", namespace=ns))
        assert len(recalled) == 0


