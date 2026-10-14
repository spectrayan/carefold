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

"""Delegation meta-tools for dynamic orchestrator routing (Feature F-50 & Milestone 6).

Exports:
- ListAgentsTool: enables discovery of available specialist agents and capabilities.
- DelegateToAgentTool: signals LangGraph dynamic routing to a target specialist agent.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from carefold.constants.agents import (
    AGENT_ORCHESTRATOR,
    TOOL_DELEGATE_TO_AGENT,
    TOOL_LIST_AGENTS,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 1. ListAgentsTool
# ============================================================================

class ListAgentsInput(BaseModel):
    """Input argument schema for ListAgentsTool (parameterless discovery)."""
    pass


class ListAgentsTool(BaseTool):
    """LangChain tool allowing the Orchestrator to inspect available specialist agents."""

    name: str = TOOL_LIST_AGENTS
    description: str = (
        "List all available specialist agents and their capabilities from the live agent catalog. "
        "Use this tool to discover which agent is best suited to handle a specific request."
    )
    args_schema: Type[BaseModel] = ListAgentsInput
    registry: Any = None

    def __init__(self, registry: Any = None, **kwargs: Any) -> None:
        super().__init__(registry=registry, **kwargs)

    def _run(self, **kwargs: Any) -> str:
        """Synchronously format agent catalog from registry."""
        if self.registry is not None and hasattr(self.registry, "format_agent_catalog"):
            return self.registry.format_agent_catalog(exclude=AGENT_ORCHESTRATOR)

        # Fallback dynamic discovery using loaders
        try:
            from carefold.config import settings
            from carefold.constants.paths import SYSTEM_AGENTS_DIR
            from carefold.loaders.agent_loader import load_agent
            agents_dir = settings.get_agents_dir()
            skills_dir = settings.get_skills_dir()
            lines = []
            candidate_dirs = []
            for entry in sorted(agents_dir.iterdir()):
                if not entry.is_dir():
                    continue
                if entry.name == SYSTEM_AGENTS_DIR:
                    for subentry in sorted(entry.iterdir()):
                        if subentry.is_dir() and not subentry.name.startswith((".", "_")):
                            candidate_dirs.append(subentry)
                elif not entry.name.startswith((".", "_")):
                    candidate_dirs.append(entry)

            for entry in candidate_dirs:
                if entry.name == AGENT_ORCHESTRATOR:
                    continue
                try:
                    manifest, effective_tools, _ = load_agent(entry, skills_dir)
                    desc = getattr(manifest, "description", "") or (
                        manifest.persona.role if hasattr(manifest.persona, "role") else ""
                    )
                    tools_str = ", ".join(effective_tools)
                    lines.append(f"- **{manifest.id}** ({manifest.title}): {desc}\n  Tools: [{tools_str}]")
                except Exception:
                    continue
            if lines:
                return "\n".join(lines)
        except Exception as exc:
            logger.debug("ListAgentsTool fallback discovery note: %s", exc)

        return (
            "- **visit-steward**: Prepares for clinical appointments, organizes questions, tracks symptoms.\n"
            "- **benefits-guide**: Health insurance navigation, copays, deductibles, prior authorization.\n"
            "- **habit-companion**: Wellness habit tracking, hydration, sleep, lifestyle routines.\n"
            "- **document-extractor**: Analyzes attachments, sanitizes PII, extracts typed structured dossiers."
        )

    async def _arun(self, **kwargs: Any) -> str:
        """Asynchronous execution delegating to _run."""
        return self._run(**kwargs)


# ============================================================================
# 2. DelegateToAgentTool
# ============================================================================

class DelegateToAgentInput(BaseModel):
    """Input argument schema for DelegateToAgentTool."""

    agent_id: str = Field(
        ...,
        description="The unique identifier of the target specialist agent (e.g. 'benefits-guide', 'visit-steward', 'document-extractor').",
    )
    instructions: str = Field(
        default="",
        description="Specific instructions, goals, questions, or context for the delegated specialist agent.",
    )


class DelegateToAgentTool(BaseTool):
    """LangChain tool signaling the orchestrator graph to route execution to a specialist agent.

    The tool call output is intercepted by the Orchestrator / Graph edge router to transition
    state['current_agent'] and state['routed_subgraph'].
    """

    name: str = TOOL_DELEGATE_TO_AGENT
    description: str = (
        "Delegate the user's request to a specialist agent by ID, providing instructions. "
        "Available specialists include: 'visit-steward', 'benefits-guide', 'habit-companion', 'document-extractor'."
    )
    args_schema: Type[BaseModel] = DelegateToAgentInput

    def _run(self, agent_id: str, instructions: str = "", **kwargs: Any) -> str:
        """Emit JSON delegation directive for graph transition."""
        payload = {
            "status": "delegated",
            "agent_id": agent_id.strip(),
            "instructions": instructions.strip(),
        }
        return json.dumps(payload)

    async def _arun(self, agent_id: str, instructions: str = "", **kwargs: Any) -> str:
        """Asynchronous delegation directive emission."""
        return self._run(agent_id=agent_id, instructions=instructions, **kwargs)


__all__ = [
    "DelegateToAgentInput",
    "DelegateToAgentTool",
    "ListAgentsInput",
    "ListAgentsTool",
]
