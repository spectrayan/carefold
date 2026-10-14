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

"""PII Sanitizer for Document & Attachment Extraction (Feature F-35 & Domain 5).

Automated masking of direct identifiers (SSN, MRN, phone numbers, street addresses,
emails) before sending document contents to external model providers, while strictly
preserving clinical terms, blood pressure (e.g. 120/80 mmHg), lab values, medications,
and dosages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Set, Tuple, Union

# ============================================================================
# 1. Replacement Tag Constants
# ============================================================================

DEFAULT_SSN_TAG: str = "[SSN]"
DEFAULT_MRN_TAG: str = "[MRN]"
DEFAULT_PHONE_TAG: str = "[PHONE]"
DEFAULT_ADDRESS_TAG: str = "[ADDRESS]"
DEFAULT_EMAIL_TAG: str = "[EMAIL]"
DEFAULT_REDACTED_TAG: str = "[REDACTED]"


# ============================================================================
# 2. Precompiled Regex Patterns
# ============================================================================

# 2.1 Email Addresses
EMAIL_PATTERN: re.Pattern[str] = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# 2.2 Social Security Numbers (SSN)
# Hyphenated / dotted / space-separated (e.g., 123-45-6789, 123.45.6789, 123 45 6789)
# Uses digit lookarounds (?<!\d) and (?!\d) to match even when adjacent to letters (e.g. 123-45-6789MRN:)
SSN_HYPHEN_PATTERN: re.Pattern[str] = re.compile(
    r"(?<!\d)\d{3}[-\s\.]\d{2}[-\s\.]\d{4}(?!\d)"
)

# Contextual SSN (labeled SSN:, Social Security:, Soc Sec: with unhyphenated or irregular formatting)
SSN_CONTEXT_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)(\b(?:ssn|social\s*security(?:\s*number)?|soc\s*sec)\b[:#\s]+)[0-9\s\-_]{7,15}"
)

# Standalone unhyphenated 9-digit SSN (strictly 9 digits, not 8, 10, or more)
SSN_UNHYPHENATED_PATTERN: re.Pattern[str] = re.compile(
    r"(?<!\d)\d{9}(?!\d)"
)

# 2.3 Medical Record Numbers (MRN)
# Direct MRN token starting with MRN (e.g. MRN44921, MRN998877)
MRN_TOKEN_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)\bMRN[0-9A-Z]+\b"
)

# Contextual MRN labeled with MRN:, Medical Record Number:, etc.
MRN_CONTEXT_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)(\b(?:mrn|medical\s*record\s*(?:no\.?|number)?|med\s*rec\s*#?)\b[:#\s]+)[A-Za-z0-9\-]+"
)

# 2.4 Phone Numbers
# US formats: (555) 234-5678, 555-234-5678, 555.234.5678, 555 234 5678
# International formats with +: +1-555-432-1098, +44 20 7946 0958, +1 (555) 234-5678
# Preserves blood pressure (120/80 mmHg uses /), dates (2026-09-30), and copays ($25)
_US_PHONE: str = (
    r"(?:(?:\+1[\s.-]?)?(?:\(\d{3}\)|\b\d{3})[\s.-]?\d{3}[\s.-]\d{4}|\(\d{3}\)\s*\d{3}[\s.-]\d{4})"
)
_INTL_PHONE: str = (
    r"(?:\+\d{1,3}[\s.-]?(?:\(?\d{1,4}\)?[\s.-]?){2,4}\d{2,4})"
)
PHONE_COMBINED_PATTERN: re.Pattern[str] = re.compile(
    rf"(?:{_INTL_PHONE}|{_US_PHONE})(?:\s*(?:ext|x|ext\.)\s*\d{{1,5}})?"
)
PHONE_CONTEXT_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)(\b(?:phone|tel|telephone|cell|mobile|fax)\b[:#\s]+)\+?[0-9\s().-]{7,20}"
)

# 2.5 Street Addresses
# Matches house number + street name + street suffix (e.g. 123 Elm Street, Springfield)
# Enforces \b on street types to avoid matching clinical words like "stay" in "stay: 24 hours".
# Uses negative lookaheads and word boundary restrictions to prevent collisions with:
# - Physician titles: "Dr. Smith" (Drive vs Doctor)
# - Diagnostic imaging: "CT scan" (Court vs Computed Tomography)
# - Pathology findings: "sentinel LN showed..." (Lane vs Lymph Node)
# - Common nouns: "different way" (Street suffix Way vs common noun way)
_STREET_TYPES: str = (
    r"(?:"
    r"Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|"
    r"Drive|Dr(?!\.\s*(?-i:[A-Z])|\s+(?-i:[A-Z][a-z]+(?:'s)?\b))\.?|"
    r"Lane|Ln(?!\s*(?:showed|positive|negative|dissection|biopsy|involvement|metastasis|resected|removed|palpable|enlarged|nodes?|status)\b)\.?|"
    r"Way(?!\s+(?:to|of|that|in|out|through)\b)|"
    r"Court|Ct(?!\s*(?:scan|imaging|angiogram|guided|results?)\b)\.?|"
    r"Place|Pl\.?|Terrace|Ter\.?|Circle|Cir\.?|"
    r"Parkway|Pkwy\.?|Highway|Hwy\.?|Loop|Square|Sq\.?|Trail|Trl\.?|Path"
    r")\b"
)
_UNIT_PATTERN: str = (
    r"(?:\s*,?\s*(?:Apt|Suite|Ste|Unit|Building|Bldg|Floor|Fl|Room|Rm|#)\.?\s*[A-Za-z0-9\-]+)?"
)
_CITY_STATE_ZIP: str = (
    r"(?:"
    r"\s*,\s*[A-Z][a-zA-Z\s.-]{1,30}?\s*,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?"
    r"|\s*,\s*[A-Z][a-zA-Z\s.-]{1,30}?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?"
    r"|\s*,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?"
    r"|\s*,\s*\d{5}(?:-\d{4})?"
    r"|\s*,\s*[A-Z][a-zA-Z\s.-]{1,30}?\s*,\s*[A-Z]{2}\b"
    r"|\s*,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?=\s*(?:[.,\n\r)]|$|\b(?:email|phone|mrn|ssn|dob)\b))"
    r")?"
)
_STREET_NAME_WORD: str = (
    r"(?!\b(?:weeks?|days?|months?|years?|hours?|minutes?|times?|doses?|dosed|"
    r"pelvic|chest|abdominal|sentinel|axillary|different|another|other|same|with|every|per)\b)"
    r"[A-Za-z0-9#\.\-]+"
)
ADDRESS_PATTERN: re.Pattern[str] = re.compile(
    rf"(?i)\b\d{{1,5}}\s+(?:{_STREET_NAME_WORD}\s+){{1,4}}{_STREET_TYPES}{_UNIT_PATTERN}{_CITY_STATE_ZIP}"
)
PO_BOX_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)\b(?:p\.?o\.?\s*box\s+\d+)(?:\s*,\s*[A-Z][a-zA-Z\s.-]{1,30}?)?(?:\s*,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)?"
)
ADDRESS_CONTEXT_PATTERN: re.Pattern[str] = re.compile(
    r"(?i)(\b(?:address|resides\s+at|residing\s+at|home\s+address)\b[:\s]+)(?:[0-9A-Za-z\s,.\-#]+?)(?=\s*(?:\n|\r|\.|$|phone|mrn|ssn|dob))"
)


# ============================================================================
# 3. Sanitization Data Model
# ============================================================================

@dataclass
class SanitizationResult:
    """Detailed result of PII sanitization including redacted item counts."""
    sanitized_text: str
    has_pii: bool = False
    redacted_counts: Dict[str, int] = field(default_factory=dict)


# ============================================================================
# 4. Core Sanitizer Functions
# ============================================================================

def sanitize_pii(text: str, mask_type: str = "tag") -> str:
    """Masks direct PII (SSN, MRN, phone, address, email) from input text.

    Args:
        text: Source text possibly containing sensitive identifiers.
        mask_type: "tag" to replace with typed placeholders ([SSN], [MRN], [PHONE], [ADDRESS]),
                   or "redacted" to replace with [REDACTED].

    Returns:
        Sanitized string safe for external model transmission.
    """
    if not text or not isinstance(text, str):
        return "" if text is None else str(text)

    is_redacted = mask_type == "redacted"
    ssn_tag = DEFAULT_REDACTED_TAG if is_redacted else DEFAULT_SSN_TAG
    mrn_tag = DEFAULT_REDACTED_TAG if is_redacted else DEFAULT_MRN_TAG
    phone_tag = DEFAULT_REDACTED_TAG if is_redacted else DEFAULT_PHONE_TAG
    addr_tag = DEFAULT_REDACTED_TAG if is_redacted else DEFAULT_ADDRESS_TAG
    email_tag = DEFAULT_REDACTED_TAG if is_redacted else DEFAULT_EMAIL_TAG

    out = text

    # 1. Mask Email Addresses
    out = EMAIL_PATTERN.sub(email_tag, out)

    # 2. Mask SSN
    # 2a. Hyphenated / dotted / spaced SSN (e.g., 123-45-6789)
    out = SSN_HYPHEN_PATTERN.sub(ssn_tag, out)
    # 2b. Contextually labeled SSN (handles irregular / subtly malformed formatting)
    out = SSN_CONTEXT_PATTERN.sub(rf"\g<1>{ssn_tag}", out)
    # 2c. Standalone unhyphenated 9-digit SSN
    out = SSN_UNHYPHENATED_PATTERN.sub(ssn_tag, out)

    # 3. Mask MRN
    # 3a. Direct MRN tokens (e.g. MRN44921, MRN998877)
    out = MRN_TOKEN_PATTERN.sub(mrn_tag, out)
    # 3b. Contextually labeled MRN (e.g. MRN: 987654)
    out = MRN_CONTEXT_PATTERN.sub(rf"\g<1>{mrn_tag}", out)

    # 4. Mask Phone Numbers
    out = PHONE_COMBINED_PATTERN.sub(phone_tag, out)
    out = PHONE_CONTEXT_PATTERN.sub(rf"\g<1>{phone_tag}", out)

    # 5. Mask Addresses
    out = ADDRESS_PATTERN.sub(addr_tag, out)
    out = PO_BOX_PATTERN.sub(addr_tag, out)

    return out


# Alias required by tests and interfaces
mask_pii = sanitize_pii


def sanitize_pii_with_metadata(text: str, mask_type: str = "tag") -> SanitizationResult:
    """Masks PII and counts redacted instances for audit and safety metadata."""
    if not text or not isinstance(text, str):
        return SanitizationResult(sanitized_text="", has_pii=False, redacted_counts={})

    counts: Dict[str, int] = {}
    counts["email"] = len(EMAIL_PATTERN.findall(text))
    counts["ssn"] = len(SSN_HYPHEN_PATTERN.findall(text)) + len(SSN_UNHYPHENATED_PATTERN.findall(text))
    counts["mrn"] = len(MRN_TOKEN_PATTERN.findall(text))
    counts["phone"] = len(PHONE_COMBINED_PATTERN.findall(text))
    counts["address"] = len(ADDRESS_PATTERN.findall(text)) + len(PO_BOX_PATTERN.findall(text))

    clean_counts = {k: v for k, v in counts.items() if v > 0}
    sanitized = sanitize_pii(text, mask_type=mask_type)
    has_pii = sum(clean_counts.values()) > 0

    return SanitizationResult(
        sanitized_text=sanitized,
        has_pii=has_pii,
        redacted_counts=clean_counts,
    )


# ============================================================================
# 5. Object-Oriented PIISanitizer Interface
# ============================================================================

class PIISanitizer:
    """Thread-safe, state-free PII Sanitizer class providing class- and instance-methods."""

    @staticmethod
    def sanitize(text: str, mask_type: str = "tag") -> str:
        """Sanitizes direct PII from input text."""
        return sanitize_pii(text, mask_type=mask_type)

    @staticmethod
    def mask(text: str) -> str:
        """Masks direct PII using default tag placeholders."""
        return sanitize_pii(text, mask_type="tag")

    @staticmethod
    def sanitize_with_metadata(text: str, mask_type: str = "tag") -> SanitizationResult:
        """Sanitizes PII and returns counts metadata."""
        return sanitize_pii_with_metadata(text, mask_type=mask_type)


__all__ = [
    "DEFAULT_ADDRESS_TAG",
    "DEFAULT_EMAIL_TAG",
    "DEFAULT_MRN_TAG",
    "DEFAULT_PHONE_TAG",
    "DEFAULT_REDACTED_TAG",
    "DEFAULT_SSN_TAG",
    "PIISanitizer",
    "SanitizationResult",
    "mask_pii",
    "sanitize_pii",
    "sanitize_pii_with_metadata",
]
