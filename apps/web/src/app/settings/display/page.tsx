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

import React from 'react';
import { Sun, Moon, Laptop, Palette, Type, Globe } from 'lucide-react';
import { useOptionalTheme } from '@/components/ThemeProvider';
import { type Theme } from '@/lib/theme';
import { cn } from '@/lib/utils';
import { useI18n } from '@/i18n';

const SAMPLE_PREVIEW_DATE = new Date('2026-10-14T14:30:00Z');
const SAMPLE_PREVIEW_NUMBER = 1284.75;

export default function DisplaySettingsPage() {
  const themeContext = useOptionalTheme();
  const currentTheme = themeContext?.theme || 'system';
  const {
    locale,
    direction,
    setLocale,
    t,
    formatDate,
    formatNumber,
    availableLocales
  } = useI18n();

  const handleSelectTheme = (nextTheme: Theme) => {
    themeContext?.setTheme(nextTheme);
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-bold text-[var(--cf-fg)] tracking-tight">
          {t('settings.display.title')}
        </h2>
        <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
          {t('settings.display.description')}
        </p>
      </div>

      {/* Theme Selection */}
      <div className="space-y-3 pb-6 border-b border-[var(--cf-border)]">
        <label className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
          <Palette className="w-4 h-4 text-[var(--cf-fg-subtle)]" />
          <span>{t('settings.display.colorTheme')}</span>
        </label>
        <p className="text-xs text-[var(--cf-fg-muted)]">
          {t('settings.display.colorThemeDesc')}
        </p>

        <div
          data-testid="theme-selector-group"
          role="radiogroup"
          aria-label="Color Theme Options"
          className="grid grid-cols-3 gap-3 pt-2"
        >
          {/* Light Theme */}
          <button
            type="button"
            data-testid="theme-option-light"
            role="radio"
            aria-checked={currentTheme === 'light'}
            onClick={() => handleSelectTheme('light')}
            className={cn(
              'flex flex-col items-center justify-center gap-2 p-4 rounded-xl border text-xs font-semibold transition-all min-h-[44px]',
              currentTheme === 'light'
                ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] border-emerald-500 ring-2 ring-emerald-500/30'
                : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border-[var(--cf-border)] hover:bg-[var(--cf-surface-3)] hover:text-[var(--cf-fg)]'
            )}
          >
            <Sun className="w-5 h-5 text-amber-500" />
            <span>{t('settings.display.light')}</span>
          </button>

          {/* Dark Theme */}
          <button
            type="button"
            data-testid="theme-option-dark"
            role="radio"
            aria-checked={currentTheme === 'dark'}
            onClick={() => handleSelectTheme('dark')}
            className={cn(
              'flex flex-col items-center justify-center gap-2 p-4 rounded-xl border text-xs font-semibold transition-all min-h-[44px]',
              currentTheme === 'dark'
                ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] border-emerald-500 ring-2 ring-emerald-500/30'
                : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border-[var(--cf-border)] hover:bg-[var(--cf-surface-3)] hover:text-[var(--cf-fg)]'
            )}
          >
            <Moon className="w-5 h-5 text-indigo-400" />
            <span>{t('settings.display.dark')}</span>
          </button>

          {/* System Theme */}
          <button
            type="button"
            data-testid="theme-option-system"
            role="radio"
            aria-checked={currentTheme === 'system'}
            onClick={() => handleSelectTheme('system')}
            className={cn(
              'flex flex-col items-center justify-center gap-2 p-4 rounded-xl border text-xs font-semibold transition-all min-h-[44px]',
              currentTheme === 'system'
                ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] border-emerald-500 ring-2 ring-emerald-500/30'
                : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border-[var(--cf-border)] hover:bg-[var(--cf-surface-3)] hover:text-[var(--cf-fg)]'
            )}
          >
            <Laptop className="w-5 h-5 text-slate-500" />
            <span>{t('settings.display.system')}</span>
          </button>
        </div>
      </div>

      {/* Language & Regional Formatting */}
      <div className="space-y-3 pb-6 border-b border-[var(--cf-border)]">
        <label className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
          <Globe className="w-4 h-4 text-[var(--cf-fg-subtle)]" />
          <span>{t('settings.display.languageTitle')}</span>
        </label>
        <p className="text-xs text-[var(--cf-fg-muted)]">
          {t('settings.display.languageDescription')}
        </p>

        <div
          data-testid="locale-selector-group"
          role="radiogroup"
          aria-label="Language & Regional Formatting Options"
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 pt-2"
        >
          {availableLocales.map((item) => {
            const isSelected = locale === item.code;
            return (
              <button
                key={item.code}
                type="button"
                data-testid={`locale-option-${item.code}`}
                role="radio"
                aria-checked={isSelected}
                onClick={() => setLocale(item.code)}
                className={cn(
                  'flex flex-col items-start justify-between gap-1.5 p-3.5 rounded-xl border text-left transition-all min-h-[56px]',
                  isSelected
                    ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] border-emerald-500 ring-2 ring-emerald-500/30'
                    : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border-[var(--cf-border)] hover:bg-[var(--cf-surface-3)] hover:text-[var(--cf-fg)]'
                )}
              >
                <div className="w-full flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-[var(--cf-fg)]">
                    {item.nativeName}
                  </span>
                  <div className="flex items-center gap-1.5">
                    {item.direction === 'rtl' && (
                      <span
                        data-testid={`locale-rtl-badge-${item.code}`}
                        className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30"
                      >
                        {t('settings.display.rtlBadge')}
                      </span>
                    )}
                    <span className="text-[11px] font-mono text-[var(--cf-fg-subtle)]">
                      {item.code}
                    </span>
                  </div>
                </div>
                <span className="text-xs text-[var(--cf-fg-subtle)]">
                  {item.name}
                </span>
              </button>
            );
          })}
        </div>

        {/* Live Localized Date & Number Preview */}
        <div
          data-testid="locale-format-preview"
          className="mt-3 p-3.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] flex flex-wrap items-center justify-between gap-4 text-xs"
        >
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[var(--cf-fg)]">
              {t('settings.display.previewDate')}:
            </span>
            <span className="font-mono text-[var(--cf-fg-muted)]">
              {formatDate(SAMPLE_PREVIEW_DATE, {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
              }, 'UTC')}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[var(--cf-fg)]">
              {t('settings.display.previewNumber')}:
            </span>
            <span className="font-mono text-[var(--cf-fg-muted)]">
              {formatNumber(SAMPLE_PREVIEW_NUMBER)}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-mono uppercase px-2 py-0.5 rounded bg-[var(--cf-surface)] border border-[var(--cf-border)] text-[var(--cf-fg-subtle)]">
              {locale} · {direction.toUpperCase()}
            </span>
          </div>
        </div>
      </div>

      {/* Typography & Contrast */}
      <div className="space-y-3">
        <label className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
          <Type className="w-4 h-4 text-[var(--cf-fg-subtle)]" />
          <span>{t('settings.display.a11yTitle')}</span>
        </label>
        <p className="text-xs text-[var(--cf-fg-muted)]">
          {t('settings.display.a11yDesc')}
        </p>
        <div className="p-4 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] text-xs text-[var(--cf-fg-subtle)] leading-relaxed">
          • Text contrast ratio: ≥ 5.48:1 (Light) and ≥ 6.75:1 (Dark)<br />
          • Minimum touch target: 44×44px for all controls<br />
          • Keyboard focus indicator: 2px solid visible outline with 2px offset
        </div>
      </div>
    </div>
  );
}
