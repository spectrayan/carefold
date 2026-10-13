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

"""Semantic clinical chunker with section boundary preservation and token overlap."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("carefold.search.chunker")

try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False


@dataclass
class ClinicalChunk:
    """Represents a bounded clinical text chunk with section context and deterministic identifier."""

    chunk_id: str
    text: str
    token_count: int
    section_name: Optional[str]
    chunk_index: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    document_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.document_id is None and "#" in self.chunk_id:
            self.document_id = self.chunk_id.split("#", 1)[0]


class ClinicalChunker:
    """Semantic clinical chunker partitioning medical narratives and records into bounded chunks.

    Attributes:
        min_tokens: Minimum token threshold for coalescing (default: 500).
        max_tokens: Maximum token ceiling before chunk subdivision (default: 800).
        overlap_tokens: Sliding window token overlap between consecutive chunks (default: 100).
        target_tokens: Target window size for chunking (default: 600 or max_tokens).
        coalesce_sections: Whether to coalesce adjacent small sections by default (default: False).
    """

    SECTIONS: Tuple[str, ...] = (
        "CHIEF COMPLAINT",
        "REASON FOR VISIT",
        "REASON FOR ENCOUNTER",
        "CC",
        "HISTORY OF PRESENT ILLNESS",
        "HPI",
        "PAST MEDICAL HISTORY",
        "PMH",
        "PAST SURGICAL HISTORY",
        "PSH",
        "CURRENT MEDICATIONS",
        "MEDICATIONS",
        "MEDS",
        "ALLERGIES",
        "DRUG ALLERGIES",
        "VITAL SIGNS",
        "VITALS",
        "PHYSICAL EXAMINATION",
        "PHYSICAL EXAM",
        "PE",
        "REVIEW OF SYSTEMS",
        "ROS",
        "LABORATORY RESULTS",
        "LABORATORY DATA",
        "LAB RESULTS",
        "LABS",
        "DIAGNOSTIC STUDIES",
        "IMAGING",
        "RADIOLOGY",
        "ASSESSMENT AND PLAN",
        "ASSESSMENT & PLAN",
        "ASSESSMENT / PLAN",
        "ASSESSMENT/PLAN",
        "ASSESSMENT",
        "PLAN",
        "IMPRESSION",
        "RECOMMENDATIONS",
        "SUBJECTIVE",
        "OBJECTIVE",
        "A/P",
        "DISCHARGE SUMMARY",
        "DISCHARGE INSTRUCTIONS",
        "DISCHARGE",
        "FOLLOW-UP",
        "FOLLOW UP",
    )

    def __init__(
        self,
        min_tokens: int = 500,
        max_tokens: int = 800,
        overlap_tokens: int = 100,
        target_tokens: Optional[int] = None,
        encoding_name: str = "cl100k_base",
        coalesce_sections: bool = False,
    ) -> None:
        self.overlap_tokens = overlap_tokens
        if target_tokens is not None:
            self.target_tokens = target_tokens
            self.max_tokens = target_tokens
            self.min_tokens = max(1, target_tokens - overlap_tokens)
        else:
            self.target_tokens = 600
            self.min_tokens = min_tokens
            self.max_tokens = max_tokens

        self.encoding_name = encoding_name
        self.coalesce_sections = coalesce_sections
        self._encoding = None

        if _TIKTOKEN_AVAILABLE:
            try:
                self._encoding = tiktoken.get_encoding(encoding_name)
            except Exception as e:
                logger.debug("Failed to load tiktoken encoding %s: %s", encoding_name, e)
                try:
                    self._encoding = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    self._encoding = None

    def count_tokens(self, text: str) -> int:
        """Estimates token count using tiktoken cl100k_base or word heuristic fallback."""
        if not text or not text.strip():
            return 0
        words = text.split()
        if len(words) == 1:
            return 1
        if self._encoding is not None:
            try:
                return len(self._encoding.encode(text))
            except Exception:
                pass
        # Fallback heuristic
        if not words:
            return 0
        return max(1, int(len(words) * 1.33))

    def _split_into_sections(self, text: str) -> List[Tuple[Optional[str], str]]:
        """Parses clinical document into section blocks tagged with normalized section headers."""
        lines = text.split("\n")
        section_blocks: List[Tuple[Optional[str], str]] = []
        current_section: Optional[str] = None
        curr_lines: List[str] = []

        for line in lines:
            trimmed = line.strip()
            upper = trimmed.upper()
            matched_sec = None

            # Detect Markdown, bold, or colon headers
            clean_hdr = re.sub(r"^[#*\s]+|[:\-*\s]+$", "", upper).strip()

            for sec in self.SECTIONS:
                # Check exact match on cleaned header, or startswith with delimiter
                if clean_hdr == sec:
                    matched_sec = sec
                    break
                if upper.startswith(f"{sec}:") or upper.startswith(f"{sec} -") or upper.startswith(f"{sec}\n"):
                    matched_sec = sec
                    break
                if upper.startswith(f"## {sec}") or upper.startswith(f"### {sec}") or upper.startswith(f"# {sec}"):
                    matched_sec = sec
                    break
                if upper == sec:
                    matched_sec = sec
                    break

            if matched_sec:
                if curr_lines:
                    block_content = "\n".join(curr_lines).strip()
                    if block_content:
                        section_blocks.append((current_section, block_content))
                    curr_lines = []
                current_section = matched_sec
                curr_lines.append(line)
            else:
                curr_lines.append(line)

        if curr_lines:
            block_content = "\n".join(curr_lines).strip()
            if block_content:
                section_blocks.append((current_section, block_content))

        return section_blocks

    def _subdivide_tokens(self, text: str) -> List[str]:
        """Subdivides text exceeding max_tokens using sliding window with overlap_tokens."""
        if self._encoding is not None:
            try:
                tokens = self._encoding.encode(text)
                if len(tokens) <= self.max_tokens:
                    return [text]

                slices: List[str] = []
                step = max(1, self.max_tokens - self.overlap_tokens)
                for start in range(0, len(tokens), step):
                    chunk_tokens = tokens[start : start + self.max_tokens]
                    slices.append(self._encoding.decode(chunk_tokens).strip())
                    if start + self.max_tokens >= len(tokens):
                        break
                return [s for s in slices if s]
            except Exception:
                pass

        # Word-based fallback
        words = text.split()
        if len(words) <= self.max_tokens:
            return [text]

        slices = []
        step = max(1, self.max_tokens - self.overlap_tokens)
        for start in range(0, len(words), step):
            window = words[start : start + self.max_tokens]
            slices.append(" ".join(window))
            if start + self.max_tokens >= len(words):
                break
        return [s for s in slices if s]

    def chunk(
        self,
        document_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        coalesce: Optional[bool] = None,
    ) -> List[ClinicalChunk]:
        """Chunks clinical document into bounded, deterministic chunks preserving sections."""
        if not text or not text.strip():
            return []

        base_meta = dict(metadata or {})
        should_coalesce = self.coalesce_sections if coalesce is None else coalesce

        # Case 1: Pure single word or very small document without multiple sections
        doc_tokens = self.count_tokens(text)
        section_blocks = self._split_into_sections(text)

        # If document has no section headers or only one section and is within max_tokens
        if len(section_blocks) <= 1 and doc_tokens <= self.max_tokens:
            sec_name = section_blocks[0][0] if section_blocks else None
            return [
                ClinicalChunk(
                    chunk_id=f"{document_id}#c0",
                    text=text.strip(),
                    token_count=doc_tokens,
                    section_name=sec_name,
                    chunk_index=0,
                    metadata=base_meta,
                    document_id=document_id,
                )
            ]

        # Case 2: Coalescing mode enabled
        if should_coalesce:
            return self._chunk_with_coalescing(document_id, section_blocks, base_meta)

        # Case 3: Preserving distinct clinical section blocks (default)
        chunks: List[ClinicalChunk] = []
        chunk_idx = 0

        for sec_name, block_text in section_blocks:
            block_tokens = self.count_tokens(block_text)
            if block_tokens <= self.max_tokens:
                c_id = f"{document_id}#c{chunk_idx}"
                chunks.append(
                    ClinicalChunk(
                        chunk_id=c_id,
                        text=block_text.strip(),
                        token_count=block_tokens,
                        section_name=sec_name,
                        chunk_index=chunk_idx,
                        metadata={**base_meta, "section": sec_name} if sec_name else dict(base_meta),
                        document_id=document_id,
                    )
                )
                chunk_idx += 1
            else:
                sub_slices = self._subdivide_tokens(block_text)
                for sub in sub_slices:
                    c_id = f"{document_id}#c{chunk_idx}"
                    chunks.append(
                        ClinicalChunk(
                            chunk_id=c_id,
                            text=sub,
                            token_count=self.count_tokens(sub),
                            section_name=sec_name,
                            chunk_index=chunk_idx,
                            metadata={**base_meta, "section": sec_name} if sec_name else dict(base_meta),
                            document_id=document_id,
                        )
                    )
                    chunk_idx += 1

        return chunks

    def _chunk_with_coalescing(
        self,
        document_id: str,
        section_blocks: List[Tuple[Optional[str], str]],
        base_meta: Dict[str, Any],
    ) -> List[ClinicalChunk]:
        """Coalesces small adjacent sections (<500 tokens) up to max_tokens."""
        chunks: List[ClinicalChunk] = []
        chunk_idx = 0
        curr_text = ""
        curr_sections: List[str] = []

        for sec_name, block_text in section_blocks:
            block_tokens = self.count_tokens(block_text)

            # If this individual block exceeds max_tokens, flush current and subdivide block
            if block_tokens > self.max_tokens:
                if curr_text:
                    chunks.append(
                        ClinicalChunk(
                            chunk_id=f"{document_id}#c{chunk_idx}",
                            text=curr_text.strip(),
                            token_count=self.count_tokens(curr_text),
                            section_name=curr_sections[0] if curr_sections else None,
                            chunk_index=chunk_idx,
                            metadata={**base_meta, "sections": list(curr_sections)},
                            document_id=document_id,
                        )
                    )
                    chunk_idx += 1
                    curr_text = ""
                    curr_sections = []

                sub_slices = self._subdivide_tokens(block_text)
                for sub in sub_slices:
                    chunks.append(
                        ClinicalChunk(
                            chunk_id=f"{document_id}#c{chunk_idx}",
                            text=sub,
                            token_count=self.count_tokens(sub),
                            section_name=sec_name,
                            chunk_index=chunk_idx,
                            metadata={**base_meta, "section": sec_name} if sec_name else dict(base_meta),
                            document_id=document_id,
                        )
                    )
                    chunk_idx += 1
                continue

            # Candidate coalesced text
            test_text = (curr_text + "\n\n" + block_text).strip() if curr_text else block_text
            test_tokens = self.count_tokens(test_text)

            if test_tokens <= self.max_tokens:
                curr_text = test_text
                if sec_name:
                    curr_sections.append(sec_name)
            else:
                if curr_text:
                    chunks.append(
                        ClinicalChunk(
                            chunk_id=f"{document_id}#c{chunk_idx}",
                            text=curr_text.strip(),
                            token_count=self.count_tokens(curr_text),
                            section_name=curr_sections[0] if curr_sections else None,
                            chunk_index=chunk_idx,
                            metadata={**base_meta, "sections": list(curr_sections)},
                            document_id=document_id,
                        )
                    )
                    chunk_idx += 1
                curr_text = block_text
                curr_sections = [sec_name] if sec_name else []

        if curr_text:
            chunks.append(
                ClinicalChunk(
                    chunk_id=f"{document_id}#c{chunk_idx}",
                    text=curr_text.strip(),
                    token_count=self.count_tokens(curr_text),
                    section_name=curr_sections[0] if curr_sections else None,
                    chunk_index=chunk_idx,
                    metadata={**base_meta, "sections": list(curr_sections)},
                    document_id=document_id,
                )
            )

        return chunks
