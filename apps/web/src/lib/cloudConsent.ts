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

import { getScopedStorageKey, getStorageUserId } from '@/lib/storageNamespace';
import { isLocalProvider, type CarefoldUserSettings } from '@/lib/settings';

export const CLOUD_CONSENT_STORAGE_KEY_PREFIX = 'carefold_cloud_consent_v1';
export const CLOUD_CONSENT_CHANGED_EVENT = 'carefold:cloud-consent-changed';

export interface CloudConsentRecord {
  grantedAt: string;
  provider: string;
  model: string;
}

export type CloudConsentMap = Record<string, CloudConsentRecord>;

export function getProfileCloudConsentKey(profileId: string = 'me', userId?: string | null): string {
  const effectiveUserId = userId !== undefined ? userId : getStorageUserId();
  const baseKey = `${CLOUD_CONSENT_STORAGE_KEY_PREFIX}_${profileId}`;
  return getScopedStorageKey(effectiveUserId, baseKey);
}

export function loadCloudConsents(profileId: string = 'me', userId?: string | null): CloudConsentMap {
  if (typeof window === 'undefined' || !window.localStorage) return {};
  try {
    const key = getProfileCloudConsentKey(profileId, userId);
    const raw = window.localStorage.getItem(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

export function hasCloudConsent(
  provider: string,
  profileId: string = 'me',
  userId?: string | null
): boolean {
  const consents = loadCloudConsents(profileId, userId);
  return Boolean(consents[provider]);
}

export function grantCloudConsent(
  provider: string,
  model: string,
  profileId: string = 'me',
  userId?: string | null
): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    const key = getProfileCloudConsentKey(profileId, userId);
    const consents = loadCloudConsents(profileId, userId);
    consents[provider] = {
      grantedAt: new Date().toISOString(),
      provider,
      model
    };
    window.localStorage.setItem(key, JSON.stringify(consents));
    window.dispatchEvent(
      new CustomEvent(CLOUD_CONSENT_CHANGED_EVENT, {
        detail: { profileId, provider, model }
      })
    );
  } catch {}
}

export function revokeCloudConsent(
  provider: string,
  profileId: string = 'me',
  userId?: string | null
): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    const key = getProfileCloudConsentKey(profileId, userId);
    const consents = loadCloudConsents(profileId, userId);
    delete consents[provider];
    window.localStorage.setItem(key, JSON.stringify(consents));
    window.dispatchEvent(
      new CustomEvent(CLOUD_CONSENT_CHANGED_EVENT, {
        detail: { profileId, provider }
      })
    );
  } catch {}
}

/**
 * Evaluates whether the cloud disclosure warning must be presented.
 * Returns true if a cloud provider is selected and sensitive PHI/connector data
 * is active without explicit user consent.
 */
export function shouldTriggerCloudDisclosure(
  settings: CarefoldUserSettings,
  hasSensitiveContext: boolean,
  profileId: string = 'me'
): boolean {
  if (isLocalProvider(settings)) {
    return false;
  }
  if (!hasSensitiveContext) {
    return false;
  }
  return !hasCloudConsent(settings.provider, profileId);
}
