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

"""Unit and integration tests for SearchIndex port and SqliteSearchIndex adapter."""

import pytest

from carefold.search.adapters.sqlite import SqliteSearchIndex, _sanitize_fts_query
from carefold.search.base import SearchIndex, SearchResult


class TestSearchPortAndModels:
    """Verifies SearchResult schema normalization and SearchIndex ABC enforcement."""

    def test_search_index_port_is_abstract(self):
        with pytest.raises(TypeError):
            SearchIndex()  # type: ignore

    def test_search_result_text_property_and_normalization(self):
        # Case A: Initialized with content
        res1 = SearchResult(
            document_id="doc-1",
            chunk_id="doc-1#c0",
            content="Normal sinus rhythm",
            score=0.95,
            profile_id="prof-1",
        )
        assert res1.content == "Normal sinus rhythm"
        assert res1.text == "Normal sinus rhythm"
        assert res1.score == 0.95
        assert res1.source == "search"

        # Case B: Initialized with text alias
        res2 = SearchResult(
            document_id="doc-2",
            chunk_id="doc-2#c0",
            text="Clear lung fields",
            score=0.88,
            profile_id="prof-1",
        )
        assert res2.content == "Clear lung fields"
        assert res2.text == "Clear lung fields"

    def test_search_result_optional_profile_id_default(self):
        res = SearchResult(
            document_id="doc-3",
            chunk_id="doc-3#c0",
            text="Sample content",
            score=1.0,
        )
        assert res.document_id == "doc-3"
        assert res.profile_id == ""


@pytest.mark.asyncio
class TestSqliteSearchIndexLifecycle:
    """Tests SqliteSearchIndex indexing, search, BM25 ranking, deletion, and reindexing."""

    async def test_indexing_and_bm25_search_happy_path(self, tmp_path):
        db_file = tmp_path / "search.db"
        idx = SqliteSearchIndex(db_path=db_file)

        await idx.index_document(
            document_id="doc-htn",
            text="Patient diagnosed with primary hypertension. Prescribed Lisinopril 10mg daily.",
            metadata={"category": "cardiology", "source": "note"},
            profile_id="prof-alpha",
        )

        results = await idx.search(query="Lisinopril", profile_id="prof-alpha")
        assert len(results) == 1
        assert results[0].document_id == "doc-htn"
        assert results[0].chunk_id == "doc-htn#c0"
        assert "Lisinopril" in results[0].content
        assert results[0].metadata["category"] == "cardiology"
        assert results[0].profile_id == "prof-alpha"
        assert results[0].score > 0.0

        await idx.close()

    async def test_search_respects_limit_and_metadata_filters(self, tmp_path):
        db_file = tmp_path / "search_filters.db"
        idx = SqliteSearchIndex(db_path=db_file)

        # Index 3 documents with the same term
        for i in range(3):
            await idx.index_document(
                document_id=f"doc-{i}",
                text=f"Clinical laboratory blood report document {i} with glucose test",
                metadata={"test_type": "blood" if i < 2 else "urine"},
                profile_id="prof-filter",
            )

        # Test limit=1
        hits_limited = await idx.search("glucose", profile_id="prof-filter", limit=1)
        assert len(hits_limited) == 1

        # Test metadata filter
        hits_urine = await idx.search("glucose", profile_id="prof-filter", filters={"test_type": "urine"})
        assert len(hits_urine) == 1
        assert hits_urine[0].document_id == "doc-2"

        await idx.close()

    async def test_delete_document_removes_all_chunks(self, tmp_path):
        db_file = tmp_path / "search_delete.db"
        idx = SqliteSearchIndex(db_path=db_file)

        await idx.index_document(
            document_id="doc-del",
            text="Echocardiogram reveals normal left ventricular ejection fraction 60%.",
            metadata={"modality": "echo"},
            profile_id="prof-del",
        )

        # Confirm document exists
        hits = await idx.search("ejection fraction", profile_id="prof-del")
        assert len(hits) == 1

        # Delete document
        deleted = await idx.delete_document("doc-del", profile_id="prof-del")
        assert deleted is True

        # Subsequent search returns 0 hits
        hits_after = await idx.search("ejection fraction", profile_id="prof-del")
        assert len(hits_after) == 0

        # Deleting non-existent document returns False
        deleted_again = await idx.delete_document("doc-del", profile_id="prof-del")
        assert deleted_again is False

        await idx.close()

    async def test_reindex_all_returns_chunk_count(self, tmp_path):
        db_file = tmp_path / "search_reindex.db"
        idx = SqliteSearchIndex(db_path=db_file)

        await idx.index_document(
            document_id="doc-r1",
            text="First clinical note regarding allergy testing.",
            metadata={},
            profile_id="prof-reindex",
        )
        await idx.index_document(
            document_id="doc-r2",
            text="Second clinical note regarding pulmonary function tests.",
            metadata={},
            profile_id="prof-reindex",
        )

        count = await idx.reindex_all("prof-reindex")
        assert count == 2

        await idx.close()


