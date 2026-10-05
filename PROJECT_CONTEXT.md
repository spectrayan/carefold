# Carefold — Living Project Context

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

Standard: Spector Living Project Context Standard  
Target System: Carefold Healthcare AI Agent Marketplace & Local Runtime  
Last Updated: 2026-10-02  
Status: Active / Verified against Codebase  

---

## 1. Architectural Vision & Core Principles

Carefold delivers a private, local-first runtime and open marketplace for specialized healthcare AI agents. It adheres to five foundational engineering principles:

1. **Local-First & Offline Resilience**:
   - Primary inference, document ingestion, and cognitive memory execution run locally on the user's workstation.
   - External network calls are strictly restricted to user-configured LLM providers (e.g., local Ollama, or optional OpenAI/Anthropic/Google endpoints via user API keys).
2. **Patient Data Sovereignty & Zero Exfiltration**:
   - Medical records, insurance documents, and conversation histories are stored within client-controlled local sandboxes.
   - Zero telemetry, analytics, or behavioral data leaves the execution environment without explicit user approval.
3. **Hexagonal Architecture (Ports and Adapters)**:
   - Domain logic and agent orchestration workflows are strictly isolated from storage engines and protocol adapters via abstract interfaces (`MemoryPort`, `CatalogPort`).
   - Adapters for SQLite FTS5, Spector MCP, and PostgreSQL can be swapped without touching core LangGraph execution nodes.
4. **Persona Purity & Clinical Boundaries**:
   - Each specialist agent maintains a focused, bounded persona (e.g., Cardiology Guide, Formulary Guide).
   - Clinical boundary guardrails prevent medical diagnosis, clinical prescribing, or acute triage replacement, routing emergency red flags immediately to local emergency care protocols.
5. **Rigorous Verification & Zero-Mock Execution**:
   - Production code operates without mock fallbacks or dummy implementations. Mocks are segregated strictly into testing fixtures.

---

## 2. Ports-and-Adapters Taxonomy

Carefold decouples state persistence and catalog discovery through clean hexagonal boundaries:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        LangGraph Workflow Core                         │
│  (InputGuardrailNode, OrchestratorNode, AgentExecutionNode, Nodes)     │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │                                 │
                   ▼ (invokes)                       ▼ (invokes)
        ┌─────────────────────┐           ┌─────────────────────┐
        │     MemoryPort      │           │     CatalogPort     │
        │     (Interface)     │           │     (Interface)     │
        └──────────┬──────────┘           └──────────┬──────────┘
                   │                                 │
         ┌─────────┴─────────┐             ┌─────────┴─────────┐
         ▼ (implements)      ▼ (roadmap)   ▼ (implements)      ▼ (roadmap)
   ┌──────────────┐   ┌──────────────┐┌──────────────┐   ┌──────────────┐
   │ SqliteMemory │   │ Spector MCP  ││ SqliteCatalog│   │  Postgres    │
   │   Adapter    │   │  / Postgres  ││   Adapter    │   │   Catalog    │
   │  (aiosqlite) │   │   Adapters   ││  (aiosqlite) │   │   Adapter    │
   └──────────────┘   └──────────────┘└──────────────┘   └──────────────┘
