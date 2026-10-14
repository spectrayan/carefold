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

import type { LocaleMetadata, SupportedLocale, TextDirection } from './types';

export const DEFAULT_LOCALE: SupportedLocale = 'en-US';

export const LOCALE_STORAGE_KEY = 'carefold-locale';

export const SUPPORTED_LOCALES: Record<SupportedLocale, LocaleMetadata> = {
  'en-US': {
    code: 'en-US',
    name: 'English (United States)',
    nativeName: 'English',
    direction: 'ltr',
    region: 'United States'
  },
  'es-ES': {
    code: 'es-ES',
    name: 'Spanish (Spain)',
    nativeName: 'Español',
    direction: 'ltr',
    region: 'España'
  },
  'fr-FR': {
    code: 'fr-FR',
    name: 'French (France)',
    nativeName: 'Français',
    direction: 'ltr',
    region: 'France'
  },
  'hi-IN': {
    code: 'hi-IN',
    name: 'Hindi (India)',
    nativeName: 'हिन्दी',
    direction: 'ltr',
    region: 'भारत'
  },
  'ar-SA': {
    code: 'ar-SA',
    name: 'Arabic (Saudi Arabia)',
    nativeName: 'العربية',
    direction: 'rtl',
    region: 'المملكة العربية السعودية'
  }
};

const LANGUAGE_PREFIX_MAP: Record<string, SupportedLocale> = {
  en: 'en-US',
  es: 'es-ES',
  fr: 'fr-FR',
  hi: 'hi-IN',
  ar: 'ar-SA'
};

export function normalizeLocale(input?: string | null): SupportedLocale {
  if (!input || typeof input !== 'string') {
    return DEFAULT_LOCALE;
  }
  const trimmed = input.trim().replace(/_/g, '-');
  if (trimmed in SUPPORTED_LOCALES) {
    return trimmed as SupportedLocale;
  }

  const lower = trimmed.toLowerCase();
  for (const key of Object.keys(SUPPORTED_LOCALES) as SupportedLocale[]) {
    if (key.toLowerCase() === lower) {
      return key;
    }
  }

  const prefix = lower.split('-')[0];
  if (prefix && prefix in LANGUAGE_PREFIX_MAP) {
    return LANGUAGE_PREFIX_MAP[prefix];
  }

  return DEFAULT_LOCALE;
}

export function getTextDirection(locale: SupportedLocale): TextDirection {
  const normalized = normalizeLocale(locale);
  return SUPPORTED_LOCALES[normalized]?.direction ?? 'ltr';
}
