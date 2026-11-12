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

"""Re-export shim delegating to yarvelle_core.api.skills."""

from __future__ import annotations

import sys as _sys

from carefold.resources.loader import get_resource_loader as _get_cf_loader
from yarvelle_core.api.skills import *  # noqa: F401, F403
import yarvelle_core.api.skills as _target_module

_target_module.MANDATORY_SAFETY_STATEMENTS[:] = list(
    _get_cf_loader().get_mandatory_intended_use_lines()
)
_sys.modules[__name__] = _target_module
