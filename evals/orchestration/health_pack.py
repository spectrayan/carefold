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

"""Builds the health eval pack from the shipped health pack.

The eval pack is written to a scratch directory at run time: ``pack.yaml``
carries the production ``orchestration`` section unchanged, and ``agents/``
holds copies of the real agents the scenarios use. Routing under eval is
therefore the routing users get. Only the guardrail flags are eval-specific:
the harness raises ``red_flag`` from a short list of words, standing in for
the production safety policy. Skills the copied agents declare are copied to
``skills/`` (without their own eval folders) so the agents load unchanged.

Two eval adaptations are applied to the copied manifests:

* any per-agent ``model`` override is dropped, so the eval backend supplies
  every model (otherwise a "fake" run would call that real local model);
* fixed-route targets are made visible. The production pack routes red flags
  and documents to hidden system agents, which core's eval checks treat as
  "hidden agents never answer"; making them visible lets scenarios script and
  expect them. Normal turns forbid them so live runs catch stray delegation.
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Iterable, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_PACK_FILE = REPO_ROOT / "backend" / "src" / "carefold" / "pack.yaml"
AGENTS_ROOT = REPO_ROOT / "agents"
SYSTEM_AGENTS_ROOT = AGENTS_ROOT / "_system"
SKILLS_ROOT = REPO_ROOT / "skills"

HEALTH_EVAL_PACK_ID = "carefold-health"

EVAL_AGENT_IDS: tuple[str, ...] = (
    "appointment-prep-coordinator",
    "benefits-coordinator",
    "document-extractor",
    "heart-care-coordinator",
    "prescription-cost-coordinator",
    "records-coordinator",
    "triage-auditor",
)
"""Agents the health scenarios use, plus every agent the pack routes name."""

RED_FLAG_WORDS: tuple[str, ...] = (
    "chest pain",
    "can't breathe",
    "cannot breathe",
    "trouble breathing",
    "stroke",
    "unconscious",
    "overdose",
    "suicidal",
)

_AGENT_FILES = ("persona.md", "metadata.yaml")


def _agent_source(agent_id: str) -> Path:
    for root in (AGENTS_ROOT, SYSTEM_AGENTS_ROOT):
        candidate = root / agent_id
        if (candidate / "agent.yaml").is_file():
            return candidate
    raise FileNotFoundError(f"agent {agent_id!r} not found under {AGENTS_ROOT}")


def fixed_route_targets(orchestration: dict) -> set[str]:
    """Agent ids the pack's fixed routes send turns to."""
    return {str(r["agent_id"]) for r in orchestration.get("fixed_routes") or [] if r.get("agent_id")}


def _eval_manifest(agent_id: str, manifest: dict, route_targets: set[str]) -> dict:
    out = {k: v for k, v in manifest.items() if k != "model"}
    if agent_id in route_targets and out.get("hidden"):
        out["hidden"] = False
    return out


def materialize_health_pack(
    dest: Path, agent_ids: Optional[Iterable[str]] = None, *, persona_markers: bool = False
) -> Path:
    """Writes the health eval pack into ``dest`` and returns its directory.

    ``persona_markers`` prepends "You are the <id> agent." to each persona so
    the scripted fake model can tell the agents apart; live runs leave it off.
    """
    ids = tuple(agent_ids) if agent_ids is not None else EVAL_AGENT_IDS
    production = yaml.safe_load(PRODUCTION_PACK_FILE.read_text(encoding="utf-8"))
    pack = {
        "schema": 1,
        "id": HEALTH_EVAL_PACK_ID,
        "title": "Carefold health pack (eval)",
        "orchestration": production["orchestration"],
        "guardrail_flags": {"red_flag": list(RED_FLAG_WORDS)},
    }
    dest = Path(dest)
    agents_dir = dest / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (dest / "pack.yaml").write_text(yaml.safe_dump(pack, sort_keys=False), encoding="utf-8")
    route_targets = fixed_route_targets(production["orchestration"])
    skills: set[str] = set()
    for agent_id in ids:
        source = _agent_source(agent_id)
        target = agents_dir / agent_id
        target.mkdir(exist_ok=True)
        for name in _AGENT_FILES:
            if (source / name).is_file():
                shutil.copyfile(source / name, target / name)
        if persona_markers:
            persona = target / "persona.md"
            persona.write_text(
                f"You are the {agent_id} agent.\n\n" + persona.read_text(encoding="utf-8"), encoding="utf-8"
            )
        manifest = yaml.safe_load((source / "agent.yaml").read_text(encoding="utf-8")) or {}
        skills.update(str(s) for s in manifest.get("skills") or [])
        (target / "agent.yaml").write_text(
            yaml.safe_dump(_eval_manifest(agent_id, manifest, route_targets), sort_keys=False),
            encoding="utf-8",
        )
    for skill_id in sorted(skills):
        source = SKILLS_ROOT / skill_id
        if not source.is_dir():
            raise FileNotFoundError(f"skill {skill_id!r} not found under {SKILLS_ROOT}")
        shutil.copytree(source, dest / "skills" / skill_id, ignore=shutil.ignore_patterns("evals"), dirs_exist_ok=True)
    return dest


__all__ = [
    "EVAL_AGENT_IDS",
    "HEALTH_EVAL_PACK_ID",
    "PRODUCTION_PACK_FILE",
    "RED_FLAG_WORDS",
    "fixed_route_targets",
    "materialize_health_pack",
]
