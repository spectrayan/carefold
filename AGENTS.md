# Carefold Autonomous Agent Manifest

<!--
  Carefold — Healthcare AI Agent Marketplace & Runtime
  Copyright 2026 Spectrayan (https://spectrayan.com)

  Licensed under the PolyForm Noncommercial License 1.0.0 and the
  Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
  Personal and household local use only. Commercial use, hosted service
  offering, rebranding, white-labeling, and redistribution of modified
  forks are prohibited without a written commercial license from Spectrayan.

  Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
-->

Specification compliance: [AGENTS.md v1.0.0](https://github.com/agent-infra/agents.md)  
Runtime version: Carefold 0.5.0-beta.2
Last updated: 2026-11-27  

---

## 1. Project Boundaries & Operational Constraints

Carefold is a source-available, local-first personal and family health AI companion and specialist agent pack running on `yarvelle-core` for privacy-preserving clinical visit preparation, health insurance navigation, and chronic care support.

### 1.1 Non-Clinical Boundary (Strict Safety Mandate)
- **Informational and Administrative Navigation Only**: Carefold agents provide educational context, visit preparation checklists, formulary navigation, and benefits explanation. Agents **never** provide formal medical diagnoses, drug dosage adjustments, clinical treatment decisions, or acute triage replacement.
- **Emergency Escalation (Red Flags)**: When an acute life-threatening emergency is detected (e.g., crushing chest pain, symptoms of acute stroke, active suicidal ideation, anaphylaxis, severe respiratory distress), all agents must immediately halt delegation and trigger an emergency refusal protocol referencing local emergency numbers alongside 911 / 988 or immediate emergency department care.
- **Patient Autonomy & Data Sovereignty**: All reasoning occurs local-first (via local LLMs like Ollama or user-controlled API keys). Patient data stays under the local runtime data directory (`~/.carefold` or `--data-dir` / `CAREFOLD_HOME`); no background telemetry or unauthorized third-party exfiltration is permitted.

### 1.2 Human-in-the-Loop (HITL) Policy
- AI agents act as cognitive aids for patients and healthcare stewards. All generated summaries, appeal letters, and clinical visit prep dossiers must be reviewed and verified by a licensed human healthcare provider or the patient before submission or clinical action.

---

## 2. System Architecture & Topology

Carefold is a domain pack built on **`yarvelle-core`** (Python runtime + `@yarvelle/ui` React primitives). Core execution, routing, 4-tier tool execution gates, audit hash chaining, envelope vault encryption, and `McpDatabaseToolbox` live in `yarvelle-core`; Carefold supplies health models, HL7 FHIR R4 persistence/terminology, clinical safety policies, specialist packs, and the Next.js web workspace (`@spectrayan/carefold-web`):

```
carefold/
├── backend/            # FastAPI + yarvelle_core.runtime health domain pack
│   ├── src/carefold/
│   │   ├── pack.yaml   # Carefold PackSpec manifest & safety.guards configuration
│   │   ├── api/ & routers/ # Health REST endpoints mounted via mount_router_contributions
│   │   ├── clinical/   # Vitals, preventive care, school forms, SMART scheduling & governed MCP db ops
│   │   ├── connectors/ # OAuth 2.0 PKCE broker, stateless relay & curated Gmail MCP
│   │   ├── db/         # Health SQLAlchemy 2.0 models & Alembic migrations
│   │   ├── engine/     # Carefold runtime factory wiring yarvelle_core.runtime + safety policy
│   │   ├── fhir/       # HL7 FHIR R4 bundle parser, terminology/UCUM normalizer, dedup & scoped repository
│   │   ├── i18n/       # BCP 47 / RFC 4647 locale catalogs & multilingual safety packs
│   │   ├── importers/  # Apple Health, C-CDA, FHIR R4, CSV & SMART Health Cards
│   │   ├── safety/     # CarefoldHealthSafetyPolicy, clause-scoped red flags & refusal_patterns.yaml
│   │   └── tools/      # Health-domain tools & thin re-exports of yarvelle-core tools
│   └── tests/          # Pytest suite (sharded in CI via CAREFOLD_TEST_SHARD) & 47-attack penetration suite
├── frontend/           # Next.js 16 + Tailwind CSS web app (@spectrayan/carefold-web) consuming @yarvelle/ui
│   ├── src/health-ui/  # @spectrayan/carefold clinical UI module (EHR chart, vitals, visits, preventive, forms)
│   └── src/i18n/       # Client BCP 47 / ICU MessageFormat, Intl formatters & LTR/RTL logical layout
├── tools/
│   ├── cli/            # Carefold CLI (@spectrayan/carefold-cli)
│   └── runner/         # Standalone agent runtime sandbox (@spectrayan/carefold-runner)
├── deploy/docker/      # Multi-arch Dockerfile and Docker Compose stack
├── agents/             # Specialist clinical/navigation/wellness coordinators + _system/ + _template/
├── skills/             # Modular clinical & administrative skill packs + _template/
├── docs/               # MkDocs Material documentation, Living ADRs (0001–0009) & Compliance Packs
└── scripts/            # licenses.mjs, check_no_git_deps.py, validate-packs.mjs, bump-version.mjs, start.sh
```

### 2.1 Specialist & System Packs (`agents/`, `skills/`)
- **Source of truth**: Discover active agents and skills directly from `agents/` and `skills/` and validate with `node scripts/validate-packs.mjs`. Never maintain hardcoded specialist tables or exact counts in `README.md`, `AGENTS.md`, or tests.
- **Pack conventions**:
  - Specialist directories and IDs use coordinator naming (`*-care-coordinator` or `*-coordinator`), never legacy `*-guide` / `*-companion` names.
  - Omit hardcoded `model:` fields in `agent.yaml`.
  - Declare `risk_class` (`admin`, `wellness`, `assist` / `clinical_assist`, `education`) in `metadata.yaml`.
  - Clinical specialists pair their domain skill with `emergency-red-flags` and `clinical-safety-boundaries` and bind only governed tools (`attach-read`, `skill-docs`, `workspace-note`, `vitals_*`, `fhir_*`, etc.).
  - Every reference file linked from `SKILL.md` must exist with matching filename; YAML manifests must end with a trailing newline.

---

## 3. Execution Runtime, Safety & Tool Governance

- **Core Runtime Delegation**: Chat execution runs through `yarvelle_core.runtime` (`CarefoldAgentExecutionService` / `create_execution_service` in `backend/src/carefold/engine/runtime.py`), wrapping `CarefoldHealthSafetyPolicy` via `build_guarded_policy(..., pack=pack)` with `release: buffered` safety guards configured in `pack.yaml`.
- **1:1 API-to-MCP Parity & Governed DB Access**: All agent database reads and mutations MUST route through governed `McpDatabaseToolbox` / FHIR MCP tools sharing the same schemas, error taxonomy (`CFD-XXX-YYY` / RFC 7807), and profile/scope auth as REST routes — never add raw agent DB write paths.
- **Zero-Mock Production Policy**: No production code in `backend/src/` or `frontend/src/` may employ fake, dummy, or facade mock implementations. All test doubles belong strictly in `backend/tests/` or `frontend/tests/`.

---

## 4. Rules of Engagement for AI Coding Agents

### 4.1 Core Boundary, Dependencies & Git Workflow
- **Minimal change principle**: Modify only files directly relevant to the assigned task; avoid unsolicited refactoring.
- **No `yarvelle-core` shadowing**: Import core runtime, routers, tools, and UI primitives from `yarvelle-core` / `@yarvelle/ui`. Never copy core modules into `backend/src/carefold/` or create parallel source trees (guarded by `test_no_core_shadow_drift.py`). All Carefold packages use the `@spectrayan/carefold*` scope.
- **No local paths or git-SHA deps in commits**: Test against unreleased local `yarvelle-core` via `just link core` (temporary editable install), keep imports backward-compatible with published PyPI/npm until core releases, and run `just unlink` + `python3 scripts/check_no_git_deps.py` before committing. Avoid unintended `backend/uv.lock` or `pnpm-lock.yaml` churn.
- **No stacked PRs**: Cut every issue branch directly off freshly fetched `origin/main`. Never commit directly to `main`, never force-push or amend pushed commits, and never merge PRs without explicit approval.
- **License header integrity**: Every `.py`, `.ts`, `.tsx`, `.js`, `.mjs`, and `.css` file must contain the Spectrayan PolyForm Noncommercial + Carefold Additional Terms header (`pnpm run check:licenses`).

### 4.2 Safety, Privacy & Frontend Invariants
- **Safety & security invariants**: Never weaken clinical safety guardrails, clause-scoped emergency red-flag patterns, PII filters, or path-traversal containment.
- **Zero real personal names / PII in repo**: Never commit real developer/user names, emails, or real personal health data in code, tests, fixtures, docs, or screenshots — always use synthetic personas (e.g., `John Doe`, `Alex Rivera`, `@example.test`).
- **Auth fail-closed**: When the backend is unreachable (`503` / network failure), redirect cleanly to `/login?error=service_unavailable`; never fall through to an authenticated dashboard or fallback `"Me"` profile.
- **Next.js 16 SSR hydration safety**: Never render browser-only state (`localStorage`, client locale, dynamic profile labels, `Date.now()`) differently on SSR vs initial client mount; gate client-derived labels behind mounted state or server snapshots.
- **Calm, jargon-free user copy**: Never expose internal crypto/implementation details (e.g., `Argon2id`) in UI copy; keep public copy neutral (no antagonistic framing against healthcare institutions) and use clinically accurate labels (e.g., "lab-reported reference ranges").
- **Local LLM tool compatibility**: Flatten single-branch nullable `anyOf`/`oneOf` JSON Schema parameters for LLM tool binding, and verify mutating MCP tools on both native tool-calling models (e.g., `qwen3:8b`, `llama3.1:8b`) and JSON-fallback models (e.g., `medgemma:27b`).

### 4.3 Test Hygiene, Isolation & Speed
- **No exact-count assertions**: Never assert exact counts of agents, skills, or tools (`len(...) == N`); assert membership (`>= 1`, `"id" in ids`) and behavior so new packs do not break unrelated tests.
- **Descriptive test names only**: Never name test files, classes, or functions after internal sprint milestones or teamwork roles (`m1`, `m2`, `batch1`, `c1`, `challenger`, `adversarial`).
- **Deterministic clocks**: Inject explicit `referenceDate` / clock parameters in time-window tests; never compare hardcoded fixture dates against wall-clock `new Date()` / `datetime.now()`.
- **Fast, offline backend tests**: Mock model factories in **both** `carefold` and `yarvelle_core` so unit tests never hit live Ollama. Gate live Ollama smoke tests behind `CAREFOLD_RUN_OLLAMA_TESTS=1`. Never duplicate golden eval or penetration suites across test files.
- **Runtime & data-dir isolation**: All persistent runtime state must stay strictly under `~/.carefold` (or `--data-dir` / `CAREFOLD_HOME`). Tests and automated runs must **never** touch `~/.carefold`, the real OS keychain, or running `ollama serve` processes — use a temp `CAREFOLD_HOME`, null keyring / temp KEK, and include `"tmp"` in any custom pytest `--basetemp` path (required by `test_home_isolation_security.py`).

### 4.4 Verification Matrix
Run before completing changes:
```bash
pnpm run check:licenses
python3 scripts/check_no_git_deps.py
node scripts/validate-packs.mjs
backend/.venv/bin/pytest backend/tests/                # CI shards via CAREFOLD_TEST_SHARD=1/3..3/3
PYTHONPATH=backend/src backend/.venv/bin/python backend/tests/penetration_suite.py
pnpm --filter @spectrayan/carefold-web typecheck
pnpm --filter @spectrayan/carefold-web test --exclude "**/api/**"
pnpm --filter @spectrayan/carefold-web build
```

### 4.5 Repository Content Policy (Product & Test Code Only)
- Commit only production code, tests/fixtures, agent/skill packs, user/contributor docs (`PROJECT_CONTEXT.md`, `docs/adr/`), and required build/CI/release tooling.
- Never commit one-off operational scripts, AI session/planning artifacts (plans, walkthroughs, scratch notes, audit reports, `.agents/`), local runtime data (`chats/`, `logs/`, `workspace/`, `attachments/`, `*.db`), or personal configuration.

---

## 5. Local Development Notes

- **Endpoints**: Backend runs on `http://127.0.0.1:8010` (`/api/health`, `/api/v1/agents`); Web UI runs on `http://localhost:3010` (`allowedDevOrigins: ['127.0.0.1']` is enabled in `frontend/next.config.ts`). Without Ollama, `/api/health` reports `degraded` (`modelReachable: false`).
- **First launch**: Register the local administrator account on `/login` before using household or agent routes.
- **`pnpm start` (`scripts/start.sh`)**: Defaults `CAREFOLD_CHECKPOINT_ENCRYPTION=false` for local dev and prepends `../yarvelle-core/backend/src` to `PYTHONPATH` when present — keep sibling `../yarvelle-core` synced to `origin/main` to prevent `ModuleNotFoundError`. If `"Missing local runtime token."` appears, check for a stale backend from another worktree holding port `8010`.
- **Pytest side effect**: `backend/tests/test_start_script.py` runs `scripts/start.sh stop` (stopping listeners on ports `8010` and `3010`); restart dev servers afterward if needed.
