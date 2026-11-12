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

"""Default runtime constants re-exported from yarvelle_core with Carefold host metadata."""
from __future__ import annotations
from yarvelle_core.constants.defaults import *  # noqa: F401, F403
import yarvelle_core.constants.defaults as _yc_mod

DEFAULT_NOTE_AGENT_ID: str = "carefold-agent"
DEFAULT_VERSION: str = "0.1.0"
APP_TITLE: str = "Carefold Local-First AI Runtime"
APP_DESCRIPTION: str = "Local-first agentic runtime, tools sandbox, safety refusal, and audit logging for health specialists."
BUNDLED_AGENT_IDS = frozenset({"appointment-prep-coordinator", "benefits-coordinator", "habit-coordinator", "suggestion-generator", "document-extractor", "orchestrator"})
BUNDLED_SKILL_IDS = frozenset({"visit-prep", "benefits-explainer", "habit-checkin"})
DEFAULT_FORBIDDEN_INTENTS = ("diagnose", "prescribe", "dose", "replace_emergency_care", "instruct_stop_medication")

def __getattr__(name: str):
    return getattr(_yc_mod, name)
