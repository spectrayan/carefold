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

"""Unit and integration tests for ClinicalChunker: boundaries, sections, and chunk IDs."""

import pytest

from carefold.search.chunker import ClinicalChunk, ClinicalChunker


class TestClinicalChunkerTokenBounds:
    """Tests chunk size boundaries, small document rule, and token limits."""

    def test_small_document_produces_single_chunk_c0(self):
        chunker = ClinicalChunker()
        text = "Patient presents with mild tension headache and seasonal allergic rhinitis."
        chunks = chunker.chunk("doc-small", text)

        assert len(chunks) == 1
        assert chunks[0].chunk_id == "doc-small#c0"
        assert chunks[0].document_id == "doc-small"
        assert chunks[0].text == text
        assert chunks[0].token_count > 0
        assert chunks[0].chunk_index == 0

    def test_single_word_produces_single_chunk(self):
        chunker = ClinicalChunker()
        chunks = chunker.chunk("doc-word", "Metformin")

        assert len(chunks) == 1
        assert chunks[0].chunk_id == "doc-word#c0"
        assert chunks[0].text == "Metformin"
        assert chunks[0].token_count >= 1

    def test_large_narrative_splits_into_overlapping_chunks(self):
        chunker = ClinicalChunker(target_tokens=100, overlap_tokens=20)
        # 300 words without section headers
        words = [f"token_{i}" for i in range(300)]
        text = " ".join(words)

        chunks = chunker.chunk("doc-large", text)
        assert len(chunks) >= 3
        assert all(ch.chunk_id.startswith("doc-large#c") for ch in chunks)
        assert [ch.chunk_index for ch in chunks] == list(range(len(chunks)))

        # Verify token counts bounded
        assert all(ch.token_count <= 150 for ch in chunks)

    def test_overlap_verification_between_adjacent_chunks(self):
        chunker = ClinicalChunker(target_tokens=50, overlap_tokens=15)
        words = [f"word{i:03d}" for i in range(120)]
        text = " ".join(words)

        chunks = chunker.chunk("doc-overlap", text)
        assert len(chunks) >= 2

        # Check overlap between chunk 0 and chunk 1
        c0_words = set(chunks[0].text.split())
        c1_words = set(chunks[1].text.split())
        shared = c0_words.intersection(c1_words)
        assert len(shared) >= 5, f"Expected overlapping tokens between adjacent chunks, got {len(shared)}"


