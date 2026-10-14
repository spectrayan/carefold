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

"""Deterministic, zero-egress local hybrid search reranker (AU-79).

Provides `LocalCrossReranker` to refine hybrid (FTS5 + vector) retrieval candidates
by boosting exact clinical code matches (LOINC, SNOMED, CVX, RxNorm, ICD-10),
token/character-bigram lexical overlap, and clinical section headers without
any external API calls or network egress.
"""

from __future__ import annotations

from typing import List, Sequence, Set, Tuple

from carefold.search.base import SearchResult

CLINICAL_SECTION_HEADERS: Tuple[str, ...] = (
    "medications",
    "allergies",
    "assessment",
    "plan",
    "immunizations",
    "vital signs",
)

CLINICAL_CODE_SYSTEM_KEYWORDS: Tuple[str, ...] = (
    "loinc",
    "snomed",
    "cvx",
    "rxnorm",
    "icd-10",
    "icd10",
)

_TOKEN_SEPARATORS = " \t\r\n,.;:()[]{}<>\"'|/\\?!"


def _tokenize_linear(text: str) -> List[str]:
    """Splits text into lowercase alphanumeric/hyphen tokens in linear O(N) time."""
    if not text:
        return []
    lowered = text.lower()
    trans_table = str.maketrans({ch: " " for ch in _TOKEN_SEPARATORS})
    cleaned = lowered.translate(trans_table)
    return [tok.strip("-") for tok in cleaned.split() if tok.strip("-")]


def _extract_clinical_codes(tokens: Sequence[str]) -> Set[str]:
    """Identifies clinical code tokens (e.g. '85354-9', 'e11.9', 'cvx', numeric codes >= 3 chars)."""
    codes: Set[str] = set()
    for tok in tokens:
        if tok in CLINICAL_CODE_SYSTEM_KEYWORDS:
            codes.add(tok)
            continue
        has_digit = any(ch.isdigit() for ch in tok)
        if not has_digit:
            continue
        if "-" in tok and len(tok) >= 3:
            codes.add(tok)
        elif len(tok) >= 3 and any(ch.isalpha() for ch in tok):
            codes.add(tok)
        elif len(tok) >= 4 and tok.isdigit():
            codes.add(tok)
    return codes


def _char_bigrams(text: str) -> Set[str]:
    """Computes character bigrams over normalized lowercase text."""
    compact = " ".join(_tokenize_linear(text))
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _compute_overlap_similarity(query: str, document_text: str) -> float:
    """Computes combined token coverage and character-bigram Jaccard similarity in [0.0, 1.0]."""
    q_tokens = set(_tokenize_linear(query))
    d_tokens = set(_tokenize_linear(document_text))
    if not q_tokens or not d_tokens:
        return 0.0

    token_coverage = len(q_tokens & d_tokens) / float(len(q_tokens))

    q_bigrams = _char_bigrams(query)
    d_bigrams = _char_bigrams(document_text)
    if q_bigrams and d_bigrams:
        union_len = len(q_bigrams | d_bigrams)
        bigram_jaccard = (len(q_bigrams & d_bigrams) / float(union_len)) if union_len else 0.0
    else:
        bigram_jaccard = 0.0

    return (0.70 * token_coverage) + (0.30 * bigram_jaccard)


class LocalCrossReranker:
    """Zero-egress, deterministic local reranker for `SearchResult` candidates (`AU-79`)."""

    BASE_SCORE_WEIGHT: float = 0.45
    CLINICAL_CODE_BOOST: float = 0.30
    OVERLAP_WEIGHT: float = 0.20
    SECTION_HEADER_BOOST: float = 0.05

    def rerank(
        self,
        query: str,
        results: Sequence[SearchResult],
        top_k: int = 10,
    ) -> List[SearchResult]:
        """Reranks `SearchResult` items deterministically using clinical code and lexical signals.

        Args:
            query: Natural language or clinical code search query.
            results: Initial retrieval results to rerank.
            top_k: Maximum number of reranked items to return (default 10).

        Returns:
            New sorted list of `SearchResult` items (up to `top_k`) with updated `score`
            and `metadata["reranked"] = True`.
        """
        if not results or top_k <= 0:
            return []

        clean_query = (query or "").strip()
        q_tokens = _tokenize_linear(clean_query)
        q_codes = _extract_clinical_codes(q_tokens)

        reranked_items: List[SearchResult] = []
        for item in results:
            doc_text = item.text or item.content or ""
            doc_lower = doc_text.lower()
            d_tokens = _tokenize_linear(doc_text)
            d_codes = _extract_clinical_codes(d_tokens)

            # 1. Base retrieval score component (0.45 weight)
            base_val = max(0.0, min(1.0, float(item.score or 0.0)))
            score = base_val * self.BASE_SCORE_WEIGHT

            # 2. Exact clinical code overlap boost (+0.30)
            code_matched = False
            if q_codes and (q_codes & d_codes):
                code_matched = True
            else:
                for qc in q_codes:
                    if qc and qc in doc_lower:
                        code_matched = True
                        break
            if code_matched:
                score += self.CLINICAL_CODE_BOOST

            # 3. Token & character bigram overlap similarity (+0.20 weight)
            overlap_sim = _compute_overlap_similarity(clean_query, doc_text)
            score += overlap_sim * self.OVERLAP_WEIGHT

            # 4. Clinical section header boost (+0.05)
            section_meta = str((item.metadata or {}).get("section") or "").lower()
            has_section = any(
                hdr in doc_lower or hdr in section_meta for hdr in CLINICAL_SECTION_HEADERS
            )
            if has_section:
                score += self.SECTION_HEADER_BOOST

            updated_meta = dict(item.metadata or {})
            updated_meta["reranked"] = True
            updated_meta["clinical_code_match"] = code_matched

            reranked_items.append(
                item.model_copy(
                    update={
                        "score": round(min(1.0, score), 6),
                        "metadata": updated_meta,
                    }
                )
            )

        reranked_items.sort(key=lambda r: (r.score, r.lexical_score, r.semantic_score), reverse=True)
        return reranked_items[: int(top_k)]
