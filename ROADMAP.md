# Carefold Product Roadmap

The Carefold roadmap outlines the architectural and community milestones driving the evolution of our local-first healthcare AI runtime and decentralized agent marketplace.

---

## Strategic Phases

```
┌───────────────────────────┐      ┌───────────────────────────┐      ┌───────────────────────────┐      ┌───────────────────────────┐
│   Phase 0: Core Sandbox   │ ──►  │ Phase 1: Hexagonal & Org  │ ──►  │  Phase 2: Spector Memory  │ ──►  │ Phase 3: Agent Store & P2P│
│        (Completed)        │      │    (Current — v0.3.0)     │      │        (Q1–Q2 2027)       │      │        (Q3–Q4 2027)       │
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

## Phase 1: Clinical Expansion & Hexagonal Architecture (Current — v0.3.0)

- [x] **Agent & Skill Scalability**:
  - Expanded specialist catalog to 22 clinical organ navigators and administrative guides.
  - Authored 23 verified clinical and navigation skill packs with evidence-based references.
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

## Phase 2: Spector Cognitive Memory Integration (Q1–Q2 2027)

- [ ] **Spector MCP Server Adapter**:
  - Concrete `SpectorMemoryAdapter` connecting Carefold to Spector's high-performance memory server over Model Context Protocol (MCP).
- [ ] **Cross-Session Cognitive Consolidation**:
  - Background memory consolidation moving salient episodic interactions into semantic user profiles.
  - Temporal decay modeling with exponential forgetting curves and reinforcement triggers.
- [ ] **Healthcare Knowledge Graph**:
  - Graph-based memory modeling for chronic condition tracking, medications, and care team rosters.
- [ ] **FHIR / CDA Export**:
  - Generation of standard HL7 FHIR (Fast Healthcare Interoperability Resources) JSON bundles from clinical visit preparation dossiers.

---

## Phase 3: Decentralized Agent Marketplace & Store (Q3–Q4 2027)

- [ ] **Signed Agent Packages (`.carefold`)**:
  - Cryptographically signed agent manifests with Ed25519 publisher signatures.
  - Immutable content addressing for verified skill packs.
- [ ] **Clinician Verification & Review Badges**:
  - Community peer-review system allowing board-certified clinicians to audit agent prompts and attach verifiable attestation badges.
- [ ] **Distributed Registry & Offline P2P Distribution**:
  - Decentralized agent repository enabling hospitals and community health workers to pull updates in air-gapped or low-bandwidth environments.
- [ ] **Multimodal Ingestion**:
  - Local DICOM imaging viewer integration with bounding-box region notes.
  - Ambient clinical audio transcript ingestion and SOAP note structuring.
