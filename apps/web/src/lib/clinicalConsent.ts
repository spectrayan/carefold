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
 *
 * In Milestone 5 (#87), clinical consent is scoped per household profile
 * (`carefold_clinical_consent_v1_<profileId>`), ensuring consent for one person
 * (e.g. Rosa) never bleeds into another person (e.g. Leo or Sam).
 */

export const CLINICAL_CONSENT_STORAGE_KEY_PREFIX = 'carefold_clinical_consent_v1';
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

import {
  FORBIDDEN_INTENT_DESCRIPTIONS,
  formatForbiddenIntent,
  describeForbiddenIntent
} from '@/lib/utils';
import { getScopedStorageKey, getStorageUserId } from '@/lib/storageNamespace';

export { FORBIDDEN_INTENT_DESCRIPTIONS, formatForbiddenIntent, describeForbiddenIntent };

/** Returns true when the agent's risk class requires explicit user consent. */
export function requiresClinicalConsent(riskClass: string | undefined | null): boolean {
  return (riskClass || '').trim().toLowerCase() === CLINICAL_ASSIST_RISK_CLASS;
}

function isValidRecord(value: unknown): value is ClinicalConsentRecord {
  if (!value || typeof value !== 'object') return false;
  const grantedAt = (value as { grantedAt?: unknown }).grantedAt;
  return typeof grantedAt === 'string' && !Number.isNaN(Date.parse(grantedAt));
}

/**
 * Returns the storage key for a profile's clinical consent.
 */
export function getProfileConsentKey(profileId: string = 'me', userId?: string | null): string {
  const effectiveUserId = userId !== undefined ? userId : getStorageUserId();
  const baseKey = `${CLINICAL_CONSENT_STORAGE_KEY_PREFIX}_${profileId}`;
  return getScopedStorageKey(effectiveUserId, baseKey);
}

/**
 * Disambiguates whether a single optional argument was passed as `userId` or `profileId`.
 * If it matches a user ID pattern (e.g. starts with 'usr-' or contains UUID format), it is treated as `userId`.
 */
function resolveProfileAndUser(
  arg1?: string | null,
  arg2?: string | null
): { profileId: string; userId?: string | null } {
  if (arg2 !== undefined) {
    return { profileId: arg1 || 'me', userId: arg2 };
  }
  if (!arg1) {
    return { profileId: 'me', userId: undefined };
  }
  if (arg1.startsWith('usr-') || /^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(arg1)) {
    return { profileId: 'me', userId: arg1 };
  }
  return { profileId: arg1, userId: undefined };
}

/** Loads all stored consents for a profile, discarding malformed or tampered entries. */
export function loadClinicalConsents(
  profileIdOrUserId?: string | null,
  explicitUserId?: string | null
): ClinicalConsentMap {
  if (typeof window === 'undefined') return {};
  try {
    const { profileId, userId } = resolveProfileAndUser(profileIdOrUserId, explicitUserId);
    const effectiveUserId = userId !== undefined ? userId : getStorageUserId();
    const key = getProfileConsentKey(profileId, userId);

    let raw = window.localStorage.getItem(key);

    // Backward-compatibility: if loading for 'me' or default, fallback to legacy key
    if (!raw && (profileId === 'me' || profileId === 'default')) {
      const legacyKey = getScopedStorageKey(effectiveUserId, CLINICAL_CONSENT_STORAGE_KEY);
      raw =
        window.localStorage.getItem(legacyKey) ||
        (!effectiveUserId ? window.localStorage.getItem(CLINICAL_CONSENT_STORAGE_KEY) : null);
    }

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

function persist(
  consents: ClinicalConsentMap,
  profileId: string = 'me',
  userId?: string | null
): void {
  if (typeof window === 'undefined') return;
  const effectiveUserId = userId !== undefined ? userId : getStorageUserId();
  const profileKey = getProfileConsentKey(profileId, userId);
  const legacyKey = getScopedStorageKey(effectiveUserId, CLINICAL_CONSENT_STORAGE_KEY);

  try {
    if (Object.keys(consents).length === 0) {
      window.localStorage.removeItem(profileKey);
      if (profileId === 'me' || profileId === 'default') {
        window.localStorage.removeItem(legacyKey);
        if (!effectiveUserId) {
          window.localStorage.removeItem(CLINICAL_CONSENT_STORAGE_KEY);
        }
      }
    } else {
      const serialized = JSON.stringify(consents);
      window.localStorage.setItem(profileKey, serialized);
      if (profileId === 'me' || profileId === 'default') {
        window.localStorage.setItem(legacyKey, serialized);
        if (!effectiveUserId) {
          window.localStorage.setItem(CLINICAL_CONSENT_STORAGE_KEY, serialized);
        }
      }
    }
  } catch {
    // Storage unavailable or quota exceeded
  }
  try {
    window.dispatchEvent(new CustomEvent(CLINICAL_CONSENT_CHANGED_EVENT, { detail: { profileId } }));
  } catch {
    // Non-DOM environments
  }
}

/** Returns true only when the user has explicitly granted consent for this agent on this profile. */
export function hasClinicalConsent(
  agentId: string | undefined | null,
  profileIdOrUserId?: string | null,
  explicitUserId?: string | null
): boolean {
  if (!agentId || !AGENT_ID_PATTERN.test(agentId)) return false;
  const { profileId, userId } = resolveProfileAndUser(profileIdOrUserId, explicitUserId);
  return Object.prototype.hasOwnProperty.call(loadClinicalConsents(profileId, userId), agentId);
}

/** Records the user's consent for the given agent with the current timestamp. */
export function grantClinicalConsent(
  agentId: string,
  now: Date = new Date(),
  profileIdOrUserId?: string | null,
  explicitUserId?: string | null
): ClinicalConsentRecord | null {
  if (!AGENT_ID_PATTERN.test(agentId)) return null;
  const { profileId, userId } = resolveProfileAndUser(profileIdOrUserId, explicitUserId);
  const record: ClinicalConsentRecord = { grantedAt: now.toISOString() };
  persist({ ...loadClinicalConsents(profileId, userId), [agentId]: record }, profileId, userId);
  return record;
}

/** Withdraws consent for a single agent from a profile. */
export function withdrawClinicalConsent(
  agentId: string,
  profileIdOrUserId?: string | null,
  explicitUserId?: string | null
): void {
  const { profileId, userId } = resolveProfileAndUser(profileIdOrUserId, explicitUserId);
  const consents = loadClinicalConsents(profileId, userId);
  if (!Object.prototype.hasOwnProperty.call(consents, agentId)) return;
  delete consents[agentId];
  persist(consents, profileId, userId);
}

/** Withdraws consent for every agent from a profile. */
export function withdrawAllClinicalConsents(
  profileIdOrUserId?: string | null,
  explicitUserId?: string | null
): void {
  const { profileId, userId } = resolveProfileAndUser(profileIdOrUserId, explicitUserId);
  persist({}, profileId, userId);
}
