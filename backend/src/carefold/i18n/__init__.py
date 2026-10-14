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
