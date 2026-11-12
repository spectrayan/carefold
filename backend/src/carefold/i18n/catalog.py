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

"""Locale catalog shim configuring Carefold locale directory on yarvelle_core.i18n.catalog."""

from __future__ import annotations

from pathlib import Path
import sys as _sys
import yarvelle_core.i18n.catalog as _target_module

_target_module.LOCALES_DIR = Path(__file__).resolve().parent.parent / "resources" / "locales"
if hasattr(_target_module, "clear_catalog_cache"):
    _target_module.clear_catalog_cache()

_sys.modules[__name__] = _target_module
