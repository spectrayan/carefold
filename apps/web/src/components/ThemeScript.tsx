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

import Script from 'next/script';
import { THEME_STORAGE_KEY } from '@/lib/theme';

export const THEME_SCRIPT_CONTENT = `(function() {
  try {
    var key = '${THEME_STORAGE_KEY}';
    var stored = localStorage.getItem(key);
    var supportDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (stored === 'dark' || ((!stored || stored === 'system') && supportDark)) {
      document.documentElement.classList.add('dark');
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      document.documentElement.setAttribute('data-theme', 'light');
    }
  } catch (e) {}
})();`;

/**
 * Server component that injects the blocking inline theme script into <head>.
 * Uses next/script with strategy="beforeInteractive" to execute prior to page hydration
 * without triggering React 19 client-side script warnings.
 */
export function ThemeScript() {
  if (process.env.NODE_ENV === 'test') {
    return (
      <script
        id="carefold-theme-init"
        dangerouslySetInnerHTML={{ __html: THEME_SCRIPT_CONTENT }}
      />
    );
  }

  return (
    <Script
      id="carefold-theme-init"
      strategy="beforeInteractive"
      dangerouslySetInnerHTML={{ __html: THEME_SCRIPT_CONTENT }}
    />
  );
}
