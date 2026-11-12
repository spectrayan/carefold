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

# 1. Eagerly register "clinical" domain and dual-version RiskClass values
if hasattr(_target_module, "AgentDomain"):
    if not hasattr(_target_module.AgentDomain, "CLINICAL"):
        try:
            _target_module.AgentDomain.CLINICAL = _target_module.AgentDomain.register("clinical")
        except ValueError:
            pass

if hasattr(_target_module, "RiskClass") and hasattr(_target_module.RiskClass, "register"):
    for _attr, _val in (("ASSIST", "assist"), ("CLINICAL_ASSIST", "clinical_assist")):
        if not hasattr(_target_module.RiskClass, _attr):
            try:
                setattr(_target_module.RiskClass, _attr, _target_module.RiskClass.register(_val))
            except ValueError:
                pass

if hasattr(_target_module, "AgentSummary") and "assist_enabled" not in _target_module.AgentSummary.model_fields:

    class _CompatAgentSummary(_target_module.AgentSummary):  # type: ignore[misc]
        assist_enabled: bool = True

        def model_post_init(self, __context: Any) -> None:
            super().model_post_init(__context)
            if "assist_enabled" in self.model_fields_set and "clinical_enabled" not in self.model_fields_set:
                self.clinical_enabled = self.assist_enabled
            elif "clinical_enabled" in self.model_fields_set and "assist_enabled" not in self.model_fields_set:
                self.assist_enabled = self.clinical_enabled

    _target_module.AgentSummary = _CompatAgentSummary  # type: ignore[misc]
    AgentSummary = _CompatAgentSummary

if (
    hasattr(_target_module, "AgentDetailResponse")
    and "assist_requires_flag" not in _target_module.AgentDetailResponse.model_fields
):

    class _CompatAgentDetailResponse(_target_module.AgentDetailResponse):  # type: ignore[misc]
        assist_requires_flag: bool = False

        def model_post_init(self, __context: Any) -> None:
            super().model_post_init(__context)
            if (
                "assist_requires_flag" in self.model_fields_set
                and "clinical_requires_flag" not in self.model_fields_set
            ):
                self.clinical_requires_flag = self.assist_requires_flag
            elif (
                "clinical_requires_flag" in self.model_fields_set
                and "assist_requires_flag" not in self.model_fields_set
            ):
                self.assist_requires_flag = self.clinical_requires_flag

    _target_module.AgentDetailResponse = _CompatAgentDetailResponse  # type: ignore[misc]
    AgentDetailResponse = _CompatAgentDetailResponse

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
