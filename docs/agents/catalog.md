# Specialist Agent Catalog

Carefold includes a living catalog of **20 specialized healthcare agents** organized into clinical organ navigators and administrative stewards, alongside the community agent starter template (`_template`) and 6 internal system agents (representing 22 total workspace agent directories under `agents/` as reported by `GET /api/health`).

Each agent operates within strict non-clinical boundaries, empowering patients with appointment preparation agendas, communication checklists, symptom tracking templates, and insurance navigation guides.

!!! info "Risk Classification & Clinical Consent Gating"
    Specialist navigators (including `visit-steward`) are classified `clinical_assist`. Before chatting with one, the web client asks for explicit, per-agent consent and only then sends `allow_clinical: true`; consent is stored in the browser and can be withdrawn in Settings. `wellness`, `admin`, and `education` agents are never gated. See [Safety Boundaries](../safety/boundaries.md#clinical-consent-gate).

---

## Organ-Specific Clinical Navigators (13 Agents)

These agents specialize in organ systems and medical subspecialties. They help patients track symptoms, prepare agendas for specialist appointments, and formulate collaborative questions for their physicians. In the local sandbox, all navigators declare their dedicated prep skill and have access to attachment reading, authorized skill references, and workspace note taking.

| Agent ID | Title | Category | Declared Skills | Permitted Tools | Risk Class |
|---|---|---|---|---|---|
| `cardiology-guide` | Cardiology Navigator | `clinical.cardiology` | `cardiology-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `derma-guide` | Dermatology Navigator | `clinical.dermatology` | `derma-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `endocrinology-guide` | Endocrinology Navigator | `clinical.endocrinology` | `endocrinology-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `ent-guide` | ENT Navigator | `clinical.ent` | `ent-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `eye-guide` | Ophthalmology Navigator | `clinical.ophthalmology` | `vision-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `gastro-guide` | Gastroenterology Navigator | `clinical.gastroenterology` | `gastro-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `nephrology-guide` | Nephrology Navigator | `clinical.nephrology` | `nephrology-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `neurology-guide` | Neurology Navigator | `clinical.neurology` | `neurology-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `oncology-navigator` | Oncology Care Steward | `clinical.oncology` | `oncology-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `ortho-guide` | Orthopedics Navigator | `clinical.orthopedics` | `ortho-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `pulmonology-guide` | Pulmonology Navigator | `clinical.pulmonology` | `pulmonology-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `rheuma-guide` | Rheumatology Navigator | `clinical.rheumatology` | `rheuma-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |
| `urology-guide` | Urology Navigator | `clinical.urology` | `urology-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |

---

## Administrative Stewards & Companions (7 Agents)

Administrative stewards assist patients in navigating healthcare bureaucracy, insurance policies, medical records, and daily habits.

| Agent ID | Title | Category | Declared Skills | Permitted Tools | Risk Class |
|---|---|---|---|---|---|
| `benefits-guide` | Benefits Guide | `navigation.insurance` | `benefits-explainer` | `attach-read`, `skill-docs` | `admin` |
| `claims-appeals-guide` | Claims & Appeals Steward | `navigation.claims` | `claims-appeals-prep` | `attach-read`, `skill-docs`, `workspace-note` | `admin` |
| `formulary-guide` | Prescription & Formulary Guide | `navigation.formulary` | `formulary-navigation` | `attach-read`, `skill-docs`, `workspace-note` | `admin` |
| `habit-companion` | Habit Companion | `wellness.habits` | `habit-checkin` | `workspace-note` | `wellness` |
| `prior-auth-navigator` | Prior Authorization Navigator | `navigation.prior_auth` | `prior-auth-prep` | `attach-read`, `skill-docs`, `workspace-note` | `admin` |
| `records-coordinator` | Medical Records Coordinator | `navigation.records` | `records-management` | `attach-read`, `skill-docs`, `workspace-note` | `admin` |
| `visit-steward` | Visit Steward | `navigation.appointments` | `visit-prep` | `attach-read`, `skill-docs`, `workspace-note` | `wellness` |

---

## Community Starter Template (1 Agent)

Carefold provides a starter template for community contributors authoring new agents:

| Agent ID | Title | Category | Declared Skills | Permitted Tools | Risk Class |
|---|---|---|---|---|---|
| `_template` | Template Agent | `wellness.template` | `_template` | *(None)* | `wellness` |

---

## Internal System Agents (`agents/_system/`)

Carefold maintains six internal agents that execute core pipeline tasks:

| Agent ID | Role & Responsibility |
|---|---|
| `orchestrator` | Coordinates two-hop intent classification, execution topology planning, and specialist dispatch. |
| `document-extractor` | Securely ingests user attachments, redacts PII, and extracts structured dossiers. |
| `quality-reviewer` | Evaluates synthesized responses for clinical safety compliance and tone neutrality. |
| `skill-generator` | Dynamically synthesizes in-memory skills or reference documents when undeclared protocols are needed. |
| `suggestion-generator` | Generates 2–3 contextual follow-up question chips based on consultation turns. |
| `triage-auditor` | Fallback routing auditor, risk tagging, and structured zero-body audit event writer. |
