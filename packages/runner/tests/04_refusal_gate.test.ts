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

import { describe, it, expect } from 'vitest';
import {
  checkSafetyRefusal,
  SAFE_REFUSAL_TEMPLATE,
  buildSafetyPreamble
} from '../src/safety/index.js';
import type { AgentManifest, SkillManifest } from '../src/types/manifest.js';

describe('Safety Refusal Gate & Output Classifier', () => {
  it('triggers refusal for clinical diagnostic assertions', () => {
    const inputs = [
      'Based on what you described, you have ADHD.',
      'You are diagnosed with hypertension.',
      'This rash indicates you have shingles.',
      'My diagnosis is that you have diabetes.',
      'You clearly have anxiety disorder.'
    ];

    for (const text of inputs) {
      const result = checkSafetyRefusal(text);
      expect(result.refused).toBe(true);
      expect(result.reason).toBe('forbidden_intent:diagnose');
      expect(result.safeResponse).toBe(SAFE_REFUSAL_TEMPLATE);
    }
  });

  it('triggers refusal for prescription and dosage recommendations', () => {
    const inputs = [
      'Take 500mg of amoxicillin twice daily.',
      'You should increase your dosage to 40mg.',
      'Take 2 pills before sleeping.',
      'The recommended dosage of ibuprofen is 800mg every 6 hours.',
      'I prescribe you some antibiotics.'
    ];

    for (const text of inputs) {
      const result = checkSafetyRefusal(text);
      expect(result.refused).toBe(true);
      expect(result.reason).toBe('forbidden_intent:dose');
      expect(result.safeResponse).toBe(SAFE_REFUSAL_TEMPLATE);
    }
  });

  it('triggers refusal for emergency care replacement or evasion', () => {
    const inputs = [
      "Don't call 911, just drink some herbal tea.",
      'Skip the emergency room, it is just a panic attack.',
      'Avoid urgent care and see if it passes tomorrow.',
      'You do not need to go to the hospital.'
    ];

    for (const text of inputs) {
      const result = checkSafetyRefusal(text);
      expect(result.refused).toBe(true);
      expect(result.reason).toBe('forbidden_intent:replace_emergency_care');
      expect(result.safeResponse).toBe(SAFE_REFUSAL_TEMPLATE);
    }
  });

  it('triggers refusal for instructing user to stop or alter medication', () => {
    const inputs = [
      'Stop taking your insulin immediately.',
      'Discontinue your antidepressants right now.',
      'Quit taking your heart medication.',
      'Taper off your medication without a doctor.'
    ];

    for (const text of inputs) {
      const result = checkSafetyRefusal(text);
      expect(result.refused).toBe(true);
      expect(result.reason).toBe('forbidden_intent:instruct_stop_medication');
      expect(result.safeResponse).toBe(SAFE_REFUSAL_TEMPLATE);
    }
  });

  it('allows benign wellness and navigation responses', () => {
    const inputs = [
      'Here are 3 questions you might want to bring up with your therapist.',
      'Your benefits plan states a $25 copay for office visits.',
      'Would you like to log your water intake for today?',
      'Preparation checklist: make sure to note when symptoms first appeared.'
    ];

    for (const text of inputs) {
      const result = checkSafetyRefusal(text);
      expect(result.refused).toBe(false);
      expect(result.safeResponse).toBeUndefined();
    }
  });

  it('does not trigger false positive when model issues a standard refusal or disclaimer', () => {
    const inputs = [
      'I cannot diagnose whether you have ADHD. Only a doctor or licensed clinician can diagnose conditions.',
      'I am unable to recommend a dose of amoxicillin. Please consult your physician.',
      SAFE_REFUSAL_TEMPLATE
    ];

    for (const text of inputs) {
      const result = checkSafetyRefusal(text);
      expect(result.refused).toBe(false);
    }
  });

  it('builds system safety preamble with forbidden intents and mandatory disclosures', () => {
    const agent: AgentManifest = {
      id: 'visit-steward',
      title: 'Visit Steward',
      version: '0.1.0',
      risk_class: 'wellness',
      skills: ['visit-prep'],
      tools: ['workspace-note'],
      forbidden: ['custom_forbidden'],
      persona: 'Instructions'
    };

    const skill: SkillManifest = {
      id: 'visit-prep',
      name: 'visit-prep',
      description: 'Visit prep',
      version: '0.1.0',
      risk_class: 'wellness',
      forbidden: ['skill_forbidden']
    };

    const preamble = buildSafetyPreamble(agent, [skill]);
    expect(preamble).toContain('CORE SYSTEM SAFETY CONTRACT');
    expect(preamble).toContain('diagnose');
    expect(preamble).toContain('dose');
    expect(preamble).toContain('replace_emergency_care');
    expect(preamble).toContain('instruct_stop_medication');
    expect(preamble).toContain('custom_forbidden');
    expect(preamble).toContain('skill_forbidden');
    expect(preamble).toContain('Not a clinician and not emergency care');
    expect(preamble).toContain('Do not change medication without the prescribing clinician');
  });
});
