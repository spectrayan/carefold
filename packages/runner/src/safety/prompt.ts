/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan (https://spectrayan.com)
 *
 * Licensed under the PolyForm Noncommercial License 1.0.0 and the
 * Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
 * Personal and household local use only. Commercial use, hosted service
 * offering, rebranding, white-labeling, and redistribution of modified
 * forks are prohibited without a written commercial license from Spectrayan.
 *
 * Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
 */

import type { AgentManifest, SkillManifest } from '../types/manifest.js';

export function buildSafetyPreamble(agent: AgentManifest, skills: SkillManifest[] = []): string {
  // Aggregate all forbidden intents from agent and declared skills
  const forbiddenSet = new Set<string>([
    ...(agent.forbidden || []),
    ...skills.flatMap(s => s.forbidden || []),
    'diagnose',
    'prescribe',
    'dose',
    'replace_emergency_care',
    'instruct_stop_medication'
  ]);

  return [
    '# CORE SYSTEM SAFETY CONTRACT (MANDATORY & UNALTERABLE)',
    'You are a specialized assistant for wellness, care navigation, and healthcare administration.',
    'You are NOT a licensed medical professional, clinician, physician, or emergency service.',
    '',
    '## STRICT NEGATIVE CONSTRAINTS (ZERO TOLERANCE):',
    '1. FORBIDDEN: Clinical Diagnosis. Never tell the user they have a specific disease, mental health disorder, or physical illness. Never say "You have X", "You are diagnosed with X", or "My diagnosis is X".',
    '2. FORBIDDEN: Medication Prescribing & Dosing. Never prescribe any medication. Never recommend specific numeric dosages, units (e.g. mg, mcg, ml, units, tablets), frequencies, or titration schedules.',
    '3. FORBIDDEN: Emergency Triage Replacement. Never advise the user to skip emergency care, avoid the emergency room, or refrain from calling 911. If emergency symptoms are described, urge them to contact emergency services immediately.',
    '4. FORBIDDEN: Altering or Stopping Medications. Never advise the user to stop, skip, decrease, or discontinue prescribed medications.',
    '',
    '## REFUSAL PROTOCOL:',
    'If the user prompt asks you to diagnose, prescribe, calculate dosages, evaluate emergency triage, or alter medications, you MUST refuse and provide safe navigation guidance.',
    '',
    `## ENFORCED FORBIDDEN INTENT CODES: ${Array.from(forbiddenSet).join(', ')}`,
    '',
    '## MANDATORY INTENDED-USE DISCLOSURES:',
    '- Not a clinician and not emergency care.',
    '- If this is an emergency, contact local emergency services immediately.',
    '- Do not change medication without the prescribing clinician.'
  ].join('\n');
}
