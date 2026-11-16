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

_FALLBACK_WORKSPACE_NOTE_MCP_TOOLS: tuple[str, ...] = (
    "create_workspace_note",
    "get_workspace_note",
    "list_workspace_notes",
    "update_workspace_note",
    "delete_workspace_note",
    "upsert_workspace_note",
)
if not hasattr(_yc_mod, "WORKSPACE_NOTE_MCP_TOOLS"):
    setattr(_yc_mod, "WORKSPACE_NOTE_MCP_TOOLS", _FALLBACK_WORKSPACE_NOTE_MCP_TOOLS)
WORKSPACE_NOTE_MCP_TOOLS = getattr(_yc_mod, "WORKSPACE_NOTE_MCP_TOOLS")

if not hasattr(_yc_mod, "expand_workspace_note_tools"):

    def _expand_workspace_note_tools(tool_names):
        names = list(tool_names or ())
        if "workspace-note" not in names and not any(
            t in WORKSPACE_NOTE_MCP_TOOLS for t in names
        ):
            return names
        for note_tool in WORKSPACE_NOTE_MCP_TOOLS:
            if note_tool not in names:
                names.append(note_tool)
        return names

    setattr(_yc_mod, "expand_workspace_note_tools", _expand_workspace_note_tools)
expand_workspace_note_tools = getattr(_yc_mod, "expand_workspace_note_tools")


def __getattr__(name: str):
    return getattr(_yc_mod, name)
