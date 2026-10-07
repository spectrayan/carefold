# Changelog

All notable changes to the Carefold project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Render Extracted Dossiers as Readable Visit-Prep & Insurance Cards (Web)** (`#94`):
  - Created `DossierCard` router component in `apps/web/src/components/chat/DossierCard.tsx` parsing `extract_document_dossier` tool results and dispatching to typed cards while safely falling back (returning null) on malformed or unknown payloads to preserve raw JSON traces in `ToolTraceCard` for full auditability.
  - Implemented `VisitPrepCard` in `apps/web/src/components/chat/VisitPrepCard.tsx` rendering reason for visit, physician instructions, follow-up timeline badge, interactive questions checklist with checkbox toggle, strikethrough styling, custom question addition, and client-side Copy/Export actions.
  - Implemented `InsuranceBenefitsCard` in `apps/web/src/components/chat/InsuranceBenefitsCard.tsx` rendering top financial metrics (annual deductible, out-of-pocket maximum, coinsurance), structured copays breakdown table, in/out-of-network rules callout, prior-authorization requirement pills, and Copy/Export actions.
  - Implemented `GenericDossierCard` in `apps/web/src/components/chat/GenericDossierCard.tsx` rendering document executive summary, key extracted numerical metrics grid, identified document sections list, and Copy/Export actions.
  - Displayed mandatory patient-friendly safety disclaimer banner on EVERY card: *"Extracted from your document. Check details with your care team or insurer."* with zero diagnostic language.
  - Created `apps/web/src/lib/checklistStorage.ts` persisting checklist states and custom questions in `localStorage` under `carefold_checklist_${threadId}_${messageId}`.
  - Integrated `DossierCard` into `apps/web/src/components/ChatMessageItem.tsx` below assistant messages while maintaining collapsible `ToolTraceCard` in `embedded-tool-traces`.
  - Added shared TypeScript interfaces in `apps/web/src/lib/types.ts` for all extracted dossier models and checklist states.
  - Added comprehensive automated Vitest test suite in `apps/web/tests/components/dossier-card.test.tsx` verifying all three card types, fallback on malformed payloads, checklist interactivity and persistence, copy/export triggers, and non-clinical disclaimer enforcement.
- **Unified Start Script & Non-Conflicting Default Ports (:8010, :3010) (DX)** (`#144`):
  - Created unified coordinator script `scripts/start.sh` (with root symlink `start.sh`) coordinating FastAPI backend and Next.js web application.
  - Added support for subcommands `all` (default foreground coordinator with SIGINT/SIGTERM trap cleanup), `start` / `daemon` (detached background with PID tracking in `.carefold.pids`), `stop` (clean termination of child PIDs and port listeners), `status` (colorized table showing ports, status, URLs), `backend` (foreground backend only), `web` (foreground web only), and `help`.
  - Configured non-conflicting default ports: Backend on `:8010` (overridable via `CAREFOLD_BACKEND_PORT` / `PORT`), Web UI on `:3010` (overridable via `CAREFOLD_WEB_PORT` / `PORT`).
  - Updated `backend/src/carefold/constants/defaults.py` to set `DEFAULT_PORT = 8010` and expanded `DEFAULT_CORS_ORIGINS` to support ports `3000`, `3010`, `8000`, and `8010` on localhost and loopback.
  - Updated `backend/src/carefold/main.py` `run()` to honor `CAREFOLD_BACKEND_PORT` / `PORT` and `CAREFOLD_BACKEND_HOST` / `HOST` environment overrides.
  - Added root `package.json` script `"start": "bash scripts/start.sh"` and updated `"dev:backend"` to `--port 8010`.
  - Updated `apps/web/package.json` `"dev"` and `"start"` scripts to `--port 3010`.
  - Updated fallback backend URL across 11 route files in `apps/web/src/app/**` (13 occurrences) from `:8000` to `:8010`.
  - Added `.carefold.pids` to `.gitignore`.
  - Added dedicated automated unit tests in `backend/tests/test_start_script.py` and updated `backend/tests/test_resource_loader.py`.
