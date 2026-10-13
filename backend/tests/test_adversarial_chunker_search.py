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

"""Adversarial stress test harness for ClinicalChunker and SqliteSearchIndex ranking."""

import pytest
import tiktoken

from carefold.search.adapters.sqlite import SqliteSearchIndex, _sanitize_fts_query
from carefold.search.chunker import ClinicalChunk, ClinicalChunker


class TestChunkBoundaryStress:
    """Stress tests for token boundary edge cases (0, 1, 499, 500, 800, 801, 10,000 tokens)."""

    def test_chunk_boundary_0_words(self):
        chunker = ClinicalChunker()
        assert chunker.chunk("doc-0", "") == []
        assert chunker.chunk("doc-0", "   \t\n\r  ") == []

    def test_chunk_boundary_1_word(self):
        chunker = ClinicalChunker()
        # Normal clinical token
        c1 = chunker.chunk("doc-1", "Metformin")
        assert len(c1) == 1
        assert c1[0].chunk_id == "doc-1#c0"
        assert c1[0].text == "Metformin"
        assert c1[0].token_count >= 1

        # Header as single word
        c_hdr = chunker.chunk("doc-hdr", "MEDICATIONS")
        assert len(c_hdr) == 1
        assert c_hdr[0].chunk_id == "doc-hdr#c0"
        assert c_hdr[0].text == "MEDICATIONS"

        # Extremely long single word (no spaces)
        long_word = "A" * 2000
        c_long = chunker.chunk("doc-long", long_word)
        assert len(c_long) == 1
        assert c_long[0].chunk_id == "doc-long#c0"

    def test_chunk_boundary_exactly_499_tokens(self):
        chunker = ClinicalChunker()
        text = " patient" * 499
        assert chunker.count_tokens(text) == 499

        chunks = chunker.chunk("doc-499", text)
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "doc-499#c0"
        assert chunks[0].token_count == 499

    def test_chunk_boundary_exactly_500_tokens(self):
        chunker = ClinicalChunker()
        text = " patient" * 500
        assert chunker.count_tokens(text) == 500

        chunks = chunker.chunk("doc-500", text)
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "doc-500#c0"
        assert chunks[0].token_count == 500

    def test_chunk_boundary_exactly_800_tokens(self):
        chunker = ClinicalChunker(max_tokens=800)
        text = " patient" * 800
        assert chunker.count_tokens(text) == 800

        # Exact upper boundary: must produce exactly 1 chunk
        chunks = chunker.chunk("doc-800", text)
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "doc-800#c0"
        assert chunks[0].token_count == 800

    def test_chunk_boundary_exactly_801_tokens(self):
        chunker = ClinicalChunker(max_tokens=800, overlap_tokens=100)
        text = " patient" * 801
        assert chunker.count_tokens(text) == 801

        # Must split into exactly 2 chunks
        chunks = chunker.chunk("doc-801", text)
        assert len(chunks) == 2
        assert chunks[0].chunk_id == "doc-801#c0"
        assert chunks[1].chunk_id == "doc-801#c1"
        assert chunks[0].token_count <= 800
        assert chunks[1].token_count <= 800

    def test_chunk_boundary_10000_tokens(self):
        chunker = ClinicalChunker(max_tokens=800, overlap_tokens=100)
        text = " patient" * 10000
        assert chunker.count_tokens(text) == 10000

        chunks = chunker.chunk("doc-10k", text)
        assert len(chunks) == 15
        assert all(ch.token_count <= 800 for ch in chunks)
        expected_ids = [f"doc-10k#c{i}" for i in range(len(chunks))]
        assert [ch.chunk_id for ch in chunks] == expected_ids


class TestOverlapIntegrity:
    """Verifies that consecutive chunks share ~100 tokens of overlapping context."""

    def test_consecutive_chunks_share_approx_100_tokens_overlap(self):
        enc = tiktoken.get_encoding("cl100k_base")
        chunker = ClinicalChunker(max_tokens=800, overlap_tokens=100)

        # Generate 2500 unique tokens
        words = [f"token_{i:04d}" for i in range(2500)]
        text = " ".join(words)
        chunks = chunker.chunk("doc-overlap", text)
        assert len(chunks) >= 3

        for i in range(len(chunks) - 1):
            c_curr = chunks[i]
            c_next = chunks[i + 1]

            toks_curr = enc.encode(c_curr.text)
            toks_next = enc.encode(c_next.text)

            # Check overlap between suffix of c_curr and prefix of c_next
            # Account for leading token whitespace difference from .strip()
            max_match = 0
            for k in range(120, 80, -1):
                for offset in range(3):
                    if toks_curr[-k:] == toks_next[offset : offset + k]:
                        max_match = max(max_match, k + offset)
                        break
                if max_match > 0:
                    break

            assert 95 <= max_match <= 105, (
                f"Consecutive chunks {i} and {i+1} overlap was {max_match}, expected ~100 tokens"
            )

    def test_overlap_with_word_heuristic_fallback(self):
        chunker = ClinicalChunker(max_tokens=200, overlap_tokens=40)
        chunker._encoding = None  # Force word-based fallback

        words = [f"term_{i:04d}" for i in range(600)]
        text = " ".join(words)
        chunks = chunker.chunk("doc-fallback-overlap", text)
        assert len(chunks) >= 3

        for i in range(len(chunks) - 1):
            w_curr = set(chunks[i].text.split())
            w_next = set(chunks[i + 1].text.split())
            shared = w_curr.intersection(w_next)
            # Overlap tokens is 40; shared words should be around 40
            assert 30 <= len(shared) <= 50, (
                f"Shared words between chunk {i} and {i+1} was {len(shared)}, expected ~40"
            )


