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

"""The health eval CLI refuses CI, needs the opt-in, and isolates its runs.

Only the scripted fake backend runs here. The live local Ollama pass is a
separate ``ollama``-marked test that is skipped unless explicitly enabled and
never runs in CI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.orchestration import cli  # noqa: E402
from yarvelle_core.testing.orch_eval.guard import CI_ENV_VARS, detect_ci  # noqa: E402

LOCAL = {"PATH": os.environ.get("PATH", ""), "YARVELLE_EVAL": "1"}


def _no_spawn(monkeypatch: pytest.MonkeyPatch) -> list:
    spawned: list = []
    monkeypatch.setattr(cli.subprocess, "call", lambda *a, **k: spawned.append(a) or 0)
    return spawned


@pytest.mark.parametrize("ci_var", ["CI", "GITHUB_ACTIONS", "RUNNER_OS"])
def test_ci_is_refused_before_anything_runs(monkeypatch: pytest.MonkeyPatch, ci_var: str) -> None:
    spawned = _no_spawn(monkeypatch)
    assert cli.main(["--backend", "ollama"], environ={**LOCAL, ci_var: "false"}) == 3
    assert spawned == []


def test_a_run_needs_the_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    spawned = _no_spawn(monkeypatch)
    assert cli.main(["--backend", "fake"], environ={"PATH": "/usr/bin"}) == 4
    assert cli.main(["--backend", "fake"], environ={"PATH": "/usr/bin", "YARVELLE_EVAL": "yes"}) == 4
    assert spawned == []


def test_judge_gate_needs_measured_agreement(monkeypatch: pytest.MonkeyPatch) -> None:
    spawned = _no_spawn(monkeypatch)
    assert cli.main(["--backend", "ollama", "--judge-gate"], environ=LOCAL) == 2
    assert cli.main(["--backend", "ollama", "--judge-gate", "--judge-agreement", "0.7"], environ=LOCAL) == 2
    assert spawned == []


def test_opted_in_local_run_spawns_an_isolated_child(monkeypatch: pytest.MonkeyPatch) -> None:
    spawned = _no_spawn(monkeypatch)
    assert cli.main(["--backend", "fake"], environ=LOCAL) == 0
    ((cmd,),) = spawned
    assert cmd[-1] == cli.CHILD_FLAG and cmd[1:3] == ["-m", "evals.orchestration"]


def test_child_refuses_to_run_without_isolation() -> None:
    env = {**LOCAL, "PYTHON_KEYRING_BACKEND": "keyring.backends.macOS.Keyring"}
    assert cli.main(["--backend", "fake", cli.CHILD_FLAG], environ=env) == 2


def test_isolated_env_uses_null_keyring_temp_home_and_temp_key(tmp_path: Path) -> None:
    base = {
        "PATH": "/usr/bin",
        "CAREFOLD_HOME": str(Path.home() / ".carefold"),
        "CAREFOLD_VAULT_PASSPHRASE": "do-not-pass-this-on",
        "YARVELLE_VAULT_PASSPHRASE": "nor-this",
        "CAREFOLD_CHECKPOINT_ENCRYPTION": "false",
    }
    env = cli.isolated_env(base, tmp_path)
    assert env["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
    assert not any(k.endswith("_VAULT_PASSPHRASE") for k in env)
    for prefix in ("CAREFOLD", "YARVELLE"):
        assert Path(env[f"{prefix}_HOME"]).is_relative_to(tmp_path)
        kek = Path(env[f"{prefix}_VAULT_KEK_FILE"])
        assert kek.is_relative_to(tmp_path)
        assert re.fullmatch(r"[0-9a-f]{64}", kek.read_text(encoding="utf-8"))
        assert kek.stat().st_mode & 0o077 == 0
    assert env["CAREFOLD_CHECKPOINT_ENCRYPTION"] == "true"


@pytest.mark.skipif(bool(detect_ci()), reason="the CLI itself refuses CI; fake scenarios run in-process there")
def test_fake_cli_run_end_to_end(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k not in CI_ENV_VARS}
    env["YARVELLE_EVAL"] = "1"
    out = tmp_path / "report"
    proc = subprocess.run(
        [sys.executable, "-m", "evals.orchestration", "--backend", "fake", "--out", str(out)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["summary"] == {"scenarios": 4, "passed": 4, "failed": 0}
    assert report["checkpoint_encryption"] is True
    assert report["backend"]["backend"] == "fake"
    assert (out / "summary.md").is_file()


WORKFLOWS = REPO_ROOT / ".github" / "workflows"
FORBIDDEN_IN_CI = ("evals.orchestration", "evals/orchestration", "YARVELLE_EVAL", "CAREFOLD_RUN_OLLAMA_TESTS", "ollama")


def test_ci_workflows_never_invoke_the_live_evals() -> None:
    files = sorted(WORKFLOWS.glob("*.y*ml"))
    assert files, "expected GitHub workflow files"
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        for needle in FORBIDDEN_IN_CI:
            assert needle.lower() not in text, f"{path.name} mentions {needle!r}"
        assert not re.search(r"pytest[^\n]*-m\s+['\"]?[^\n]*\bollama\b", text), path.name


@pytest.mark.ollama
@pytest.mark.skipif(bool(detect_ci()), reason="live local evals never run in CI")
def test_live_local_ollama_pass(tmp_path: Path) -> None:
    """Opt-in only (CAREFOLD_RUN_OLLAMA_TESTS): one scenario on local glm-4.7-flash, judged by llama3.1:8b."""
    env = {k: v for k, v in os.environ.items() if k not in CI_ENV_VARS}
    env["YARVELLE_EVAL"] = "1"
    out = tmp_path / "live"
    proc = subprocess.run(
        [sys.executable, "-m", "evals.orchestration", "--backend", "ollama", "--scenario",
         "routine-then-red-flag-referral", "--judge-samples", "1", "--out", str(out)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=1800,
    )
    if proc.returncode == 2:
        pytest.skip(f"local Ollama or models unavailable: {proc.stderr.strip()[-300:]}")
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["backend"]["subject_model"] != report["backend"]["judge_model"]
    assert report["summary"]["scenarios"] == 1