- **Conversation History Sidebar: List, Resume, Rename and Delete Past Sessions (Web)** (`#93`):
  - Created storage index utility module `apps/web/src/lib/sessionHistory.ts` managing `carefold_threads_index_v1` in `localStorage` with automated migration of legacy `carefold_msgs_*` threads, LRU pruning (up to 50 sessions), and cross-tab/event synchronization.
  - Implemented Next.js route handler proxy `apps/web/src/app/api/chat/threads/[id]/route.ts` with strict alphanumeric slug validation forwarding `GET /api/chat/threads/[id]` to the LangGraph execution backend checkpoint store.
  - Implemented responsive, accessible `SessionHistorySidebar` component in `apps/web/src/components/chat/SessionHistorySidebar.tsx` with collapsible desktop rail, mobile drawer overlay, inline keyboard/button renaming (Enter/Escape/Save/Cancel), and safe delete confirmation alert dialog (`role="alertdialog"`, `aria-modal="true"`).
  - Integrated history sidebar toggle button (`data-testid="history-sidebar-toggle"`), atomic session switching without cross-thread contamination, message upsertion, and delete event handling into `apps/web/src/app/chat/ChatClient.tsx`.
  - Added comprehensive automated unit, route proxy, component, and end-to-end integration test suites across `apps/web/tests/lib/session-history.test.ts`, `apps/web/tests/lib/threads-proxy-route.test.ts`, `apps/web/tests/components/session-history-sidebar.test.tsx`, and `apps/web/tests/components/chat-session-history-integration.test.tsx`.
- **Data-Driven Marketplace Filters: Real Domains, Care Stages & Caregivers (Web)** (`#88`):
  - Created proxy route `apps/web/src/app/api/agents/categories/route.ts` proxying `GET /api/agents/categories` to the backend with 503 fallback error handling.
  - Updated `apps/web/src/app/page.tsx` to fetch installed agents and category taxonomy in parallel via `Promise.all` and forward `initialCategories` to `MarketplaceClient`.
  - Implemented data-driven domain pills in `apps/web/src/app/MarketplaceClient.tsx` dynamically pruning domains with 0 matching agents (`Therapy`, `Education` hidden on bundled workspace), with seamless offline fallback deriving active domains directly from `initialAgents`.
  - Added "When" care-stage filter pills (`data-testid="care-stage-filters"`): `All Stages`, `Before visit` (`pre_visit`), `During visit` (`during_visit`), `After visit` (`post_visit`), `Follow-up` (`follow_up`), and `Daily living` (`daily_living`).
  - Added accessible "For caregivers" toggle switch (`data-testid="caregiver-filter"`, `role="switch"`, `aria-checked`) filtering agents by `target_audience.includes('caregiver')`.
  - Implemented multi-facet conjunction filtering combining search keywords, domain, risk class, care stage, and caregiver criteria via boolean AND.
  - Enhanced agent cards with caregiver badges (`data-testid="caregiver-badge"`) and formatted care stage badges (`data-testid="care-stage-badge"`).
  - Added accessible empty-state UI with "Clear all filters" button (`data-testid="clear-all-filters-btn"`) resetting all active filters.
  - Implemented `formatCareStage` helper in `apps/web/src/lib/utils.ts`.
  - Added automated test coverage in `apps/web/tests/components/marketplace-filters.test.tsx` and `apps/web/tests/lib/categories-proxy-route.test.ts`, and updated `apps/web/tests/adversarial/marketplace-adversarial.test.tsx`.
- **Markdown & JSON Dossier Export in Consultation Header (Web)** (`#34`):
  - Added `DossierExportMenu` component in `apps/web/src/components/chat/DossierExportMenu.tsx` positioned in the consultation header adjacent to the New Session button.
  - Implemented pure client-side export utilities in `apps/web/src/lib/dossierExport.ts` (`formatDossierMarkdown`, `formatDossierJson`, `generateDossierFilename`, `downloadBlob`, `exportDossier`) with 0 network roundtrips.
  - Prepended mandatory non-clinical safety disclaimer banner to both Markdown and JSON exports per `AGENTS.md` §1.1.
  - Enforced data minimization and privacy invariants: stripped internal tool traces (`toolTraces`, `traces`) and binary attachment buffers from exports.
  - Adhered to standard filename pattern: `carefold-<agent-id>-prep-<YYYY-MM-DD>.md` / `.json`.
  - Added full keyboard accessibility (Escape key dismissal, focus restoration) and click-outside dismissal with disabled states when the transcript is empty or actively streaming.
  - Added comprehensive automated test coverage in `apps/web/tests/lib/dossier-export.test.ts` and `apps/web/tests/components/dossier-export.test.tsx`.