class TestClinicalChunkerSectionPreservation:
    """Tests clinical section header detection, coalescing, and massive section splitting."""

    def test_preserves_standard_clinical_section_headers(self):
        chunker = ClinicalChunker()
        note = (
            "CHIEF COMPLAINT\nSevere retrosternal chest pain.\n\n"
            "HISTORY OF PRESENT ILLNESS\nPain started 2 hours ago radiating to jaw.\n\n"
            "MEDICATIONS\nAspirin 81mg daily, Atorvastatin 40mg daily.\n\n"
            "ASSESSMENT AND PLAN\nAcute coronary syndrome. Admit to CCU for catheterization."
        )

        chunks = chunker.chunk("doc-cardio", note)
        assert len(chunks) == 4
        sec_names = [ch.section_name for ch in chunks]
        assert "CHIEF COMPLAINT" in sec_names
        assert "HISTORY OF PRESENT ILLNESS" in sec_names
        assert "MEDICATIONS" in sec_names
        assert "ASSESSMENT AND PLAN" in sec_names

    def test_detects_markdown_and_colon_headers(self):
        chunker = ClinicalChunker()
        text = (
            "## VITALS\nBP: 120/80 mmHg, HR: 72 bpm, SpO2: 98%.\n\n"
            "**Allergies:**\nPenicillin (anaphylaxis), Sulfa drugs (rash).\n\n"
            "LABS:\nSodium: 140 mEq/L, Potassium: 4.1 mEq/L, Creatinine: 0.9 mg/dL."
        )

        chunks = chunker.chunk("doc-hdrs", text)
        assert len(chunks) == 3
        sec_names = [ch.section_name for ch in chunks]
        assert "VITALS" in sec_names
        assert "ALLERGIES" in sec_names
        assert "LABS" in sec_names

    def test_coalesces_small_sections_when_enabled(self):
        chunker = ClinicalChunker(min_tokens=500, max_tokens=800, coalesce_sections=True)
        note = (
            "CHIEF COMPLAINT\nMild rash.\n\n"
            "VITALS\nTemp 98.6 F, BP 118/76.\n\n"
            "MEDICATIONS\nNone."
        )

        # Small note (< 500 tokens total) should coalesce into single chunk
        chunks = chunker.chunk("doc-coalesce", note)
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "doc-coalesce#c0"
        assert "Mild rash" in chunks[0].text
        assert "Temp 98.6 F" in chunks[0].text
        assert "None" in chunks[0].text

    def test_subdivides_massive_single_section(self):
        chunker = ClinicalChunker(target_tokens=100, overlap_tokens=20)
        # 350 words in a single section
        body = " ".join([f"finding_{i}" for i in range(350)])
        text = f"PHYSICAL EXAMINATION\n{body}"

        chunks = chunker.chunk("doc-pe", text)
        assert len(chunks) >= 3
        # All sub-chunks must retain section_name
        assert all(ch.section_name == "PHYSICAL EXAMINATION" for ch in chunks)
        # Deterministic IDs
        assert chunks[0].chunk_id == "doc-pe#c0"
        assert chunks[1].chunk_id == "doc-pe#c1"
        assert chunks[2].chunk_id == "doc-pe#c2"


class TestClinicalChunkerEdgeCases:
    """Tests boundary inputs, token fallbacks, and metadata inheritance."""

    def test_empty_and_whitespace_returns_empty_list(self):
        chunker = ClinicalChunker()
        assert chunker.chunk("doc-empty", "") == []
        assert chunker.chunk("doc-ws", "   \n\t   ") == []

    def test_deterministic_chunk_ids_and_zero_indexing(self):
        chunker = ClinicalChunker(target_tokens=50, overlap_tokens=10)
        text = " ".join([f"word_{i}" for i in range(150)])
        chunks = chunker.chunk("att-uuid-1234", text)

        assert len(chunks) >= 3
        for idx, ch in enumerate(chunks):
            assert ch.chunk_id == f"att-uuid-1234#c{idx}"
            assert ch.document_id == "att-uuid-1234"
            assert ch.chunk_index == idx

    def test_metadata_inheritance_across_all_chunks(self):
        chunker = ClinicalChunker(target_tokens=50, overlap_tokens=10)
        text = " ".join([f"word_{i}" for i in range(150)])
        meta = {"user_id": "usr-1", "source": "upload", "mime_type": "text/plain"}

        chunks = chunker.chunk("doc-meta", text, metadata=meta)
        for ch in chunks:
            assert ch.metadata["user_id"] == "usr-1"
            assert ch.metadata["source"] == "upload"

    def test_fallback_token_estimation_when_tiktoken_disabled(self):
        chunker = ClinicalChunker()
        # Force fallback by clearing _encoding
        chunker._encoding = None

        text = "Aspirin 81 mg oral daily for secondary prevention of stroke"
        token_count = chunker.count_tokens(text)
        assert token_count > 0
        # 10 words * 1.33 = ~13 tokens
        assert 10 <= token_count <= 20

        chunks = chunker.chunk("doc-fallback", text)
        assert len(chunks) == 1
        assert chunks[0].token_count == token_count

    def test_extreme_text_5000_words_terminates_cleanly(self):
        chunker = ClinicalChunker(target_tokens=500, overlap_tokens=100)
        huge = " ".join(["patient_record_data"] * 5000)
        chunks = chunker.chunk("doc-huge", huge)

        assert len(chunks) >= 10
        assert all(ch.chunk_id.startswith("doc-huge#c") for ch in chunks)
