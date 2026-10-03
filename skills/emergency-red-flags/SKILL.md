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

name: emergency-red-flags
description: Standard emergency escalation protocols and acute clinical symptom red
  flags requiring immediate 911 / ER referral.
license: Apache-2.0
compatibility: Requires local LLM or API key for model access
allowed-tools: skill-docs
metadata:
  risk_class: wellness
  domain: clinical
  category: clinical.emergency
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

# Emergency Red Flags Protocol Skill

This skill standardizes acute clinical red-flag detection and emergency escalation across the Carefold agent ecosystem. When users describe acute, unstable, or life-threatening symptoms, agents must immediately halt routine dialogue and direct the individual to emergency medical services.

## Intended Use & Safety Disclosures
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician

## Scope & Capabilities
1. **System-Specific Red Flag Directory**: Catalogs acute cardiovascular, pulmonary, neurological, abdominal, allergic, and surgical emergencies.
2. **Immediate Diversion Protocol**: Provides standardized, clear language instructing users to contact 911 or seek urgent emergency medical attention.
3. **De-escalation of Delaying Behaviors**: Advises users against waiting for regular office hours or attempting home self-treatment when emergency indicators are present.
4. **Structured References**: Provides comprehensive multi-system emergency reference documentation via `skill-docs`.

## Reference Materials
This skill provides two core reference documents in `references/`:
- `references/acute_red_flags_directory.md`: Multi-system classification of life-threatening signs and symptoms across cardiovascular, respiratory, neurologic, and trauma domains.
- `references/emergency_escalation_protocol.md`: Immediate patient diversion protocol, 911 referral scripts, and critical escalation guidelines.

Use the `skill-docs` tool with `skill_id: "emergency-red-flags"` and `doc: "acute_red_flags_directory.md"` or `doc: "emergency_escalation_protocol.md"`.

## Strict Negative Constraints
1. **Never Triage Down**: Never reassure a user who presents with red-flag emergency symptoms that they can safely wait.
2. **Never Suggest Home Remedies for Crises**: Never suggest resting, drinking fluids, or home remedies when acute emergency symptoms are active.
3. **Always Prioritize Emergency Activation**: Emergency referral must take absolute precedence over routine agenda drafting or record analysis.