- **Privacy & Browser Data Settings: Delete Conversations and Stored API Keys** (`#92`):
  - Added dedicated "Privacy & Browser Data" section in `apps/web/src/components/SettingsModal.tsx` showing stored conversation count, estimated storage footprint, and saved API keys status.
  - Implemented storage utility functions in `apps/web/src/lib/settings.ts` (`getBrowserStorageSummary`, `formatStorageSize`, `deleteCurrentConversation`, `deleteAllConversations`, and `clearStoredApiKeys`).
  - Added accessible confirmation dialog (`role="alertdialog"`, `aria-modal="true"`, focus trap on Cancel, Escape dismissal) for destructive actions (deleting current conversation, clearing all conversations, and removing saved API keys).
  - Ensured data isolation: deleting conversations wipes `carefold_msgs_*` and `carefold_thread_*` without affecting UI theme, clinical consents, or non-secret provider settings; clearing API keys resets credentials while preserving endpoints, provider selection, and model names.
  - Added event-driven synchronization in `apps/web/src/app/chat/ChatClient.tsx` (`carefold:conversations-cleared`, `carefold:conversation-deleted`) to immediately reset the active conversation and abort streaming without requiring page refresh.
  - Displayed explicit disclaimer in UI and confirmation dialogs clarifying that operations clear browser data only and Carefold stores no data on remote servers.
  - Added comprehensive automated test suite in `apps/web/tests/components/settings-modal.test.tsx` verifying metrics display, confirmation cancellation, safe deletion, key clearing, and keyboard accessibility.
- **Responsive Mobile Navigation Drawer in Navbar (Web)** (`#89`):
  - Added responsive hamburger menu toggle button (`data-testid="mobile-menu-toggle"`, `sm:hidden`) in `apps/web/src/components/Navbar.tsx` below `sm` breakpoint (< 640px) with accessible ARIA attributes (`aria-expanded`, `aria-controls="mobile-navigation"`, `aria-label="Toggle navigation menu"`).
  - Implemented collapsible mobile navigation panel (`id="mobile-navigation"`, `data-testid="mobile-navigation"`) rendering `Marketplace` and `Chat` route links with WCAG-compliant touch targets (`min-h-[44px]`).
  - Added auto-close on navigation link clicks, route changes (`pathname`), window resize to `>= 640px`, and `Escape` key press with focus restoration to toggle button and focus trap loop.
  - Added automated test suite `apps/web/tests/components/navbar.test.tsx` asserting all disclosure interactions, keyboard navigation, and desktop layout preservation.
- **Skip-to-Content Link & Plain-Language Agent Selector Labels (Web)** (`#91`):
  - Added accessible, visually-hidden-until-focused "Skip to main content" bypass link in `apps/web/src/app/layout.tsx` targeting `<main id="main-content" tabIndex={-1}>` (WCAG 2.1 AA SC 2.4.1).
  - Implemented centralized `formatRiskClass` (with aliases `formatRiskLabel` and `formatRiskClassLabel`) in `apps/web/src/lib/utils.ts` mapping internal risk tokens (`clinical_assist`, `wellness`, `admin`, `education`) to plain-language, patient-friendly labels.
  - Updated chat agent dropdown in `apps/web/src/app/chat/ChatClient.tsx` to render plain risk labels in `<option>` text, added `<label htmlFor="agent-selector" className="sr-only">Select health agent</label>`, `id="agent-selector"`, `aria-label="Select health agent"`, and `aria-describedby="agent-selector-description"`.
  - Reused `formatRiskClass` across `apps/web/src/app/MarketplaceClient.tsx` and `apps/web/src/app/agents/[id]/AgentDetailClient.tsx` risk badges to eliminate raw snake_case tokens across user-facing views.
- **Expanded Emergency Red-Flag Golden Test Cases in Safety Suite** (`#36`):
  - Expanded `evals/safety.golden.jsonl` from 20 to 43 verified test cases conforming to the `EvalCase` schema, covering acute emergency red flags across stroke (BE FAST signs), cardiovascular, respiratory, anaphylaxis, pediatric emergencies, diabetic ketoacidosis (DKA), suicidal crisis, severe hemorrhage, and malignant hypertension, alongside benign educational and wellness controls.
  - Added automated test suite `backend/tests/test_evals_safety_golden.py` validating dataset integrity, schema conformity, clinical category distribution, 100% emergency recall, 0% false positives on benign controls, and clean offline evaluation runner execution (`run_safety_suite`).
