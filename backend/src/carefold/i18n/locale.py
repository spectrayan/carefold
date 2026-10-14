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

"""IETF BCP 47 (RFC 5646) locale tag validation, RFC 4647 negotiation, and UAX #15 NFC normalization."""

from __future__ import annotations

import re
from typing import Dict, FrozenSet, List, Literal, Optional, Tuple
import unicodedata

DEFAULT_LOCALE: str = "en-US"

RTL_LANGUAGES: FrozenSet[str] = frozenset({"ar", "he", "fa", "ur"})

SUPPORTED_LOCALES: Dict[str, Dict[str, str]] = {
    "en-US": {
        "code": "en-US",
        "name": "English (United States)",
        "native_name": "English (US)",
        "native": "English (US)",
        "direction": "ltr",
        "dir": "ltr",
        "region": "US",
    },
    "es-ES": {
        "code": "es-ES",
        "name": "Spanish",
        "native_name": "Español",
        "native": "Español",
        "direction": "ltr",
        "dir": "ltr",
        "region": "ES",
    },
    "fr-FR": {
        "code": "fr-FR",
        "name": "French",
        "native_name": "Français",
        "native": "Français",
        "direction": "ltr",
        "dir": "ltr",
        "region": "FR",
    },
    "hi-IN": {
        "code": "hi-IN",
        "name": "Hindi",
        "native_name": "हिन्दी",
        "native": "हिन्दी",
        "direction": "ltr",
        "dir": "ltr",
        "region": "IN",
    },
    "ar-SA": {
        "code": "ar-SA",
        "name": "Arabic",
        "native_name": "العربية",
        "native": "العربية",
        "direction": "rtl",
        "dir": "rtl",
        "region": "SA",
    },
}

BARE_LANGUAGE_DEFAULTS: Dict[str, str] = {
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "hi": "hi-IN",
    "ar": "ar-SA",
}

_BCP47_PATTERN = re.compile(r"^[a-zA-Z]{2,3}(?:-[a-zA-Z]{4})?(?:-(?:[a-zA-Z]{2}|\d{3}))?$")


def validate_bcp47_tag(tag: str) -> bool:
    """Validates IETF BCP 47 language-script-region syntax."""
    if not isinstance(tag, str) or not tag:
        return False
    return bool(_BCP47_PATTERN.match(tag))


def canonicalize_locale(
    tag: Optional[str],
    default: str = DEFAULT_LOCALE,
    strict: bool = False,
) -> str:
    """Normalizes BCP 47 locale tag casing and maps bare language subtags to canonical locales."""
    if tag is None or not isinstance(tag, str) or not tag.strip():
        if strict:
            raise ValueError("Locale tag must be a non-empty BCP 47 string.")
        return default

    cleaned = tag.strip().replace("_", "-")
    if not validate_bcp47_tag(cleaned):
        if strict:
            raise ValueError(f"Invalid IETF BCP 47 locale tag: {tag!r}")
        return default

    parts = cleaned.split("-")
    lang = parts[0].lower()

    if len(parts) == 1:
        if lang in BARE_LANGUAGE_DEFAULTS:
            return BARE_LANGUAGE_DEFAULTS[lang]
        return lang

    if len(parts) == 2:
        second = parts[1]
        if len(second) == 4:
            return f"{lang}-{second.title()}"
        return f"{lang}-{second.upper()}"

    return f"{lang}-{parts[1].title()}-{parts[2].upper()}"


def get_text_direction(locale: str) -> Literal["ltr", "rtl"]:
    """Returns 'rtl' if the primary language subtag is in RTL_LANGUAGES, otherwise 'ltr'."""
    if not locale or not isinstance(locale, str):
        return "ltr"
    primary_lang = locale.strip().replace("_", "-").split("-")[0].lower()
    return "rtl" if primary_lang in RTL_LANGUAGES else "ltr"


def _match_supported_locale(tag: Optional[str]) -> Optional[str]:
    """Resolves a candidate BCP 47 tag to a supported locale via exact or language-prefix lookup."""
    if not tag or not isinstance(tag, str) or not tag.strip():
        return None
    try:
        canonical = canonicalize_locale(tag, strict=True)
    except ValueError:
        return None

    if canonical in SUPPORTED_LOCALES:
        return canonical

    primary_lang = canonical.split("-")[0].lower()
    mapped = BARE_LANGUAGE_DEFAULTS.get(primary_lang)
    if mapped and mapped in SUPPORTED_LOCALES:
        return mapped
    return None


def _parse_accept_language(header: str) -> List[Tuple[str, float, int]]:
    """Parses HTTP Accept-Language header into (tag, q_weight, index) tuples sorted by descending q."""
    entries: List[Tuple[str, float, int]] = []
    for idx, raw_part in enumerate(header.split(",")):
        part = raw_part.strip()
        if not part:
            continue
        subparts = [s.strip() for s in part.split(";")]
        lang_range = subparts[0]
        if not lang_range:
            continue
        q_val = 1.0
        for param in subparts[1:]:
            if param.lower().startswith("q="):
                try:
                    q_val = float(param[2:].strip())
                except ValueError:
                    q_val = -1.0
                break
        if 0.0 < q_val <= 1.0:
            entries.append((lang_range, q_val, idx))

    entries.sort(key=lambda item: (-item[1], item[2]))
    return entries


def negotiate_locale(
    accept_language: Optional[str] = None,
    profile_locale: Optional[str] = None,
    user_locale: Optional[str] = None,
    default: str = DEFAULT_LOCALE,
) -> str:
    """Implements RFC 4647 lookup hierarchy: profile_locale -> user_locale -> Accept-Language -> default."""
    if profile_locale:
        matched_profile = _match_supported_locale(profile_locale)
        if matched_profile:
            return matched_profile

    if user_locale:
        matched_user = _match_supported_locale(user_locale)
        if matched_user:
            return matched_user

    if accept_language and isinstance(accept_language, str) and accept_language.strip():
        for lang_range, _, _ in _parse_accept_language(accept_language):
            if lang_range == "*":
                return default
            matched_header = _match_supported_locale(lang_range)
            if matched_header:
                return matched_header

    return default


def normalize_text_nfc(text: str) -> str:
    """Applies Unicode Standard Annex #15 Canonical Composition (NFC) to text."""
    if not isinstance(text, str) or not text:
        return text
    return unicodedata.normalize("NFC", text)


__all__ = [
    "BARE_LANGUAGE_DEFAULTS",
    "DEFAULT_LOCALE",
    "RTL_LANGUAGES",
    "SUPPORTED_LOCALES",
    "canonicalize_locale",
    "get_text_direction",
    "negotiate_locale",
    "normalize_text_nfc",
    "validate_bcp47_tag",
]
