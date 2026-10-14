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
Last Updated: 2026-10-14  
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
| `refusal` | `{"reason": "...", "message": "...", "category": "..."}` | Triggered on emergency red flags or clinical boundary refusal. Optional `category` identifies acute emergency sign. |
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

---

## 6. Carefold Autonomy & Multi-Profile Household Architecture (`AU-01`–`AU-81`)

Carefold extends its local-first runtime into a full multi-profile household care organizer and policy-gated autonomous execution engine across Milestones Phase1–Phase6 (`AU-01`–`AU-81`):

### 6.1 Multi-User Household Profiles, Envelope Encryption & Content-Addressed Storage

- **Multi-User & Household Profiles**:
  - Relational identity and RBAC tables (`users`, `sessions` / `user_sessions`, `profiles`, `profile_access`, `profile_consents`, `viewer_invites`) support household stewardship across `self`, `child`, `parent`, `spouse`, and `dependent` profiles.
  - Access control enforces fail-closed profile scoping (`owner`, `caregiver`, `viewer`) on every API route and tool invocation (`ADR-0007`), with COPPA guardian-only connector guards for under-13 pediatric profiles (`E11.6`).
  - Dual operational modes (`ADR-0006`): `Mode L` (local-first desktop bound to `127.0.0.1` with SQLite) and `Mode S` (multi-user self-hosted server with PostgreSQL and OIDC/Argon2id authentication).
- **Per-Profile Envelope Encryption (`profile_keys`, `ADR-0005`)**:
  - A 256-bit Master Key (`KEK`, resolved from OS keyring, cloud KMS, file, or environment) wraps and derives per-profile AES-256-GCM Data Encryption Keys (`DEKs`) via `HKDF-SHA256` (`carefold/vault/`).
  - Encrypted `credentials` bind authenticated additional data (`aad_binding = carefold:p:{profile_id}:c:{connection_id}`) and support key rotation (`dek_version`) and instant cryptographic erasure (crypto-shredding) upon profile deletion (`Titan S2`).
- **Content-Addressed Storage (`attachments`, `profile_attachments`, `ADR-0007`)**:
  - Patient uploads are stored in a per-profile partitioned Content-Addressed Storage (CAS) layout (`<carefold_home>/data/files/<user_id>/<profile_id>/<sha256[:2]>/<sha256>`), eliminating path traversal vulnerabilities and preventing cross-tenant deduplication side-channels.

### 6.2 Clinical Domain Records & Organizer Schema

- **FHIR R4 Clinical Repository (`health_resources`)**:
  - Stores validated HL7 FHIR R4 / R4B JSONB payloads (`Observation`, `Condition`, `MedicationRequest`, `MedicationStatement`, `AllergyIntolerance`, `Immunization`, `Encounter`, `DocumentReference`, `DiagnosticReport`) indexed by profile, category, canonical `system`/`code` (`LOINC`, `SNOMED CT`, `RxNorm`, `CVX`, `ICD-10-CM`), and effective date.
- **Care Coordination & Household Workflows**:
  - `appointments` & `reminders`: Clinical visit scheduling, pre-visit prep checklists, and timezone-aware (`TIMESTAMPTZ` + IANA timezone) notification queues.
  - `preventive_records`: Deterministic preventive care rules engine tracking age/sex-specific USPSTF, CDC, and ACIP screening and immunization intervals.
  - `school_forms` & `school_ics_feeds`: Pediatric/camp health form autofill with field-level provenance (`AU-39`) and one-way `.ics` school calendar ingestion (`AU-61`).
  - `email_drafts`: Local-first care correspondence drafting (`draft_care_email`) stored offline before any optional external send approval.
  - `import_batches`: Idempotent clinical importers (`carefold/importers/`) supporting Apple Health `export.xml`, HL7 C-CDA XML, FHIR R4 Bundles, CSV vitals, and offline RFC 7515 JWS-verified SMART Health Cards (`.smart-health-card`, `AU-77`).
  - `companion_devices`: Paired iOS HealthKit (`AU-62`) and Android Health Connect (`AU-80`) mobile companions using SHA-256 token digests and pinned TLS certificate fingerprints.

### 6.3 Scoped Connectors, Provenance & Taint Tracking

- **Scoped Connector SDK (`libs/connectors/`)**:
  - Declarative YAML manifests (`ConnectorManifest`) and `@runtime_checkable` `Connector` implementations (`streams`, `fetch`, `map`, `tools`) enforced by `ScopedHttp` egress allowlisting (`allowed_hosts`, HTTPS-only, RFC 1918 / link-local SSRF blocking).
  - State persisted across `connections`, `credentials`, `consent_grants` (granular `connector × profile × category × purpose` matrix), `sync_runs`, `mcp_tool_pins`, `routines`, and `jobs`.
