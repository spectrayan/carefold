# Testing & Quality Gates

Carefold is safety-critical software: it must refuse clinical decisions, escalate emergencies, keep patient data inside the local sandbox, and never ship a mocked code path. The test suite is organized so that each of those guarantees is checked automatically on every pull request.

This page describes how the suites are organized, what each one verifies, and how to run them locally.

---

## Principles

- **Behavior over implementation.** Tests assert on observable contracts: REST and SSE payloads, refusal output, extracted dossier schemas, sandbox decisions, and audit records. They avoid coupling to private helpers so refactors do not break them.
- **Zero mocks in production code.** No production module under `backend/src/` or `apps/web/src/` contains a fake or bypass path. Test doubles live only in test directories: the deterministic `MockChatModel` in `backend/tests/fixtures/fake_model.py`, the fixtures in `backend/tests/conftest.py` and `backend/tests/e2e/conftest.py`, and per-test stubs in the web and package suites.
- **Deterministic by default.** The standard suites run without a model server, network access, or API keys. Tests that need a live LLM are opt-in.
- **Safety regressions are blocking.** Guardrail, red-flag, PII, and sandbox tests run in CI on every pull request, and the penetration suite must pass in full.

---

## Test Tiers

Carefold's end-to-end suites follow four tiers. Each tier answers a different question.

| Tier | Question it answers | What it covers |
|---|---|---|
| **1. Feature coverage** | Does each feature honor its contract? | Happy path, input validation, output schema, error handling, and isolation for every feature. |
| **2. Boundaries & corner cases** | Does it hold at the limits? | Exact size limits (for example 10 MB uploads and 10 MB + 1 byte), retry and reflection ceilings, temperature bounds, ReDoS-resistant patterns on very long inputs, adjacent PII identifiers, `$0` and seven-figure grounding values, path traversal and null-byte inputs, empty and fragmented SSE chunks. |
| **3. Cross-feature interactions** | Do the parts compose correctly? | Guardrail → refusal → audit; provider factory → agent node; ingestion → PII sanitizer → dossier extraction → grounding; tool node → tool validator → traces; error node → SSE stream → audit; checkpointer → multi-turn resume; backend SSE events → web UI parser. |
| **4. Real-world scenarios** | Does a whole patient journey work? | Pre-visit preparation from an uploaded summary, insurance benefits and prior-authorization questions, emergency refusal and redirection, multi-turn journeys that switch specialists, and recovery from malformed attachments. |

---

## Suite Map

| Suite | Location | What it verifies | Runs in CI |
|---|---|---|---|
| Backend unit & regression | `backend/tests/test_*.py` | API routes, LangGraph nodes, guardrails, red-flag patterns, PII sanitizer, grounding validator, catalog and memory adapters, sandboxed tools. Includes adversarial and stress variants. | ✅ |
| Backend end-to-end (Tiers 1–4) | `backend/tests/e2e/` | `test_features.py`, `test_boundaries.py`, `test_interactions.py`, `test_scenarios.py`, plus context and safety gating, multi-agent execution, response synthesis, persona purity, and specialty coverage. | ✅ |
| Penetration suite | `backend/tests/penetration_suite.py` | 47 attacks covering path traversal, symlink escapes, shell injection, undeclared skill-doc access, and PII leakage. All 47 must pass. | ✅ |
| Live Ollama integration | `backend/tests/integration/` | Multi-turn conversations against a real local model. Opt-in (see below). | — |
| Web unit & component | `apps/web/tests/{components,lib,adversarial}/` | Chat streaming, settings, marketplace, accessibility, and adversarial UI inputs. | ✅ |
| Web API integration | `apps/web/tests/api/` | Next.js route handlers against a running FastAPI backend. Excluded from CI because it needs a live backend. | — |
| Runner & CLI packages | `packages/runner/tests/`, `packages/cli/tests/` | Manifest and skill-pack validation, tool permission unions, adversarial manifests, the pack validator, streaming runs. | ✅ (release) |
| Workspace end-to-end (Tiers 1–4) | `tests/e2e/` | CLI scaffolding and commands, manifests, tools, safety refusal, audit logging, SSE, web pages, attachments, offline evals, and container packaging, from the outside in. | — |
| Offline safety evals | `evals/` | Golden prompts in `evals/safety.golden.jsonl` scored for refusal correctness and grounding. | — |

---

## Running the Tests

All commands run from the repository root.

### Pull request gates

These are the checks CI runs on every pull request. Run them before opening one:

```bash
# 1. License headers
pnpm run check:licenses

# 2. Backend unit, regression, and end-to-end suites
backend/.venv/bin/pytest backend/tests/

# 3. Penetration suite (47 attacks)
PYTHONPATH=backend/src backend/.venv/bin/python backend/tests/penetration_suite.py

# 4. Frontend typecheck
pnpm --filter web typecheck

# 5. Frontend unit and component tests
pnpm --filter web test --exclude "**/api/**"

# 6. Frontend production build
pnpm --filter web build
```

### Targeted runs

```bash
# One backend end-to-end tier
backend/.venv/bin/pytest backend/tests/e2e/test_boundaries.py -v

# Runner and CLI packages
pnpm --filter @carefold/runner test
pnpm --filter @carefold/cli test

# Workspace end-to-end suite
pnpm run test:e2e
```

### Opt-in suites

```bash
# Live Ollama multi-turn tests (requires a running Ollama daemon)
CAREFOLD_RUN_OLLAMA_TESTS=1 backend/.venv/bin/pytest backend/tests/integration/ -m ollama

# Optional overrides
CAREFOLD_OLLAMA_URL=http://localhost:11434 CAREFOLD_OLLAMA_MODEL=llama3.2:3b \
  CAREFOLD_RUN_OLLAMA_TESTS=1 backend/.venv/bin/pytest backend/tests/integration/

# Web API integration tests (start the backend first: pnpm dev:backend)
pnpm --filter web exec vitest run tests/api

# Offline safety evals (mock provider by default)
PYTHONPATH=backend/src backend/.venv/bin/python evals/runner.py --verbose
```

---

## Writing Tests

- **Put test doubles in test directories only.** Reuse `MockChatModel` from `backend/tests/fixtures/fake_model.py` for backend model calls. In the web app, stub `fetch` per test with `vi.stubGlobal`.
- **Cover the tier that matches the change.** A new feature needs Tier 1 cases at minimum. A new limit or threshold needs Tier 2 cases at, just below, and just above it. A change that crosses packages needs a Tier 3 interaction test.
- **Never weaken a safety test to make it pass.** Red-flag patterns, refusal output, PII redaction, and sandbox checks are product requirements. Known gaps are tracked as `xfail` with a reason until they are fixed, never deleted.
- **Keep the default run hermetic.** Anything that needs a network, a model server, or API keys must be opt-in through an environment variable or marker, as the Ollama suite is.
