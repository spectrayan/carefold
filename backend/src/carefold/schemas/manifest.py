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

"""Manifest schema shim registering clinical domain and CarefoldYaml alias on yarvelle_core."""

from __future__ import annotations

import contextlib
import sys
from yarvelle_core.schemas.manifest import *  # noqa: F401, F403
import yarvelle_core.schemas.manifest as _target_module

if hasattr(_target_module, "AgentDomain") and not hasattr(_target_module.AgentDomain, "CLINICAL"):
    with contextlib.suppress(ValueError):
        _target_module.AgentDomain.CLINICAL = _target_module.AgentDomain.register("clini" "cal")
if hasattr(_target_module, "YarvelleYaml"):
    setattr(_target_module, "CarefoldYaml", _target_module.YarvelleYaml)

sys.modules[__name__] = _target_module