```

### 2.1 MemoryPort Interface (`carefold.memory.ports.memory_port`)

The `MemoryPort` manages cognitive agent memory across temporal tiers and namespaces:

- **`remember(key, value, tier, namespace, metadata)`**: Stores or updates an entry within a specified `MemoryTier` and isolation namespace (e.g., `agent:visit-steward`, `user:patient_1`).
- **`recall(query, tier, namespace, limit)`**: Executes natural language or keyword retrieval, returning scored memory dictionaries sorted by cognitive salience and relevance.
- **`forget(key, namespace)`**: Removes a specific memory record.
- **`reinforce(key, namespace, delta)`**: Dynamically adjusts memory salience scores (boosting frequently accessed memories or applying decay).
- **`close()`**: Gracefully terminates underlying database connections or network sockets.

### 2.2 CatalogPort Interface (`carefold.memory.ports.catalog_port`)

The `CatalogPort` indexes, discovers, and queries specialist agent and skill manifests:

- **`index_agent(manifest)`**: Inserts or updates an `AgentManifest` in the catalog.
- **`index_skill(manifest)`**: Inserts or updates a `SkillManifest` in the catalog.
- **`search_agents(query, domain, category, limit)`**: Full-text and taxonomy search across agent titles, descriptions, personas, and declared skills.
- **`search_skills(query, domain, category, limit)`**: Full-text search across clinical skill packs and intended-use specifications.
- **`get_category_tree()`**: Computes a hierarchical taxonomy tree containing total indexed agents and counts per clinical/administrative domain.
- **`close()`**: Releases underlying database connections.

### 2.3 Concrete Adapters & Factory Resolution

- **`SqliteMemoryAdapter` (`carefold.memory.adapters.sqlite.memory_adapter`)**:
  - Implemented using asynchronous `aiosqlite`.
  - Uses SQLite FTS5 virtual tables (`memory_fts`) with BM25 full-text ranking.
  - Implements salience scoring combining match score with time decay (`salience * exp(-decay_rate * delta_t)`).
- **`SqliteCatalogAdapter` (`carefold.memory.adapters.sqlite.catalog_adapter`)**:
  - Uses SQLite FTS5 virtual tables (`agents_fts`, `skills_fts`) for sub-millisecond local agent and skill discovery.
  - Builds dynamic category trees for UI navigation and orchestrator routing.
- **Pluggable Factory (`carefold.memory.factory`)**:
  - `create_memory_port(backend="sqlite", **kwargs)`
  - `create_catalog_port(backend="sqlite", **kwargs)`
  - Roadmap: Native support for Spector cognitive memory server (`backend="spector"`) and enterprise relational storage (`backend="postgres"`).

---

## 3. Cognitive Memory Tiers

Carefold organizes agent state and knowledge across 4 cognitive memory tiers defined by `MemoryTier(str, Enum)`:

| Tier | Lifecycle | Scope & Purpose | Examples | Storage Target |
|---|---|---|---|---|
| **`WORKING`** | Ephemeral (Session / Turn) | Active task execution scratchpad, intermediate tool outputs, current reasoning trace. | Extracted unverified lab values, pending tool call arguments. | In-memory `AgentState` / SQLite ephemeral table |
| **`EPISODIC`** | Short-to-Medium Term | Autobiographical interaction history, chronological conversation turns, timestamped user actions. | Prior visit discussion notes, previous questions asked by patient. | SQLite `memory_records` with FTS5 & salience decay |
| **`SEMANTIC`** | Long-Term (Persistent) | Consolidated factual healthcare profile, extracted insurance parameters, user preferences. | Annual deductible amount, preferred pharmacy, in-network hospital group. | SQLite `memory_records` (tier: `semantic`) / Spector MCP |
| **`PROCEDURAL`** | Immutable / Versioned | Step-by-step clinical workflows, SOP execution rules, protocols, skill action guidelines. | Cardiology visit prep checklist, prior authorization appeal steps. | Markdown skill files in `skills/` & catalog FTS5 index |

---

## 4. Core Execution Pipelines

### 4.1 Dual Ingestion & Extraction Pipeline

Carefold features a dual-path document ingestion pipeline that extracts typed, grounded dossiers from patient attachments:

```
[User Attachment / File Upload]  OR  [In-turn Tool: extract_document_dossier]
                          │
                          ▼
             ┌─────────────────────────┐
             │    Sandboxed Reader     │ ◄── Path traversal & symlink check
             └────────────┬────────────┘
                          │
                          ▼
             ┌─────────────────────────┐
             │  Regex PII Sanitization │ ◄── Masks SSN, MRN, phone, address
             └────────────┬────────────┘
                          │
                          ▼
             ┌─────────────────────────┐
             │ Pydantic Structured Ext │ ◄── InsuranceBenefitsDossier,
             └────────────┬────────────┘     ClinicalVisitDossier, Generic
                          │
                          ▼
             ┌─────────────────────────┐
             │ Grounding Verification  │ ◄── Validates numerical tokens vs source
             └────────────┬────────────┘
                          │
                          ▼
             ┌─────────────────────────┐
             │  AgentState Dossier Hub │ ──► Attached to AgentState.document_dossiers
             └─────────────────────────┘
