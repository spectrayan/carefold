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

"""Re-export shim delegating to yarvelle_core.workflows.nodes."""

from __future__ import annotations

import yarvelle_core.workflows.nodes as _yc_nodes
from carefold.clinical.host_bridges import CarefoldInputGuardrailNode as InputGuardrailNode
from carefold.clinical.host_bridges import CarefoldWorkflowRefusalNode as RefusalNode

_RETIRED = frozenset({"OrchestratorDecision", "OrchestratorNode", "SupervisorNode"})
for _k in dir(_yc_nodes):
    if not _k.startswith("_") and _k not in _RETIRED and _k not in ("InputGuardrailNode", "RefusalNode"):
        globals()[_k] = getattr(_yc_nodes, _k)
__all__ = [k for k in getattr(_yc_nodes, "__all__", []) if k not in _RETIRED]


def __getattr__(name: str):
    if name in _RETIRED:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(_yc_nodes, name)
