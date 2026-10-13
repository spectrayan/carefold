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

"""Unit and integration tests for SpectorSearchIndex adapter with hermetic test double."""

from typing import Any, Dict, List, Optional
import pytest

from spector_client.exceptions import TransportError
from spector_client.models import MemoryTier, RecallRecord, SearchRecord

from carefold.search.adapters.spector import SpectorSearchIndex
from carefold.search.adapters.sqlite import SqliteSearchIndex
from carefold.search.base import SearchResult


class ControllableSpectorMemoryClient:
    """Hermetic test double for AsyncMemoryClient."""

    def __init__(self, healthy: bool = True, exc: Optional[Exception] = None) -> None:
        self.healthy = healthy
        self.exc = exc or TransportError("Connection refused: Spector daemon offline")
        self.remembered_records: List[Dict[str, Any]] = []
        self.browse_records: List[Dict[str, Any]] = []
        self.vacuum_called: bool = False
        self.forgotten_ids: List[str] = []
        self.lexical_mock_hits: List[SearchRecord] = []
        self.vector_mock_hits: List[RecallRecord] = []

    async def remember(self, text: str, tier: Any = None, tags: list = None, metadata: dict = None, **kwargs) -> Dict[str, Any]:
        if not self.healthy:
            raise self.exc
        rec = {
            "id": (metadata or {}).get("chunk_id", f"mem_{len(self.remembered_records)}"),
            "text": text,
            "tier": tier,
            "tags": tags or [],
            "metadata": metadata or {},
        }
        self.remembered_records.append(rec)
        return rec

    async def search(self, query: str, top_k: int = 10) -> List[SearchRecord]:
        if not self.healthy:
            raise self.exc
        return self.lexical_mock_hits[:top_k]

    async def recall(self, query: str, top_k: int = 10, profile: str = "BALANCED", **kwargs) -> List[RecallRecord]:
        if not self.healthy:
            raise self.exc
        return self.vector_mock_hits[:top_k]

    async def browse(self, tags: list = None) -> List[Dict[str, Any]]:
        if not self.healthy:
            raise self.exc
        return self.browse_records

    async def forget(self, memory_id: str, reason: str = None) -> None:
        if not self.healthy:
            raise self.exc
        self.forgotten_ids.append(memory_id)

    async def vacuum(self, tier: str = None) -> Dict[str, Any]:
        if not self.healthy:
            raise self.exc
        self.vacuum_called = True
        return {"purged": len(self.remembered_records)}

    async def status(self) -> Dict[str, Any]:
        if not self.healthy:
            raise self.exc
        return {"status": "ok", "memories": len(self.remembered_records)}


class ControllableSpectorClient:
    """Hermetic test double for AsyncSpectorClient."""

    def __init__(self, memory_client: ControllableSpectorMemoryClient) -> None:
        self.memory = memory_client
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
class TestSpectorNamespaceIsolationAndMetadata:
    """Verifies X-Namespace header binding and rich chunk metadata indexing."""

    async def test_client_profile_namespace_isolation_headers(self):
        adapter = SpectorSearchIndex(base_url="http://localhost:7070", fallback_to_sqlite=False)
        client = adapter._get_client_for_profile("prof-tenant-xyz")

        # Verify physical disk partition via X-Namespace header in client transport
        assert client._transport.config.namespace == "prof-tenant-xyz"
        assert client._transport.config.get_auth_headers()["X-Namespace"] == "prof-tenant-xyz"

        # Verify client caching per profile
        client2 = adapter._get_client_for_profile("prof-tenant-xyz")
        assert client is client2

        # Verify distinct client for different profile
        client_other = adapter._get_client_for_profile("prof-tenant-abc")
        assert client_other._transport.config.namespace == "prof-tenant-abc"
        assert client_other is not client

        await adapter.close()

    async def test_chunk_metadata_indexing_fields(self, tmp_path):
        mem = ControllableSpectorMemoryClient(healthy=True)
        fake_client = ControllableSpectorClient(mem)
        sqlite_fallback = SqliteSearchIndex(db_path=tmp_path / "fallback.db")

        adapter = SpectorSearchIndex(
            client=fake_client,
            fallback_index=sqlite_fallback,
            fallback_to_sqlite=True,
        )

        clinical_doc = (
            "CHIEF COMPLAINT\nSevere retrosternal chest pain.\n\n"
            "MEDICATIONS\nAspirin 81mg PO daily, Metoprolol 25mg PO BID."
        )

        await adapter.index_document(
            document_id="doc-meta-test",
            text=clinical_doc,
            metadata={"filename": "cardio_note.txt", "source": "upload"},
            profile_id="prof-meta",
            user_id="usr-99",
        )

        # Must have indexed 2 chunks
        assert len(mem.remembered_records) == 2

        chunk0 = mem.remembered_records[0]
        meta0 = chunk0["metadata"]
        assert meta0["document_id"] == "doc-meta-test"
        assert meta0["source_doc_id"] == "doc-meta-test"
        assert meta0["chunk_id"] == "doc-meta-test#c0"
        assert meta0["chunk_index"] == 0
        assert meta0["section_header"] == "CHIEF COMPLAINT"
        assert meta0["token_count"] > 0
        assert meta0["profile_id"] == "prof-meta"
        assert meta0["user_id"] == "usr-99"

        # Check tags
        assert "doc:doc-meta-test" in chunk0["tags"]
        assert "chunk:doc-meta-test#c0" in chunk0["tags"]
        assert "profile:prof-meta" in chunk0["tags"]
        assert "section:chief complaint" in chunk0["tags"]

        await adapter.close()


