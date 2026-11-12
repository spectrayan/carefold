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

"""Backward-compatibility re-export shim for yarvelle_core.schemas.manifest."""

from __future__ import annotations

import sys
from typing import Any

from yarvelle_core.schemas.manifest import *  # noqa: F401, F403
import yarvelle_core.schemas.manifest as _target_module

# 1. Eagerly register "clinical" domain on core AgentDomain
if hasattr(_target_module, "AgentDomain"):
    if not hasattr(_target_module.AgentDomain, "CLINICAL"):
        try:
            _target_module.AgentDomain.CLINICAL = _target_module.AgentDomain.register("clinical")
        except ValueError:
            pass

# 2. Attach CarefoldYaml backward-compatible alias onto target module
if hasattr(_target_module, "YarvelleYaml"):
    setattr(_target_module, "CarefoldYaml", _target_module.YarvelleYaml)

CarefoldYaml = getattr(_target_module, "YarvelleYaml", None)

sys.modules[__name__] = _target_module


def __getattr__(name: str) -> Any:
    if name == "CarefoldYaml":
        return getattr(_target_module, "YarvelleYaml")
    return getattr(_target_module, name)


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(dir(_target_module)) | {"CarefoldYaml"})
