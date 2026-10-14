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

"""Typed notes architecture, category validation, and after-visit extraction engine (AU-35).

Delivers:
- 7 canonical note categories: visit, symptom, question, after_visit, school, scratchpad, general
- Strict note category validation with optional legacy mapping
- After-visit clinical extraction engine parsing diagnoses, medications, tests, and follow-ups
- 1-indexed source line citations ([Note Line X]) grounded against original note content
- Mandatory non-clinical disclaimer: "Extracted from your notes, not formal medical advice."
"""

from __future__ import annotations

from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

logger = logging.getLogger("carefold.clinical.notes")

NON_CLINICAL_DISCLAIMER: str = "Extracted from your notes, not formal medical advice."


class NoteType(str, Enum):
    """Canonical categories for clinical and personal workspace notes (AU-35)."""

    VISIT = "visit"              # Clinical consultation, provider encounter, or exam notes
    SYMPTOM = "symptom"          # Patient symptom journal, flare-ups, severity, triggers
    QUESTION = "question"        # Patient-prepared questions for doctor or upcoming visit
    AFTER_VISIT = "after_visit"  # Encounter debrief, discharge summary, plan takeaways
    SCHOOL = "school"            # School health forms, sports clearance, excuse letters
    SCRATCHPAD = "scratchpad"    # Ephemeral rough drafts, temporary notes
    GENERAL = "general"          # General medical history, family notes, administrative


VALID_NOTE_TYPES: frozenset[str] = frozenset(t.value for t in NoteType)


def validate_note_type(note_type: str, allow_legacy: bool = False) -> str:
    """Validates note category against canonical 7 categories.

    Args:
        note_type: Raw note type string.
        allow_legacy: If True, maps legacy types (clinical_prep -> question, visit_summary -> after_visit).

    Returns:
        Normalized lower-case note type string.

    Raises:
        ValueError: If note type is invalid, empty, or unparseable.
    """
    if not note_type or not str(note_type).strip():
        raise ValueError("Note type must be a non-empty string.")

    clean = str(note_type).strip().lower()

    if clean in VALID_NOTE_TYPES:
        return clean

    if allow_legacy:
        legacy_mappings = {
            "clinical_prep": NoteType.QUESTION.value,
            "visit_summary": NoteType.AFTER_VISIT.value,
        }
        if clean in legacy_mappings:
            return legacy_mappings[clean]

    supported = ", ".join(sorted(VALID_NOTE_TYPES))
    raise ValueError(
        f"Invalid note type '{note_type}'. Must be one of: {supported}"
    )


class ExtractedClinicalItem(BaseModel):
    """Structured clinical entity with source line citation."""

    text: str = Field(..., description="Verbatim or cleaned clinical statement from the note")
    citation: str = Field(..., description="1-indexed physical line citation format: [Note Line X]")


class AfterVisitSummary(BaseModel):
    """Structured extraction output parsed from encounter notes."""

    diagnoses: List[Dict[str, Any]] = Field(default_factory=list)
    medication_adjustments: List[Dict[str, Any]] = Field(default_factory=list)
    ordered_tests: List[Dict[str, Any]] = Field(default_factory=list)
    follow_up_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_reminders: List[Dict[str, Any]] = Field(default_factory=list)
    disclaimer: str = Field(default=NON_CLINICAL_DISCLAIMER)
    extracted_items_count: int = Field(default=0)


def extract_after_visit_summary(note_content: str) -> Dict[str, Any]:
    """Extracts diagnoses, medication adjustments, ordered tests, follow-up with [Note Line X] citations.

    Enforces strict line citations, excludes generic OTC advice from prescription medications,
    and attaches the mandatory non-clinical disclaimer.
    """
    diagnoses: List[Dict[str, Any]] = []
    medications: List[Dict[str, Any]] = []
    tests: List[Dict[str, Any]] = []
    follow_up: List[Dict[str, Any]] = []
    reminders: List[Dict[str, Any]] = []

    lines = note_content.splitlines() if note_content else []

    for idx, line in enumerate(lines, 1):
        clean = line.strip()
        if not clean:
            continue
        lower = clean.lower()

        # 1. Diagnoses / Clinical Findings
        if any(k in lower for k in (
            "diagnosed with",
            "diagnosis:",
            "assessment:",
            "impression:",
            "primary diagnosis",
            "secondary diagnosis",
            "clinical findings:",
            "evaluated for",
            "problem list:",
            "findings:",
        )):
            diagnoses.append({"text": clean, "citation": f"[Note Line {idx}]"})

        # 2. Medication Adjustments (Prescriptions / dosage changes)
        # Invariant: Must NOT be generic over-the-counter advice (OTC decongestants, etc.)
        elif ("over-the-counter" not in lower and "otc" not in lower) and (
            any(k in lower for k in ("prescribed", "start taking", "started on", "medication:", "dosage:", "dose:", "rx:"))
            or (
                any(k in lower for k in (
                    "increased", "decreased", "titrated", "adjusted", "reduced",
                    "discontinue", "discontinued", "stop taking", "stopped", "taper off", "wean off"
                ))
                and any(u in lower for u in ("mg", "mcg", "ml", "tablet", "tablets", "capsule", "capsules", "units", "daily"))
            )
        ):
            medications.append({"text": clean, "citation": f"[Note Line {idx}]"})

        # 3. Ordered Tests / Labs / Imaging
        elif any(k in lower for k in (
            "ordered lab",
            "ordered test",
            "ordered blood",
            "ordered imaging",
            "blood work",
            "blood test",
            "lipid panel",
            "metabolic panel",
            "cbc",
            "mri",
            "x-ray",
            "xray",
            "ultrasound",
            "biopsy",
            "tilt table test",
            "ct scan",
            "echocardiogram",
            "ekg",
            "ecg",
            "urinalysis",
            "test:",
            "labs:",
            "imaging:",
            "order placed",
        )):
            tests.append({"text": clean, "citation": f"[Note Line {idx}]"})

        # 4. Follow-Up Timeline
        elif any(k in lower for k in (
            "follow up in",
            "follow-up in",
            "return in",
            "schedule visit",
            "next appointment",
            "return to clinic",
            "recheck in",
            "see doctor in",
            "follow up with",
            "follow-up with",
            "rtc in",
            "come back in",
        )):
            follow_up.append({"text": clean, "citation": f"[Note Line {idx}]"})

        # 5. Recommended Reminders
        elif any(k in lower for k in (
            "schedule upcoming",
            "schedule fasting",
            "refill",
            "reminder:",
            "remind me",
            "bring log",
            "monitor bp daily",
            "track blood sugar",
            "repeat labs",
            "set reminder",
        )):
            reminders.append({"text": clean, "citation": f"[Note Line {idx}]"})

    total_count = len(diagnoses) + len(medications) + len(tests) + len(follow_up) + len(reminders)

    return {
        "diagnoses": diagnoses,
        "medication_adjustments": medications,
        "ordered_tests": tests,
        "follow_up_timeline": follow_up,
        "recommended_reminders": reminders,
        "disclaimer": NON_CLINICAL_DISCLAIMER,
        "extracted_items_count": total_count,
    }


__all__ = [
    "AfterVisitSummary",
    "ExtractedClinicalItem",
    "NON_CLINICAL_DISCLAIMER",
    "NoteType",
    "VALID_NOTE_TYPES",
    "extract_after_visit_summary",
    "validate_note_type",
]