@pytest.mark.asyncio
class TestReciprocalRankFusionHybridSearch:
    """Verifies RRF (k=60) formulation, score normalization [0.0, 1.0], and multi-tier tie-breaking."""

    async def test_rrf_hybrid_fusion_score_calculation_and_normalization(self):
        mem = ControllableSpectorMemoryClient(healthy=True)
        fake_client = ControllableSpectorClient(mem)
        adapter = SpectorSearchIndex(client=fake_client, fallback_to_sqlite=False, rrf_k=60)

        # Prepare candidates:
        # candidate_1: Rank #1 in BM25, Rank #1 in Vector -> normalized score must be 1.0
        # candidate_2: Rank #2 in BM25, Rank #2 in Vector -> normalized score must be 61 / 62 ≈ 0.983871
        # candidate_3: Rank #3 in BM25, not present in Vector -> normalized score = (0.5/63) * 61 ≈ 0.484127
        mem.lexical_mock_hits = [
            SearchRecord(id="c1", text="Doc 1 content", score=10.0, tags=[], metadata={"chunk_id": "c1", "document_id": "d1"}),
            SearchRecord(id="c2", text="Doc 2 content", score=8.0, tags=[], metadata={"chunk_id": "c2", "document_id": "d2"}),
            SearchRecord(id="c3", text="Doc 3 content", score=5.0, tags=[], metadata={"chunk_id": "c3", "document_id": "d3"}),
        ]
        mem.vector_mock_hits = [
            RecallRecord(id="c1", text="Doc 1 content", score=0.95, tier=MemoryTier.SEMANTIC, tags=[], valence=0, arousal=0, importance=1.0, metadata={"chunk_id": "c1", "document_id": "d1"}, similarity=0.95, age_days=0.0, decay_factor=1.0),
            RecallRecord(id="c2", text="Doc 2 content", score=0.85, tier=MemoryTier.SEMANTIC, tags=[], valence=0, arousal=0, importance=1.0, metadata={"chunk_id": "c2", "document_id": "d2"}, similarity=0.85, age_days=0.0, decay_factor=1.0),
        ]

        results = await adapter.search(query="chest pain", profile_id="prof-rrf", mode="hybrid")
        assert len(results) == 3

        # Rank 1: c1
        assert results[0].chunk_id == "c1"
        assert results[0].score == 1.0
        assert results[0].lexical_score == 10.0
        assert results[0].semantic_score == 0.95

        # Rank 2: c2
        assert results[1].chunk_id == "c2"
        expected_c2 = round(((0.5 / 62) + (0.5 / 62)) * 61, 6)
        assert results[1].score == expected_c2

        # Rank 3: c3
        assert results[2].chunk_id == "c3"
        expected_c3 = round((0.5 / 63) * 61, 6)
        assert results[2].score == expected_c3

        await adapter.close()

    async def test_single_branch_hit_score_normalization(self):
        mem = ControllableSpectorMemoryClient(healthy=True)
        fake_client = ControllableSpectorClient(mem)
        adapter = SpectorSearchIndex(client=fake_client, fallback_to_sqlite=False, rrf_k=60)

        # Only lexical hit at rank #1
        mem.lexical_mock_hits = [
            SearchRecord(id="c_lex_only", text="Lexical hit", score=10.0, tags=[], metadata={"chunk_id": "c_lex_only", "document_id": "d_lex"}),
        ]
        mem.vector_mock_hits = []

        results = await adapter.search("inhaler", profile_id="prof-single", mode="hybrid")
        assert len(results) == 1
        # Score = (0.5 / 61) * 61 = 0.5
        assert results[0].score == 0.5

        await adapter.close()

    async def test_deterministic_tie_breaking(self):
        mem = ControllableSpectorMemoryClient(healthy=True)
        fake_client = ControllableSpectorClient(mem)
        adapter = SpectorSearchIndex(client=fake_client, fallback_to_sqlite=False, rrf_k=60)

        # Both items appear only in lexical: item_b is rank 1 (score 0.5), item_a is rank 2.
        # But suppose two items have equal RRF score (e.g. rank #1 in lexical vs rank #1 in vector):
        mem.lexical_mock_hits = [
            SearchRecord(id="c_alpha", text="Alpha text", score=20.0, tags=[], metadata={"chunk_id": "c_alpha", "document_id": "d_a"}),
        ]
        mem.vector_mock_hits = [
            RecallRecord(id="c_beta", text="Beta text", score=0.9, tier=MemoryTier.SEMANTIC, tags=[], valence=0, arousal=0, importance=1.0, metadata={"chunk_id": "c_beta", "document_id": "d_b"}, similarity=0.9, age_days=0.0, decay_factor=1.0),
        ]

        # Both c_alpha and c_beta have RRF score = (0.5/61)*61 = 0.5.
        # c_alpha has lexical_score=20.0, c_beta has lexical_score=0.0.
        # Multi-tier tie breaking: c_alpha (higher lexical_score) MUST come first!
        results = await adapter.search("ambiguous", profile_id="prof-tie", mode="hybrid")
        assert len(results) == 2
        assert results[0].chunk_id == "c_alpha"
        assert results[1].chunk_id == "c_beta"

        await adapter.close()