- **Starter & Coordinated v2 Connectors**:
  - First-party connectors: **Withings** (`withings`), **Google Calendar** (`google-calendar`), **CalDAV** (`caldav`), **Epic SMART on FHIR** (`epic-smart`), and **Curated Gmail MCP** (`gmail-mcp`: `gmail_search_messages`, `gmail_get_thread`, `gmail_send_message`).
  - Coordinated v2 connectors (`AU-70`–`AU-76`): **Oracle Health (Cerner)** (`oracle-health`), **athenahealth** (`athenahealth`), **CMS Blue Button 2.0** (`cms-blue-button`), **Oura Ring** (`oura`), **Google Health / Fitbit** (`google-health`), **Microsoft 365 Graph** (`microsoft-graph`), and **Zocdoc / SMART Scheduling Links** (`zocdoc`).
  - **Stateless OAuth 2.0 PKCE Callback Bounce Relay (`ADR-0008`, `AU-70`)**: Verifies `<= 120s` TTL HMAC-SHA256 relay tickets and single-use nonces while storing zero tokens and zero PHI on the relay.
  - **Remote MCP Tool Schema Pinning (`mcp_tool_pins`, `Titan S7`, `AU-57`)**: Computes canonical SHA-256 digests over `(name, description, inputSchema)` and halts execution (`409 Conflict` / `drift_blocked`) on upstream schema drift.

### 6.4 4-Tier Tool Execution Gate, Taint Propagation & Hash-Chained Audit Log

- **4-Tier Tool Execution Gate (`ADR-0004`, `carefold/engine/tool_exec.py`)**:
  - Every tool declares a deterministic risk tier—`read`, `write_local`, `write_external`, or `irreversible`—evaluated against the active autonomy level (`A0` Manual, `A1` Assisted, `A2` Autonomous).
  - `irreversible` actions (such as `gmail_send_message` or external appointment booking confirmation) **always** halt execution and require a single-use human `Approval` (`approvals` table) cryptographically bound to the exact `payload_hash`, even under `A2`.
- **Monotone Taint Propagation (`UntrustedResult`)**:
  - Any tool returning external or unverified content (`trust_level="untrusted"`, e.g., EHR clinical narratives, web search snippets, or email bodies) wraps its output in `UntrustedResult` and fences content in `<untrusted_external_content>`. Once a turn is tainted, all `write_external` and `irreversible` calls automatically escalate to require explicit human approval.
- **Tamper-Evident Audit Hash Chain (`audit_events`, `AU-78`)**:
  - Every tool call, policy decision, approval consumption, and connector sync is recorded in `audit_events` linked via a per-profile SHA-256 hash chain (`prev_hash` $\rightarrow$ `entry_hash` anchored at `GENESIS`) and verified via `verify_profile_audit_chain()` (`carefold/audit/hash_chain.py`).

### 6.5 Hybrid Retrieval (`SearchIndex`) & 3-Tier Memory Consolidation

- **Hybrid Retrieval (`chunks`, `chunks_fts`, `chunks_vec`, `ADR-0007`)**:
  - `ClinicalChunker` segments documents into structure-aware `chunks` indexed simultaneously in SQLite FTS5 (`chunks_fts` BM25 lexical search) and `sqlite-vec` (`chunks_vec` dense vector embeddings).
  - Retrieval combines lexical and semantic rankings via **Reciprocal Rank Fusion (`RRF`)**, **Maximal Marginal Relevance (`MMR`)** diversity filtering, and optional local cross-encoder reranking (`carefold/search/reranker.py`, `AU-79`).
- **3-Tier Memory Consolidation**:
  - Background consolidation promotes high-salience `working` turn state into `episodic` session memories and distills durable clinical facts into `semantic` profile records with exponential time-decay weighting.

---

## 7. End-to-End Internationalization & Multilingual Safety (`i18n` / `l10n`, `ADR-0009`)

Carefold implements a five-layer, standards-based internationalization architecture across `backend/src/carefold/i18n/` and `apps/web/src/i18n/`:

1. **IETF BCP 47 Locale Tags & RFC 4647 Negotiation (`carefold.i18n.locale`)**:
   - First-class supported locales: `en-US` (English), `es-ES` (Spanish — `Español`), `fr-FR` (French — `Français`), `hi-IN` (Hindi — `हिन्दी`), and `ar-SA` (Arabic — `العربية`, `dir="rtl"`).
   - Deterministic 4-level locale lookup (`negotiate_locale`): `Profile.preferred_locale` $\triangleright$ `User.preferred_locale` $\triangleright$ HTTP `Accept-Language` (`RFC 4647` quality-weighted matching with primary-subtag fallback) $\triangleright$ `en-US`.
