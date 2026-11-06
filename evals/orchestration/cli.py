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

"""Command line for the Carefold health evals: ``python -m evals.orchestration``.

Local-only. The parent process refuses CI (exit 3) and needs the explicit
``YARVELLE_EVAL=1`` opt-in (exit 4) before anything runs. The work then runs
in a child process with an isolated environment: a null OS keyring, a
throwaway home directory and a throwaway vault key file, so a run never reads
or writes the real Carefold home or keychain.

Backends: ``fake`` (scripted, offline, default) and ``ollama`` (free local
models; subject glm-4.7-flash, judge llama3.1:8b). There is no hosted or paid
backend.

Exit codes: 0 every scenario passed, 1 a scenario failed, 2 setup problem
(for example Ollama or a model missing), 3 refused in CI, 4 not opted in.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
CHILD_FLAG = "--isolated-child"
ISOLATION_MARKER = "CAREFOLD_HEALTH_EVAL_ISOLATED"
NULL_KEYRING = "keyring.backends.null.Keyring"
EXIT_OK, EXIT_FAILED, EXIT_SETUP = 0, 1, 2
_ENV_PREFIXES = ("CAREFOLD", "YARVELLE")


def build_parser() -> argparse.ArgumentParser:
    from .ollama_backend import DEFAULT_JUDGE_MODEL, DEFAULT_OLLAMA_BASE_URL, DEFAULT_SEED, DEFAULT_SUBJECT_MODEL

    p = argparse.ArgumentParser(prog="python -m evals.orchestration", description=__doc__.split("\n\n")[0])
    p.add_argument("--backend", choices=("fake", "ollama"), default="fake")
    p.add_argument("--scenario", action="append", default=[], help="scenario id (repeatable; default all)")
    p.add_argument("--subject", default=DEFAULT_SUBJECT_MODEL, help="local Ollama subject model")
    p.add_argument("--judge", default=DEFAULT_JUDGE_MODEL, help="local Ollama judge model (must differ)")
    p.add_argument("--base-url", default=DEFAULT_OLLAMA_BASE_URL, help="loopback Ollama URL only")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--judge-samples", type=int, default=3)
    p.add_argument("--no-judge", action="store_true", help="skip judge scoring on the ollama backend")
    p.add_argument(
        "--judge-gate",
        action="store_true",
        help="let judge verdicts fail the run; needs --judge-agreement of at least 0.8",
    )
    p.add_argument("--judge-agreement", type=float, default=None, help="measured judge/label agreement (0-1)")
    p.add_argument("--out", type=Path, default=None, help="report directory (default ~/.yarvelle-evals/...)")
    p.add_argument(CHILD_FLAG, action="store_true", help=argparse.SUPPRESS)
    return p


def isolated_env(base: Mapping[str, str], workdir: Path) -> Dict[str, str]:
    """Environment for the child run: null keyring, temp home, temp vault key."""
    env = {k: v for k, v in base.items() if not k.endswith("_VAULT_PASSPHRASE")}
    home = workdir / "home"
    home.mkdir(parents=True, exist_ok=True)
    kek = workdir / "vault-kek.hex"
    kek.write_text(secrets.token_hex(32), encoding="utf-8")
    kek.chmod(0o600)
    env["PYTHON_KEYRING_BACKEND"] = NULL_KEYRING
    env["YARVELLE_ENV_PREFIX"] = "CAREFOLD"
    for prefix in _ENV_PREFIXES:
        env[f"{prefix}_HOME"] = str(home)
        env[f"{prefix}_VAULT_KEK_FILE"] = str(kek)
    env["CAREFOLD_CHECKPOINT_ENCRYPTION"] = "true"
    env["YARVELLE_CORE_CHECKPOINT_ENCRYPTION"] = "true"
    env[ISOLATION_MARKER] = str(workdir)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT)] + [p for p in [base.get("PYTHONPATH")] if p])
    return env


def _guard(environ: Mapping[str, str]) -> Optional[int]:
    from yarvelle_core.testing.orch_eval.guard import EvalRefusedError, ensure_not_ci, ensure_opted_in

    try:
        ensure_not_ci(environ)
        ensure_opted_in(environ)
    except EvalRefusedError as err:
        print(str(err), file=sys.stderr)
        return err.exit_code
    return None


def main(argv: Optional[Sequence[str]] = None, environ: Optional[Mapping[str, str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ if environ is None else environ)
    refused = _guard(env)  # CI first, then the opt-in; nothing else runs before this
    if refused is not None:
        return refused
    args = build_parser().parse_args(argv)
    if args.isolated_child:
        return _child_main(args, env)
    if args.judge_gate and not _gate_allowed(args.judge_agreement):
        print("--judge-gate needs --judge-agreement of at least 0.8 (measured on labelled turns)", file=sys.stderr)
        return EXIT_SETUP
    with tempfile.TemporaryDirectory(prefix="carefold-health-eval-") as tmp:
        child_env = isolated_env(env, Path(tmp))
        cmd = [sys.executable, "-m", "evals.orchestration", *argv, CHILD_FLAG]
        return subprocess.call(cmd, env=child_env, cwd=str(REPO_ROOT))


def _gate_allowed(agreement: Optional[float]) -> bool:
    from .judge import can_enable_gate

    return can_enable_gate(agreement)


def _check_isolation(env: Mapping[str, str]) -> Optional[str]:
    workdir = env.get(ISOLATION_MARKER)
    if not workdir:
        return "the isolated child must be started by the CLI parent"
    if env.get("PYTHON_KEYRING_BACKEND") != NULL_KEYRING:
        return "the OS keyring is not the null keyring"
    for prefix in _ENV_PREFIXES:
        home = env.get(f"{prefix}_HOME") or ""
        if not home.startswith(workdir):
            return f"{prefix}_HOME is not the throwaway eval home"
    return None


def _child_main(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    problem = _check_isolation(env)
    if problem:
        print(f"refusing to run: {problem}", file=sys.stderr)
        return EXIT_SETUP
    try:
        report = asyncio.run(_run(args, Path(env[ISOLATION_MARKER])))
    except _SetupError as err:
        print(str(err), file=sys.stderr)
        return EXIT_SETUP
    out = args.out or _default_out()
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out / "summary.md").write_text(render_summary(report), encoding="utf-8")
    print(render_summary(report))
    print(f"report: {out / 'report.json'}")
    return EXIT_OK if report["summary"]["failed"] == 0 else EXIT_FAILED


class _SetupError(RuntimeError):
    pass


def _default_out() -> Path:
    from yarvelle_core.testing.orch_eval.guard import default_output_root

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return default_output_root() / "carefold-health" / stamp


async def _run(args: argparse.Namespace, workdir: Path) -> Dict[str, Any]:
    import carefold  # noqa: F401 - registers Carefold's agent domains on core
    from yarvelle_core.config import settings
    from yarvelle_core.vault.checkpoints import checkpoint_encryption_enabled, reset_checkpoint_keyring_cache

    from . import judge as judge_mod
    from .runner import ScenarioLintError, build_pack, load_health_scenarios, run_health_scenarios

    settings.checkpoint_encryption = True
    reset_checkpoint_keyring_cache()
    loaded = load_health_scenarios()
    known = {s.id for _p, s in loaded}
    unknown = sorted(set(args.scenario) - known)
    if unknown:
        raise _SetupError(f"unknown scenario(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}")
    fake = args.backend == "fake"
    pack = build_pack(workdir / "eval", persona_markers=fake)
    backend_info: Dict[str, Any]
    judge_model = None
    if fake:
        from yarvelle_core.testing.orch_eval.fake import FakeBackend

        factory = FakeBackend
        backend_info = FakeBackend().describe()
    else:
        from .ollama_backend import OllamaBackend, OllamaUnavailableError, require_ollama_models

        try:
            status = require_ollama_models((args.subject, args.judge), base_url=args.base_url)
            probe = OllamaBackend(
                subject_model=args.subject, judge_model=args.judge, base_url=args.base_url, seed=args.seed,
                status=status,
            )
        except (OllamaUnavailableError, ValueError, judge_mod.SameModelJudgeError) as err:
            raise _SetupError(str(err)) from err

        def factory() -> Any:
            return OllamaBackend(
                subject_model=args.subject, judge_model=args.judge, base_url=args.base_url, seed=args.seed,
                status=status,
            )

        backend_info = probe.describe()
        if not args.no_judge:
            judge_model = probe.judge_model_instance()
    try:
        results = await run_health_scenarios(loaded, pack, factory, args.scenario or None)
    except ScenarioLintError as err:
        raise _SetupError(f"scenario lint failed: {err}") from err
    records: List[Any] = []
    if judge_model is not None:
        by_id = {s.id: s for _p, s in loaded}
        records = judge_mod.judge_results(
            results, by_id, judge_model, samples=args.judge_samples, gate=args.judge_gate
        )
    failed = [r.scenario_id for r in results if not r.passed]
    return {
        "suite": "carefold-health",
        "backend": backend_info,
        "checkpoint_encryption": checkpoint_encryption_enabled(),
        "judge": {
            "enabled": judge_model is not None,
            "mode": "gated" if args.judge_gate else "soft",
            "samples": args.judge_samples,
        },
        "summary": {"scenarios": len(results), "passed": len(results) - len(failed), "failed": len(failed)},
        "failed_scenarios": failed,
        "results": [r.to_dict() for r in results],
        "judge_records": [j.to_dict() for j in records],
    }


def render_summary(report: Mapping[str, Any]) -> str:
    b = report["backend"]
    s = report["summary"]
    lines = [
        f"# Carefold health evals ({b.get('backend')})",
        "",
        f"subject: {b.get('subject_model', b.get('model'))}; judge: {b.get('judge_model', '-')}"
        f" (judge {report['judge']['mode']}, enabled={report['judge']['enabled']})",
        f"scenarios: {s['scenarios']}, passed: {s['passed']}, failed: {s['failed']}",
        "",
    ]
    judged = {(j["scenario_id"], j["turn"]): j for j in report.get("judge_records", [])}
    for r in report["results"]:
        status = "PASS" if r.get("passed") else "FAIL"
        lines.append(f"## {r['id']}: {status}")
        for t in r.get("turns", []):
            num = t.get("turn")
            fails = [f"{c['name']}: {c.get('detail', '')}" for c in t.get("checks", []) if c["status"] == "fail"]
            j = judged.get((r["id"], num))
            jtxt = f" judge {j['rubric']} {j['score']}/5 {j['verdict']}" if j else ""
            lines.append(f"- turn {num}: {'ok' if not fails else 'FAIL'}{jtxt}")
            lines.extend(f"  - {f[:300]}" for f in fails)
        if r.get("error"):
            lines.append(f"- error: {r['error']}")
        lines.append("")
    return "\n".join(lines)


__all__ = ["EXIT_FAILED", "EXIT_OK", "EXIT_SETUP", "build_parser", "isolated_env", "main", "render_summary"]
