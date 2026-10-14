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

"""Deterministic safety refusal classifier.

Intercepts clinical diagnosis, dosing/prescriptions, emergency triage diversion,
and medication discontinuation. Employs markdown normalization and disclaimer
neutralization to prevent false positives on responsible wellness disclosures.

All regex patterns, vocabularies, normalization rules, and disclaimers are
sourced dynamically from external YAML resources via ResourceLoader.
Zero raw regex strings or disclaimer texts are directly embedded in Python code.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional

from carefold.constants.defaults import FORBIDDEN_INTENT_PREFIX
from carefold.resources.loader import RefusalPattern, get_resource_loader
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE


@dataclass(frozen=True)
class SafetyCheckResult:
    refused: bool
    reason: Optional[str] = None
    safe_response: Optional[str] = None


# Module initialization from external resources
_loader = get_resource_loader()
_refusal_data: Dict[str, Any] = _loader.get_refusal_patterns()
_resolved_blocks: Dict[str, str] = _loader._resolve_building_blocks()
_norm: Dict[str, Any] = _refusal_data.get("normalization", {})

# Vocabularies & subpatterns (exported for full backward compatibility)
COMMON_CONDITIONS_LIST: List[str] = list(_refusal_data.get("building_blocks", {}).get("common_conditions_list", []))
COMMON_CONDITIONS: str = _resolved_blocks.get("COMMON_CONDITIONS", "")
CONDITION_TAIL: str = _resolved_blocks.get("CONDITION_TAIL", "")
DOSING_UNITS: str = _resolved_blocks.get("DOSING_UNITS", "")
SINGLE_NUM: str = _resolved_blocks.get("SINGLE_NUM", "")
FRACTION_OR_NUM: str = _resolved_blocks.get("FRACTION_OR_NUM", "")
NUMERIC_QUANTITY: str = _resolved_blocks.get("NUMERIC_QUANTITY", "")
PROVIDER_ROLE: str = _resolved_blocks.get("PROVIDER_ROLE", "")
DISCLAIMER_MED_TARGET: str = _resolved_blocks.get("DISCLAIMER_MED_TARGET", "")
ALL_CESSATION_DRUGS: str = _resolved_blocks.get("ALL_CESSATION_DRUGS", "")
ALL_KINSHIPS: str = _resolved_blocks.get("ALL_KINSHIPS", "")
KINSHIP_MODIFIER: str = _resolved_blocks.get("KINSHIP_MODIFIER", "")
CAREGIVER_RECIPIENT: str = _resolved_blocks.get("CAREGIVER_RECIPIENT", "")
DOSING_RECIPIENT: str = _resolved_blocks.get("DOSING_RECIPIENT", "")
FAMILY_POSSESSIVE_DETERMINERS: str = _resolved_blocks.get("FAMILY_POSSESSIVE_DETERMINERS", "")
DIAGNOSTIC_SUBJECTS: str = _resolved_blocks.get("DIAGNOSTIC_SUBJECTS", "")
CONFIRM_SUBJECTS: str = _resolved_blocks.get("CONFIRM_SUBJECTS", "")
SUBJECT_QUALIFIER: str = _resolved_blocks.get("SUBJECT_QUALIFIER", "")

# Compiled disclaimer clauses and refusal patterns
DISCLAIMER_CLAUSES: List[re.Pattern] = _loader.get_compiled_disclaimer_clauses()
REFUSAL_PATTERNS: List[RefusalPattern] = _loader.get_compiled_refusal_patterns()

# Compiled normalization regexes
_HTML_STRIP_REGEX: re.Pattern = re.compile(_norm.get("html_strip", ""), re.IGNORECASE)
_MARKDOWN_STRIP_REGEX: re.Pattern = re.compile(_norm.get("markdown_strip", ""))
_ELLIPSES_REGEX: re.Pattern = re.compile(_norm.get("ellipses_strip", ""))
_QUOTE_NORMALIZE_REGEX: re.Pattern = re.compile(_norm.get("quote_normalize", ""))
_SENTENCE_SPLIT_REGEX: re.Pattern = re.compile(_norm.get("sentence_split", ""))

_ANCHORED_REFUSAL_PATTERNS: List[RefusalPattern] = [p for p in REFUSAL_PATTERNS if "^" in p.regex.pattern or "$" in p.regex.pattern]


def reload_safety_resources() -> None:
    """Reloads patterns and clauses from ResourceLoader into module globals."""
    global _refusal_data, _resolved_blocks, _norm
    global COMMON_CONDITIONS_LIST, COMMON_CONDITIONS, CONDITION_TAIL, DOSING_UNITS
    global SINGLE_NUM, FRACTION_OR_NUM, NUMERIC_QUANTITY, PROVIDER_ROLE
    global DISCLAIMER_MED_TARGET, ALL_CESSATION_DRUGS, ALL_KINSHIPS, KINSHIP_MODIFIER
    global CAREGIVER_RECIPIENT, DOSING_RECIPIENT, FAMILY_POSSESSIVE_DETERMINERS
    global DIAGNOSTIC_SUBJECTS, CONFIRM_SUBJECTS, SUBJECT_QUALIFIER
    global DISCLAIMER_CLAUSES, REFUSAL_PATTERNS, _ANCHORED_REFUSAL_PATTERNS
    global _HTML_STRIP_REGEX, _MARKDOWN_STRIP_REGEX, _ELLIPSES_REGEX, _QUOTE_NORMALIZE_REGEX, _SENTENCE_SPLIT_REGEX

    _loader.clear_cache()
    _refusal_data = _loader.get_refusal_patterns()
    _resolved_blocks = _loader._resolve_building_blocks()
    _norm = _refusal_data.get("normalization", {})

    COMMON_CONDITIONS_LIST = list(_refusal_data.get("building_blocks", {}).get("common_conditions_list", []))
    COMMON_CONDITIONS = _resolved_blocks.get("COMMON_CONDITIONS", "")
    CONDITION_TAIL = _resolved_blocks.get("CONDITION_TAIL", "")
    DOSING_UNITS = _resolved_blocks.get("DOSING_UNITS", "")
    SINGLE_NUM = _resolved_blocks.get("SINGLE_NUM", "")
    FRACTION_OR_NUM = _resolved_blocks.get("FRACTION_OR_NUM", "")
    NUMERIC_QUANTITY = _resolved_blocks.get("NUMERIC_QUANTITY", "")
    PROVIDER_ROLE = _resolved_blocks.get("PROVIDER_ROLE", "")
    DISCLAIMER_MED_TARGET = _resolved_blocks.get("DISCLAIMER_MED_TARGET", "")
    ALL_CESSATION_DRUGS = _resolved_blocks.get("ALL_CESSATION_DRUGS", "")
    ALL_KINSHIPS = _resolved_blocks.get("ALL_KINSHIPS", "")
    KINSHIP_MODIFIER = _resolved_blocks.get("KINSHIP_MODIFIER", "")
    CAREGIVER_RECIPIENT = _resolved_blocks.get("CAREGIVER_RECIPIENT", "")
    DOSING_RECIPIENT = _resolved_blocks.get("DOSING_RECIPIENT", "")
    FAMILY_POSSESSIVE_DETERMINERS = _resolved_blocks.get("FAMILY_POSSESSIVE_DETERMINERS", "")
    DIAGNOSTIC_SUBJECTS = _resolved_blocks.get("DIAGNOSTIC_SUBJECTS", "")
    CONFIRM_SUBJECTS = _resolved_blocks.get("CONFIRM_SUBJECTS", "")
    SUBJECT_QUALIFIER = _resolved_blocks.get("SUBJECT_QUALIFIER", "")

    DISCLAIMER_CLAUSES = _loader.get_compiled_disclaimer_clauses()
    REFUSAL_PATTERNS = _loader.get_compiled_refusal_patterns()

    _HTML_STRIP_REGEX = re.compile(_norm.get("html_strip", ""), re.IGNORECASE)
    _MARKDOWN_STRIP_REGEX = re.compile(_norm.get("markdown_strip", ""))
    _ELLIPSES_REGEX = re.compile(_norm.get("ellipses_strip", ""))
    _QUOTE_NORMALIZE_REGEX = re.compile(_norm.get("quote_normalize", ""))
    _SENTENCE_SPLIT_REGEX = re.compile(_norm.get("sentence_split", ""))

    _ANCHORED_REFUSAL_PATTERNS = [p for p in REFUSAL_PATTERNS if "^" in p.regex.pattern or "$" in p.regex.pattern]


# Hard refusal categories (Tier 1): immediate full content suppression/replacement
# Covers acute emergencies, direct medication dosing/prescribing, replacing ER care, and stopping meds.
HARD_REFUSAL_PREFIXES: tuple[str, ...] = (
    "emergency_red_flag",
    "emergency_red_flags",
    f"{FORBIDDEN_INTENT_PREFIX}prescribe",
    f"{FORBIDDEN_INTENT_PREFIX}dose",
    f"{FORBIDDEN_INTENT_PREFIX}instruct_stop_medication",
    f"{FORBIDDEN_INTENT_PREFIX}replace_emergency_care",
)


def is_hard_refusal_reason(reason: Optional[str]) -> bool:
    """Evaluates whether a refusal reason requires a hard refusal (Tier 1).

    Tier 1 hard refusals completely suppress content and display an emergency/refusal card.
    Applies to acute emergency red flags, prescription directives, dosing, stopping medications,
    and emergency room diversion.

    Tier 2 soft clinical boundaries (e.g. diagnose, medical_prohibited) preserve the generated
    educational output and attach an explicit clinical boundary notice.
    """
    if not reason:
        return False
    lower = reason.lower().strip()
    return any(lower.startswith(prefix) or prefix in lower for prefix in HARD_REFUSAL_PREFIXES)


def check_safety_refusal(text: Optional[str]) -> SafetyCheckResult:
    """Evaluates whether the given text triggers the medical safety refusal gate."""
    if not text or not isinstance(text, str):
        return SafetyCheckResult(refused=False)

    # 1. Normalize formatting decorators:
    # Remove HTML tags (e.g. <b>, </b>, <i>, </i>)
    normalized_text = _HTML_STRIP_REGEX.sub("", text)
    # Remove markdown formatting characters (*, _, `, #, ~)
    normalized_text = _MARKDOWN_STRIP_REGEX.sub("", normalized_text)
    # Normalize ellipses (... or …) to spaces so they do not break sentences or token streams
    normalized_text = _ELLIPSES_REGEX.sub(" ", normalized_text)
    # Normalize single quotation marks and apostrophes to standard ASCII single quote
    if _QUOTE_NORMALIZE_REGEX.pattern:
        normalized_text = _QUOTE_NORMALIZE_REGEX.sub("'", normalized_text)
    else:
        normalized_text = (
            normalized_text.replace("\u2019", "'")
            .replace("\u2018", "'")
            .replace("\u0092", "'")
        )

    # 2. Neutralize legitimate disclaimer and history clauses by replacing them with spaces of equal length
    sanitized_text = normalized_text
    for disclaimer_regex in DISCLAIMER_CLAUSES:
        sanitized_text = disclaimer_regex.sub(lambda m: " " * len(m.group(0)), sanitized_text)

    # 3. Check for refusal patterns against full sanitized text
    for pattern in REFUSAL_PATTERNS:
        if pattern.regex.search(sanitized_text):
            return SafetyCheckResult(
                refused=True,
                reason=f"{FORBIDDEN_INTENT_PREFIX}{pattern.category}",
                safe_response=SAFE_REFUSAL_TEMPLATE,
            )

    # 4. Check anchored patterns against individual sentences if present
    if _ANCHORED_REFUSAL_PATTERNS:
        sentences = _SENTENCE_SPLIT_REGEX.split(sanitized_text)
        if len(sentences) > 1:
            for sentence in sentences:
                trimmed = sentence.strip()
                if not trimmed or trimmed == sanitized_text:
                    continue

                for pattern in _ANCHORED_REFUSAL_PATTERNS:
                    if pattern.regex.search(trimmed):
                        return SafetyCheckResult(
                            refused=True,
                            reason=f"{FORBIDDEN_INTENT_PREFIX}{pattern.category}",
                            safe_response=SAFE_REFUSAL_TEMPLATE,
                        )

    return SafetyCheckResult(refused=False)



__all__ = [
    "COMMON_CONDITIONS",
    "COMMON_CONDITIONS_LIST",
    "CONDITION_TAIL",
    "DOSING_UNITS",
    "SINGLE_NUM",
    "FRACTION_OR_NUM",
    "NUMERIC_QUANTITY",
    "PROVIDER_ROLE",
    "DISCLAIMER_MED_TARGET",
    "ALL_CESSATION_DRUGS",
    "ALL_KINSHIPS",
    "KINSHIP_MODIFIER",
    "CAREGIVER_RECIPIENT",
    "DOSING_RECIPIENT",
    "FAMILY_POSSESSIVE_DETERMINERS",
    "DIAGNOSTIC_SUBJECTS",
    "CONFIRM_SUBJECTS",
    "SUBJECT_QUALIFIER",
    "DISCLAIMER_CLAUSES",
    "REFUSAL_PATTERNS",
    "RefusalPattern",
    "SafetyCheckResult",
    "check_safety_refusal",
    "reload_safety_resources",
    "HARD_REFUSAL_PREFIXES",
    "is_hard_refusal_reason",
]

