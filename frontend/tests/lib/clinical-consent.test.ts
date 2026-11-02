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
    expect(hasClinicalConsent('heart-care-coordinator')).toBe(false);
    expect(loadClinicalConsents()).toEqual({});
  });

  it('grants consent per agent with a timestamp', () => {
    const now = new Date('2026-10-05T12:00:00.000Z');
    const record = grantClinicalConsent('heart-care-coordinator', now);

    expect(record).toEqual({ grantedAt: '2026-10-05T12:00:00.000Z' });
    expect(hasClinicalConsent('heart-care-coordinator')).toBe(true);
    expect(hasClinicalConsent('brain-nerve-care-coordinator')).toBe(false);

    const stored = JSON.parse(localStorage.getItem(CLINICAL_CONSENT_STORAGE_KEY) || '{}');
    expect(stored['heart-care-coordinator'].grantedAt).toBe('2026-10-05T12:00:00.000Z');
  });

  it('withdraws consent for a single agent and for all agents', () => {
    grantClinicalConsent('heart-care-coordinator');
    grantClinicalConsent('brain-nerve-care-coordinator');

    withdrawClinicalConsent('heart-care-coordinator');
    expect(hasClinicalConsent('heart-care-coordinator')).toBe(false);
    expect(hasClinicalConsent('brain-nerve-care-coordinator')).toBe(true);

    withdrawAllClinicalConsents();
    expect(hasClinicalConsent('brain-nerve-care-coordinator')).toBe(false);
    expect(localStorage.getItem(CLINICAL_CONSENT_STORAGE_KEY)).toBeNull();
  });

  it('dispatches a change event on grant and withdraw', () => {
    const listener = vi.fn();
    window.addEventListener(CLINICAL_CONSENT_CHANGED_EVENT, listener);
    grantClinicalConsent('heart-care-coordinator');
    withdrawClinicalConsent('heart-care-coordinator');
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
    expect(hasClinicalConsent('heart-care-coordinator')).toBe(false);

    localStorage.setItem(CLINICAL_CONSENT_STORAGE_KEY, JSON.stringify(['heart-care-coordinator']));
    expect(hasClinicalConsent('heart-care-coordinator')).toBe(false);

    localStorage.setItem(
      CLINICAL_CONSENT_STORAGE_KEY,
      JSON.stringify({
        'heart-care-coordinator': true,
        'brain-nerve-care-coordinator': { grantedAt: 'not-a-date' },
        '../bad': { grantedAt: '2026-10-05T12:00:00.000Z' },
        'skin-care-coordinator': { grantedAt: '2026-10-05T12:00:00.000Z' }
      })
    );
    expect(Object.keys(loadClinicalConsents())).toEqual(['skin-care-coordinator']);
  });

  it('describes forbidden intents in plain language', () => {
    expect(describeForbiddenIntent('diagnose')).toMatch(/Diagnose a condition/);
    expect(describeForbiddenIntent('replace_emergency_care')).toMatch(/emergency/i);
    expect(describeForbiddenIntent('custom_intent_key')).toBe('Custom intent key.');
  });
});
