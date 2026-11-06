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

"""Production-configured core routing primitives for offline tests.

The forked Carefold ``OrchestratorNode`` / ``GraphBuilder`` were retired in
favour of ``yarvelle_core``'s implementations, which the live runtime
(``carefold.engine.runtime``) configures with the health pack's orchestration
spec and default agent. These thin wrappers mirror
``CarefoldAgentExecutionService._build_orchestrated_graph``: pack orchestration,
default agent, ``CarefoldHealthSafetyPolicy``, soft orchestration audit, and
Carefold's refusal and response-synthesizer nodes. They are test-only; no
compatibility shim is added under ``backend/src``.
"""

from __future__ import annotations

from typing import Any

from yarvelle_core.engine.builder import GraphBuilder as CoreGraphBuilder
from yarvelle_core.workflows.nodes.orchestrator_node import (
    TIER1_DOMAIN_CLASSIFIER_PROMPT,
    DomainClassification,
    OrchestratorDecision,
)
from yarvelle_core.workflows.nodes.orchestrator_node import (
    OrchestratorNode as CoreOrchestratorNode,
)


def pack_orchestration() -> Any:
    """Return the health pack orchestration spec used by the live runtime."""
    from carefold import get_pack

    return get_pack().orchestration


class OrchestratorNode(CoreOrchestratorNode):
    """Core orchestrator defaulted to the Carefold pack orchestration spec."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "orchestration" not in kwargs:
            kwargs["orchestration"] = pack_orchestration()
        orch = kwargs["orchestration"]
        if "default_agent" not in kwargs and orch is not None:
            kwargs["default_agent"] = getattr(orch, "default_agent", None)
        super().__init__(*args, **kwargs)


async def soft_orchestration_audit(event: Any) -> None:
    """Best-effort audit sink matching ``CarefoldAgentExecutionService``."""
    try:
        from yarvelle_core.engine.builder import _record_orchestration_audit

        await _record_orchestration_audit(event)
    except Exception:  # pragma: no cover - mirrors runtime soft-audit behaviour
        pass


class GraphBuilder(CoreGraphBuilder):
    """Core graph builder defaulted to the Carefold pack orchestration spec."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        from carefold.engine.refusal_node import CarefoldRefusalNode
        from carefold.safety.policy import CarefoldHealthSafetyPolicy

        kwargs.setdefault("orchestration_audit_sink", soft_orchestration_audit)
        if kwargs.get("registry") is None:
            # The service always injects a workspace AgentRegistry
            # (core ``AgentExecutionService._agent_registry``, inherited by
            # ``CarefoldAgentExecutionService``); do the same.
            from yarvelle_core.agents.registry import AgentRegistry
            from yarvelle_core.config import settings

            skills_dir = settings.get_skills_dir()
            kwargs["registry"] = AgentRegistry(
                agents_dir=settings.get_agents_dir(),
                skills_dir=skills_dir if skills_dir.is_dir() else None,
            )
        if kwargs.get("safety_policy") is None:
            kwargs["safety_policy"] = CarefoldHealthSafetyPolicy()
        if "orchestration" not in kwargs:
            kwargs["orchestration"] = pack_orchestration()
        orch = kwargs["orchestration"]
        if "default_agent" not in kwargs and orch is not None:
            kwargs["default_agent"] = getattr(orch, "default_agent", None)
        super().__init__(*args, **kwargs)
        if "refusal" not in self._custom_nodes:
            self.with_node("refusal", CarefoldRefusalNode())

    def build(self, *args: Any, **kwargs: Any) -> Any:
        """Attach Carefold's synthesizer exactly as ``_build_orchestrated_graph`` does."""
        from carefold.engine.response_synthesizer import CarefoldResponseSynthesizerNode

        if "response_synthesizer" not in self._custom_nodes:
            self.with_node(
                "response_synthesizer",
                CarefoldResponseSynthesizerNode(
                    model=self.model,
                    agent_titles=self._agent_titles(),
                ),
            )
        return super().build(*args, **kwargs)


__all__ = [
    "TIER1_DOMAIN_CLASSIFIER_PROMPT",
    "DomainClassification",
    "GraphBuilder",
    "OrchestratorDecision",
    "OrchestratorNode",
    "pack_orchestration",
    "soft_orchestration_audit",
]
