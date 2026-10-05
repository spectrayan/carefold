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

'use client';

import { useEffect, useState } from 'react';
import {
  CLINICAL_CONSENT_CHANGED_EVENT,
  CLINICAL_CONSENT_STORAGE_KEY,
  type ClinicalConsentMap,
  loadClinicalConsents
} from '@/lib/clinicalConsent';

/**
 * Subscribes to the clinical consent store. `loaded` stays false during SSR and
 * the first client render so gated UI never flashes an incorrect state.
 */
export function useClinicalConsents(): { consents: ClinicalConsentMap; loaded: boolean } {
  const [consents, setConsents] = useState<ClinicalConsentMap>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const refresh = () => setConsents(loadClinicalConsents());
    const handleStorage = (e: StorageEvent) => {
      if (e.key === null || e.key === CLINICAL_CONSENT_STORAGE_KEY) refresh();
    };

    refresh();
    setLoaded(true);
    window.addEventListener(CLINICAL_CONSENT_CHANGED_EVENT, refresh);
    window.addEventListener('storage', handleStorage);
    return () => {
      window.removeEventListener(CLINICAL_CONSENT_CHANGED_EVENT, refresh);
      window.removeEventListener('storage', handleStorage);
    };
  }, []);

  return { consents, loaded };
}