2. **Unicode UAX #15 `NFC` Normalization & Provenance Storage (`0010_i18n_and_locale_storage`)**:
   - All user-authored text and search chunks pass through `normalize_text_nfc()` (`unicodedata.normalize("NFC", text)`) before persistence, SHA-256 content addressing, and SQLite FTS5 indexing.
   - Relational tables store explicit locale preferences and document provenance (`users.preferred_locale`, `profiles.preferred_locale`, `notes.locale`, `attachments.locale`, `health_resources.locale`).
3. **HL7 FHIR R4 Language-Neutral Clinical Coding**:
   - Clinical `system` and `code` fields remain strictly language-neutral (`LOINC`, `SNOMED CT`, `RxNorm`, `CVX`, `ICD-10-CM`), while human-facing display labels and summaries localize per profile.
4. **ICU MessageFormat Catalogs & Multilingual Emergency Red Flags (`carefold.i18n.catalog`)**:
   - JSON translation catalogs (`backend/src/carefold/resources/locales/*.json`) support ICU variable interpolation and plural rules (`zero`, `one`, `other`).
   - Deterministic offline safety guardrails provide localized non-clinical disclaimers (`get_localized_disclaimer`), localized emergency contact directives (`get_localized_emergency_directive`: `911`, `988`, `112`), and multilingual acute red-flag detection (`detect_multilingual_red_flag`) across English, Spanish, French, Hindi, and Arabic.
5. **Bidirectional (`LTR` / `RTL`) Layout & `Intl` Formatting (`apps/web/src/i18n/`)**:
   - Client formatting uses native `Intl.DateTimeFormat`, `Intl.NumberFormat`, `Intl.RelativeTimeFormat`, and `Intl.PluralRules`.
   - Document direction (`dir="ltr"` / `dir="rtl"`) and W3C CSS Logical Properties (`ms-*`, `me-*`, `ps-*`, `pe-*`, `inset-inline-*`, `text-start`) mirror the application shell automatically for RTL locales (`ar-SA`) while meeting WCAG 2.1 AA contrast and keyboard accessibility standards.

---

## 8. Living ADRs & Compliance Documentation Reference

| Document / Record | Path | Scope |
|---|---|---|
| **ADR-0001** | `docs/adr/0001-orchestrator-driven-agent-architecture.md` | 5-phase LangGraph orchestrator, two-hop routing, and safety guardrails. |
| **ADR-0002** | `docs/adr/0002-hexagonal-memory-and-catalog-ports.md` | Hexagonal `MemoryPort` and `CatalogPort` interfaces and SQLite FTS5 adapters. |
| **ADR-0003** | `docs/adr/0003-progressive-disclosure-skill-context-management.md` | Progressive disclosure skill loading and token budget governance. |
| **ADR-0004** | `docs/adr/0004-policy-approvals-and-resume.md` | 4-tier policy gate, monotone taint propagation, and single-use `Approval` tokens. |
| **ADR-0005** | `docs/adr/0005-vault-threat-model-and-kek-sources.md` | Envelope encryption keyring vault, `HKDF-SHA256` per-profile DEKs, and KEK sources. |
| **ADR-0006** | `docs/adr/0006-deployment-modes-and-requirement-tiers.md` | Mode L (Local Desktop) vs Mode S (Server) and Tier A / Tier S invariants. |
| **ADR-0007** | `docs/adr/0007-content-addressed-storage-and-hybrid-search.md` | Per-profile partitioned CAS layout and hybrid FTS5 + `sqlite-vec` `SearchIndex`. |
| **ADR-0008** | `docs/adr/0008-oauth-relay-and-stateless-callback.md` | Stateless OAuth 2.0 PKCE callback bounce relay (`<= 120s` TTL) with zero token custody. |
| **ADR-0009** | `docs/adr/0009-internationalization-and-multilingual-architecture.md` | 5-layer i18n architecture, BCP 47 / RFC 4647 negotiation, UAX #15 `NFC`, and RTL UI. |
| **Connector Authoring** | `docs/connectors/authoring.md` | Scoped Connector SDK (`libs/connectors`), FHIR R4 validation, and taint rules. |
| **OAuth, Threat Model & ASVS L2/CASA Pack** | `docs/compliance/google-verification-and-casa.md` | Google OAuth scope least-privilege matrix, OWASP ASVS L2 (`asvs-l2-checklist.md`) / CASA Tier 2/3 controls, and threat model (`threat-model.md`). |
| **Legal, Regulatory & Privacy Readiness Pack** | `docs/compliance/legal-and-regulatory-pack.md` | HIPAA Safe Harbor & MHMDA privacy readiness (`hipaa-readiness.md`), consent withdrawal & data erasure (`dpdp-readiness.md`), non-clinical wellness positioning (`wellness-positioning.md`), FTC HBNR runbook, and COPPA under-13 safeguards. |

