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

"""Sub-agents use the configured main model unless an agent overrides it on purpose.

Shipped agents used to pin ``model: ollama:llama3.2``, so when the main agent
delegated, every sub-agent ran on llama3.2 whatever model the user had chosen.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "agents"

# Agents that deliberately run on their own model. Each entry needs a reason.
INTENTIONAL_MODEL_OVERRIDES: dict[str, str] = {}


def _manifests() -> list[Path]:
    return sorted(p for p in AGENTS_DIR.rglob("agent.yaml") if "_template" not in p.parts)


def test_shipped_agents_do_not_pin_a_model() -> None:
    pinned = {
        p.parent.name: yaml.safe_load(p.read_text(encoding="utf-8")).get("model")
        for p in _manifests()
        if "model" in (yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    }
    assert set(pinned) == set(INTENTIONAL_MODEL_OVERRIDES), pinned


def test_the_agent_template_leaves_the_model_to_the_runtime() -> None:
    template = yaml.safe_load((AGENTS_DIR / "_template" / "agent.yaml").read_text(encoding="utf-8"))
    assert "model" not in template


def test_delegated_subagents_run_on_the_main_model() -> None:
    from yarvelle_core.agents.registry import AgentRegistry
    from yarvelle_core.engine.orchestration.runtime import _subagent_specs

    registry = AgentRegistry(agents_dir=AGENTS_DIR, skills_dir=REPO_ROOT / "skills")
    main = FakeListChatModel(responses=["ok"])
    specs = _subagent_specs(registry, main, None)
    assert specs
    assert {s["name"]: s["model"] for s in specs if s["model"] is not main} == {}


def test_carefold_loader_only_sets_a_model_when_the_agent_declares_one(tmp_path: Path) -> None:
    from carefold.loaders.agent_loader import load_subagent_from_yaml

    plain = tmp_path / "plain-agent"
    plain.mkdir()
    (plain / "agent.yaml").write_text("id: plain-agent\ntitle: Plain\ndescription: d\npersona: hi\n", encoding="utf-8")
    assert "model" not in load_subagent_from_yaml(plain)

    pinned = tmp_path / "pinned-agent"
    pinned.mkdir()
    (pinned / "agent.yaml").write_text(
        "id: pinned-agent\ntitle: Pinned\ndescription: d\npersona: hi\nmodel: ollama:qwen3:8b\n", encoding="utf-8"
    )
    assert load_subagent_from_yaml(pinned)["model"] == "ollama:qwen3:8b"


@pytest.mark.parametrize("value", ["ollama:qwen3:8b", "qwen3:8b"])
def test_an_explicit_agent_model_is_still_honoured(tmp_path: Path, value: str) -> None:
    from yarvelle_core.agents.registry import AgentRegistry
    from yarvelle_core.engine.orchestration.runtime import _subagent_specs

    agent = tmp_path / "agents" / "override-agent"
    agent.mkdir(parents=True)
    (agent / "agent.yaml").write_text(
        f"id: override-agent\ntitle: Override\ndescription: An agent on its own model.\npersona: persona.md\nmodel: {value}\n",
        encoding="utf-8",
    )
    (agent / "persona.md").write_text("You help.\n", encoding="utf-8")
    registry = AgentRegistry(agents_dir=tmp_path / "agents")
    main = FakeListChatModel(responses=["ok"])
    (spec,) = _subagent_specs(registry, main, None)
    assert spec["model"] is not main and "qwen3:8b" in str(spec["model"])
