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

"""ICU MessageFormat catalog loader, translation resolver, and multilingual clinical safety guardrails."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from carefold.i18n.locale import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    canonicalize_locale,
    negotiate_locale,
    normalize_text_nfc,
)

LOCALES_DIR: Path = Path(__file__).resolve().parent.parent / "resources" / "locales"

_SIMPLE_VAR_PATTERN = re.compile(r"\{([a-zA-Z0-9_]+)\}")

# Multilingual acute emergency red-flag phrases (all stored in UAX #15 NFC form)
MULTILINGUAL_RED_FLAG_PATTERNS: Dict[str, List[Tuple[str, str]]] = {
    "en-US": [
        ("chest pain", "cardiopulmonary_emergency"),
        ("crushing chest", "cardiopulmonary_emergency"),
        ("shortness of breath", "respiratory_emergency"),
        ("difficulty breathing", "respiratory_emergency"),
        ("can't breathe", "respiratory_emergency"),
        ("cannot breathe", "respiratory_emergency"),
        ("stroke symptoms", "neurological_emergency"),
        ("suicidal", "self_harm_emergency"),
        ("suicide", "self_harm_emergency"),
        ("kill myself", "self_harm_emergency"),
        ("end my life", "self_harm_emergency"),
    ],
    "es-ES": [
        ("dolor en el pecho", "cardiopulmonary_emergency"),
        ("opresión en el pecho", "cardiopulmonary_emergency"),
        ("dificultad para respirar", "respiratory_emergency"),
        ("falta de aire", "respiratory_emergency"),
        ("no puedo respirar", "respiratory_emergency"),
        ("suicidio", "self_harm_emergency"),
        ("quitarme la vida", "self_harm_emergency"),
        ("matarme", "self_harm_emergency"),
    ],
    "fr-FR": [
        ("douleur thoracique", "cardiopulmonary_emergency"),
        ("douleur dans la poitrine", "cardiopulmonary_emergency"),
        ("difficulté à respirer", "respiratory_emergency"),
        ("mal à respirer", "respiratory_emergency"),
        ("essoufflement aigu", "respiratory_emergency"),
        ("suicide", "self_harm_emergency"),
        ("me suicider", "self_harm_emergency"),
        ("mettre fin à mes jours", "self_harm_emergency"),
    ],
    "hi-IN": [
        ("सीने में दर्द", "cardiopulmonary_emergency"),
        ("छाती में दर्द", "cardiopulmonary_emergency"),
        ("सांस लेने में तकलीफ", "respiratory_emergency"),
        ("सांस नहीं आ रही", "respiratory_emergency"),
        ("आत्महत्या", "self_harm_emergency"),
        ("खुदकुशी", "self_harm_emergency"),
    ],
    "ar-SA": [
        ("ألم في الصدر", "cardiopulmonary_emergency"),
        ("ضيق في التنفس", "respiratory_emergency"),
        ("صعوبة في التنفس", "respiratory_emergency"),
        ("انتحار", "self_harm_emergency"),
        ("أقتل نفسي", "self_harm_emergency"),
    ],
}


@lru_cache(maxsize=1)
def _load_all_raw_catalogs() -> Dict[str, Dict[str, Any]]:
    """Reads and caches all built-in locale JSON catalogs from constant filenames."""
    base_dir = LOCALES_DIR.resolve()
    catalogs: Dict[str, Dict[str, Any]] = {}
    for code in ("en-US", "es-ES", "fr-FR", "hi-IN", "ar-SA"):
        target_path = base_dir / f"{code}.json"
        if target_path.is_file():
            raw = target_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            catalogs[code] = data if isinstance(data, dict) else {}
    return catalogs


def _load_raw_catalog(locale: str) -> Dict[str, Any]:
    """Returns a cached locale JSON catalog for the negotiated BCP 47 tag."""
    catalogs = _load_all_raw_catalogs()
    safe_locale = locale if locale in catalogs else negotiate_locale(profile_locale=locale, default=DEFAULT_LOCALE)
    return dict(catalogs.get(safe_locale) or catalogs.get(DEFAULT_LOCALE, {}))


_load_raw_catalog.cache_clear = _load_all_raw_catalogs.cache_clear  # type: ignore[attr-defined]


def get_catalog(locale: str = DEFAULT_LOCALE) -> Dict[str, Any]:
    """Returns the resolved message catalog for a locale with fallback to en-US."""
    resolved = negotiate_locale(profile_locale=locale, default=DEFAULT_LOCALE)
    base = _load_raw_catalog(DEFAULT_LOCALE)
    if resolved == DEFAULT_LOCALE:
        return dict(base)
    override = _load_raw_catalog(resolved)
    merged: Dict[str, Any] = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged


def _select_cldr_plural_category(count: int | float, locale: str) -> List[str]:
    """Returns ordered candidate CLDR plural categories for a numeric count and locale."""
    primary_lang = (locale or DEFAULT_LOCALE).split("-")[0].lower()
    n = abs(count)
    i = int(n)

    candidates: List[str] = [f"={i}"]
    if n == 0:
        candidates.append("zero")

    if primary_lang == "ar":
        mod100 = i % 100
        if n == 0:
            candidates.append("zero")
        elif n == 1:
            candidates.append("one")
        elif n == 2:
            candidates.append("two")
        elif 3 <= mod100 <= 10:
            candidates.append("few")
        elif 11 <= mod100 <= 99:
            candidates.append("many")
        candidates.append("other")
        return candidates

    if primary_lang in ("fr", "hi"):
        if i in (0, 1):
            candidates.append("one")
        candidates.append("other")
        return candidates

    # Default (en, es, etc.)
    if n == 1:
        candidates.append("one")
    elif n == 2:
        candidates.append("two")
    candidates.append("other")
    return candidates


def _parse_plural_branches(body: str) -> Dict[str, str]:
    """Parses ICU plural branches like 'zero {No items} one {# item} other {# items}'."""
    branches: Dict[str, str] = {}
    idx = 0
    length = len(body)

    while idx < length:
        while idx < length and body[idx].isspace():
            idx += 1
        if idx >= length:
            break

        # Read selector key (e.g. zero, one, two, few, many, other, =0, =1)
        key_start = idx
        while idx < length and not body[idx].isspace() and body[idx] != "{":
            idx += 1
        selector = body[key_start:idx].strip()

        while idx < length and body[idx].isspace():
            idx += 1
        if idx >= length or body[idx] != "{":
            break

        # Read balanced {...} block
        idx += 1  # skip opening '{'
        depth = 1
        content_start = idx
        while idx < length and depth > 0:
            if body[idx] == "{":
                depth += 1
            elif body[idx] == "}":
                depth -= 1
            idx += 1
        branch_text = body[content_start : idx - 1]
        if selector:
            branches[selector] = branch_text

    return branches


def _expand_icu_blocks(template: str, params: Dict[str, Any], locale: str) -> str:
    """Expands top-level ICU {var, plural, ...} blocks in a message template."""
    result: List[str] = []
    idx = 0
    length = len(template)

    while idx < length:
        if template[idx] != "{":
            result.append(template[idx])
            idx += 1
            continue

        # Find matching '}'
        depth = 1
        pos = idx + 1
        while pos < length and depth > 0:
            if template[pos] == "{":
                depth += 1
            elif template[pos] == "}":
                depth -= 1
            pos += 1

        if depth != 0:
            result.append(template[idx:])
            break

        inner = template[idx + 1 : pos - 1]
        parts = [p.strip() for p in inner.split(",", 2)]
        if len(parts) == 3 and parts[1].lower() == "plural":
            var_name = parts[0]
            raw_val = params.get(var_name, 0)
            try:
                num_val: int | float = int(raw_val) if float(raw_val).is_integer() else float(raw_val)
            except (ValueError, TypeError):
                num_val = 0

            branches = _parse_plural_branches(parts[2])
            selected_template = ""
            for cat in _select_cldr_plural_category(num_val, locale):
                if cat in branches:
                    selected_template = branches[cat]
                    break
            if not selected_template and "other" in branches:
                selected_template = branches["other"]

            formatted_num = str(num_val)
            rendered = selected_template.replace("#", formatted_num)
            rendered = _SIMPLE_VAR_PATTERN.sub(
                lambda m: str(params.get(m.group(1), m.group(0))),
                rendered,
            )
            result.append(rendered)
        else:
            # Simple variable placeholder {var}
            var_key = inner.strip()
            if var_key in params:
                result.append(str(params[var_key]))
            else:
                result.append("{" + inner + "}")

        idx = pos

    return "".join(result)


def format_icu_message(
    template: str,
    params: Optional[Dict[str, Any]] = None,
    locale: str = DEFAULT_LOCALE,
) -> str:
    """Formats an ICU MessageFormat string supporting {variable} and {count, plural, ...}."""
    if not isinstance(template, str) or not template:
        return ""
    effective_params = params or {}
    return _expand_icu_blocks(template, effective_params, locale=locale)


def _lookup_key(catalog: Dict[str, Any], key: str) -> Optional[str]:
    """Resolves a dot-separated key against a catalog dictionary (case-insensitive section lookup)."""
    if not key:
        return None
    node: Any = catalog
    for segment in key.split("."):
        if not isinstance(node, dict):
            return None
        if segment in node:
            node = node[segment]
        else:
            lower_seg = segment.lower()
            matched_key = next((k for k in node.keys() if k.lower() == lower_seg), None)
            if matched_key is None:
                return None
            node = node[matched_key]
    return node if isinstance(node, str) else None


def translate(
    key: str,
    locale: str = DEFAULT_LOCALE,
    params: Optional[Dict[str, Any]] = None,
) -> str:
    """Resolves a dot-separated translation key with fallback from locale -> en-US."""
    resolved_locale = negotiate_locale(profile_locale=locale, default=DEFAULT_LOCALE)
    cat = _load_raw_catalog(resolved_locale)
    template = _lookup_key(cat, key)
    if template is None and resolved_locale != DEFAULT_LOCALE:
        fallback_cat = _load_raw_catalog(DEFAULT_LOCALE)
        template = _lookup_key(fallback_cat, key)
    if template is None:
        return key
    return format_icu_message(template, params=params, locale=resolved_locale)


def get_localized_disclaimer(locale: str = DEFAULT_LOCALE) -> str:
    """Returns the localized non-clinical intended-use disclaimer for the requested locale."""
    return translate("safety.disclaimer_banner", locale=locale)


def get_localized_emergency_directive(locale: str = DEFAULT_LOCALE) -> str:
    """Returns the localized acute emergency refusal directive for the requested locale."""
    return translate("safety.emergency_directive", locale=locale)


def detect_multilingual_red_flag(text: str) -> Optional[Dict[str, str]]:
    """Checks UAX #15 NFC normalized text against multilingual acute emergency red-flag phrases."""
    if not isinstance(text, str) or not text.strip():
        return None

    normalized = normalize_text_nfc(text).casefold()

    # Check non-English locales first so specific scripts/phrases match their native locale,
    # followed by English (en-US).
    locale_check_order = ("es-ES", "fr-FR", "hi-IN", "ar-SA", "en-US")
    for loc in locale_check_order:
        patterns = MULTILINGUAL_RED_FLAG_PATTERNS.get(loc, [])
        for phrase, category in patterns:
            norm_phrase = normalize_text_nfc(phrase).casefold()
            if norm_phrase in normalized:
                return {
                    "detected": "true",
                    "locale": loc,
                    "category": category,
                    "matched_phrase": normalize_text_nfc(phrase),
                    "emergency_directive": get_localized_emergency_directive(loc),
                    "disclaimer": get_localized_disclaimer(loc),
                }

    return None


__all__ = [
    "LOCALES_DIR",
    "MULTILINGUAL_RED_FLAG_PATTERNS",
    "detect_multilingual_red_flag",
    "format_icu_message",
    "get_catalog",
    "get_localized_disclaimer",
    "get_localized_emergency_directive",
    "translate",
]
