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

import React, { useEffect, useState } from 'react';
import {
  DEFAULT_USER_SETTINGS,
  loadSettings,
  getProviderPrivacyState,
  type CarefoldUserSettings
} from '@/lib/settings';

export function FooterPrivacyNotice() {
  const [settings, setSettings] = useState<CarefoldUserSettings>(DEFAULT_USER_SETTINGS);

  useEffect(() => {
    setSettings(loadSettings());

    const handleSettingsChange = (e: Event) => {
      const customEvent = e as CustomEvent<CarefoldUserSettings>;
      if (customEvent.detail) {
        setSettings(customEvent.detail);
      } else {
        setSettings(loadSettings());
      }
    };

    window.addEventListener('carefold:settings-changed', handleSettingsChange);
    return () => {
      window.removeEventListener('carefold:settings-changed', handleSettingsChange);
    };
  }, []);

  const privacyState = getProviderPrivacyState(settings);

  return (
    <div data-testid="footer-privacy-notice" suppressHydrationWarning>
      {privacyState.footerText}
    </div>
  );
}