@pytest.mark.asyncio
class TestResilientCircuitBreakerAndFallback:
    """Verifies automatic fallback to SQLite on TransportError and zero HTTP 500 errors."""

    async def test_circuit_breaker_activates_fallback_on_transport_error(self, tmp_path):
        sqlite_db = tmp_path / "cb_fallback.db"
        sqlite_fallback = SqliteSearchIndex(db_path=sqlite_db)

        # Pre-populate SQLite fallback
        await sqlite_fallback.index_document(
            document_id="doc-cb",
            text="Emergency cardiac pacing indications: third degree AV block.",
            metadata={"source": "sqlite_fallback"},
            profile_id="prof-cb",
        )

        # Spector daemon is dead (raises TransportError)
        dead_mem = ControllableSpectorMemoryClient(healthy=False, exc=TransportError("Connection refused: 7070"))
        dead_client = ControllableSpectorClient(dead_mem)

        adapter = SpectorSearchIndex(
            client=dead_client,
            fallback_index=sqlite_fallback,
            fallback_to_sqlite=True,
            cooldown_seconds=10.0,
        )

        assert adapter._is_degraded is False

        # Search should NOT raise TransportError; it must seamlessly return SQLite hits
        results = await adapter.search(query="cardiac pacing", profile_id="prof-cb")
        assert len(results) == 1
        assert results[0].document_id == "doc-cb"
        assert "cardiac pacing" in results[0].content

        # Circuit breaker must now be in degraded state
        assert adapter._is_degraded is True
        assert adapter._cooldown_until > 0.0

        await adapter.close()

    async def test_fallback_disabled_raises_transport_error(self):
        dead_mem = ControllableSpectorMemoryClient(healthy=False, exc=TransportError("Daemon down"))
        dead_client = ControllableSpectorClient(dead_mem)

        adapter = SpectorSearchIndex(
            client=dead_client,
            fallback_to_sqlite=False,
        )

        with pytest.raises(TransportError):
            await adapter.search("query", profile_id="prof-err")

        await adapter.close()

    async def test_delete_document_and_profile_index_delegation(self, tmp_path):
        sqlite_fallback = SqliteSearchIndex(db_path=tmp_path / "del_fallback.db")
        await sqlite_fallback.index_document(
            document_id="doc-del-spec",
            text="Document to be purged from Spector and SQLite.",
            metadata={},
            profile_id="prof-del-spec",
        )

        mem = ControllableSpectorMemoryClient(healthy=True)
        mem.browse_records = [{"id": "mem_spec_1", "text": "Document to be purged"}]
        client = ControllableSpectorClient(mem)

        adapter = SpectorSearchIndex(
            client=client,
            fallback_index=sqlite_fallback,
            fallback_to_sqlite=True,
        )

        # Delete document
        del_res = await adapter.delete_document("doc-del-spec", profile_id="prof-del-spec")
        assert del_res is True
        assert "mem_spec_1" in mem.forgotten_ids

        # Delete profile index
        purged_count = await adapter.delete_profile_index("prof-del-spec")
        assert mem.vacuum_called is True
        assert purged_count >= 0

        await adapter.close()
