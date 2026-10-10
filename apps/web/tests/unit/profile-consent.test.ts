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

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  CLINICAL_CONSENT_STORAGE_KEY,
  getProfileConsentKey,
  grantClinicalConsent,
  hasClinicalConsent,
  loadClinicalConsents,
  withdrawClinicalConsent,
  withdrawAllClinicalConsents
} from '@/lib/clinicalConsent';
import {
  checkTeenHandoverStatus,
  dismissTeenHandoverReminder
} from '@/lib/familyProfiles';

describe('Per-Profile Clinical Consent & Teen Handover Suite (#87)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe('Group 1: Per-Profile Clinical Consent Scoping', () => {
    it('isolates consent between household profiles (no consent bleeding)', () => {
      // Initially neither Rosa nor Me have consent
      expect(hasClinicalConsent('cardiology-guide', 'rosa')).toBe(false);
      expect(hasClinicalConsent('cardiology-guide', 'me')).toBe(false);

      // Grant consent for Rosa
      const now = new Date('2026-10-09T10:00:00.000Z');
      grantClinicalConsent('cardiology-guide', now, 'rosa');

      // Rosa now has consent
      expect(hasClinicalConsent('cardiology-guide', 'rosa')).toBe(true);

      // Me strictly DOES NOT inherit Rosa's consent
      expect(hasClinicalConsent('cardiology-guide', 'me')).toBe(false);

      // Leo strictly DOES NOT inherit Rosa's consent
      expect(hasClinicalConsent('cardiology-guide', 'leo')).toBe(false);

      // Verify stored under Rosa's scoped key
      const rosaKey = getProfileConsentKey('rosa');
      expect(rosaKey).toContain('clinical_consent_v1_rosa');
      const rosaStored = JSON.parse(localStorage.getItem(rosaKey) || '{}');
      expect(rosaStored['cardiology-guide'].grantedAt).toBe('2026-10-09T10:00:00.000Z');
    });

    it('withdrawing consent for one profile does not affect others', () => {
      grantClinicalConsent('cardiology-guide', new Date(), 'rosa');
      grantClinicalConsent('cardiology-guide', new Date(), 'me');

      expect(hasClinicalConsent('cardiology-guide', 'rosa')).toBe(true);
      expect(hasClinicalConsent('cardiology-guide', 'me')).toBe(true);

      // Withdraw only for Rosa
      withdrawClinicalConsent('cardiology-guide', 'rosa');
      expect(hasClinicalConsent('cardiology-guide', 'rosa')).toBe(false);
      expect(hasClinicalConsent('cardiology-guide', 'me')).toBe(true);

      // Withdraw all for 'me'
      withdrawAllClinicalConsents('me');
      expect(hasClinicalConsent('cardiology-guide', 'me')).toBe(false);
    });
  });

  describe('Group 2: Legacy Migration Fallback', () => {
    it('gracefully recovers legacy unscoped consent for the primary "me" profile', () => {
      // Simulate existing legacy consent in storage
      localStorage.setItem(
        CLINICAL_CONSENT_STORAGE_KEY,
        JSON.stringify({
          'pulmonology-guide': { grantedAt: '2026-09-01T12:00:00.000Z' }
        })
      );

      // Loading for 'me' should recover the legacy consent
      const consents = loadClinicalConsents('me');
      expect(consents['pulmonology-guide']).toBeDefined();
      expect(hasClinicalConsent('pulmonology-guide', 'me')).toBe(true);

      // But other profiles should not see legacy consent
      expect(hasClinicalConsent('pulmonology-guide', 'rosa')).toBe(false);
    });
  });

  describe('Group 3: 90-Day Teen Handover Reminder Protocol', () => {
    const referenceDate = new Date('2026-10-09T12:00:00.000Z');

    it('returns shouldShowReminder: false for young minors (e.g. age 10)', () => {
      const childProfile = {
        id: 'leo',
        dateOfBirth: '2016-06-15',
        age: 10
      };
      const status = checkTeenHandoverStatus(childProfile, referenceDate);
      expect(status.isEligible).toBe(false);
      expect(status.isApproaching18).toBe(false);
      expect(status.hasReached18).toBe(false);
      expect(status.shouldShowReminder).toBe(false);
    });

    it('detects minors approaching 18 within the 90-day window', () => {
      // 18th birthday on 2026-11-20 (41-42 days from 2026-10-09)
      const teenProfile = {
        id: 'ava',
        dateOfBirth: '2008-11-20',
        age: 17
      };
      const status = checkTeenHandoverStatus(teenProfile, referenceDate);
      expect(status.isEligible).toBe(true);
      expect(status.isApproaching18).toBe(true);
      expect(status.hasReached18).toBe(false);
      expect([41, 42]).toContain(status.daysRemaining);
      expect(status.shouldShowReminder).toBe(true);
    });

    it('detects dependents who have recently reached 18 within the 90-day transition window', () => {
      // 18th birthday was 2026-09-15 (24 days ago)
      const adultProfile = {
        id: 'adult-ava',
        dateOfBirth: '2008-09-15',
        age: 18
      };
      const status = checkTeenHandoverStatus(adultProfile, referenceDate);
      expect(status.isEligible).toBe(true);
      expect(status.hasReached18).toBe(true);
      expect(status.shouldShowReminder).toBe(true);
    });

    it('suppresses the reminder for 30 days once dismissed', () => {
      const teenProfile = {
        id: 'ava',
        dateOfBirth: '2008-11-20',
        age: 17
      };

      // Before dismissal
      expect(checkTeenHandoverStatus(teenProfile, referenceDate).shouldShowReminder).toBe(true);

      // Dismiss reminder
      dismissTeenHandoverReminder('ava');

      // Check right after dismissal (same day)
      const statusAfter = checkTeenHandoverStatus(teenProfile, referenceDate);
      expect(statusAfter.isDismissed).toBe(true);
      expect(statusAfter.shouldShowReminder).toBe(false);

      // Check 35 days later (suppression expired)
      const laterDate = new Date('2026-11-14T12:00:00.000Z');
      const statusLater = checkTeenHandoverStatus(teenProfile, laterDate);
      expect(statusLater.isDismissed).toBe(false);
      expect(statusLater.shouldShowReminder).toBe(true);
    });
  });
});
