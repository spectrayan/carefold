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
