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

"""Backward-compatibility re-export shim for yarvelle_core.schemas.chat."""

from __future__ import annotations

import sys
from typing import Any

from yarvelle_core.schemas.chat import *  # noqa: F401, F403
import yarvelle_core.schemas.chat as _target_module

if hasattr(_target_module, "ChatRequestBody") and "allow_assist" not in _target_module.ChatRequestBody.model_fields:

    class _CompatChatRequestBody(_target_module.ChatRequestBody):  # type: ignore[misc]
        allow_assist: bool = False

        def model_post_init(self, __context: Any) -> None:
            super().model_post_init(__context)
            if "allow_assist" in self.model_fields_set and "allow_clinical" not in self.model_fields_set:
                self.allow_clinical = self.allow_assist
            elif "allow_clinical" in self.model_fields_set and "allow_assist" not in self.model_fields_set:
                self.allow_assist = self.allow_clinical

    _target_module.ChatRequestBody = _CompatChatRequestBody  # type: ignore[misc]
    ChatRequestBody = _CompatChatRequestBody

sys.modules[__name__] = _target_module


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(dir(_target_module)))
