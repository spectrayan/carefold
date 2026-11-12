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

"""Model constants re-exported from yarvelle_core with Carefold mock model identifier."""

from __future__ import annotations

from yarvelle_core.constants.models import *  # noqa: F401, F403

DEFAULT_MOCK_MODEL: str = "carefold-mock"

import yarvelle_core.constants.models as _yc_mod

def __getattr__(name: str):
    return getattr(_yc_mod, name)
