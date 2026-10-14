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

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { CarefoldLogo } from '@/components/ui/CarefoldLogo';
import {
  I18nProvider,
  useI18n,
  LOCALE_STORAGE_KEY,
  normalizeLocale,
  getTextDirection,
  formatIcuMessage,
  formatLocalizedDate,
  formatLocalizedNumber,
  formatLocalizedRelativeTime
} from '@/i18n';
import DisplaySettingsPage from '@/app/settings/display/page';
import { ThemeProvider } from '@/components/ThemeProvider';

function I18nTestHarness() {
  const { locale, direction, setLocale, t, formatDate, formatNumber } = useI18n();
  return (
    <div>
      <span data-testid="active-locale">{locale}</span>
      <span data-testid="active-direction">{direction}</span>
      <span data-testid="translated-chat">{t('nav.chat')}</span>
      <span data-testid="translated-disclaimer">{t('safety.disclaimerBanner')}</span>
      <span data-testid="plural-zero">{t('common.appointmentCount', { count: 0 })}</span>
      <span data-testid="plural-one">{t('common.appointmentCount', { count: 1 })}</span>
      <span data-testid="plural-many">{t('common.appointmentCount', { count: 4 })}</span>
      <span data-testid="formatted-date">
        {formatDate('2026-10-14T14:30:00Z', { year: 'numeric', month: 'short', day: 'numeric' }, 'UTC')}
      </span>
      <span data-testid="formatted-number">{formatNumber(1284.75)}</span>
      <button type="button" data-testid="switch-es" onClick={() => setLocale('es-ES')}>
        Spanish
      </button>
      <button type="button" data-testid="switch-fr" onClick={() => setLocale('fr-FR')}>
        French
      </button>
      <button type="button" data-testid="switch-hi" onClick={() => setLocale('hi-IN')}>
        Hindi
      </button>
      <button type="button" data-testid="switch-ar" onClick={() => setLocale('ar-SA')}>
        Arabic
      </button>
      <button type="button" data-testid="switch-en" onClick={() => setLocale('en-US')}>
        English
      </button>
    </div>
  );
}