class TestClinicalHeaderCorruption:
    """Stress tests clinical header parsing against noisy, missing newline, and stacked headers."""

    def test_noisy_and_markdown_header_formatting(self):
        chunker = ClinicalChunker()
        text = (
            "### * CHIEF COMPLAINT * :\n"
            "Patient reports worsening retrosternal pain.\n\n"
            "***MEDICATIONS***:\n"
            "Aspirin 81mg, Nitroglycerin sublingual.\n\n"
            "#### ASSESSMENT/PLAN\n"
            "Rule out acute coronary syndrome."
        )
        chunks = chunker.chunk("doc-noisy", text)
        assert len(chunks) == 3
        sections = [ch.section_name for ch in chunks]
        assert "CHIEF COMPLAINT" in sections
        assert "MEDICATIONS" in sections
        assert "ASSESSMENT/PLAN" in sections

    def test_lowercase_header_variants(self):
        chunker = ClinicalChunker()
        text = (
            "chief complaint:\n"
            "Severe shortness of breath.\n\n"
            "review of systems\n"
            "Positive for dry cough, negative for fever.\n\n"
            "plan\n"
            "Start nebulized albuterol."
        )
        chunks = chunker.chunk("doc-lower", text)
        assert len(chunks) == 3
        sections = [ch.section_name for ch in chunks]
        assert "CHIEF COMPLAINT" in sections
        assert "REVIEW OF SYSTEMS" in sections
        assert "PLAN" in sections

    def test_multiple_headers_in_close_proximity(self):
        chunker = ClinicalChunker()
        text = (
            "CHIEF COMPLAINT\n"
            "REASON FOR VISIT\n"
            "HISTORY OF PRESENT ILLNESS\n"
            "Patient with syncope after standing.\n\n"
            "ASSESSMENT\n"
            "PLAN\n"
            "Orthostatic hypotension. Increase fluid intake."
        )
        chunks = chunker.chunk("doc-stacked", text)
        assert len(chunks) >= 2
        assert all(len(ch.text.strip()) > 0 for ch in chunks)
        assert all(ch.token_count > 0 for ch in chunks)

    def test_missing_newlines_inline_headers_preserves_content(self):
        chunker = ClinicalChunker()
        inline = "CHIEF COMPLAINT: chest pain MEDICATIONS: aspirin ASSESSMENT: stable"
        chunks = chunker.chunk("doc-inline", inline)
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "doc-inline#c0"
        assert "chest pain" in chunks[0].text
        assert "aspirin" in chunks[0].text
        assert "stable" in chunks[0].text

    def test_unrecognized_corrupted_header_preserves_data(self):
        chunker = ClinicalChunker()
        text = (
            "CHIEF COMPLAINT\n"
            "Chest pain.\n\n"
            "1.2.3 --- UNKNOWN SECTION $$$ ---\n"
            "Confidential ECG showing ST elevations.\n\n"
            "PLAN\n"
            "Emergency angiography."
        )
        chunks = chunker.chunk("doc-corrupt", text)
        all_text = " ".join(ch.text for ch in chunks)
        assert "Confidential ECG showing ST elevations." in all_text


