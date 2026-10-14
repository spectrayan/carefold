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

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  SUPPORTED_LOCALES,
  getTextDirection,
  normalizeLocale
} from './config';
import {
  formatIcuMessage,
  formatLocalizedDate,
  formatLocalizedNumber,
  formatLocalizedRelativeTime
} from './formatters';
import type {
  LocaleMetadata,
  SupportedLocale,
  TextDirection,
  TranslationDictionary
} from './types';

import enUS from './locales/en-US.json';
import esES from './locales/es-ES.json';
import frFR from './locales/fr-FR.json';
import hiIN from './locales/hi-IN.json';
import arSA from './locales/ar-SA.json';

const CATALOGS: Record<SupportedLocale, TranslationDictionary> = {
  'en-US': enUS as TranslationDictionary,
  'es-ES': esES as TranslationDictionary,
  'fr-FR': frFR as TranslationDictionary,
  'hi-IN': hiIN as TranslationDictionary,
  'ar-SA': arSA as TranslationDictionary
};

export interface I18nContextValue {
  locale: SupportedLocale;
  direction: TextDirection;
  setLocale: (nextLocale: SupportedLocale | string) => void;
  t: (key: string, values?: Record<string, string | number>) => string;
  formatDate: (
    date: Date | string | number,
    options?: Intl.DateTimeFormatOptions,
    timeZone?: string
  ) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatRelativeTime: (value: number, unit: Intl.RelativeTimeFormatUnit) => string;
  availableLocales: LocaleMetadata[];
}

const I18nContext = createContext<I18nContextValue | null>(null);

function resolveNestedKey(dict: TranslationDictionary, dottedKey: string): string | undefined {
  const segments = dottedKey.split('.');
  let cursor: string | TranslationDictionary | undefined = dict;
  for (const segment of segments) {
    if (cursor && typeof cursor === 'object' && segment in cursor) {
      cursor = cursor[segment];
    } else {
      return undefined;
    }
  }
  return typeof cursor === 'string' ? cursor : undefined;
}

function applyDocumentLocaleAttributes(locale: SupportedLocale, direction: TextDirection) {
  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.lang = locale;
    document.documentElement.dir = direction;
  }
}

function useStandaloneLocaleState(
  initialLocale: SupportedLocale = DEFAULT_LOCALE,
  active: boolean = true
): I18nContextValue {
  const [locale, setLocaleState] = useState<SupportedLocale>(initialLocale);

  useEffect(() => {
    if (!active) return;

    let hydratedLocale = initialLocale;
    try {
      const saved = window.localStorage.getItem(LOCALE_STORAGE_KEY);
      if (saved) {
        hydratedLocale = normalizeLocale(saved);
      }
    } catch {}
    setLocaleState(hydratedLocale);
    applyDocumentLocaleAttributes(hydratedLocale, getTextDirection(hydratedLocale));

    const handleLocaleChange = (event: Event) => {
      const customEvent = event as CustomEvent<{ locale?: string }>;
      if (customEvent.detail?.locale) {
        const next = normalizeLocale(customEvent.detail.locale);
        setLocaleState(next);
        applyDocumentLocaleAttributes(next, getTextDirection(next));
      }
    };

    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === LOCALE_STORAGE_KEY && event.newValue) {
        const next = normalizeLocale(event.newValue);
        setLocaleState(next);
        applyDocumentLocaleAttributes(next, getTextDirection(next));
      }
    };

    window.addEventListener('carefold:locale-change', handleLocaleChange);
    window.addEventListener('storage', handleStorageChange);
    return () => {
      window.removeEventListener('carefold:locale-change', handleLocaleChange);
      window.removeEventListener('storage', handleStorageChange);
    };
  }, [initialLocale, active]);

  const setLocale = useCallback((nextInput: SupportedLocale | string) => {
    const next = normalizeLocale(nextInput);
    const nextDir = getTextDirection(next);
    setLocaleState(next);
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {}
    applyDocumentLocaleAttributes(next, nextDir);
    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('carefold:locale-change', {
          detail: { locale: next, direction: nextDir }
        })
      );
    }
  }, []);

  const direction = getTextDirection(locale);

  const t = useCallback(
    (key: string, values?: Record<string, string | number>): string => {
      const activeDict = CATALOGS[locale] ?? CATALOGS[DEFAULT_LOCALE];
      const rawTemplate =
        resolveNestedKey(activeDict, key) ??
        resolveNestedKey(CATALOGS[DEFAULT_LOCALE], key) ??
        key;
      return formatIcuMessage(rawTemplate, values, locale);
    },
    [locale]
  );

  const formatDate = useCallback(
    (
      date: Date | string | number,
      options?: Intl.DateTimeFormatOptions,
      timeZone?: string
    ): string => formatLocalizedDate(date, locale, options, timeZone),
    [locale]
  );

  const formatNumber = useCallback(
    (value: number, options?: Intl.NumberFormatOptions): string =>
      formatLocalizedNumber(value, locale, options),
    [locale]
  );

  const formatRelativeTime = useCallback(
    (value: number, unit: Intl.RelativeTimeFormatUnit): string =>
      formatLocalizedRelativeTime(value, unit, locale),
    [locale]
  );

  const availableLocales = useMemo(() => Object.values(SUPPORTED_LOCALES), []);

  return useMemo(
    () => ({
      locale,
      direction,
      setLocale,
      t,
      formatDate,
      formatNumber,
      formatRelativeTime,
      availableLocales
    }),
    [
      locale,
      direction,
      setLocale,
      t,
      formatDate,
      formatNumber,
      formatRelativeTime,
      availableLocales
    ]
  );
}

export interface I18nProviderProps {
  children: React.ReactNode;
  defaultLocale?: SupportedLocale;
}

export function I18nProvider({
  children,
  defaultLocale = DEFAULT_LOCALE
}: I18nProviderProps) {
  const value = useStandaloneLocaleState(defaultLocale, true);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  const fallback = useStandaloneLocaleState(DEFAULT_LOCALE, context === null);
  return context ?? fallback;
}
