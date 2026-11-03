# Agent Manifest Specification

Every agent in Carefold is defined by an `agent.yaml` manifest and an accompanying `persona.md` file residing in its dedicated directory under `agents/<agent_id>/`.

This specification formalizes the `AgentManifest` Pydantic model defined in `backend/src/carefold/schemas/manifest.py`.

---

## Directory Layout

Each agent directory contains:

```
agents/heart-care-coordinator/
├── agent.yaml      # Structured metadata, taxonomy, declared skills, and tool permissions
└── persona.md      # Pure clinical persona, empathy instructions, and interview protocols
```

---

## Manifest Schema (`agent.yaml`)

### Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | `str` | Yes | Unique kebab-case identifier (e.g., `heart-care-coordinator`). |
| `title` | `str` | Yes | Human-readable display name (e.g., `Cardiology Guide`). |
| `version` | `str` | Yes | Semantic version string (e.g., `0.1.0`). |
| `domain` | `str` | Yes | High-level taxonomy domain: `clinical`, `therapy`, `wellness`, `navigation`, or `education`. |
| `category` | `str` | Yes | Dot-notated hierarchical category path (e.g., `clinical.cardiology`). |
| `risk_class` | `str` | Yes | Safety risk class: `wellness`, `admin`, `education`, or `clinical_assist`. |
| `care_stages` | `List[str]` | Yes | Applicable patient stages: `pre_visit`, `post_visit`, `chronic_care`, `triage`. |
| `target_audience` | `str` | Yes | Primary user: `patient`, `caregiver`, or `provider`. |
| `tags` | `List[str]` | No | Keywords for full-text search and marketplace filtering. |
| `icon` | `str` | No | Icon name for web UI display (e.g., `heart-pulse`). |
| `maturity` | `str` | No | Lifecycle status: `experimental`, `candidate`, `production`. |
| `model` | `Optional[str]` | No | Optional LLM override. If omitted, uses global default model (`llama3.2`). |
| `can_delegate` | `bool` | No | Whether this agent may request delegation to peer specialists (default `true`). |
| `max_iterations` | `int` | No | Maximum tool loop iterations (default `3`, clamped to `1..10`). |
| `description` | `str` | Yes | Multi-sentence summary of capabilities and patient benefits. |
| `hidden` | `bool` | No | If `true`, hides agent from public marketplace listings (used for `_system` agents). |
| `skills` | `List[str]` | Yes | Array of declared skill IDs (e.g., `["cardiology-prep", "clinical-safety-boundaries"]`). |
| `tools` | `List[str]` | Yes | Array of permitted sandboxed tool IDs (e.g., `["skill-docs", "workspace-note"]`). |
| `forbidden` | `List[str]` | No | Array of forbidden intent tokens (e.g., `["diagnose", "prescribe", "dose"]`). |

---

## Annotated Example: `heart-care-coordinator/agent.yaml`

```yaml
id: heart-care-coordinator
title: Cardiology Guide
version: 0.1.0
domain: clinical
category: clinical.cardiology
risk_class: clinical_assist
care_stages:
  - pre_visit
  - chronic_care
target_audience: patient
tags:
  - cardiology
  - heart
  - hypertension
  - blood-pressure
  - arrhythmias
icon: heart-pulse
maturity: production
can_delegate: true
max_iterations: 3
description: >
  Empathetic cardiovascular companion helping patients prepare for cardiology
  consultations, organize blood pressure logs, and track heart health symptoms.
skills:
  - cardiology-prep
  - clinical-safety-boundaries
tools:
  - skill-docs
  - workspace-note
forbidden:
  - diagnose
  - prescribe
  - dose
  - replace_emergency_care
  - instruct_stop_medication
```

---

## Persona Specification (`persona.md`)

The `persona.md` document provides the clinical tone, empathy framework, patient interview steps, and organ-specific safety boundaries.

Under Carefold's **Persona Purity Contract**, personas must never contain:
- Filesystem paths (e.g., `skills/cardiology-prep/references/...`).
- Low-level tool invocation JSON or function calling syntax.
- Hardcoded references to tool registries.

### Example Persona Structure (`heart-care-coordinator/persona.md`):

```markdown
# Role & Clinical Scope
You are the Carefold Cardiology Guide, an empathetic, non-diagnostic cardiovascular
health navigator. Your mission is to help patients prepare for visits with cardiologists,
clarify cardiovascular terminology, and systematically organize symptom logs.

# Empathy & Communication Framework
- Adopt a calm, reassuring, and active-listening bedside tone.
- Validate patient anxieties regarding cardiovascular symptoms without offering false reassurance.
- Use clear, patient-friendly language, translating complex medical jargon (e.g., "hypertension" -> "high blood pressure").

# Consultation Methodology
1. Inquire about the primary reason for consultation preparation.
2. Review relevant vital signs (blood pressure, pulse rate) if already recorded.
3. Structure questions to ask the cardiologist at the upcoming visit.

# Emergency Red Flags (Immediate Referral)
If the patient reports crushing or squeezing chest pain, pain radiating to the left arm or jaw,
shortness of breath with chest tightness, or sudden unexplained fainting:
- Immediately direct the patient to dial 911 or visit the nearest emergency room.
- Do not continue routine consultation steps.
```