```

1. **Sandboxed File Reading**: Enforces containment within `attachments/` with zero null-byte or directory-escape vulnerabilities.
2. **PII Masking**: Automatically sanitizes sensitive health identifiers (HIPAA Safe Harbor standard).
3. **Structured Extraction**: Converts raw OCR or text into typed models:
   - `InsuranceBenefitsDossier`: Deductibles, copays, out-of-pocket maximums, prior authorization rules.
   - `ClinicalVisitDossier`: Chief complaints, vital signs, medication lists, lab trends.
   - `GenericDocumentDossier`: General medical summaries.
4. **Numerical Grounding**: Every currency, percentage, and clinical measurement is cross-checked against the raw source text to prevent LLM hallucination.

### 4.2 Two-Hop Orchestrator Routing Pipeline

To scale beyond hundreds of specialist agents without context overflow, Carefold employs Two-Hop Routing:

- **Hop 1: Domain Classification**:
  - The `OrchestratorNode` classifies the intent into high-level domains: `clinical`, `navigation`, `wellness`, `admin`.
- **Hop 2: Specialist Resolution**:
  - The orchestrator issues an FTS5 search query via `CatalogPort.search_agents(query, domain=domain)` against specialist personas, categories, and skill keywords.
  - The top-ranking specialist is selected (e.g., `cardiology-guide`).
  - If no confident match is found, the workflow safely defaults to `visit-steward` or `triage-auditor`.
- **Dynamic Skill Provisioning**:
  - Only the reference documents and skills declared by the routed specialist are loaded into the prompt context, keeping token utilization minimal and eliminating distraction.

### 4.3 SSE Streaming Wire Protocol

Real-time interactions stream from the FastAPI backend to the Next.js client using Server-Sent Events (SSE):

| Event Type | Payload Format | Description |
|---|---|---|
| `token` | `{"content": "..."}` | Incremental LLM text generation tokens. |
| `tool_start` | `{"tool": "...", "input": {...}}` | Live notification that a tool invocation has commenced. |
| `tool_end` | `{"tool": "...", "output": {...}}` | Output or result returned from the sandboxed tool. |
| `tool_error` | `{"tool": "...", "error": "..."}` | Non-fatal tool execution error notification. |
| `suggestions` | `{"suggestions": ["...", "..."]}` | Context-aware follow-up suggestion chips for the UI. |
| `disclaimer` | `{"text": "..."}` | Mandatory non-clinical disclaimer banner. |
| `refusal` | `{"reason": "...", "directive": "..."}` | Triggered on emergency red flags or clinical boundary refusal. |
| `done` | `{"thread_id": "...", "status": "ok"}` | Final completion packet closing the stream. |

---

## 5. Security & Verification Architecture

Carefold enforces security through defense-in-depth:

1. **47-Point Security Penetration Suite (`backend/tests/penetration_suite.py`)**:
   - Tests path traversal, symlink escapes, shell injection, undeclared skill doc access, and PII leakage.
   - Must achieve 47/47 passing tests on every CI run.
2. **License Automation**:
   - Monorepo tooling (`scripts/licenses.mjs`, `pnpm run check:licenses`) ensures 100% adherence to the Spectrayan Apache-2.0 copyright header across Python, TypeScript, and CSS files.
3. **Clinical Quality Gates**:
   - Golden evaluation datasets in `evals/` benchmark prompt alignment, refusal correctness, and factual grounding before any agent manifest is approved.
4. **Clinical-Assist Consent Gate (`#87`)**:
   - The backend returns `403` for `GET /api/agents/{id}` and refuses `POST /api/chat` for `clinical_assist` agents unless `allow_clinical=true`.
   - The web client never assumes consent: per-agent consent is granted through `ClinicalConsentDialog`, stored only in browser storage (`carefold_clinical_consent_v1`, managed by `apps/web/src/lib/clinicalConsent.ts`), and read at request time. The Next.js proxy routes default `allow_clinical` to `false`.
   - `AgentSummary` (from `GET /api/agents`) includes the agent's `forbidden` list so the dialog can render it before consent.
