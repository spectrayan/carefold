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

"""Pack orchestration config validates and references existing agents."""

from __future__ import annotations

from pathlib import Path

import yaml
from packaging.version import Version
from yarvelle_core import __version__ as core_version
from yarvelle_core.pack.spec import PackManifest
from yarvelle_core.pack.validator import validate_pack_spec
from yarvelle_core.schemas.orchestration import GuardrailFlagTrigger, HasAttachmentsTrigger

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_YAML = REPO_ROOT / "backend" / "src" / "carefold" / "pack.yaml"
SYNTHESIS_MD = (
    REPO_ROOT
    / "backend"
    / "src"
    / "carefold"
    / "resources"
    / "prompts"
    / "orchestrator"
    / "synthesis.md"
)
AGENTS_ROOT = REPO_ROOT / "agents"


def _agent_dirs() -> set[str]:
    found: set[str] = set()
    if not AGENTS_ROOT.is_dir():
        return found
    for path in AGENTS_ROOT.rglob("agent.yaml"):
        found.add(path.parent.name)
    return found


def test_pack_yaml_orchestration_validates_as_manifest() -> None:
    data = yaml.safe_load(PACK_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    manifest = PackManifest.model_validate(data)
    assert manifest.requires_core == ">=0.2.2,<0.3.0"
    assert manifest.orchestration is not None
    orch = manifest.orchestration
    assert orch.default_agent == "appointment-prep-coordinator"
    assert orch.limits.max_agents == 4
    assert {r.route_id for r in orch.fixed_routes} == {"document-intake"}
    doc = next(r for r in orch.fixed_routes if r.route_id == "document-intake")
    assert isinstance(doc.when, HasAttachmentsTrigger)
    assert doc.agent_id == "document-extractor"
    # Red flags have no fixed route: the input guardrail answers them with the
    # vetted referral before routing, and triage-auditor output is internal.
    assert not [r for r in orch.fixed_routes if isinstance(r.when, GuardrailFlagTrigger)]
    assert orch.synthesis.instructions.strip() == SYNTHESIS_MD.read_text(encoding="utf-8").strip()


def test_get_pack_orchestration_and_core_compat() -> None:
    import carefold

    pack = carefold.get_pack()
    assert pack.requires_core == ">=0.2.2,<0.3.0"
    assert pack.routing_hints is not None
    assert pack.routing_hints.patterns_resource == "resources/routing_patterns.yaml"
    assert getattr(pack.routing_hints, "patterns_path", None) is None
    assert pack.orchestration is not None
    validate_pack_spec(pack, core_version=core_version)
    assert Version(core_version) >= Version("0.2.2")


def test_orchestration_referenced_agents_exist_on_disk() -> None:
    import carefold

    pack = carefold.get_pack()
    assert pack.orchestration is not None
    agent_dirs = _agent_dirs()
    missing = [aid for aid in pack.orchestration.referenced_agent_ids() if aid not in agent_dirs]
    assert not missing, f"orchestration references missing agents: {missing}"


def test_synthesis_prompt_file_exists_and_is_bounded() -> None:
    text = SYNTHESIS_MD.read_text(encoding="utf-8").strip()
    assert text
    assert len(text) <= 4000
