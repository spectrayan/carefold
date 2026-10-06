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
