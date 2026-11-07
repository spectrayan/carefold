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

"""Which agents a pack fixed route may hand a turn to.

``hidden: true`` means internal: the agent is not listed in the catalog, a
user can never pick it, and the main agent can never delegate to it. Only a
fixed route declared in the pack can send it a turn. So a fixed route targets
either a visible agent, or an internal agent this file names on purpose,
which must stay locked down (no delegation, admin risk class, not pickable).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_YAML = REPO_ROOT / "backend" / "src" / "carefold" / "pack.yaml"

# Internal agents a fixed route may target, each with the reason.
INTERNAL_ROUTE_TARGETS: dict[str, str] = {
    "document-extractor": (
        "uploads go through the extraction sandbox (attach-read, sanitize_pii, "
        "extract_structured_data, validate_grounding); user-facing agents keep "
        "the Phase 0 tool set"
    ),
}

# Routes that still target an internal agent this file does not approve.
# The audit-leak PR removes red-flag-escalation; drop this entry when it merges.
PENDING_REMOVAL: dict[str, str] = {
    "red-flag-escalation": "triage-auditor output is internal audit text",
}


def _registry():
    from carefold.agents.registry import AgentRegistry

    return AgentRegistry(REPO_ROOT / "agents", REPO_ROOT / "skills")


def _routes_from_pack_yaml() -> list[tuple[str, str]]:
    data = yaml.safe_load(PACK_YAML.read_text(encoding="utf-8"))
    return [(r["route_id"], r["agent_id"]) for r in data["orchestration"]["fixed_routes"]]


def _routes_from_pack_spec() -> list[tuple[str, str]]:
    import carefold

    orch = carefold.get_pack().orchestration
    assert orch is not None
    return [(r.route_id, r.agent_id) for r in orch.fixed_routes]


@pytest.mark.parametrize("source", [_routes_from_pack_yaml, _routes_from_pack_spec], ids=["pack.yaml", "get_pack"])
def test_fixed_routes_target_visible_or_approved_internal_agents(source) -> None:
    registry = _registry()
    bad = {}
    for route_id, agent_id in source():
        manifest = registry.get(agent_id)
        assert manifest is not None, f"route {route_id} targets unknown agent {agent_id}"
        if not manifest.hidden or agent_id in INTERNAL_ROUTE_TARGETS or route_id in PENDING_REMOVAL:
            continue
        bad[route_id] = agent_id
    assert bad == {}, f"fixed routes target unapproved internal agents: {bad}"


@pytest.mark.parametrize("agent_id", sorted(INTERNAL_ROUTE_TARGETS))
def test_approved_internal_targets_stay_locked_down(agent_id: str) -> None:
    from yarvelle_core.engine.orchestration.runtime import pick_rejection

    registry = _registry()
    manifest = registry.get(agent_id)
    assert manifest is not None
    assert manifest.hidden is True
    assert manifest.can_delegate is False
    assert str(getattr(manifest.risk_class, "value", manifest.risk_class)) == "admin"
    # A user can never pick it; only the pack route reaches it.
    assert pick_rejection(registry, agent_id) == "hidden"


def test_the_main_agent_is_never_offered_an_internal_agent() -> None:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from yarvelle_core.engine.orchestration.runtime import _subagent_specs

    registry = _registry()
    offered = {s["name"] for s in _subagent_specs(registry, FakeListChatModel(responses=["ok"]), None)}
    internal = {a for a in [*INTERNAL_ROUTE_TARGETS, "triage-auditor"] if registry.get(a) is not None}
    assert offered and not (offered & internal)


def test_approved_internal_targets_are_still_routed_to() -> None:
    """Keeps the approval list honest: every entry is used by a route."""
    targets = {agent for _route, agent in _routes_from_pack_yaml()}
    assert set(INTERNAL_ROUTE_TARGETS) <= targets
