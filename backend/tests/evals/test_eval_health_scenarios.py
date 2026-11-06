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

"""Health scenarios lint against the eval pack and pass on the scripted fake model.

These runs use core's scripted fake backend only: deterministic, free and
offline. Live model runs are local-only and never happen in pytest.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fixtures.checkpoint_crypto import use_test_checkpoint_keyring  # noqa: E402

from evals.orchestration.runner import (  # noqa: E402
    build_pack,
    lint_health_scenarios,
    load_health_scenarios,
    run_health_scenarios,
)

EXPECTED_SCENARIOS = {
    "bp-meds-cost-followup",
    "partial-failure-honesty",
    "pinned-agent-then-document",
    "red-flag-escalation-then-routine",
}


def test_health_scenarios_are_multi_turn_and_lint_clean(tmp_path: Path) -> None:
    loaded = load_health_scenarios()
    assert {s.id for _p, s in loaded} == EXPECTED_SCENARIOS
    assert all(len(s.turns) >= 2 for _p, s in loaded)
    assert all(set(s.backends) <= {"fake", "ollama"} for _p, s in loaded)
    assert lint_health_scenarios(loaded, build_pack(tmp_path)) == []


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any outbound socket (e.g. a real local Ollama call) fails the test."""
    import socket

    def _refuse(self, address):  # noqa: ANN001
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"fake eval run tried to open a network connection to {address!r}")
        return _real_connect(self, address)

    _real_connect = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)


@pytest.mark.asyncio
async def test_every_health_scenario_passes_on_the_fake_backend(tmp_path: Path, no_network: None) -> None:
    from yarvelle_core.testing.orch_eval.fake import FakeBackend

    loaded = load_health_scenarios()
    results = await run_health_scenarios(loaded, build_pack(tmp_path, persona_markers=True), FakeBackend)

    assert {r.scenario_id for r in results} == EXPECTED_SCENARIOS
    failures = {r.scenario_id: r.failures() for r in results if not r.passed}
    assert failures == {}
    # Judged turns are reported, not silently dropped (scored by the Carefold judge).
    judged = [c for r in results for t in r.turns for c in t.checks if c.name.startswith("judge:")]
    assert judged


@pytest.mark.asyncio
async def test_fake_runs_use_encrypted_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: None
) -> None:
    """Scenario threads resume through encrypted checkpoints (throwaway test key)."""
    from yarvelle_core.vault.checkpoints import checkpoint_encryption_enabled

    use_test_checkpoint_keyring(monkeypatch)
    assert checkpoint_encryption_enabled()
    from yarvelle_core.testing.orch_eval.fake import FakeBackend

    loaded = [(p, s) for p, s in load_health_scenarios() if s.id == "bp-meds-cost-followup"]
    (result,) = await run_health_scenarios(loaded, build_pack(tmp_path, persona_markers=True), FakeBackend)
    assert result.passed, result.failures()
    assert len(result.turns) == 2
