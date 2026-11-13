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

<h1 align="center">Carefold</h1>

<p align="center">
  <strong>Local-First Personal & Family Health AI Companion & Specialist Runtime.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-PolyForm_Noncommercial_+_Additional_Terms-047857.svg?style=for-the-badge" alt="License" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12+-3776AB.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/Node.js-22_LTS-339933.svg?style=for-the-badge&logo=nodedotjs&logoColor=white" alt="Node" /></a>
  <a href="https://nextjs.org/"><img src="https://img.shields.io/badge/Next.js-16_Turbopack-000000.svg?style=for-the-badge&logo=nextdotjs&logoColor=white" alt="Next.js" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.115-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="deploy/docker/docker-compose.yml"><img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker Compose" /></a>
  <a href="https://github.com/spectrayan/carefold/actions"><img src="https://img.shields.io/github/actions/workflow/status/spectrayan/carefold/ci.yml?branch=main&style=for-the-badge" alt="Build" /></a>
  <a href="https://spectrayan.github.io/carefold/"><img src="https://img.shields.io/badge/Docs-MkDocs-blue?logo=materialformkdocs&style=for-the-badge" alt="Docs" /></a>
</p>

<p align="center">
  <em>"Great care starts with prepared patients and supported families. Carefold brings local-first AI to your household—helping you organize records, prepare thoughtful questions for your care team, and navigate coverage with clarity and privacy."</em>
</p>

---

