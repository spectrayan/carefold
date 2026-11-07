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

"""Loads, lints and runs the health scenarios on a backend.

Thin glue over ``yarvelle_core.testing.orch_eval``: core loads and lints the
scenarios and drives each conversation; this module supplies the health eval
pack. Callers are responsible for the run gates (see ``cli``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

from evals.orchestration.health_pack import materialize_health_pack

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


class ScenarioLintError(ValueError):
    """Scenarios do not match the health eval pack."""


def load_health_scenarios(paths: Optional[Sequence[Path]] = None) -> List[Tuple[Path, Any]]:
    """Loads scenario files (default: every file under ``scenarios/``)."""
    from yarvelle_core.testing.orch_eval.loader import load_scenario_files

    return list(load_scenario_files([str(p) for p in (paths or [SCENARIOS_DIR])]))


def build_pack(workdir: Path, *, persona_markers: bool = False) -> Any:
    """Materializes and loads the health eval pack under ``workdir``.

    Use ``persona_markers=True`` for the scripted fake backend.
    """
    from yarvelle_core.testing.orch_eval.pack import load_eval_pack

    pack = load_eval_pack(materialize_health_pack(Path(workdir) / "pack", persona_markers=persona_markers))
    return _with_production_safety_policy(pack)


def _with_production_safety_policy(pack: Any) -> Any:
    """The loaded pack, but guarded by Carefold's production safety policy.

    Core's harness policy only raises keyword flags and never refuses, so an
    emergency would reach an agent under eval when it never does for users.
    """
    import dataclasses

    from carefold.safety.policy import CarefoldHealthSafetyPolicy

    base = type(pack)

    @dataclasses.dataclass(frozen=True)
    class CarefoldHealthEvalPack(base):  # type: ignore[valid-type, misc]
        def safety_policy(self) -> Any:
            return CarefoldHealthSafetyPolicy()

    return CarefoldHealthEvalPack(**{f.name: getattr(pack, f.name) for f in dataclasses.fields(pack)})


def lint_health_scenarios(loaded: Sequence[Tuple[Path, Any]], pack: Any) -> List[str]:
    """Problems found checking each scenario against the pack (empty when clean)."""
    from yarvelle_core.testing.orch_eval.lint import lint_against_pack

    problems: List[str] = []
    for path, scenario in loaded:
        if scenario.pack != pack.id:
            problems.append(f"{path.name}: wants pack {scenario.pack!r}, health pack is {pack.id!r}")
            continue
        problems.extend(f"{path.name}: {p}" for p in lint_against_pack(scenario, pack))
    return problems


async def run_health_scenarios(
    loaded: Sequence[Tuple[Path, Any]],
    pack: Any,
    backend_factory: Callable[[], Any],
    scenario_ids: Optional[Sequence[str]] = None,
) -> List[Any]:
    """Runs the scenarios that list the backend; lint problems raise first."""
    from yarvelle_core.testing.orch_eval.driver import run_scenarios

    problems = lint_health_scenarios(loaded, pack)
    if problems:
        raise ScenarioLintError("; ".join(problems))
    wanted = set(scenario_ids or [])
    scenarios = [s for _p, s in loaded if not wanted or s.id in wanted]
    return await run_scenarios(scenarios, pack, backend_factory)


__all__ = [
    "SCENARIOS_DIR",
    "ScenarioLintError",
    "build_pack",
    "lint_health_scenarios",
    "load_health_scenarios",
    "run_health_scenarios",
]
