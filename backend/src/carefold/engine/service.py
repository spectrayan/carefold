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

"""Production AgentExecutionService: yarvelle-core runtime with health-pack orchestration.

The forked Carefold service implementation is replaced by
``CarefoldAgentExecutionService``, which wraps core's Deep Agents runtime and
injects pack orchestration, the health safety policy, and a routing-aware
input guardrail. There is no legacy runtime feature flag.
"""

from __future__ import annotations

from yarvelle_core.engine.service import (
    strip_internal_suggestion_leakage,
    strip_reference_doc_preamble,
)

from carefold.engine.runtime import (
    CarefoldAgentExecutionService,
    CarefoldAgentExecutionService as AgentExecutionService,
    create_execution_service,
)

__all__ = [
    "AgentExecutionService",
    "CarefoldAgentExecutionService",
    "create_execution_service",
    "strip_internal_suggestion_leakage",
    "strip_reference_doc_preamble",
]
