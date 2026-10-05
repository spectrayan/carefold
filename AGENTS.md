# Carefold Autonomous Agent Manifest

<!--
  Carefold — Healthcare AI Agent Marketplace & Runtime
  Copyright 2026 Spectrayan

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->

Specification compliance: [AGENTS.md v1.0.0](https://github.com/agent-infra/agents.md)  
Runtime version: Carefold 0.4.0-beta.1
Last updated: 2026-10-04  

---

## 1. Project Boundaries & Operational Constraints

Carefold is an open-source, local-first healthcare AI agent marketplace and execution runtime designed for privacy-preserving clinical visit preparation, health insurance navigation, and chronic care support.

### 1.1 Non-Clinical Boundary (Strict Safety Mandate)
- **Informational and Administrative Navigation Only**: Carefold agents provide educational context, visit preparation checklists, formulary navigation, and benefits explanation. Agents **never** provide formal medical diagnoses, drug dosage adjustments, clinical treatment decisions, or acute triage replacement.
- **Emergency Escalation (Red Flags)**: When an acute life-threatening emergency is detected (e.g., crushing chest pain, symptoms of acute stroke, active suicidal ideation, anaphylaxis, severe respiratory distress), all agents must immediately halt delegation and trigger an emergency refusal protocol with local emergency contacts (e.g., call 911 / 988 or seek immediate emergency department care).
- **Patient Autonomy & Data Sovereignty**: All reasoning occurs local-first (via local LLMs like Ollama or user-controlled API keys). Patient data stays in the local runtime workspace and attachment sandbox; no background telemetry or unauthorized third-party exfiltration is permitted.

### 1.2 Human-in-the-Loop (HITL) Policy
- AI agents act as cognitive aids for patients and healthcare stewards. All generated summaries, appeal letters, and clinical visit prep dossiers must be reviewed and verified by a licensed human healthcare provider or the patient before submission or clinical action.

---

## 2. System Architecture & Topology

The Carefold repository is structured as a modular monorepo:

```
carefold/
├── backend/            # FastAPI + LangGraph multi-agent execution runtime
│   ├── src/carefold/
│   │   ├── engine/     # LangGraph workflow builder, runner, and SSE streaming service
│   │   ├── memory/     # Hexagonal ports (MemoryPort, CatalogPort) & SQLite FTS5 adapters
│   │   ├── model/      # Multi-provider LLM abstraction (Ollama, Anthropic, OpenAI, Google)
│   │   ├── tools/      # Sandboxed file, extraction, and delegation tools
│   │   └── workflows/  # LangGraph state machine, nodes, and extraction subgraphs
│   └── tests/          # Pytest suite & 47-attack penetration test harness
├── apps/web/           # Next.js 15 Tailwind CSS agent marketplace and consultation UI
├── packages/
│   ├── cli/            # Carefold CLI for agent authoring and local execution
│   └── runner/         # Standalone agent runtime sandbox
├── agents/             # 22 Specialist clinical/navigational agents + 6 system agents
├── skills/             # 23 Modular clinical skill packs with reference guidelines
├── docs/               # Verified MkDocs Material documentation & Living ADR framework
└── .github/            # GitHub Actions CI/CD matrix, CodeQL, and community templates
```

### 2.1 Specialist Agent Topology (22 Specialists)

Carefold organizes clinical and administrative specialists under clear clinical risk classes (`admin`, `wellness`, `clinical_assist`, `education`):

| Agent Identifier | Domain | Category | Risk Class | Key Skills |
|---|---|---|---|---|
| `cardiology-guide` | `clinical` | `cardiology` | `clinical_assist` | `cardiology-prep`, `emergency-red-flags`, `clinical-safety-boundaries` |
| `pulmonology-guide` | `clinical` | `pulmonology` | `clinical_assist` | `pulmonology-prep`, `emergency-red-flags`, `clinical-safety-boundaries` |
| `derma-guide` | `clinical` | `dermatology` | `clinical_assist` | `derma-prep`, `clinical-safety-boundaries` |
| `gastro-guide` | `clinical` | `gastroenterology` | `clinical_assist` | `gastro-prep`, `clinical-safety-boundaries` |
| `neurology-guide` | `clinical` | `neurology` | `clinical_assist` | `neurology-prep`, `emergency-red-flags`, `clinical-safety-boundaries` |
| `nephrology-guide` | `clinical` | `nephrology` | `clinical_assist` | `nephrology-prep`, `clinical-safety-boundaries` |
| `endocrinology-guide` | `clinical` | `endocrinology` | `clinical_assist` | `endocrinology-prep`, `clinical-safety-boundaries` |
| `rheuma-guide` | `clinical` | `rheumatology` | `clinical_assist` | `rheuma-prep`, `clinical-safety-boundaries` |
| `ortho-guide` | `clinical` | `orthopedics` | `clinical_assist` | `ortho-prep`, `clinical-safety-boundaries` |
| `urology-guide` | `clinical` | `urology` | `clinical_assist` | `urology-prep`, `clinical-safety-boundaries` |
| `ent-guide` | `clinical` | `ent` | `clinical_assist` | `ent-prep`, `clinical-safety-boundaries` |
| `eye-guide` | `clinical` | `ophthalmology` | `clinical_assist` | `vision-prep`, `clinical-safety-boundaries` |
| `oncology-navigator` | `clinical` | `oncology` | `clinical_assist` | `oncology-prep`, `emergency-red-flags`, `clinical-safety-boundaries` |
| `visit-steward` | `clinical` | `general` | `clinical_assist` | `visit-prep`, `emergency-red-flags`, `clinical-safety-boundaries` |
| `benefits-guide` | `navigation` | `insurance` | `admin` | `benefits-explainer`, `records-management` |
| `claims-appeals-guide` | `navigation` | `appeals` | `admin` | `claims-appeals-prep`, `benefits-explainer` |
| `prior-auth-navigator` | `navigation` | `authorizations` | `admin` | `prior-auth-prep`, `records-management` |
| `formulary-guide` | `navigation` | `pharmacy` | `admin` | `formulary-navigation`, `benefits-explainer` |
| `records-coordinator` | `navigation` | `records` | `admin` | `records-management` |
| `habit-companion` | `wellness` | `habits` | `wellness` | `habit-checkin` |
| `_template` | `clinical` | `template` | `education` | Starter template for community agents |

### 2.2 System Agents (`agents/_system`)

System agents manage orchestration, safety enforcement, document intelligence, and dynamic generation:

1. **`orchestrator`**: Two-hop intent classification, dynamic skill provisioning, and agent routing.
2. **`document-extractor`**: Ingestion sandbox, PII sanitization, structured Pydantic dossier extraction, and numerical grounding validation.
3. **`quality-reviewer`**: Clinical safety boundary audit, tone inspection, and persona alignment verification.
4. **`skill-generator`**: Synthesis of dynamic skill manifests and validation templates from clinical guidelines.
5. **`suggestion-generator`**: Context-aware follow-up suggestion chips presented in the client UI.
6. **`triage-auditor`**: Compliance logging, risk tagging, and clinical safety telemetry.

---

## 3. Agent Toolsets & Sandbox Security

Agents interact with the environment exclusively through registered, sandboxed tools defined in `backend/src/carefold/tools/`.

### 3.1 Tool Registry
- **`attach-read`**: Sandboxed reading of patient-uploaded medical records, bills, and PDFs in `attachments/`. Strict protection against path traversal (`../`), null bytes, and symlink escapes.
- **`workspace-note`**: Reading and writing ephemeral notes in `workspace/notes/`.
- **`skill-docs`**: Authorized access to reference clinical guidelines declared on the agent's manifest. Attempting to access undeclared skill documentation is blocked immediately.
- **`delegate_to_agent`**: Inter-agent routing mechanism controlled by the orchestrator.
- **`list_agents`**: Querying the `CatalogPort` for available specialist agents.
- **`sanitize_pii`**: Redacts Social Security Numbers (SSN), Medical Record Numbers (MRN), phone numbers, physical addresses, and patient identifiers.
- **`extract_structured_data`**: Transforms unstructured text into validated Pydantic models (`InsuranceBenefitsDossier`, `ClinicalVisitDossier`, `GenericDocumentDossier`).
- **`validate_grounding`**: Verifies that extracted numerical values (e.g., copays, deductibles, lab values) are strictly grounded in the source text.
- **`extract_document_dossier`**: Composite dual-invocation tool wrapping file ingestion, sanitization, extraction, and grounding.

### 3.2 Zero-Mock Production Policy
- No production code in `backend/src/` or `apps/web/src/` may employ fake, dummy, or facade mock implementations.
- All test doubles and mocks must reside exclusively within test directories (`tests/fixtures/`, `backend/tests/conftest.py`, or `apps/web/tests/mocks/`).

---

## 4. Orchestration Nodes & LangGraph Lifecycle

Carefold executes multi-agent workflows using a 5-phase deterministic LangGraph state machine:

```
[User Input]
     │
     ▼
┌────────────────────────────────────────┐
│ Phase 1: Context Load & Memory Recall  │ ◄── MemoryPort.recall(query, WORKING/EPISODIC)
└────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────┐
│ Phase 2: Input Guardrail & Validation  │ ──► [Emergency / Safety Violation] ──► [RefusalNode]
└────────────────────────────────────────┘
     │ (Passed)
     ▼
┌────────────────────────────────────────┐
│ Phase 3: Plan & Provision              │ ◄── CatalogPort.search_agents() / Two-Hop Routing
└────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────┐
│ Phase 4: Specialist Agent Execution    │ ◄── ToolNode (Sandboxed Tools & Subgraphs)
└────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────┐
│ Phase 5: Synthesize, Guard & Stream    │ ──► [SSE Stream: Token, Tools, Suggestions, Disclaimer]
└────────────────────────────────────────┘
```

1. **Phase 1: Context Load & Memory Recall (`InputGuardrailNode`)**:
   - Ingests user query, conversation history, and thread state.
   - Queries `MemoryPort` for relevant episodic and semantic memories using FTS5 search and salience ranking.
2. **Phase 2: Input Guardrail & Validation (`InputGuardrailNode`, `RefusalNode`)**:
   - Evaluates emergency red flags and non-clinical boundary violations.
   - If a red flag is detected, immediately terminates execution and returns a safe emergency directive.
3. **Phase 3: Plan & Provision (`OrchestratorNode`)**:
   - Executes Two-Hop Routing: Hop 1 classifies domain; Hop 2 searches the `CatalogPort` using BM25 full-text matching against specialist manifests.
   - Injects authorized reference documents and tool schemas into the execution context.
4. **Phase 4: Specialist Execution (`AgentExecutionNode`, `ToolNode`)**:
   - Invokes specialist agent with persona instructions and provisioned reference skills.
   - Handles tool calling loops up to `DEFAULT_MAX_ITERATIONS` (3 turns).
5. **Phase 5: Response Synthesis & Guardrails (`ResponseSynthesizerNode`, `OutputGuardrailNode`, `SuggestionNode`)**:
   - Verifies grounding and persona purity.
   - Generates contextual follow-up chips and attaches non-clinical disclaimers.
   - Emits Server-Sent Events (SSE) to the web UI.

---

## 5. Rules of Engagement for AI Coding Agents

All AI coding assistants (e.g., Cursor, Claude Code, GitHub Copilot, Gemini CLI) operating within this repository must adhere to the following rules:

1. **Minimal Change Principle**:
   - Modify only files directly relevant to the assigned task. Never perform unsolicited refactoring or stylistic reformatting.
2. **License Header Integrity**:
   - Every `.py`, `.ts`, `.tsx`, `.js`, `.mjs`, and `.css` file must contain the official Spectrayan Apache-2.0 copyright header.
   - Verify license compliance using `pnpm run check:licenses`.
3. **Safety & Security Invariants**:
   - Never weaken clinical safety guardrails, emergency red-flag patterns, or PII regex filters in `resources/` or `subgraphs/extraction/`.
   - Never bypass file path traversal protections in `tools/sandboxed.py` or `tools/attachments.py`.
4. **Verification Gates**:
   - Before completing any task, execute the full verification matrix:
     ```bash
     # 1. License Check
     pnpm run check:licenses

     # 2. Backend Unit & Regression Tests
     backend/.venv/bin/pytest backend/tests/

     # 3. Security Penetration Suite (47 Attacks)
     PYTHONPATH=backend/src backend/.venv/bin/python backend/tests/penetration_suite.py

     # 4. Frontend Typecheck
     pnpm --filter web typecheck

     # 5. Frontend Unit & Component Tests
     pnpm --filter web test --exclude "**/api/**"

     # 6. Frontend Production Build
     pnpm --filter web build
     ```
5. **Documentation Integrity**:
   - Any modification to agent contracts, memory ports, or workflow state must be reflected in `PROJECT_CONTEXT.md` and `docs/adr/`.
6. **Repository Content Policy (Product & Test Code Only)**:
   - Commit only production code, tests and test fixtures, agent/skill packs, user and contributor documentation, and the build, CI, and release tooling those require (for example `scripts/licenses.mjs`, `scripts/bump-version.mjs`, `scripts/validate-packs.mjs`).
   - Never commit one-off operational or administrative scripts (GitHub organization or team provisioning, account setup, migrations run once by hand), AI-agent planning or session artifacts (implementation plans, task lists, walkthroughs, scratch notes, audit reports), local runtime data (`chats/`, `logs/`, `workspace/`, `attachments/`, `catalog.db`), or personal configuration.
   - Organization governance automation belongs in the internal tooling repository, not in this product repository.