describe('Official Carefold Brand Mark and Frontend i18n Framework', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.lang = 'en';
    document.documentElement.dir = 'ltr';
  });

  describe('CarefoldLogo Brand Component', () => {
    it('renders the folded-care SVG brand mark with accessible label and custom size', () => {
      render(<CarefoldLogo size={32} />);

      const logoContainer = screen.getByTestId('carefold-logo');
      expect(logoContainer).toBeInTheDocument();

      const svg = screen.getByRole('img', { name: /carefold brand mark/i });
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveAttribute('width', '32');
      expect(svg).toHaveAttribute('height', '32');
      expect(screen.queryByTestId('carefold-logo-wordmark')).not.toBeInTheDocument();
    });

    it('renders the Carefold wordmark when showWordmark is enabled', () => {
      render(<CarefoldLogo size={24} showWordmark />);

      expect(screen.getByTestId('carefold-logo')).toBeInTheDocument();
      const wordmark = screen.getByTestId('carefold-logo-wordmark');
      expect(wordmark).toBeInTheDocument();
      expect(wordmark).toHaveTextContent('Carefold');
    });
  });

  describe('Locale Normalization, Directionality, and ICU Formatters', () => {
    it('normalizes BCP 47 tags and language prefixes with fallback to en-US', () => {
      expect(normalizeLocale('en-US')).toBe('en-US');
      expect(normalizeLocale('es_ES')).toBe('es-ES');
      expect(normalizeLocale('fr')).toBe('fr-FR');
      expect(normalizeLocale('hi-in')).toBe('hi-IN');
      expect(normalizeLocale('ar')).toBe('ar-SA');
      expect(normalizeLocale('unknown-XX')).toBe('en-US');
      expect(normalizeLocale(null)).toBe('en-US');
    });

    it('resolves text direction accurately for LTR and RTL locales', () => {
      expect(getTextDirection('en-US')).toBe('ltr');
      expect(getTextDirection('es-ES')).toBe('ltr');
      expect(getTextDirection('fr-FR')).toBe('ltr');
      expect(getTextDirection('hi-IN')).toBe('ltr');
      expect(getTextDirection('ar-SA')).toBe('rtl');
    });

    it('formats ICU message templates with variable interpolation and plural rules', () => {
      const template =
        '{patient} has {count, plural, zero {no records} one {# record} other {# records}} ready.';
      expect(formatIcuMessage(template, { patient: 'Rosa', count: 0 }, 'en-US')).toBe(
        'Rosa has no records ready.'
      );
      expect(formatIcuMessage(template, { patient: 'Rosa', count: 1 }, 'en-US')).toBe(
        'Rosa has 1 record ready.'
      );
      expect(formatIcuMessage(template, { patient: 'Rosa', count: 5 }, 'en-US')).toBe(
        'Rosa has 5 records ready.'
      );
    });

    it('formats localized dates, numbers, and relative time via Intl APIs', () => {
      const sampleDate = new Date('2026-10-14T00:00:00Z');
      const enDate = formatLocalizedDate(sampleDate, 'en-US', undefined, 'UTC');
      const esDate = formatLocalizedDate(sampleDate, 'es-ES', undefined, 'UTC');
      expect(enDate).toContain('2026');
      expect(esDate).toContain('2026');

      expect(formatLocalizedNumber(12500.5, 'en-US')).toBe('12,500.5');
      expect(formatLocalizedRelativeTime(-1, 'day', 'en-US').toLowerCase()).toContain('yesterday');
    });
  });

  describe('I18nProvider and useI18n Hook', () => {
    it('initializes with en-US and switches across es-ES, hi-IN, and ar-SA with RTL updates', () => {
      render(
        <I18nProvider>
          <I18nTestHarness />
        </I18nProvider>
      );

      expect(screen.getByTestId('active-locale')).toHaveTextContent('en-US');
      expect(screen.getByTestId('active-direction')).toHaveTextContent('ltr');
      expect(screen.getByTestId('translated-chat')).toHaveTextContent('Chats');
      expect(screen.getByTestId('plural-zero')).toHaveTextContent('No upcoming appointments');
      expect(screen.getByTestId('plural-one')).toHaveTextContent('1 upcoming appointment');
      expect(screen.getByTestId('plural-many')).toHaveTextContent('4 upcoming appointments');
      expect(document.documentElement.lang).toBe('en-US');
      expect(document.documentElement.dir).toBe('ltr');

      // Switch to Spanish (es-ES)
      fireEvent.click(screen.getByTestId('switch-es'));
      expect(screen.getByTestId('active-locale')).toHaveTextContent('es-ES');
      expect(screen.getByTestId('active-direction')).toHaveTextContent('ltr');
      expect(screen.getByTestId('translated-chat')).toHaveTextContent('Consultas');
      expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('es-ES');
      expect(document.documentElement.lang).toBe('es-ES');
      expect(document.documentElement.dir).toBe('ltr');

      // Switch to Hindi (hi-IN)
      fireEvent.click(screen.getByTestId('switch-hi'));
      expect(screen.getByTestId('active-locale')).toHaveTextContent('hi-IN');
      expect(screen.getByTestId('active-direction')).toHaveTextContent('ltr');
      expect(screen.getByTestId('translated-chat')).toHaveTextContent('चैट');
      expect(document.documentElement.lang).toBe('hi-IN');
      expect(document.documentElement.dir).toBe('ltr');

      // Switch to Arabic (ar-SA) and verify RTL directionality
      fireEvent.click(screen.getByTestId('switch-ar'));
      expect(screen.getByTestId('active-locale')).toHaveTextContent('ar-SA');
      expect(screen.getByTestId('active-direction')).toHaveTextContent('rtl');
      expect(screen.getByTestId('translated-chat')).toHaveTextContent('المحادثات');
      expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('ar-SA');
      expect(document.documentElement.lang).toBe('ar-SA');
      expect(document.documentElement.dir).toBe('rtl');
    });
  });

  describe('DisplaySettingsPage Language & Regional Selector', () => {
    it('renders locale-selector-group with RTL badge and switches locale on click', () => {
      render(
        <ThemeProvider>
          <I18nProvider>
            <DisplaySettingsPage />
          </I18nProvider>
        </ThemeProvider>
      );

      const selectorGroup = screen.getByTestId('locale-selector-group');
      expect(selectorGroup).toBeInTheDocument();

      const enOption = screen.getByTestId('locale-option-en-US');
      const esOption = screen.getByTestId('locale-option-es-ES');
      const frOption = screen.getByTestId('locale-option-fr-FR');
      const hiOption = screen.getByTestId('locale-option-hi-IN');
      const arOption = screen.getByTestId('locale-option-ar-SA');

      expect(enOption).toHaveAttribute('aria-checked', 'true');
      expect(esOption).toBeInTheDocument();
      expect(frOption).toBeInTheDocument();
      expect(hiOption).toBeInTheDocument();
      expect(arOption).toBeInTheDocument();
      expect(screen.getByTestId('locale-rtl-badge-ar-SA')).toHaveTextContent('RTL');
      expect(screen.getByTestId('locale-format-preview')).toBeInTheDocument();

      fireEvent.click(arOption);
      expect(arOption).toHaveAttribute('aria-checked', 'true');
      expect(document.documentElement.lang).toBe('ar-SA');
      expect(document.documentElement.dir).toBe('rtl');
      expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('ar-SA');

      fireEvent.click(esOption);
      expect(esOption).toHaveAttribute('aria-checked', 'true');
      expect(document.documentElement.lang).toBe('es-ES');
      expect(document.documentElement.dir).toBe('ltr');
    });
  });
});
