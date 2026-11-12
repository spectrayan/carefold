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

"""Backward-compatibility re-export shim for yarvelle_core.search.adapters.spector."""

from __future__ import annotations

from typing import Any

from yarvelle_core.search.adapters.spector import *  # noqa: F401, F403
import yarvelle_core.search.adapters.spector as _target_module
from yarvelle_core.search.adapters.spector import SpectorSearchIndex as _CoreSpectorSearchIndex

from carefold.search.chunker import ClinicalChunker as _DefaultChunker


class SpectorSearchIndex(_CoreSpectorSearchIndex):
    """Carefold search adapter defaulting to Carefold's section-aware chunker."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("chunker") is None and len(args) < 6:
            kwargs["chunker"] = _DefaultChunker()
        super().__init__(*args, **kwargs)


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(dir(_target_module)))
