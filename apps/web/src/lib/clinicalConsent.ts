/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * Clinical-assist consent store.
 *
 * The backend refuses to describe or execute `clinical_assist` agents unless the
 * request carries `allow_clinical=true`. This module is the single client-side
 * source of truth for that flag: consent is granted per agent by the user through
 * the consent dialog, persisted in browser localStorage (never sent anywhere
 * else), and read at request time so that withdrawing consent takes effect on the
 * very next request.
 */

export const CLINICAL_CONSENT_STORAGE_KEY = 'carefold_clinical_consent_v1';

/** DOM event dispatched on `window` whenever consent is granted or withdrawn. */
export const CLINICAL_CONSENT_CHANGED_EVENT = 'carefold:clinical-consent-changed';

export const CLINICAL_ASSIST_RISK_CLASS = 'clinical_assist';

export interface ClinicalConsentRecord {
  /** ISO 8601 timestamp of when the user granted consent. */
  grantedAt: string;
}

export type ClinicalConsentMap = Record<string, ClinicalConsentRecord>;

const AGENT_ID_PATTERN = /^[a-zA-Z0-9_-]+$/;

/** Default forbidden intents applied to every bundled agent manifest. */
export const DEFAULT_FORBIDDEN_INTENTS = [
  'diagnose',
  'prescribe',
  'dose',
  'replace_emergency_care',
  'instruct_stop_medication'
] as const;

const FORBIDDEN_INTENT_DESCRIPTIONS: Record<string, string> = {
  diagnose: 'Diagnose a condition or tell you what illness you have.',
  prescribe: 'Prescribe, recommend, or switch medications or treatments.',
  dose: 'Tell you how much of a medication to take or how to change a dose.',
  replace_emergency_care: 'Replace emergency services or your care team in an urgent situation.',
  instruct_stop_medication: 'Tell you to stop, skip, or pause a medication.'
};

/** Returns true when the agent's risk class requires explicit user consent. */
export function requiresClinicalConsent(riskClass: string | undefined | null): boolean {
  return (riskClass || '').trim().toLowerCase() === CLINICAL_ASSIST_RISK_CLASS;
}

/** Translates a manifest forbidden-intent key into plain language. */
export function describeForbiddenIntent(intent: string): string {
  const key = intent.trim().toLowerCase();
  if (FORBIDDEN_INTENT_DESCRIPTIONS[key]) {
    return FORBIDDEN_INTENT_DESCRIPTIONS[key];
  }
  const words = key.replace(/[_-]+/g, ' ').trim();
  return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}.` : '';
}

function isValidRecord(value: unknown): value is ClinicalConsentRecord {
  if (!value || typeof value !== 'object') return false;
  const grantedAt = (value as { grantedAt?: unknown }).grantedAt;
  return typeof grantedAt === 'string' && !Number.isNaN(Date.parse(grantedAt));
}

/** Loads all stored consents, discarding malformed or tampered entries. */
export function loadClinicalConsents(): ClinicalConsentMap {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(CLINICAL_CONSENT_STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};

    const result: ClinicalConsentMap = {};
    for (const [agentId, record] of Object.entries(parsed as Record<string, unknown>)) {
      if (AGENT_ID_PATTERN.test(agentId) && isValidRecord(record)) {
        result[agentId] = { grantedAt: record.grantedAt };
      }
    }
    return result;
  } catch {
    return {};
  }
}

function persist(consents: ClinicalConsentMap): void {
  if (typeof window === 'undefined') return;
  try {
    if (Object.keys(consents).length === 0) {
      window.localStorage.removeItem(CLINICAL_CONSENT_STORAGE_KEY);
    } else {
      window.localStorage.setItem(CLINICAL_CONSENT_STORAGE_KEY, JSON.stringify(consents));
    }
  } catch {
    // Storage unavailable or quota exceeded: consent simply is not persisted.
  }
  try {
    window.dispatchEvent(new CustomEvent(CLINICAL_CONSENT_CHANGED_EVENT));
  } catch {
    // Non-DOM environments
  }
}

/** Returns true only when the user has explicitly granted consent for this agent. */
export function hasClinicalConsent(agentId: string | undefined | null): boolean {
  if (!agentId || !AGENT_ID_PATTERN.test(agentId)) return false;
  return Object.prototype.hasOwnProperty.call(loadClinicalConsents(), agentId);
}

/** Records the user's consent for the given agent with the current timestamp. */
export function grantClinicalConsent(agentId: string, now: Date = new Date()): ClinicalConsentRecord | null {
  if (!AGENT_ID_PATTERN.test(agentId)) return null;
  const record: ClinicalConsentRecord = { grantedAt: now.toISOString() };
  persist({ ...loadClinicalConsents(), [agentId]: record });
  return record;
}

/** Withdraws consent for a single agent. */
export function withdrawClinicalConsent(agentId: string): void {
  const consents = loadClinicalConsents();
  if (!Object.prototype.hasOwnProperty.call(consents, agentId)) return;
  delete consents[agentId];
  persist(consents);
}

/** Withdraws consent for every agent. */
export function withdrawAllClinicalConsents(): void {
  persist({});
}
