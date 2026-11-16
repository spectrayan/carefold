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

"""Agent constants re-exported from yarvelle_core with Carefold pack IDs."""

from __future__ import annotations

from yarvelle_core.constants.agents import *  # noqa: F401, F403

AGENT_VISIT_PREP_COORDINATOR: str = "appointment-prep-coordinator"
AGENT_BENEFITS_COORDINATOR: str = "benefits-coordinator"
AGENT_HABIT_COORDINATOR: str = "habit-coordinator"
DEFAULT_ROUTING_FALLBACK_AGENT: str = AGENT_VISIT_PREP_COORDINATOR
RISK_CLASS_CLINICAL_ASSIST: str = "assist"
BUNDLED_AGENT_IDS = frozenset({
    AGENT_VISIT_PREP_COORDINATOR,
    AGENT_BENEFITS_COORDINATOR,
    AGENT_HABIT_COORDINATOR,
    "suggestion-generator",
    "document-extractor",
    "orchestrator",
})
ALL_BUNDLED_AGENT_IDS = BUNDLED_AGENT_IDS

import yarvelle_core.constants.agents as _yc_mod

def __getattr__(name: str):
    return getattr(_yc_mod, name)
