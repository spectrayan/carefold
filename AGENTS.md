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
Runtime version: Carefold 0.4.0-beta.1
Last updated: 2026-10-14  

---

## 1. Project Boundaries & Operational Constraints

Carefold is a source-available, local-first personal and family health AI companion and specialist agent runtime designed for privacy-preserving clinical visit preparation, health insurance navigation, and chronic care support.

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
│   │   ├── audit/      # Tamper-evident SHA-256 hash-chained audit_events
│   │   ├── clinical/   # Preventive care rules, school forms, and SMART scheduling
│   │   ├── companion/  # Paired iOS HealthKit & Android Health Connect sync
│   │   ├── connectors/ # OAuth 2.0 PKCE broker, stateless relay, and curated Gmail MCP
│   │   ├── db/         # SQLAlchemy 2.0 declarative models & Alembic migrations
│   │   ├── engine/     # LangGraph workflow builder, runner, SSE, and 4-tier ToolExecutionGate
│   │   ├── i18n/       # BCP 47 / RFC 4647 locale negotiation, UAX #15 NFC, ICU catalogs & multilingual safety
│   │   ├── importers/  # Apple Health, C-CDA, FHIR R4, CSV & SMART Health Cards (.smart-health-card)
│   │   ├── memory/     # Hexagonal ports (MemoryPort, CatalogPort) & SQLite FTS5 adapters
│   │   ├── model/      # Multi-provider LLM abstraction (Ollama, Anthropic, OpenAI, Google)
│   │   ├── search/     # Hybrid SearchIndex (FTS5 + sqlite-vec, RRF, MMR & local reranker)
│   │   ├── storage/    # Per-profile Content-Addressed Storage (CAS)
│   │   ├── tools/      # Sandboxed file, extraction, and delegation tools
│   │   ├── vault/      # Envelope encryption keyring vault (HKDF-SHA256 per-profile AES-256-GCM DEKs)
│   │   └── workflows/  # LangGraph state machine, nodes, and extraction subgraphs
│   └── tests/          # Pytest suite & 47-attack penetration test harness
├── apps/web/           # Next.js 15 Tailwind CSS agent marketplace and consultation UI
│   └── src/i18n/       # Client BCP 47 / ICU MessageFormat, Intl formatters & bidirectional LTR/RTL support
├── libs/
│   └── connectors/     # Scoped Connector SDK, ScopedHttp egress sandbox & starter/v2 connectors
├── packages/
│   ├── cli/            # Carefold CLI for agent authoring and local execution
│   └── runner/         # Standalone agent runtime sandbox
├── agents/             # 23 Specialist clinical/navigational agents + 6 system agents
├── skills/             # 24 Modular clinical skill packs with reference guidelines
├── docs/               # Verified MkDocs Material documentation, Living ADRs & Compliance Packs
│   ├── adr/            # Living Architecture Decision Records (0001–0009)
│   ├── compliance/     # OAuth CASA Tier 2/3, OWASP ASVS L2, Threat Model & Regulatory Readiness Packs
│   └── connectors/     # Scoped Connector SDK authoring guide
└── .github/            # GitHub Actions CI/CD matrix, CodeQL, and community templates
```

### 2.1 Specialist Agent Topology (23 Specialists)

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
| `hematology-guide` | `clinical` | `hematology` | `clinical_assist` | `hematology-prep`, `emergency-red-flags`, `clinical-safety-boundaries` |
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

### 2.3 Autonomy, Scoped Connectors, Internationalization & Living ADRs

- **Scoped Connector SDK (`libs/connectors/`)**:
  - Declarative `ConnectorManifest` YAML files, `ScopedHttp` outbound host allowlisting, `UntrustedResult` taint tracking, and first-party/v2 connectors (`withings`, `google-calendar`, `caldav`, `epic-smart`, `gmail-mcp`, `oracle-health`, `athenahealth`, `cms-blue-button`, `oura`, `google-health`, `microsoft-graph`, `zocdoc`).
- **End-to-End Internationalization (`backend/src/carefold/i18n/`, `apps/web/src/i18n/`, `ADR-0009`)**:
  - IETF BCP 47 locale tags (`en-US`, `es-ES`, `fr-FR`, `hi-IN`, `ar-SA`), RFC 4647 quality-weighted locale negotiation, Unicode UAX #15 `NFC` canonical storage normalization, language-neutral HL7 FHIR R4 coding, ICU MessageFormat translation catalogs, multilingual acute red-flag detection, and bidirectional (`LTR`/`RTL`) layout mirroring via W3C CSS Logical Properties.
- **Living Architecture Decision Records (`docs/adr/0001`–`0009`) & Compliance Packs (`docs/compliance/`)**:
  - Living ADRs `0001` through `0009` govern orchestration (`0001`), hexagonal ports (`0002`), progressive disclosure (`0003`), 4-tier policy approvals & taint propagation (`0004`), envelope keyring vault (`0005`), Mode L / Mode S deployment tiers (`0006`), partitioned CAS & hybrid search (`0007`), stateless PKCE OAuth bounce relay (`0008`), and 5-layer internationalization (`0009`).
  - `docs/compliance/` provides verification and regulatory readiness documentation covering Google OAuth CASA Tier 2/3 & OWASP ASVS L2 (`google-verification-and-casa.md`, `asvs-l2-checklist.md`, `threat-model.md`) and HIPAA Safe Harbor, MHMDA, DPDP, FTC HBNR, COPPA under-13, and non-clinical wellness positioning (`legal-and-regulatory-pack.md`, `hipaa-readiness.md`, `dpdp-readiness.md`, `wellness-positioning.md`).

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
   - Every `.py`, `.ts`, `.tsx`, `.js`, `.mjs`, and `.css` file must contain the official Spectrayan PolyForm Noncommercial + Carefold Additional Terms copyright header.
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