- **Provider-Aware Data Residency Indicator & Dynamic Privacy Copy (Web)** (`#85`):
  - Added fail-closed loopback host resolution (`isLoopbackHost`, `isLocalProvider`, `getProviderPrivacyState`) in `apps/web/src/lib/settings.ts` validating `localhost`, `127.0.0.0/8`, and IPv6 loopback (`::1`) while classifying LAN/WAN endpoints, remote hosts, and unparseable URLs as remote/cloud.
  - Replaced legacy Ollama pill in `Navbar.tsx` with reactive provider-aware status button (`data-testid="provider-status-badge"`), emerald on-device badge, amber cloud/remote badge, and accessible privacy explainer popover with quick-switch action to local Ollama.
  - Replaced hardcoded empty-state text in `ChatClient.tsx` with dynamic privacy copy that respects active provider residency and suppresses on-device claims when cloud or remote providers are selected.
  - Added client component `FooterPrivacyNotice.tsx` in `apps/web/src/app/layout.tsx` to dynamically render footer privacy copy synchronized via `carefold:settings-changed`.
- **Dedicated Emergency Escalation Card for Red-Flag Refusals (Web & Backend)** (`#86`):
  - Added accessible, high-contrast `EmergencyEscalationCard` component rendered upon acute emergency red-flag refusals (`role="alert"`, assertive live region, auto-focus).
  - Prominent emergency header ("This may be an emergency"), direct click-to-call action (`tel:911`), emergency room directory link (Google Maps), and 988 Suicide & Crisis Lifeline link (`tel:988`) for crisis indicators.
  - Displays verbatim acute referral message emitted by the backend safety guardrail while maintaining non-clinical boundary disclaimer and keeping composer unlocked for continuing the session.
  - Isolated emergency contact numbers in `apps/web/src/lib/emergency.ts` (`EmergencyServicesConfig`) for multi-region localization.
  - Enhanced backend `AgentExecutionService.format_refusal_event` and `builder.py` to forward verbatim refusal messages and emergency category metadata via SSE.
- **Clinical-Consent Gate for `clinical_assist` Agents (Web)** (`#87`):
  - Per-agent consent dialog covering what the agent can help with, its `forbidden` list in plain language, and emergency guidance (911 / 988), with an explicit acknowledgement step.
  - Consent persisted only in browser storage (`carefold_clinical_consent_v1`, with grant timestamp); "Clinical assist: consent given" chip in the chat header; withdraw per agent or all agents in Settings.
  - Agent detail pages show a read-only summary until consent is given.
  - `GET /api/agents` summaries now include each agent's `forbidden` list.

### Fixed
- **Accurate specialist agent and skill pack counts in GET /api/health** (`#71`): Filtered out underscore-prefixed directories (`_system`, `_template`) in backend health workspace statistics to report accurate counts (22 specialists, 24 skills) aligned with the specialist agent catalog, skill packs, and web health route.
- **Docker Compose environment variable alignment** (`#69`): Aligned `docker/docker-compose.yml` with backend Pydantic settings by renaming `OLLAMA_URL` to `CAREFOLD_OLLAMA_URL` (defaulting to `http://ollama:11434/v1`), switching `backend` to `CAREFOLD_WORKSPACE_ROOT=/app`, adding `CAREFOLD_WORKSPACE=/app` on `web`, and replacing unused `CAREFOLD_DATA` with `CAREFOLD_AUDIT_LOG_PATH` pointing to the persistent `/data` volume.
- **Sanitize memory deletion logging against CRLF log injection** (`#125`): Neutralized CodeQL `py/log-injection` (CWE-117) alerts by stripping carriage return (`\r`) and newline (`\n`) characters from user-controlled `key` and `namespace` parameters prior to interpolation in `carefold/api/memory.py` error logs via new `sanitize_log_value` utility in `carefold.logging`.
- **Web client no longer sends `allow_clinical=true` without user consent** (`#87`): `ChatClient.tsx`, the agent detail page, and the `/api/agents`, `/api/agents/[id]`, and `/api/chat` proxy routes previously hard-coded or defaulted consent to `true`. They now send the stored user decision and default to `false`; `/api/chat` no longer treats truthy non-boolean values (e.g. `"false"`) as consent.

### Planned
- Native Spector MCP server memory adapter.
- HL7 FHIR bundle generation from visit preparation dossiers.
- Offline P2P distributed agent registry.

---

## [0.4.0-beta.1] - 2026-10-04

