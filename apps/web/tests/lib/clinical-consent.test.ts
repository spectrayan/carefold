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

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  CLINICAL_CONSENT_CHANGED_EVENT,
  CLINICAL_CONSENT_STORAGE_KEY,
  describeForbiddenIntent,
  grantClinicalConsent,
  hasClinicalConsent,
  loadClinicalConsents,
  requiresClinicalConsent,
  withdrawAllClinicalConsents,
  withdrawClinicalConsent
} from '@/lib/clinicalConsent';

describe('clinicalConsent store', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('only clinical_assist requires consent', () => {
    expect(requiresClinicalConsent('clinical_assist')).toBe(true);
    expect(requiresClinicalConsent(' Clinical_Assist ')).toBe(true);
    expect(requiresClinicalConsent('wellness')).toBe(false);
    expect(requiresClinicalConsent('admin')).toBe(false);
    expect(requiresClinicalConsent('education')).toBe(false);
    expect(requiresClinicalConsent(undefined)).toBe(false);
  });

  it('has no consent by default', () => {
    expect(hasClinicalConsent('cardiology-guide')).toBe(false);
    expect(loadClinicalConsents()).toEqual({});
  });

  it('grants consent per agent with a timestamp', () => {
    const now = new Date('2026-10-05T12:00:00.000Z');
    const record = grantClinicalConsent('cardiology-guide', now);

    expect(record).toEqual({ grantedAt: '2026-10-05T12:00:00.000Z' });
    expect(hasClinicalConsent('cardiology-guide')).toBe(true);
    expect(hasClinicalConsent('neurology-guide')).toBe(false);

    const stored = JSON.parse(localStorage.getItem(CLINICAL_CONSENT_STORAGE_KEY) || '{}');
    expect(stored['cardiology-guide'].grantedAt).toBe('2026-10-05T12:00:00.000Z');
  });

  it('withdraws consent for a single agent and for all agents', () => {
    grantClinicalConsent('cardiology-guide');
    grantClinicalConsent('neurology-guide');

    withdrawClinicalConsent('cardiology-guide');
    expect(hasClinicalConsent('cardiology-guide')).toBe(false);
    expect(hasClinicalConsent('neurology-guide')).toBe(true);

    withdrawAllClinicalConsents();
    expect(hasClinicalConsent('neurology-guide')).toBe(false);
    expect(localStorage.getItem(CLINICAL_CONSENT_STORAGE_KEY)).toBeNull();
  });

  it('dispatches a change event on grant and withdraw', () => {
    const listener = vi.fn();
    window.addEventListener(CLINICAL_CONSENT_CHANGED_EVENT, listener);
    grantClinicalConsent('cardiology-guide');
    withdrawClinicalConsent('cardiology-guide');
    window.removeEventListener(CLINICAL_CONSENT_CHANGED_EVENT, listener);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it('rejects invalid agent ids', () => {
    expect(grantClinicalConsent('../etc/passwd')).toBeNull();
    expect(hasClinicalConsent('../etc/passwd')).toBe(false);
    expect(hasClinicalConsent('')).toBe(false);
    expect(hasClinicalConsent(null)).toBe(false);
  });

  it('fails closed on malformed or tampered storage', () => {
    localStorage.setItem(CLINICAL_CONSENT_STORAGE_KEY, 'not-json');
    expect(hasClinicalConsent('cardiology-guide')).toBe(false);

    localStorage.setItem(CLINICAL_CONSENT_STORAGE_KEY, JSON.stringify(['cardiology-guide']));
    expect(hasClinicalConsent('cardiology-guide')).toBe(false);

    localStorage.setItem(
      CLINICAL_CONSENT_STORAGE_KEY,
      JSON.stringify({
        'cardiology-guide': true,
        'neurology-guide': { grantedAt: 'not-a-date' },
        '../bad': { grantedAt: '2026-10-05T12:00:00.000Z' },
        'derma-guide': { grantedAt: '2026-10-05T12:00:00.000Z' }
      })
    );
    expect(Object.keys(loadClinicalConsents())).toEqual(['derma-guide']);
  });

  it('describes forbidden intents in plain language', () => {
    expect(describeForbiddenIntent('diagnose')).toMatch(/Diagnose a condition/);
    expect(describeForbiddenIntent('replace_emergency_care')).toMatch(/emergency/i);
    expect(describeForbiddenIntent('custom_intent_key')).toBe('Custom intent key.');
  });
});
