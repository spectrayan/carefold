<!--
Carefold — Healthcare AI Agent Marketplace & Runtime
Copyright 2026 Spectrayan (https://spectrayan.com)
Licensed under the PolyForm Noncommercial License 1.0.0 and the Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
-->

# Carefold health evals (multi-turn orchestration)

Local-only evals that run Carefold's health agents through multi-turn
conversations on yarvelle-core's eval driver
(`yarvelle_core.testing.orch_eval`), and check routing, delegation, task
states, notices, answer content and encrypted checkpoint resume.

Nothing here runs a hosted or paid model, and nothing here runs in GitHub CI
except the offline fake-model tests.

## What is in here

| Path | What |
| --- | --- |
| `health_pack.py` | Builds the eval pack from the shipped pack (`backend/src/carefold/pack.yaml`, `agents/`, `skills/`). |
| `scenarios/*.yaml` | Four two-turn health scenarios (scripted fake replies included). `partial-failure-honesty` is fake-only: its helper failure is scripted and a live model cannot be made to fail on cue. |
| `runner.py` | Loads, lints and runs scenarios through the core driver. |
| `judge.py`, `rubrics/` | Separate-model LLM judge (Spector style) and four health rubrics. |
| `ollama_backend.py` | Free local Ollama backend (loopback URLs only). |
| `cli.py`, `__main__.py` | `python -m evals.orchestration`. |

### Eval adaptations to the shipped pack

The pack is copied from the shipped one; `backend/tests/evals/test_eval_health_pack.py`
fails if it drifts. Three documented changes:

1. **No pinned agent model.** Agent manifests pin `model: ollama:llama3.2`;
   the copies drop it so the eval backend supplies every model. Without this a
   "fake" run quietly calls the real local llama3.2 for every sub-agent.
2. **Fixed-route targets are visible.** The red-flag and document routes go to
   `triage-auditor` and `document-extractor`, which are `hidden: true`. Core's
   eval checks treat hidden agents as "never answer", so the copies are
   visible; main-agent turns forbid them so a live run catches stray delegation.
3. **Persona markers (fake runs only).** The scripted fake model finds an agent
   by "You are the <id> agent."; live runs keep the shipped personas.

## Running

Fake model (deterministic, offline). These also run in normal `pytest`:

```bash
cd backend && .venv/bin/pytest tests/evals -q
```

The CLI refuses CI (exit 3) and needs an explicit opt-in (exit 4):

```bash
# from the repo root
YARVELLE_EVAL=1 backend/.venv/bin/python -m evals.orchestration --backend fake
```

Free local Ollama (subject `glm-4.7-flash`, judge `llama3.1:8b`; pull the
models yourself, the CLI never does):

```bash
YARVELLE_EVAL=1 backend/.venv/bin/python -m evals.orchestration --backend ollama \
  --subject glm-4.7-flash --judge llama3.1:8b --judge-samples 3
```

Optional pytest smoke for the live pass (skipped unless enabled, never in CI):

```bash
cd backend && CAREFOLD_RUN_OLLAMA_TESTS=1 .venv/bin/pytest tests/evals/test_eval_cli.py -m ollama
```

Reports go to `~/.yarvelle-evals/carefold-health/<timestamp>/` (`report.json`,
`summary.md`) or `--out DIR`.

### Isolation

The CLI runs the suite in a child process with `PYTHON_KEYRING_BACKEND` set to
the null keyring, a throwaway `CAREFOLD_HOME`/`YARVELLE_HOME`, a throwaway
vault key file, no vault passphrase, and checkpoint encryption on. It never
reads or writes `~/.carefold` or the OS keychain.

### Judge

The judge is a different model from the subject (same model is refused). It
returns JSON (`score` 1-5, `verdict`, `reasons`, `evidence_quotes`), retries
unparseable replies, falls back to a conservative fail, and aggregates samples
by median score and majority verdict (a spread of 2+ is `unsure`).

Judging is **soft** by default: scores are reported on the `judge:` checks
(status `skip`) and in the report, but never fail a run. `--judge-gate` turns
verdicts into pass/fail and is only allowed with `--judge-agreement >= 0.8`
measured on labelled turns (no calibration set ships yet).

Exit codes: 0 pass, 1 a scenario failed, 2 setup problem (Ollama or a model
missing, bad args), 3 refused in CI, 4 not opted in.
