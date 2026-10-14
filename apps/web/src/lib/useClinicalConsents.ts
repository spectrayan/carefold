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

'use client';

import { useEffect, useState } from 'react';
import {
  CLINICAL_CONSENT_CHANGED_EVENT,
  CLINICAL_CONSENT_STORAGE_KEY,
  CLINICAL_CONSENT_STORAGE_KEY_PREFIX,
  type ClinicalConsentMap,
  loadClinicalConsents
} from '@/lib/clinicalConsent';

/**
 * Subscribes to the clinical consent store for a specific profile (defaults to 'me').
 * `loaded` stays false during SSR and the first client render so gated UI never flashes
 * an incorrect state.
 */
export function useClinicalConsents(profileId: string = 'me'): { consents: ClinicalConsentMap; loaded: boolean } {
  const [consents, setConsents] = useState<ClinicalConsentMap>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const refresh = () => setConsents(loadClinicalConsents(profileId));
    const handleStorage = (e: StorageEvent) => {
      if (
        e.key === null ||
        e.key === CLINICAL_CONSENT_STORAGE_KEY ||
        e.key.includes(CLINICAL_CONSENT_STORAGE_KEY_PREFIX)
      ) {
        refresh();
      }
    };

    refresh();
    setLoaded(true);
    window.addEventListener(CLINICAL_CONSENT_CHANGED_EVENT, refresh);
    window.addEventListener('storage', handleStorage);
    return () => {
      window.removeEventListener(CLINICAL_CONSENT_CHANGED_EVENT, refresh);
      window.removeEventListener('storage', handleStorage);
    };
  }, [profileId]);

  return { consents, loaded };
}
