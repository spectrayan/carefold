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

"""Carefold clinical PHI sanitizer composing yarvelle_core's domain-neutral PII sanitizer.

Adds clinical Medical Record Number (MRN) masking and clinical terminology collision
guards (imaging/pathology abbreviations such as pelvic CT, sentinel LN, dosage phrasing)
on top of ``yarvelle_core.workflows.subgraphs.extraction.sanitizer``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from yarvelle_core.tools.extraction_tools import (
    SanitizePIIInput,
    SanitizePIITool as _CoreSanitizePIITool,
)
from yarvelle_core.workflows.subgraphs.extraction import sanitizer as _core_sanitizer
from yarvelle_core.workflows.subgraphs.extraction.sanitizer import (
    ADDRESS_CONTEXT_PATTERN,
    ADDRESS_PATTERN,
    DEFAULT_ADDRESS_TAG,
    DEFAULT_EMAIL_TAG,
    DEFAULT_PHONE_TAG,
    DEFAULT_REDACTED_TAG,
    DEFAULT_SSN_TAG,
    EMAIL_PATTERN,
    PHONE_COMBINED_PATTERN,
    PHONE_CONTEXT_PATTERN,
    PO_BOX_PATTERN,
    SSN_CONTEXT_PATTERN,
    SSN_HYPHEN_PATTERN,
    SSN_UNHYPHENATED_PATTERN,
    SanitizationResult,
)

DEFAULT_RECORD_ID_TAG: str = getattr(_core_sanitizer, "DEFAULT_RECORD_ID_TAG", "[RECORD_ID]")
RECORD_ID_TOKEN_PATTERN: re.Pattern[str] = getattr(
    _core_sanitizer,
    "RECORD_ID_TOKEN_PATTERN",
    re.compile(r"(?i)(?:(?<=\d)|\b)(?:REC|ID|ACCT|MEM)[0-9A-Z]+\b"),
)
RECORD_ID_CONTEXT_PATTERN: re.Pattern[str] = getattr(
    _core_sanitizer,
    "RECORD_ID_CONTEXT_PATTERN",
    re.compile(
        r"(?i)((?:(?<=\d)|\b)(?:record\s*(?:id|no\.?|number)|reference\s*(?:id|no\.?|number)|account\s*(?:id|no\.?|number)|member\s*(?:id|no\.?|number))\b[:#\s]+)[A-Za-z0-9\-]+"
    ),
)

DEFAULT_MRN_TAG: str = "[MRN]"

MRN_TOKEN_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)(?:(?<=\d)|\b)MRN[0-9A-Z]+\b"
)

MRN_CONTEXT_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)((?:(?<=\d)|\b)(?:mrn|medical\s*record\s*(?:no\.?|number)?|med\s*rec)\b[:#\s]+)[A-Za-z0-9\-]+"
)

_CLINICAL_COLLISION_GUARD_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)\b(?:dosed\s+)?\d{1,5}\s+(?:(?:pelvic|chest|abdominal|sentinel|axillary|different|doses?|dosed)\s+){1,3}"
    r"(?:CT|LN|Way|Dr\.?)(?:\s+(?:scan|imaging|biopsy|dissection|nodes?|results?|showed))?\b"
    r"|\b(?:rec|acct|mem)[a-z]{4,}\b"
)


def sanitize_pii(text: str, mask_type: str = "tag") -> str:
    """Masks direct PII and clinical MRN identifiers while preserving clinical terminology."""
    if not text or not isinstance(text, str):
        return "" if text is None else str(text)

    is_redacted = mask_type == "redacted"
    mrn_tag = DEFAULT_REDACTED_TAG if is_redacted else DEFAULT_MRN_TAG

    shielded_spans: List[str] = []

    def _shield(match: re.Match[str]) -> str:
        idx = len(shielded_spans)
        shielded_spans.append(match.group(0))
        return f"__CF_CLIN_GUARD_{idx}__"

    out = _CLINICAL_COLLISION_GUARD_PATTERN.sub(_shield, text)
    out = MRN_TOKEN_PATTERN.sub(mrn_tag, out)
    out = MRN_CONTEXT_PATTERN.sub(rf"\g<1>{mrn_tag}", out)
    out = _core_sanitizer.sanitize_pii(out, mask_type=mask_type)

    for idx, original in enumerate(shielded_spans):
        out = out.replace(f"__CF_CLIN_GUARD_{idx}__", original)

    return out


mask_pii = sanitize_pii


def sanitize_pii_with_metadata(text: str, mask_type: str = "tag") -> SanitizationResult:
    """Masks clinical PHI + general PII and returns redacted counts including 'mrn'."""
    if not text or not isinstance(text, str):
        return SanitizationResult(sanitized_text="", has_pii=False, redacted_counts={})

    shielded_for_counts = re.sub(r"(?i)\b(?:rec|acct|mem)[a-z]{4,}\b", "", text)
    base_meta = _core_sanitizer.sanitize_pii_with_metadata(shielded_for_counts, mask_type=mask_type)
    counts: Dict[str, int] = dict(base_meta.redacted_counts)
    mrn_count = len(MRN_TOKEN_PATTERN.findall(text))
    if mrn_count > 0:
        counts["mrn"] = mrn_count

    sanitized = sanitize_pii(text, mask_type=mask_type)
    has_pii = bool(counts) or sanitized != text
    return SanitizationResult(
        sanitized_text=sanitized,
        has_pii=has_pii,
        redacted_counts=counts,
    )


class PIISanitizer:
    """Thread-safe clinical + general PII sanitizer facade."""

    @staticmethod
    def sanitize(text: str, mask_type: str = "tag") -> str:
        return sanitize_pii(text, mask_type=mask_type)

    @staticmethod
    def mask(text: str) -> str:
        return sanitize_pii(text, mask_type="tag")

    @staticmethod
    def sanitize_with_metadata(text: str, mask_type: str = "tag") -> SanitizationResult:
        return sanitize_pii_with_metadata(text, mask_type=mask_type)


class SanitizePIITool(_CoreSanitizePIITool):
    """Carefold clinical PII/PHI sanitization tool including MRN masking."""

    def _run(self, text: str, mask_type: str = "tag", **kwargs: Any) -> str:
        return sanitize_pii(text, mask_type=mask_type)


__all__ = [
    "ADDRESS_CONTEXT_PATTERN",
    "ADDRESS_PATTERN",
    "DEFAULT_ADDRESS_TAG",
    "DEFAULT_EMAIL_TAG",
    "DEFAULT_MRN_TAG",
    "DEFAULT_PHONE_TAG",
    "DEFAULT_RECORD_ID_TAG",
    "DEFAULT_REDACTED_TAG",
    "DEFAULT_SSN_TAG",
    "EMAIL_PATTERN",
    "MRN_CONTEXT_PATTERN",
    "MRN_TOKEN_PATTERN",
    "PHONE_COMBINED_PATTERN",
    "PHONE_CONTEXT_PATTERN",
    "PIISanitizer",
    "PO_BOX_PATTERN",
    "RECORD_ID_CONTEXT_PATTERN",
    "RECORD_ID_TOKEN_PATTERN",
    "SSN_CONTEXT_PATTERN",
    "SSN_HYPHEN_PATTERN",
    "SSN_UNHYPHENATED_PATTERN",
    "SanitizationResult",
    "SanitizePIIInput",
    "SanitizePIITool",
    "mask_pii",
    "sanitize_pii",
    "sanitize_pii_with_metadata",
]
