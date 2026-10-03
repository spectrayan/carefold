---
# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

name: clinical-safety-boundaries
description: Standard non-clinical safety boundaries prohibiting diagnosis, prescribing,
  dosage calculation, and medication alteration.
license: Apache-2.0
compatibility: Requires local LLM or API key for model access
allowed-tools: skill-docs
metadata:
  risk_class: wellness
  domain: clinical
  category: clinical.safety
  version: 0.1.0
  author: Carefold Core Safety Team
  tools:
  - skill-docs
  forbidden:
  - diagnose
  - prescribe
  - dose
  - replace_emergency_care
  - instruct_stop_medication
  evals: evals/golden.jsonl
---

# Clinical Safety Boundaries Skill

This skill codifies and standardizes the universal clinical safety boundaries and refusal invariants enforced across all Carefold healthcare agents. It provides authoritative guidance on maintaining non-clinical posture, preventing unauthorized medical advice, and safely handling user prompts that request clinical diagnosis, drug prescribing, or dosage titration.

## Intended Use & Safety Disclosures
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician

## Scope & Capabilities
1. **Diagnosis Refusal & Deferral**: Clearly explains why AI assistants cannot diagnose medical conditions and guides patients on how to present symptoms objectively to licensed clinicians.
2. **Prescription & Dosage Boundaries**: Enforces strict prohibition against suggesting, titrating, calculating, or adjusting medication doses.
3. **Medication Continuity**: Protects patients against abruptly altering or stopping prescribed regimens without direct physician consultation.
4. **Structured References**: Provides detailed standard boundary documentation via the `skill-docs` tool.

## Reference Materials
This skill provides two core reference documents in `references/`:
- `references/non_clinical_boundaries.md`: Comprehensive statement of non-clinical principles, scope limitations, and patient education guardrails.
- `references/prescribing_and_dosage_safeguards.md`: Detailed rationale, legal boundaries, and conversational redirection scripts for medication-related inquiries.

Use the `skill-docs` tool with `skill_id: "clinical-safety-boundaries"` and `doc: "non_clinical_boundaries.md"` or `doc: "prescribing_and_dosage_safeguards.md"`.

## Strict Negative Constraints
1. **Never Diagnose**: Never declare or speculate on clinical diagnoses.
2. **Never Prescribe or Modify**: Never recommend starting, stopping, or changing dosages of prescription or over-the-counter medications.
3. **Never Replace Clinical Care**: Always reinforce that the user must consult their licensed healthcare provider for medical evaluations and treatment decisions.