**Carefold** is a source-available, local-first personal and family health AI companion and specialist agent runtime built on [`yarvelle-core`](https://github.com/yarvelle/yarvelle-core) and `@yarvelle/ui`. Designed to work alongside your doctors, care teams, and health plans, Carefold runs on your own hardware (or private household instance) to help you prepare for clinical visits, organize health records and physiological vitals across family members, track USPSTF/ACIP preventive screenings and pediatric school forms, and understand health insurance benefits.

It pairs a **5-phase LangGraph orchestration engine** with **25 specialist clinical, administrative, and wellness navigators**, **28 modular clinical skill packs**, multi-profile household care with per-profile AES-256-GCM envelope encryption, scoped health and calendar connectors (`Epic SMART on FHIR`, `Withings`, `Google Calendar`, `CalDAV`, `Google Workspace Gmail MCP`, `Microsoft 365 Graph`, `Apple Health`, `FHIR R4`, `C-CDA`, `SMART Health Cards`), multilingual support (`en-US`, `es-ES`, `fr-FR`, `hi-IN`, `ar-SA` with `RTL`), and a two-tier clinical safety guardrail system.

### 🖥️ Household Care Dashboard

<p align="center">
  <img src="docs/assets/screenshots/dashboard.png" alt="Carefold Household Care Dashboard" width="100%" />
</p>

<details>
  <summary>📸 <strong>Explore More Carefold Screens</strong> — Consultation Studio, Specialist Marketplace, Vitals & Biometrics, Clinical Visits, Preventive Care, Scoped Connectors, Household Profiles & Diagnostics (Click to expand)</summary>
  <br />

  <h4>1. Specialist Consultation Studio (Streaming SSE & Clinical Preparation Agenda)</h4>
  <p align="center">
    <img src="docs/assets/screenshots/chat-consultation.png" alt="Carefold Specialist Consultation Studio" width="100%" />
  </p>

  <h4>2. Specialist Agent Marketplace (25 Clinical, Insurance & Wellness Navigators)</h4>
  <p align="center">
    <img src="docs/assets/screenshots/agents-marketplace.png" alt="Carefold Specialist Agent Marketplace" width="100%" />
  </p>

  <h4>3. Specialist Agent Detail & Plain-Language Clinical Safety Boundaries</h4>
  <p align="center">
    <img src="docs/assets/screenshots/agent-detail.png" alt="Carefold Specialist Agent Detail" width="100%" />
  </p>

  <h4>4. Modular Clinical & Administrative Skills Catalog (28 Skill Packs)</h4>
  <p align="center">
    <img src="docs/assets/screenshots/skills-catalog.png" alt="Carefold Skills Catalog" width="100%" />
  </p>

  <h4>5. Vitals & Biometrics Tracker (FHIR R4 LOINC Observations & Diurnal BP Trends)</h4>
  <p align="center">
    <img src="docs/assets/screenshots/vitals-tracker.png" alt="Carefold Vitals & Biometrics Tracker" width="100%" />
  </p>

  <h4>6. Clinical Visits & Appointment Preparation Schedule</h4>
  <p align="center">
    <img src="docs/assets/screenshots/appointments-schedule.png" alt="Carefold Clinical Visits & Schedule" width="100%" />
  </p>

  <h4>7. Preventive Care Checklist (USPSTF / ACIP Guidelines) & Pediatric School Forms</h4>
  <p align="center">
    <img src="docs/assets/screenshots/preventive-care.png" alt="Carefold Preventive Care & School Forms" width="100%" />
  </p>

  <h4>8. Local Workspace Library (Sanitized Attachments & Visit Preparation Notes)</h4>
  <p align="center">
    <img src="docs/assets/screenshots/documents-library.png" alt="Carefold Documents & Notes Library" width="100%" />
  </p>

  <h4>9. Scoped External Data Connections, OAuth 2.0 PKCE & Consent Hub</h4>
  <p align="center">
    <img src="docs/assets/screenshots/scoped-connections.png" alt="Carefold Scoped External Connections Hub" width="100%" />
  </p>

  <h4>10. Family & Household Care Profiles</h4>
  <p align="center">
    <img src="docs/assets/screenshots/family-profiles.png" alt="Carefold Family & Household Profiles" width="100%" />
  </p>

  <h4>11. Tamper-Evident Activity & Safety Audit Log</h4>
  <p align="center">
    <img src="docs/assets/screenshots/activity-audit-log.png" alt="Carefold Activity & Safety Audit Log" width="100%" />
  </p>

  <h4>12. Runtime Health & Setup Diagnostics</h4>
  <p align="center">
    <img src="docs/assets/screenshots/settings-diagnostics.png" alt="Carefold System Health & Diagnostics" width="100%" />
  </p>
</details>

---

## ⚡ 30-Second Quickstart

Get a local Carefold runtime and household companion running in seconds:


### 1. Instant Launch via Prebuilt Docker Container
Run Carefold with a single command using the published multi-architecture image (supports Apple Silicon `arm64` and Intel/AMD `amd64` automatically):

```bash
# Pull and start the all-in-one container (Next.js UI on :3000, FastAPI backend on :8000)
docker pull ghcr.io/spectrayan/carefold:latest

# Run container (connecting to local Ollama on your host machine)
docker run -d \
  --name carefold \
  -p 127.0.0.1:3000:3000 \
  -p 127.0.0.1:8000:8000 \
  -e OLLAMA_URL=http://host.docker.internal:11434/v1 \
  -v carefold-data:/data \
  ghcr.io/spectrayan/carefold:latest
```
Visit `http://localhost:3000` to browse specialist helpers and launch private household consultations.

> [!TIP]
> - **Connecting to Ollama on host**: On Docker Desktop (macOS / Windows), use `-e OLLAMA_URL=http://host.docker.internal:11434/v1` so the container can reach your host machine's Ollama instance.
> - **Legacy tags on Apple Silicon**: If pulling older single-architecture tags (e.g. `0.3.0-beta.1`), append `--platform linux/amd64` to `docker pull` and `docker run`.

### 2. Launch via Docker Compose (Build from Source)

To build and run the entire stack locally:

```bash
# 1. Set up the environment variables
cp deploy/docker/.env.example deploy/docker/.env
echo "CAREFOLD_VAULT_KEK=$(openssl rand -hex 32)" >> deploy/docker/.env

# 2. Start the stack
docker compose up -d

# 3. (Optional) Start with local Ollama AI
docker compose --profile local-ai up -d
```

### 3. Local Monorepo Development

**Prerequisites**: Python 3.12+ (tested on 3.12 and 3.14), Node.js 22 LTS, and `pnpm` (>=9.0.0).

```bash
# Clone repository
git clone https://github.com/spectrayan/carefold.git
cd carefold

# Install frontend and workspace dependencies
pnpm install

# Set up backend virtual environment
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -e "backend[dev]"
pip install -r backend/requirements-dev.txt

# Option A: Start both backend (:8010) and Next.js UI (:3010) with the unified launcher
./start.sh

# Option B: Run in separate terminals
# Terminal 1 — FastAPI Backend (:8010)
PYTHONPATH=backend/src backend/.venv/bin/uvicorn carefold.main:app --host 127.0.0.1 --port 8010 --reload

# Terminal 2 — Next.js Web UI (:3010)
pnpm --filter @spectrayan/carefold-web dev
```
Visit `http://localhost:3010` to open the Carefold Web UI.

---

## 🏥 Specialist Agent Topology (25 Specialists & 28 Skills)

Carefold features a modular catalog of **25 specialist clinical, administrative, and wellness navigators** backed by **28 clinical and administrative skill packs**, organized into three core domains:

- **Clinical Organ & Specialty Navigators (`clinical_assist` — 18 Specialists)**: Dedicated navigators for Cardiology (`heart-care-coordinator`), Pulmonology (`lung-breathing-coordinator`), Gastroenterology (`digestive-care-coordinator`), Oncology (`cancer-care-coordinator`), Neurology (`brain-nerve-care-coordinator`), Nephrology (`kidney-care-coordinator`), Dermatology (`skin-care-coordinator`), Endocrinology (`diabetes-thyroid-coordinator`), Orthopedics (`bone-joint-care-coordinator`), Rheumatology (`autoimmune-care-coordinator`), Urology (`bladder-pelvic-care-coordinator`), ENT (`ent-care-coordinator`), Ophthalmology (`eye-care-coordinator`), Hematology (`blood-care-coordinator`), Podiatry (`foot-care-coordinator`), Vascular Medicine (`circulation-vein-care-coordinator`), Oral Health (`dental-care-coordinator`), and General Visit Preparation (`appointment-prep-coordinator`). Each specialist helps you organize symptoms, review lab trends and vital signs, and prepare clear, prioritized questions to discuss with your clinician.
- **Administrative & Insurance Stewards (`admin` — 5 Specialists)**: Stewards for Health Insurance Benefits & Coverage explanation (`benefits-coordinator`), Prior Authorization preparation (`prior-authorization-coordinator`), Claims & Denials Appeals (`claims-appeals-coordinator`), Prescription Drug Formularies (`prescription-cost-coordinator`), and Multi-Provider Medical Records coordination (`records-coordinator`).
- **Wellness & Nutrition Companions (`wellness` — 2 Specialists)**: Daily companions for chronic care routines, hydration, and sleep check-ins (`habit-coordinator`) plus evidence-based dietary pattern planning and medical nutrition therapy visit preparation (`nutrition-coordinator`).

### Exploring Available Agents

You can explore, search, and interact with all specialist agents through:
- **Web Consultation Studio**: Launch the web app (`./start.sh` or `pnpm dev:web` at `http://localhost:3010`) to browse and chat with any specialist helper.
- **Living Documentation Catalog**: Read [`docs/agents/catalog.md`](docs/agents/catalog.md) for detailed descriptions, taxonomy classifications, and key capabilities.
- **Carefold CLI & API**: Run `carefold agent list` or query `GET /api/v1/agents` to inspect the runtime catalog programmatically.

### System Infrastructure Agents (`agents/_system`)
* **`orchestrator`**: Two-hop intent classification, dynamic skill provisioning, and multi-topology dispatch.
* **`document-extractor`**: Ingestion sandbox, PII sanitization, structured Pydantic extraction, and numerical grounding validation.
* **`quality-reviewer`**: Clinical safety boundary audit, tone inspection, and persona alignment verification.
* **`triage-auditor`**: Compliance logging, risk tagging, and clinical safety telemetry.
* **`skill-generator`**: Synthesis of dynamic skill manifests and validation templates from clinical guidelines.
* **`suggestion-generator`**: Context-aware follow-up suggestion chips presented in the client UI.

---

## 🧠 Cognitive Memory, Hybrid Retrieval & Household Isolation

Carefold implements a hexagonal architecture for memory, search, and household data isolation on top of `yarvelle-core`:

* **Per-Profile Household Scoping & Envelope Encryption**: Every family member profile (`Self`, `Child`, `Parent`, `Spouse`) is isolated at the database, Content-Addressed Storage (`CAS`), and cryptographic levels using per-profile `HKDF-SHA256` / `AES-256-GCM` Data Encryption Keys (`ADR-0005`, `ADR-0007`).
* **`MemoryPort` & 3-Tier Consolidation**: Cognitive memory interface supporting working, episodic, and semantic memory tiers with salience ranking and decay (`ADR-0002`).
* **Hybrid `SearchIndex`**: Combines SQLite `FTS5` lexical BM25 search with `sqlite-vec` dense embeddings, Reciprocal Rank Fusion (`RRF`), and Maximal Marginal Relevance (`MMR`).
* **End-to-End Internationalization (`ADR-0009`)**: Supports `en-US`, `es-ES`, `fr-FR`, `hi-IN`, and `ar-SA` (`RTL`) with IETF BCP 47 locale negotiation, Unicode UAX #15 `NFC` canonical storage normalization, HL7 FHIR R4 language-neutral clinical coding, and localized safety disclaimers.

---

## 🛡️ Two-Tier Clinical Safety, Policy Gates & Sandboxed Security

Carefold enforces strict safety invariants to protect families and ensure non-clinical boundaries:

### 1. Two-Tier Clinical Boundary System
* **Tier 1 (Multilingual Emergency Red Flags)**: Instant termination with `911`/`988`/`112` emergency escalation when acute symptoms are detected across supported languages (e.g., crushing chest pain, acute stroke FAST symptoms, anaphylaxis, severe respiratory distress, or active self-harm crisis).
* **Tier 2 (Collaborative Clinical Preparation)**: Helps patients organize questions and records for their licensed healthcare providers while never diagnosing conditions, prescribing medications, or adjusting dosages.

### 2. Four-Tier Policy Gate & Zero-Trust Sandbox (`ADR-0004`)
* **4-Tier Tool Execution Gate**: Classifies every tool into `read`, `write_local`, `write_external`, or `irreversible` across user-selectable autonomy levels (`A0` Manual, `A1` Assisted, `A2` Routine) with monotone taint tracking (`UntrustedResult`) and SHA-256 hash-chained `audit_events`.
* **Path Traversal & Symlink Shield**: Strict lexical normalization and containment checks preventing `../` traversal, null bytes, and symlink escapes across `attachments/` and `workspace/notes/`.
* **47-Attack Penetration Test Suite**: Automated security verification covering path traversal, command injection, symlink overwrites, and unauthorized skill access.

---

## 🚀 Quality Gates & Verification Matrix

Carefold maintains rigorous verification standards across all code changes:

```bash
# 1. Spectrayan License Header Check
pnpm run check:licenses

# 2. Backend Pytest Suite
PYTHONPATH=backend/src backend/.venv/bin/pytest backend/tests/

# 3. Security Penetration Suite (47 Attack Vectors)
PYTHONPATH=backend/src backend/.venv/bin/python backend/tests/penetration_suite.py

# 4. Frontend Typecheck
pnpm --filter @spectrayan/carefold-web typecheck

# 5. Frontend Unit & Component Tests
pnpm --filter @spectrayan/carefold-web test --exclude "**/api/**"

# 6. Frontend Production Build
pnpm --filter @spectrayan/carefold-web build
```

---

## 📜 Architecture Decision Records (ADRs)

Carefold documents all major architectural decisions in [`docs/adr/`](docs/adr/):
* [ADR 0001: Orchestrator-Driven Agent Architecture](docs/adr/0001-orchestrator-driven-agent-architecture.md)
* [ADR 0002: Hexagonal Memory and Catalog Ports](docs/adr/0002-hexagonal-memory-and-catalog-ports.md)
* [ADR 0003: Progressive Disclosure & Skill Context Management](docs/adr/0003-progressive-disclosure-skill-context-management.md)
* [ADR 0004: Policy Approvals & Resume](docs/adr/0004-policy-approvals-and-resume.md)
* [ADR 0005: Vault Threat Model & Per-Profile Envelope Encryption](docs/adr/0005-vault-threat-model-and-kek-sources.md)
* [ADR 0006: Deployment Modes & Requirement Tiers (Mode L vs Mode S)](docs/adr/0006-deployment-modes-and-requirement-tiers.md)
* [ADR 0007: Content-Addressed Storage & Hybrid Search Index](docs/adr/0007-content-addressed-storage-and-hybrid-search.md)
* [ADR 0008: Stateless OAuth 2.0 PKCE Bounce Relay & Scoped Connectors](docs/adr/0008-oauth-relay-and-stateless-callback.md)
* [ADR 0009: End-to-End Internationalization & Multilingual Architecture](docs/adr/0009-internationalization-and-multilingual-architecture.md)

---

## 👥 Contributors

Thank you to all the contributors who help build and improve Carefold!

<p align="left">
  <a href="https://github.com/spectrayan/carefold/graphs/contributors">
    <img src="https://contrib.rocks/image?repo=spectrayan/carefold" alt="Carefold Contributors" />
  </a>
</p>

---

## 📄 License, Personal/Household Terms & Trademarks

Carefold is **source-available** software licensed under the **[PolyForm Noncommercial License 1.0.0](LICENSE)** together with the **[Carefold Additional Terms](ADDITIONAL-TERMS.md)** and the **[Carefold Trademark Policy](TRADEMARKS.md)**:

- **Permitted (Free Personal & Household Local Use)**: You may install, run, study, and modify Carefold for **personal and family use** on your own local hardware or private household instance, and contribute improvements back to the official repository under the **[Carefold Individual CLA](CLA.md)**.
- **Prohibited Without a Commercial License**: Selling, reselling, offering Carefold as a hosted service (SaaS/API/portal), deploying inside any business or healthcare organization, **rebranding or white-labeling**, removing Carefold/Spectrayan attribution, or redistributing modified forks outside your household is strictly prohibited.
- **Commercial Licensing**: For commercial, clinical, enterprise, or OEM licensing inquiries, contact `licensing@spectrayan.com`.

See [`LICENSE`](LICENSE), [`ADDITIONAL-TERMS.md`](ADDITIONAL-TERMS.md), [`TRADEMARKS.md`](TRADEMARKS.md), [`CLA.md`](CLA.md), and [`NOTICE`](NOTICE) for full terms.

Required Notice: Copyright © 2026 Spectrayan (https://spectrayan.com). All rights reserved.