### Added
- **Multi-Architecture Container Support (`linux/amd64`, `linux/arm64`)**:
  - Configured QEMU and Docker Buildx across `.github/workflows/release.yml` and `.github/workflows/docker-publish.yml` to produce dual-architecture container images.
  - Native image execution on Apple Silicon (ARM64) and Linux x86_64 without platform emulation flags (`#108`).
- **Carefold Governance Teams & CODEOWNERS Alignment**:
  - Provisioned 10 official Carefold governance teams in the `@spectrayan` GitHub organization (`carefold`, `carefold-maintainers`, `carefold-maintainers-backend`, `carefold-maintainers-frontend`, `carefold-maintainers-packages`, `carefold-clinical-ai`, `carefold-infra`, `carefold-docs`, `carefold-committers`, `carefold-security`) per `GOVERNANCE.md` (`#109`).
  - Added automated idempotent team provisioning script (`scripts/provision-carefold-teams.sh`).
  - Bound all repository paths in `.github/CODEOWNERS` directly to `@spectrayan/ai-engineering`, `@sbharatjoshi`, and specialized subsystem maintainer teams.
- **Vascular Specialist Agent (`vascular-guide`) & Skill Pack (`vascular-prep`)**:
  - Added specialist clinical agent for vascular health visit preparation, arterial/venous screening checklists, and peripheral artery disease context (`#105`).
- **CSV & TSV Structured Attachment Ingestion**:
  - Added formatted table representations and numerical column extraction for tabular lab and billing attachments (`#104`).

### Fixed
- **Container Entrypoint & Packaging Resources**:
  - Corrected Next.js binary path (`/app/apps/web/node_modules/.bin/next start`) and POSIX signal trap handling (`INT TERM`) in `docker/Dockerfile`.
  - Added package data declaration in `backend/pyproject.toml` so runtime safety assets (`red_flags.json`) are bundled inside container builds.
- **Host Networking & Ollama URL Auto-Detection**:
  - Added standard `OLLAMA_URL` environment variable support across backend runtime settings and model resolvers.
  - Documented Docker Desktop host networking (`http://host.docker.internal:11434/v1`).
- **Web Health Check & Navigation Status Badge**:
  - Proxied `/api/health` from Next.js web application to FastAPI backend health status and environment variables, resolving the false "Ollama: Offline" status indicator in the top navbar.
- **Soft Boundary Audit Event Schema & Stream Error Guarding**:
  - Added `"boundary_warning"` to `AuditEventType` literal in `backend/src/carefold/schemas/audit.py`, eliminating Pydantic `ValidationError` upon stream turn completion.
  - Guarded audit log writes in `AgentExecutionService` with defensive `try...except` exception logging to prevent audit logging failures from interrupting active SSE streams.

---

## [0.3.0-beta.1] - 2026-10-02

### Added
- **Automated Release Pipeline (`.github/workflows/release.yml`)**:
  - Full end-to-end release automation supporting git tag triggers (`v*`) and manual `workflow_dispatch`.
  - Quality verification gates: Apache-2.0 license check, pytest suite, 47-attack security penetration tests, web typecheck, vitest component tests, Next.js production build, CLI and runner tests.
  - Multi-target Docker container publishing to GitHub Container Registry (`ghcr.io/spectrayan/carefold`): `all-in-one`, `backend`, and `web` images with GHA caching.
  - Automated GitHub Release generation with changelog notes extraction and pre-release flagging.
- **LangGraph Deep Agents Architecture & 3-Tier Progressive Disclosure (ADR-0003)**:
  - Decomposed 22 specialist agent manifests into runtime contracts (`agent.yaml`), slim persona definitions (`persona_slim.md`), and catalog descriptors (`metadata.yaml`).
  - Standardized all 23 skill packs under Agent Skills specification `SKILL.md` YAML frontmatter with strict risk classification and tool declaration.
  - Reduced baseline agent system prompt token overhead by >60% via on-demand skill reading and native YAML loading.
- **Clinical Safety Middleware & Consent Gate**:
  - `ClinicalSafetyMiddleware` enforcing closed tool sandbox (`PHASE_0_REGISTRY`) and automatic thread elevation to `clinical_assist`.
  - Explicit clinical consent protocol (`allow_clinical=True`) across backend API and frontend consultation client (`ChatClient.tsx`).
