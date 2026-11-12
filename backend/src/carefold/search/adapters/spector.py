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

"""SpectorSearchIndex shim defaulting chunker to Carefold ClinicalChunker."""

from __future__ import annotations

from typing import Any
from yarvelle_core.search.adapters.spector import *  # noqa: F401, F403
import yarvelle_core.search.adapters.spector as _target_module
from yarvelle_core.search.adapters.spector import SpectorSearchIndex as _CoreIdx
from carefold.search.chunker import ClinicalChunker as _DefaultChunker


class _Meta(type(_CoreIdx)):
    def __instancecheck__(cls, instance: Any) -> bool:
        return super().__instancecheck__(instance) or isinstance(instance, _CoreIdx)


class SpectorSearchIndex(_CoreIdx, metaclass=_Meta):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("chunker") is None and len(args) < 6:
            kwargs["chunker"] = _DefaultChunker()
        super().__init__(*args, **kwargs)


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)
