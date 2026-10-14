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

"""Carefold Internationalization (i18n) package: BCP 47 locales, ICU catalogs, and multilingual safety."""

from carefold.i18n.catalog import (
    LOCALES_DIR,
    MULTILINGUAL_RED_FLAG_PATTERNS,
    detect_multilingual_red_flag,
    format_icu_message,
    get_catalog,
    get_localized_disclaimer,
    get_localized_emergency_directive,
    translate,
)
from carefold.i18n.locale import (
    BARE_LANGUAGE_DEFAULTS,
    DEFAULT_LOCALE,
    RTL_LANGUAGES,
    SUPPORTED_LOCALES,
    canonicalize_locale,
    get_text_direction,
    negotiate_locale,
    normalize_text_nfc,
    validate_bcp47_tag,
)

__all__ = [
    "BARE_LANGUAGE_DEFAULTS",
    "DEFAULT_LOCALE",
    "LOCALES_DIR",
    "MULTILINGUAL_RED_FLAG_PATTERNS",
    "RTL_LANGUAGES",
    "SUPPORTED_LOCALES",
    "canonicalize_locale",
    "detect_multilingual_red_flag",
    "format_icu_message",
    "get_catalog",
    "get_localized_disclaimer",
    "get_localized_emergency_directive",
    "get_text_direction",
    "negotiate_locale",
    "normalize_text_nfc",
    "translate",
    "validate_bcp47_tag",
]
