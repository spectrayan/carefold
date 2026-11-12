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

"""Re-export shim delegating to yarvelle_core.engine."""

from __future__ import annotations

import yarvelle_core.engine as _yc_engine
from carefold.engine.runtime import CarefoldAgentExecutionService

_RETIRED = frozenset({"GraphBuilder", "create_agent_graph"})
for _k in dir(_yc_engine):
    if not _k.startswith("_") and _k not in _RETIRED:
        globals()[_k] = getattr(_yc_engine, _k)
AgentExecutionService = CarefoldAgentExecutionService
__all__ = [k for k in getattr(_yc_engine, "__all__", []) if k not in _RETIRED]


def __getattr__(name: str):
    if name in _RETIRED:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(_yc_engine, name)
