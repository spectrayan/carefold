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

"""Document chunker re-exporting yarvelle_core chunker with Carefold ClinicalChunker."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from yarvelle_core.search.chunker import Chunker, DocumentChunk, StructuralChunker  # noqa: F401

ClinicalChunk = DocumentChunk


class ClinicalChunker(StructuralChunker):
    """Semantic section chunker partitioning structured narratives into bounded chunks."""

    SECTIONS: Tuple[str, ...] = (
        "CHIEF COMPLAINT", "REASON FOR VISIT", "REASON FOR ENCOUNTER", "CC",
        "HISTORY OF PRESENT ILLNESS", "HPI", "PAST MEDICAL HISTORY", "PMH",
        "PAST SURGICAL HISTORY", "PSH", "CURRENT MEDICATIONS", "MEDICATIONS", "MEDS",
        "ALLERGIES", "DRUG ALLERGIES", "VITAL SIGNS", "VITALS",
        "PHYSICAL EXAMINATION", "PHYSICAL EXAM", "PE", "REVIEW OF SYSTEMS", "ROS",
        "LABORATORY RESULTS", "LABORATORY DATA", "LAB RESULTS", "LABS",
        "DIAGNOSTIC STUDIES", "IMAGING", "RADIOLOGY",
        "ASSESSMENT AND PLAN", "ASSESSMENT & PLAN", "ASSESSMENT / PLAN", "ASSESSMENT/PLAN",
        "ASSESSMENT", "PLAN", "IMPRESSION", "RECOMMENDATIONS",
        "SUBJECTIVE", "OBJECTIVE", "A/P",
        "DISCHARGE SUMMARY", "DISCHARGE INSTRUCTIONS", "DISCHARGE", "FOLLOW-UP", "FOLLOW UP",
    )

    def _split_into_sections(self, text: str) -> List[Tuple[Optional[str], str]]:
        section_blocks: List[Tuple[Optional[str], str]] = []
        current_section: Optional[str] = None
        curr_lines: List[str] = []
        for line in text.split("\n"):
            upper = line.strip().upper()
            clean_hdr = re.sub(r"^[#*\s]+|[:\-*\s]+$", "", upper).strip()
            matched_sec = None
            for sec in self.SECTIONS:
                if (
                    clean_hdr == sec
                    or upper == sec
                    or upper.startswith((f"{sec}:", f"{sec} -", f"{sec}\n", f"## {sec}", f"### {sec}", f"# {sec}"))
                ):
                    matched_sec = sec
                    break
            if matched_sec:
                if curr_lines:
                    block = "\n".join(curr_lines).strip()
                    if block:
                        section_blocks.append((current_section, block))
                    curr_lines = []
                current_section = matched_sec
            curr_lines.append(line)
        if curr_lines:
            block = "\n".join(curr_lines).strip()
            if block:
                section_blocks.append((current_section, block))
        return section_blocks


__all__ = ["Chunker", "DocumentChunk", "ClinicalChunk", "StructuralChunker", "ClinicalChunker"]
