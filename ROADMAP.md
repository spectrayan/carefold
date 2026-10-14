# Carefold Product Roadmap

The Carefold roadmap outlines the architectural and community milestones driving the evolution of our local-first healthcare AI runtime, multi-profile household care organizer, and decentralized agent marketplace.

---

## Strategic Phases

```
┌───────────────────────────┐      ┌───────────────────────────┐      ┌───────────────────────────┐      ┌───────────────────────────┐
│  Phase 0–1: Core & Hex    │ ──►  │ Phase 2: Autonomy Phase1–Phase6   │ ──►  │  Phase 3: i18n & WCAG AA  │ ──►  │ Phase 4: Spector & P2P    │
│    (Completed — v0.3.0)   │      │ (Completed — AU-01..AU-81)│      │ (Current — Batch 8 v0.4.0)│      │        (2027 Roadmap)     │
└───────────────────────────┘      └───────────────────────────┘      └───────────────────────────┘      └───────────────────────────┘
```

---

## Phase 0: Local-First Core & Sandboxed Tooling (Completed — Q3 2026)

- [x] Initial LangGraph multi-agent execution engine with FastAPI.
- [x] Next.js 15 Tailwind CSS consultation chat UI with model selector.
- [x] Sandboxed file reader and local attachment store (`attachments/`).
- [x] Dual-invocation document extraction pipeline with PII sanitization.
- [x] Zero-mock architecture eliminating artificial production test doubles.
- [x] Baseline security penetration test harness blocking path traversal attacks.

---

## Phase 1: Clinical Expansion & Hexagonal Architecture (Completed — v0.3.0)

- [x] **Agent & Skill Scalability**:
  - Expanded specialist catalog to 23 clinical organ navigators and administrative guides (including `hematology-guide`).
  - Authored verified clinical and navigation skill packs with evidence-based references.
- [x] **Hexagonal Ports-and-Adapters Architecture**:
  - `MemoryPort` defining 4 cognitive tiers (`WORKING`, `EPISODIC`, `SEMANTIC`, `PROCEDURAL`).
  - `CatalogPort` for sub-millisecond specialist discovery and category tree queries.
  - High-performance `SqliteMemoryAdapter` and `SqliteCatalogAdapter` using SQLite FTS5.
- [x] **Two-Hop Intent Routing**:
  - Tier-1 domain classification followed by Tier-2 BM25 specialist resolution.
  - Dynamic skill provisioning limiting context windows and reducing hallucination.
- [x] **Enterprise Open-Source Governance**:
  - Canonical `AGENTS.md` and `PROJECT_CONTEXT.md` manifests.
  - Spectrayan Apache-2.0 copyright and license automation tooling.
  - Contributor Covenant v2.1 Code of Conduct and Coordinated Security Disclosure policy.
- [x] **Documentation & Architecture Decision Records**:
  - MkDocs Material documentation site with instant search and dark/light modes.
  - Living ADR framework (`docs/adr/`) with Mermaid flowcharts and sequence diagrams.
- [x] **Production CI/CD Matrix**:
  - GitHub Actions matrix covering Python 3.12/3.14, Node 22 LTS, CodeQL, and Docker builds.

---

## Phase 2: Carefold Autonomy Milestones Phase1–Phase6 (`AU-01`–`AU-81`) (Completed — Q4 2026)

- [x] **Milestone Phase1 (`AU-01`–`AU-20`): Control Loop, Envelope Keyring Vault & Multi-Profile Identity**:
  - Multi-user & household care profiles (`users`, `sessions`, `profiles`, `profile_access`, `profile_consents`, `viewer_invites`) with fail-closed RBAC (`owner`, `caregiver`, `viewer`) and Mode L / Mode S deployment tiers (`ADR 0006`).
  - 4-tier tool execution policy gate (`read`, `write_local`, `write_external`, `irreversible`) across `A0`–`A2` autonomy levels, monotone taint propagation (`UntrustedResult`), and single-use `Approval` tokens (`ADR 0004`).
  - Per-profile cryptographic envelope encryption (`profile_keys`, `HKDF-SHA256` AES-256-GCM DEKs, `ADR 0005`) with deterministic crypto-shredding (`Titan S2`).
- [x] **Milestone Phase2 (`AU-21`–`AU-27`): Hybrid SearchIndex, Document Intelligence & Partitioned CAS**:
  - Per-profile Content-Addressed Storage (`attachments`, `profile_attachments`) eliminating cross-tenant deduplication side-channels (`ADR 0007`).
  - Hybrid retrieval (`chunks`, `chunks_fts` BM25 + `chunks_vec` `sqlite-vec` float32 embeddings with Reciprocal Rank Fusion `RRF` and Maximal Marginal Relevance `MMR`) and 3-tier memory consolidation (`working` $\rightarrow$ `episodic` $\rightarrow$ `semantic`).
