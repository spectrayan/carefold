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

"""Thin compatibility re-export over `carefold.connectors.withings` (#338)."""

from __future__ import annotations

from typing import Any

import carefold.connectors.withings as _impl
from carefold.connectors.withings import *  # noqa: F401, F403
from carefold.connectors.withings import __all__  # noqa: F401


def __getattr__(name: str) -> Any:
    return getattr(_impl, name)