@pytest.mark.asyncio
class TestSqliteSearchIndexProfileIsolation:
    """Verifies strict profile isolation and fail-closed security invariants."""

    async def test_strict_cross_profile_isolation(self, tmp_path):
        db_file = tmp_path / "isolation.db"
        idx = SqliteSearchIndex(db_path=db_file)

        # Profile 1 has Asthma inhaler
        await idx.index_document(
            document_id="doc-asthma",
            text="Patient requires Albuterol HFA inhaler for acute asthma flare-ups.",
            metadata={"condition": "asthma"},
            profile_id="profile_1",
        )

        # Profile 2 has Cardiology Beta Blocker
        await idx.index_document(
            document_id="doc-cardio",
            text="Patient prescribed Metoprolol succinate for rate control.",
            metadata={"condition": "cardiology"},
            profile_id="profile_2",
        )

        # Search asthma in profile_1 returns doc-asthma
        p1_asthma = await idx.search("asthma", profile_id="profile_1")
        assert len(p1_asthma) == 1
        assert p1_asthma[0].document_id == "doc-asthma"

        # Search asthma in profile_2 returns ZERO hits (leak impossible)
        p2_asthma = await idx.search("asthma", profile_id="profile_2")
        assert len(p2_asthma) == 0

        # Search Metoprolol in profile_1 returns ZERO hits
        p1_cardio = await idx.search("Metoprolol", profile_id="profile_1")
        assert len(p1_cardio) == 0

        # Search Metoprolol in profile_2 returns doc-cardio
        p2_cardio = await idx.search("Metoprolol", profile_id="profile_2")
        assert len(p2_cardio) == 1
        assert p2_cardio[0].document_id == "doc-cardio"

        await idx.close()

    async def test_fail_closed_on_empty_or_whitespace_profile_id(self, tmp_path):
        db_file = tmp_path / "fail_closed.db"
        idx = SqliteSearchIndex(db_path=db_file)

        # Search with invalid profile_id raises ValueError
        for bad_pid in ["", "   ", None]:
            with pytest.raises(ValueError, match="profile_id is required"):
                await idx.search("query", profile_id=bad_pid)  # type: ignore

            with pytest.raises(ValueError, match="profile_id is required"):
                await idx.index_document("doc-1", "text", {}, profile_id=bad_pid)  # type: ignore

            with pytest.raises(ValueError, match="profile_id is required"):
                await idx.delete_document("doc-1", profile_id=bad_pid)  # type: ignore

            with pytest.raises(ValueError, match="profile_id is required"):
                await idx.delete_profile_index(profile_id=bad_pid)  # type: ignore

            with pytest.raises(ValueError, match="profile_id is required"):
                await idx.reindex_all(profile_id=bad_pid)  # type: ignore

        await idx.close()

    async def test_delete_profile_index_cascade_purges_only_target_profile(self, tmp_path):
        db_file = tmp_path / "cascade.db"
        idx = SqliteSearchIndex(db_path=db_file)

        # Index 3 docs in profile_victim
        for i in range(3):
            await idx.index_document(
                document_id=f"doc-victim-{i}",
                text=f"Victim medical document {i} with confidential biopsy results.",
                metadata={},
                profile_id="profile_victim",
            )

        # Index 2 docs in profile_retained
        for i in range(2):
            await idx.index_document(
                document_id=f"doc-retained-{i}",
                text=f"Retained medical document {i} with dermatology exam notes.",
                metadata={},
                profile_id="profile_retained",
            )

        # Purge profile_victim
        deleted_count = await idx.delete_profile_index("profile_victim")
        assert deleted_count == 3

        # Confirm profile_victim search returns 0 hits
        assert len(await idx.search("biopsy", profile_id="profile_victim")) == 0

        # Confirm profile_retained is 100% intact
        retained_hits = await idx.search("dermatology", profile_id="profile_retained")
        assert len(retained_hits) == 2

        # Purge alias compatibility
        purged = await idx.purge_profile("profile_retained")
        assert purged == 2
        assert len(await idx.search("dermatology", profile_id="profile_retained")) == 0

        await idx.close()


@pytest.mark.asyncio
class TestSqliteQuerySanitization:
    """Verifies that special characters and SQL/FTS syntax characters do not crash the search engine."""

    async def test_query_sanitizer_function(self):
        assert _sanitize_fts_query("") == ""
        assert _sanitize_fts_query("   ") == ""
        # Strips special characters
        sanitized = _sanitize_fts_query('hypertension: stage-2 ("severe") * acute')
        assert '"hypertension"*' in sanitized
        assert '"stage"*' in sanitized
        assert '"2"*' in sanitized
        assert '"severe"*' in sanitized
        assert '"acute"*' in sanitized

    async def test_special_characters_do_not_throw_sqlite_operational_error(self, tmp_path):
        db_file = tmp_path / "sanitization.db"
        idx = SqliteSearchIndex(db_path=db_file)

        await idx.index_document(
            document_id="doc-syntax",
            text="Blood pressure 140/90 mmHg. Patient taking Hydrochlorothiazide 25mg.",
            metadata={},
            profile_id="prof-syntax",
        )

        # Execute queries with dangerous FTS syntax characters
        problematic_queries = [
            'AND NOT OR "SELECT * FROM users"',
            "hypertension: acute - chronic",
            "(eGFR < 60) AND (proteinuria > 300)",
            '"""unterminated string',
            "*:* MATCH *",
            "!!! @@@ $$$ %%% ^^^ &&& ***",
        ]

        for q in problematic_queries:
            # Must not raise sqlite3.OperationalError
            results = await idx.search(query=q, profile_id="prof-syntax")
            assert isinstance(results, list)

        await idx.close()
