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

"""Re-export shim delegating to yarvelle_core.api.health."""

from __future__ import annotations

import sys as _sys

from carefold.constants.defaults import DEFAULT_VERSION as _CF_VERSION
from yarvelle_core.api.health import *  # noqa: F401, F403
import yarvelle_core.api.health as _target_module

_target_module.DEFAULT_VERSION = _CF_VERSION
_sys.modules[__name__] = _target_module