- [x] **Milestone Phase3 (`AU-28`–`AU-40`): Clinical Organizer, Preventive Care & Health Imports**:
  - HL7 FHIR R4 clinical repository (`health_resources`), `appointments`, `reminders`, USPSTF/CDC/ACIP `preventive_records` engine, pediatric `school_forms` autofill, PHI-sanitized web search, and idempotent `import_batches` (Apple Health XML, C-CDA XML, FHIR R4 Bundles, CSV vitals).
- [x] **Milestone Phase4 (`AU-51`–`AU-56`): Scoped Connector SDK (`libs/connectors`) & v1 Starter Connectors**:
  - OAuth 2.0 PKCE (`S256`) broker, granular `consent_grants` matrix (`connector × profile × category × purpose`), `ScopedHttp` egress allowlisting, and starter connectors (`withings`, `google-calendar`, `caldav`, `epic-smart`).
- [x] **Milestone Phase5 (`AU-57`–`AU-63`): Remote MCP Pinning, Routines, School ICS & iOS Companion**:
  - Curated `gmail-mcp` (`gmail_search_messages`, `gmail_get_thread`, `gmail_send_message`), `mcp_tool_pins` SHA-256 schema drift protection (`Titan S7`), standing `routines`, `email_drafts`, `school_ics_feeds`, and iOS HealthKit companion pairing (`companion_devices`).
- [x] **Milestone Phase6 (`AU-64`–`AU-65`, `AU-70`–`AU-81`): Coordinated v2 Connectors, Stateless Relay, Audit Hash Chain & Compliance Packs**:
  - Stateless PKCE OAuth callback bounce relay (`ADR 0008`), v2 connectors (`oracle-health`, `athenahealth`, `cms-blue-button`, `oura`, `google-health`, `microsoft-graph`, `zocdoc` / SMART Scheduling Links), offline RFC 7515 JWS-verified SMART Health Cards (`.smart-health-card`), SHA-256 `audit_events` hash chain, local cross-encoder reranker, Android Health Connect companion, signed `.carefold` packaging (`carefold.packaging`), and compliance packs (`docs/compliance/`).

---

## Phase 3: End-to-End Internationalization (`ADR 0009`) & WCAG AA UI Polish (Completed — Batch 8, v0.4.0)

- [x] **5-Layer Standards-Driven Internationalization (`ADR 0009`, `#151`)**:
  - IETF BCP 47 locale validation (`en-US`, `es-ES`, `fr-FR`, `hi-IN`, `ar-SA`) and RFC 4647 quality-weighted locale negotiation (`Profile.preferred_locale` $\triangleright$ `User.preferred_locale` $\triangleright$ `Accept-Language` $\triangleright$ `en-US`).
  - UTF-8 + Unicode UAX #15 `NFC` canonical normalization (`0010_i18n_and_locale_storage`) across `notes`, `attachments`, `health_resources`, and `ClinicalChunker`.
  - Language-neutral HL7 FHIR R4 coding (`LOINC`, `SNOMED CT`, `RxNorm`, `CVX`, `ICD-10-CM`) paired with ICU MessageFormat translation catalogs, localized non-clinical disclaimers, multilingual acute red-flag detection, ECMAScript `Intl` formatters, and bidirectional (`LTR`/`RTL`) layout mirroring via W3C CSS Logical Properties.
- [x] **WCAG 2.1 AA Accessibility, Brand Identity & Consultation UI Polish (`#171`–`#183`)**:
  - Unified Carefold SVG brand identity (`CarefoldLogo`, `logo.svg`, `icon.svg`, `favicon.svg`, `manifest.json`) (`#183`).
  - Responsive mobile top bar & navigation drawer (`#171`, `#174`), inline agent switches (`#172`), sticky consultation disclaimer & header hierarchy (`#173`, `#178`), consolidated attachment dropzone (`#175`), keyboard-accessible tabs (`#176`), first-visit onboarding banner (`#177`), dark-mode WCAG AA contrast & error boundaries (`#179`, `#182`), settings search & dirty-state badge (`#180`), and runtime status retry controls (`#181`).

---

## Phase 4: Spector Cognitive Memory Server & Decentralized P2P Agent Store (2027 Roadmap)

- [ ] **Spector MCP Server Adapter**:
  - Concrete `SpectorMemoryAdapter` connecting Carefold to Spector's distributed memory server over Model Context Protocol (MCP).
- [ ] **Clinician Verification & Review Badges**:
  - Community peer-review system allowing board-certified clinicians to audit agent prompts and attach verifiable attestation badges.
- [ ] **Distributed Registry & Offline P2P Distribution**:
  - Decentralized agent repository enabling hospitals and community health workers to pull updates in air-gapped or low-bandwidth environments.
- [ ] **Multimodal Ingestion**:
  - Local DICOM imaging viewer integration with bounding-box region notes.
  - Ambient clinical audio transcript ingestion and SOAP note structuring.