@pytest.mark.asyncio
class TestFTS5InjectionAttacks:
    """Stress tests SqliteSearchIndex against FTS5 syntax injection, operators, and unicode payloads."""

    async def test_unbalanced_quotes_and_sql_injection(self, tmp_path):
        db_path = tmp_path / "fts_quotes.db"
        idx = SqliteSearchIndex(db_path=db_path)
        await idx.index_document(
            document_id="doc-quotes",
            text="Patient diagnosed with coronary artery disease. Taking Atorvastatin 40mg.",
            metadata={"specialty": "cardiology"},
            profile_id="prof-quote",
        )

        malicious_queries = [
            '"',
            '"""',
            '"""""',
            '"unterminated phrase',
            "' OR 1=1 --",
            "'; DROP TABLE document_chunks_fts; --",
            '"""SELECT * FROM document_chunks_fts"""',
        ]

        for q in malicious_queries:
            results = await idx.search(q, profile_id="prof-quote")
            assert isinstance(results, list)

        # Confirm table still exists and data intact
        healthy = await idx.search("Atorvastatin", profile_id="prof-quote")
        assert len(healthy) == 1

        await idx.close()

    async def test_raw_fts_operators_and_combinations(self, tmp_path):
        db_path = tmp_path / "fts_operators.db"
        idx = SqliteSearchIndex(db_path=db_path)
        await idx.index_document(
            document_id="doc-ops",
            text="Clinical findings: Lisinopril for hypertension. Metformin for diabetes mellitus.",
            metadata={},
            profile_id="prof-ops",
        )

        operator_queries = [
            "AND",
            "OR",
            "NOT",
            "NEAR",
            "NEAR/2",
            "NEAR(a, b)",
            "*",
            "^",
            "*** ^^^",
            "AND NOT OR NEAR * ^",
            "content:Lisinopril",
            "rank:5",
            "{content} : Lisinopril",
            "col:val",
            "MATCH *",
            "--- +++ === !!! ???",
        ]

        for op in operator_queries:
            results = await idx.search(op, profile_id="prof-ops")
            assert isinstance(results, list)

        await idx.close()

    async def test_null_bytes_in_queries_and_text(self, tmp_path):
        db_path = tmp_path / "fts_nulls.db"
        idx = SqliteSearchIndex(db_path=db_path)

        # Index document with null byte in content
        await idx.index_document(
            document_id="doc-null",
            text="Blood pressure 130/85\x00 with normal pulse rate.",
            metadata={},
            profile_id="prof-null",
        )

        null_queries = [
            "\x00",
            "pressure\x00normal",
            "\x00\x00\x00",
            "pressure\x00' OR '1'='1",
        ]

        for nq in null_queries:
            results = await idx.search(nq, profile_id="prof-null")
            assert isinstance(results, list)

        # Normal query matches despite null byte in text
        res = await idx.search("pressure", profile_id="prof-null")
        assert len(res) == 1

        await idx.close()

    async def test_non_ascii_and_unicode_payloads(self, tmp_path):
        db_path = tmp_path / "fts_unicode.db"
        idx = SqliteSearchIndex(db_path=db_path)

        await idx.index_document(
            document_id="doc-multi",
            text=(
                "El paciente tiene hipertensión arterial. "
                "Пациент страдает гипертонией. "
                "المريض يعاني من ارتفاع ضغط الدم. "
                "2 型 糖尿病 和 高血压. "
                "Patient taking pills 💊 for exam."
            ),
            metadata={},
            profile_id="prof-multi",
        )

        # Spanish
        assert len(await idx.search("hipertensión", profile_id="prof-multi")) == 1
        # Russian Cyrillic
        assert len(await idx.search("гипертонией", profile_id="prof-multi")) == 1
        # Arabic
        assert len(await idx.search("ارتفاع", profile_id="prof-multi")) == 1
        # Chinese (space-delimited)
        assert len(await idx.search("糖尿病", profile_id="prof-multi")) == 1
        # Emojis (safe degradation)
        emoji_res = await idx.search("💊", profile_id="prof-multi")
        assert isinstance(emoji_res, list)
        # RTL override attack
        rtl_res = await idx.search("\u202ehipertensión\u202c", profile_id="prof-multi")
        assert isinstance(rtl_res, list)
        # Zero-width spaces
        zws_res = await idx.search("hiper\u200btensión", profile_id="prof-multi")
        assert isinstance(zws_res, list)

        await idx.close()

    async def test_bm25_search_ranking_oracle(self, tmp_path):
        db_path = tmp_path / "fts_ranking.db"
        idx = SqliteSearchIndex(db_path=db_path)

        # Document 1: High relevance (multiple occurrences of acute myocardial infarction)
        await idx.index_document(
            document_id="doc-ami",
            text="Acute myocardial infarction confirmed. Emergency myocardial infarction protocol initiated.",
            metadata={},
            profile_id="prof-rank",
        )

        # Document 2: Low relevance (single peripheral mention)
        await idx.index_document(
            document_id="doc-general",
            text="General wellness examination with family history of myocardial infarction.",
            metadata={},
            profile_id="prof-rank",
        )

        results = await idx.search("myocardial infarction", profile_id="prof-rank", limit=10)
        assert len(results) == 2
        # Doc 1 must be ranked first (higher score in SearchResult)
        assert results[0].document_id == "doc-ami"
        assert results[1].document_id == "doc-general"
        assert results[0].score >= results[1].score

        await idx.close()


class TestDeterministicChunkIDFormatting:
    """Verifies chunk ID format f"{doc_id}#c{idx}" and collision resistance."""

    def test_chunk_ids_never_collide_across_documents(self):
        chunker = ClinicalChunker()
        doc_ids = [
            "doc-alpha",
            "doc-alpha#c0",
            "doc-beta",
            "doc",
            "doc#1",
            "urn:uuid:6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        ]
        text = (
            "CHIEF COMPLAINT\nSevere migraine.\n\n"
            "MEDICATIONS\nSumatriptan 50mg.\n\n"
            "ASSESSMENT AND PLAN\nMigraine with aura."
        )

        all_chunk_ids = set()
        for doc_id in doc_ids:
            chunks = chunker.chunk(doc_id, text)
            assert len(chunks) == 3
            for idx, ch in enumerate(chunks):
                expected_id = f"{doc_id}#c{idx}"
                assert ch.chunk_id == expected_id
                assert ch.document_id == doc_id
                assert ch.chunk_id not in all_chunk_ids, f"Collision detected on {ch.chunk_id}!"
                all_chunk_ids.add(ch.chunk_id)
