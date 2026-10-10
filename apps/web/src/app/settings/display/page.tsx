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

import React from 'react';
import { Sun, Moon, Laptop, Palette, Type } from 'lucide-react';
import { useOptionalTheme } from '@/components/ThemeProvider';
import { type Theme } from '@/lib/theme';
import { cn } from '@/lib/utils';

export default function DisplaySettingsPage() {
  const themeContext = useOptionalTheme();
  const currentTheme = themeContext?.theme || 'system';

  const handleSelectTheme = (t: Theme) => {
    themeContext?.setTheme(t);
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-bold text-[var(--cf-fg)] tracking-tight">
          Appearance & Display
        </h2>
        <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
          Customize theme palette, contrast modes, and text accessibility.
        </p>
      </div>

      {/* Theme Selection */}
      <div className="space-y-3 pb-6 border-b border-[var(--cf-border)]">
        <label className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
          <Palette className="w-4 h-4 text-[var(--cf-fg-subtle)]" />
          <span>Color Theme</span>
        </label>
        <p className="text-xs text-[var(--cf-fg-muted)]">
          Choose whether Carefold uses a light theme, dark slate theme, or follows your system settings.
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
            <span>Light</span>
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
            <span>Dark</span>
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
            <span>System</span>
          </button>
        </div>
      </div>

      {/* Typography & Contrast */}
      <div className="space-y-3">
        <label className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
          <Type className="w-4 h-4 text-[var(--cf-fg-subtle)]" />
          <span>Accessibility & Typography Floor</span>
        </label>
        <p className="text-xs text-[var(--cf-fg-muted)]">
          All typography strictly enforces a 12px font size minimum and WCAG 2.1 AA contrast across light and dark modes.
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