- **Autonomous Agent Manifest (`AGENTS.md`)**: Full specification adherence defining operational boundaries, tool privileges, and AI coding agent guidelines.
- **Living Project Context (`PROJECT_CONTEXT.md`)**: Spector-grade architectural specification capturing hexagonal ports, 4 cognitive memory tiers, and execution pipelines.
- **Open-Source Governance & Community Suite**:
  - `CONTRIBUTING.md` with Conventional Commits, DCO requirements, and test gates.
  - `GOVERNANCE.md` detailing meritocratic maintainer model and decision-making workflows.
  - `CODE_OF_CONDUCT.md` adopting Contributor Covenant v2.1.
  - `SECURITY.md` establishing Coordinated Vulnerability Disclosure SLAs and clinical safety reporting.
  - `ROADMAP.md` covering multi-phase evolution from local core to decentralized agent store.
  - `.github/CODEOWNERS`, `.github/pull_request_template.md`, and issue templates for bugs, features, and clinical agent proposals.
- **Licensing & Attribution Automation**:
  - Root `NOTICE` file complying with Spector attribution standards.
  - Automated license check and fix tooling (`scripts/licenses.mjs`, `pnpm check:licenses`, `pnpm fix:licenses`).
  - Spectrayan Apache-2.0 copyright headers applied across 417 source files.
- **CI/CD Quality Matrix**:
  - Unified multi-job GitHub Actions CI (`.github/workflows/ci.yml`) covering Python (3.12, 3.14), Node (20, 22), penetration security, and license enforcement.
  - GitHub CodeQL static analysis (`codeql.yml`), automated license remediation (`license-fix.yml`), MkDocs Pages deployment (`docs.yml`), and multi-stage Docker build workflow (`docker-publish.yml`).
- **Verified MkDocs Material Portal & Living ADRs**:
  - Modern documentation site configured with search, dark/light theme, and code annotations.
  - Living Architecture Decision Records in `docs/adr/` featuring Mermaid diagrams for the 5-phase orchestrator lifecycle and hexagonal memory ports.

### Changed
- Replaced legacy "Phase 0" branding in Next.js web UI with "Open Source" badge and "Local Secure Sandbox".
- Updated web footer to `Carefold • Healthcare AI Agent Marketplace • Apache-2.0`.

### Removed
- Cleaned 9 obsolete planning documents from `docs/` (`00-README.md` through `06-backlog-index.md`, `orchestrator_redesign.md`).

---

## [0.2.0] - 2026-09-15

### Added
- **Hexagonal Cognitive Memory Architecture**:
  - Abstract `MemoryPort` supporting 4 cognitive tiers (`WORKING`, `EPISODIC`, `SEMANTIC`, `PROCEDURAL`).
  - Abstract `CatalogPort` for specialist agent and skill indexing and category hierarchy generation.
  - High-performance asynchronous `SqliteMemoryAdapter` and `SqliteCatalogAdapter` using SQLite FTS5 and BM25 relevance scoring.
- **Two-Hop Intent Routing & Orchestrator Node**:
  - Tier-1 broad domain classification followed by Tier-2 specialist manifest resolution.
  - Dynamic skill and reference document provisioning to prevent context window bloat.
- **Expanded Specialist Catalog & Skill Packs**:
  - 22 specialist clinical organ navigators and administrative guides.
  - 23 clinical skill packs with evidence-based medical guidelines and 3-line intended-use statements.
- **Dual Ingestion & Structured Extraction Pipeline**:
  - Dual invocation via user file upload or in-turn tool call `extract_document_dossier`.
  - HIPAA-aligned regex PII sanitization.
  - Pydantic models for `InsuranceBenefitsDossier`, `ClinicalVisitDossier`, and `GenericDocumentDossier`.
  - Numerical grounding validator preventing hallucinated currencies and lab numbers.
- **Security Penetration Test Suite**:
  - 47 automated security tests verifying path traversal prevention, symlink protection, null-byte blocking, and skill authorization barriers.

### Changed
- Refactored monolithic agent execution engine into class-based LangGraph nodes under `carefold.workflows.nodes`.
- Streamlined `AgentState` schema to support subgraphs, dossiers, tool traces, and refusal metadata.

### Fixed
- Addressed path traversal vulnerability in attachment file reading.
- Resolved race condition during SQLite checkpointer initialization.

---

## [0.1.0] - 2026-08-01

### Added
- Initial local-first healthcare AI prototype with FastAPI backend and LangGraph execution engine.
- Next.js 15 Tailwind CSS consultation chat UI with model and provider selection.
- Local sandboxed attachment storage in `attachments/`.
- Foundational `visit-steward` and `benefits-guide` agent manifests.
- Basic streaming responses using Server-Sent Events (SSE).
