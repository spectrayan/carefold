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

"""The Carefold health eval pack mirrors the production pack and loads cleanly."""

from __future__ import annotations

from pathlib import Path
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.orchestration.health_pack import (  # noqa: E402
    EVAL_AGENT_IDS,
    HEALTH_EVAL_PACK_ID,
    PRODUCTION_PACK_FILE,
    materialize_health_pack,
)


def test_materialized_pack_loads_through_core_eval_pack_loader(tmp_path: Path) -> None:
    from yarvelle_core.testing.orch_eval.pack import load_eval_pack

    root = materialize_health_pack(tmp_path / "pack")
    pack = load_eval_pack(root)

    assert pack.id == HEALTH_EVAL_PACK_ID
    assert set(pack.agent_ids) == set(EVAL_AGENT_IDS)
    assert pack.hidden_ids == ["triage-auditor"]
    assert pack.route_ids == ["document-intake"]


def test_eval_runs_use_carefolds_production_safety_policy(tmp_path: Path) -> None:
    from carefold.safety.policy import CarefoldHealthSafetyPolicy
    from evals.orchestration.runner import build_pack

    pack = build_pack(tmp_path)
    assert isinstance(pack.safety_policy(), CarefoldHealthSafetyPolicy)
    assert pack.route_ids == ["document-intake"]


def test_eval_pack_orchestration_matches_production_pack(tmp_path: Path) -> None:
    """No drift: the eval pack routes exactly like the shipped health pack."""
    root = materialize_health_pack(tmp_path / "pack")
    eval_spec = yaml.safe_load((root / "pack.yaml").read_text(encoding="utf-8"))["orchestration"]
    production = yaml.safe_load(PRODUCTION_PACK_FILE.read_text(encoding="utf-8"))["orchestration"]
    assert eval_spec == production


def test_eval_agents_are_the_real_agents_with_two_eval_adaptations(tmp_path: Path) -> None:
    """Agent manifests are copied as shipped except: no pinned model (the eval
    backend supplies every model, so a fake run never calls a real one), and
    fixed-route targets are visible so scenarios can script and expect them."""
    root = materialize_health_pack(tmp_path / "pack")
    route_targets = {"document-extractor"}
    for agent_id in EVAL_AGENT_IDS:
        copied = yaml.safe_load((root / "agents" / agent_id / "agent.yaml").read_text(encoding="utf-8"))
        originals = [REPO_ROOT / "agents" / agent_id, REPO_ROOT / "agents" / "_system" / agent_id]
        source = next(p for p in originals if (p / "agent.yaml").is_file())
        original = yaml.safe_load((source / "agent.yaml").read_text(encoding="utf-8"))
        assert "model" not in copied, agent_id
        expected = {k: v for k, v in original.items() if k != "model"}
        if agent_id in route_targets:
            assert original.get("hidden") is True
            expected["hidden"] = False
        assert copied == expected, agent_id
        assert (root / "agents" / agent_id / "persona.md").read_text(encoding="utf-8") == (
            source / "persona.md"
        ).read_text(encoding="utf-8")


def test_fake_marker_mode_only_prepends_the_persona_marker(tmp_path: Path) -> None:
    """The scripted fake model finds an agent by "You are the <id> agent."; live
    runs keep the shipped persona text untouched."""
    root = materialize_health_pack(tmp_path / "pack", persona_markers=True)
    for agent_id in EVAL_AGENT_IDS:
        originals = [REPO_ROOT / "agents" / agent_id, REPO_ROOT / "agents" / "_system" / agent_id]
        source = next(p for p in originals if (p / "agent.yaml").is_file())
        persona = (root / "agents" / agent_id / "persona.md").read_text(encoding="utf-8")
        marker = f"You are the {agent_id} agent.\n\n"
        assert persona == marker + (source / "persona.md").read_text(encoding="utf-8")
