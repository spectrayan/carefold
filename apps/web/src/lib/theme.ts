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

/**
 * Carefold Multi-Theme Utilities & Storage
 *
 * Provides theme types, localStorage persistence, OS preference detection,
 * and DOM reflection via document.documentElement class & attribute.
 */

export type Theme = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'carefold_theme';
export const VALID_THEMES: Theme[] = ['light', 'dark', 'system'];

/**
 * Returns the effective OS preference ('light' | 'dark').
 */
export function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'light';
  try {
    const mql = typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : null;
    return mql && mql.matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

/**
 * Reads initial theme from localStorage safely. Defaults to 'system'.
 */
export function getStoredTheme(defaultTheme: Theme = 'system'): Theme {
  if (typeof window === 'undefined' || !window.localStorage) return defaultTheme;
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY) as Theme;
    if (stored && VALID_THEMES.includes(stored)) {
      return stored;
    }
  } catch {
    // Storage access restricted or disabled
  }
  return defaultTheme;
}

/**
 * Persists selected theme to localStorage safely.
 */
export function setStoredTheme(theme: Theme): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage quota or sandboxed iframe protection
  }
}

/**
 * Resolves an abstract theme ('light' | 'dark' | 'system') into concrete 'light' | 'dark'.
 */
export function resolveTheme(theme: Theme): ResolvedTheme {
  if (theme === 'system') {
    return getSystemTheme();
  }
  return theme;
}

/**
 * Synchronously adds or removes the 'dark' class on document.documentElement
 * and sets the data-theme attribute.
 */
export function applyThemeToDOM(resolved: ResolvedTheme): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (resolved === 'dark') {
    root.classList.add('dark');
    root.setAttribute('data-theme', 'dark');
  } else {
    root.classList.remove('dark');
    root.setAttribute('data-theme', 'light');
  }
}

/**
 * CamelCase alias for applyThemeToDOM
 */
export const applyThemeToDom = applyThemeToDOM;
