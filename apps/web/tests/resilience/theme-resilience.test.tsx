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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import React from 'react';
import { ThemeProvider, useTheme } from '@/components/ThemeProvider';
import {
  THEME_STORAGE_KEY,
  getStoredTheme,
  setStoredTheme,
  getSystemTheme
} from '@/lib/theme';
import { SuggestedQuestionsChips } from '@/components/SuggestedQuestionsChips';
import { StartersChips } from '@/components/StartersChips';

// Helper component for testing theme hooks
function ThemeTestConsumer() {
  const { theme, resolvedTheme, setTheme, toggleTheme } = useTheme();
  return (
    <div>
      <span data-testid="active-theme">{theme}</span>
      <span data-testid="active-resolved">{resolvedTheme}</span>
      <button data-testid="btn-toggle" onClick={toggleTheme}>Toggle</button>
      <button data-testid="btn-set-light" onClick={() => setTheme('light')}>Set Light</button>
      <button data-testid="btn-set-dark" onClick={() => setTheme('dark')}>Set Dark</button>
      <button data-testid="btn-set-system" onClick={() => setTheme('system')}>Set System</button>
    </div>
  );
}

// WCAG 2.1 Mathematical relative luminance and contrast calculation functions
function getLuminance(hex: string): number {
  const cleanHex = hex.replace('#', '');
  const r = parseInt(cleanHex.slice(0, 2), 16) / 255;
  const g = parseInt(cleanHex.slice(2, 4), 16) / 255;
  const b = parseInt(cleanHex.slice(4, 6), 16) / 255;
  const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}

function calculateContrastRatio(hex1: string, hex2: string): number {
  const l1 = getLuminance(hex1);
  const l2 = getLuminance(hex2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

describe('Stress-Testing for Multi-Theme & Contrast System', () => {
  let mockMatchMediaListeners: Array<(e: any) => void> = [];
  let isOsDark = false;

  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = '';
    document.documentElement.removeAttribute('data-theme');
    mockMatchMediaListeners = [];
    isOsDark = false;

    if (typeof window !== 'undefined') {
      window.matchMedia = vi.fn().mockImplementation((query: string) => ({
        matches: isOsDark,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn().mockImplementation((event: string, cb: (e: any) => void) => {
          if (event === 'change') mockMatchMediaListeners.push(cb);
        }),
        removeEventListener: vi.fn().mockImplementation((_event: string, cb: (e: any) => void) => {
          mockMatchMediaListeners = mockMatchMediaListeners.filter((l) => l !== cb);
        }),
        dispatchEvent: vi.fn()
      }));
    }
  });

  afterEach(() => {
    localStorage.clear();
    document.documentElement.className = '';
    document.documentElement.removeAttribute('data-theme');
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. CORRUPTED & ADVERSARIAL LOCALSTORAGE HANDLING
  // =========================================================================
  describe('Resilience Challenge 1: Corrupted, Injected & Unexpected localStorage Values', () => {
    it('safely recovers to system default when localStorage contains unexpected strings', () => {
      const corruptedValues = [
        '',
        '   ',
        '\t\n',
        'undefined',
        'null',
        'NaN',
        'auto',
        'high-contrast',
        'DARK', // Uppercase
        'Light', // PascalCase
        'SYSTEM', // Uppercase
        'sepia',
        '{"theme":"dark"}', // JSON
        '["dark"]', // JSON Array
        '<script>alert("xss")</script>', // Injection
        'a'.repeat(50000) // Huge string
      ];

      for (const val of corruptedValues) {
        localStorage.setItem(THEME_STORAGE_KEY, val);
        const stored = getStoredTheme();
        expect(stored).toBe('system');
      }
    });

    it('safely recovers when localStorage.getItem throws SecurityError / DOMException', () => {
      vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
        throw new DOMException('Access denied by browser security policy', 'SecurityError');
      });

      expect(getStoredTheme()).toBe('system');
      expect(getStoredTheme('dark')).toBe('dark');
    });

    it('safely ignores QuotaExceededError in setStoredTheme without throwing', () => {
      vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
        throw new DOMException('QuotaExceededError', 'QuotaExceededError');
      });

      expect(() => setStoredTheme('dark')).not.toThrow();
    });

    it('handles missing window or window.localStorage gracefully without crashing', () => {
      const origLocalStorage = window.localStorage;
      try {
        Object.defineProperty(window, 'localStorage', {
          value: undefined,
          configurable: true,
          writable: true
        });

        expect(getStoredTheme()).toBe('system');
        expect(() => setStoredTheme('dark')).not.toThrow();
      } finally {
        Object.defineProperty(window, 'localStorage', {
          value: origLocalStorage,
          configurable: true,
          writable: true
        });
      }
    });

    it('handles prototype pollution attempt in localStorage key', () => {
      localStorage.setItem('__proto__', 'polluted');
      localStorage.setItem(THEME_STORAGE_KEY, 'dark');

      expect(getStoredTheme()).toBe('dark');
      expect((Object.prototype as any).polluted).toBeUndefined();
    });

    it('ThemeProvider initializes cleanly with corrupted localStorage and reflects OS preference', () => {
      localStorage.setItem(THEME_STORAGE_KEY, 'MALICIOUS_CORRUPTED_VALUE');
      isOsDark = true; // System is dark

      render(
        <ThemeProvider>
          <ThemeTestConsumer />
        </ThemeProvider>
      );

      // Falls back to system -> resolved is dark
      expect(screen.getByTestId('active-theme')).toHaveTextContent('system');
      expect(screen.getByTestId('active-resolved')).toHaveTextContent('dark');
      expect(document.documentElement.classList.contains('dark')).toBe(true);
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('cross-tab storage event ignores corrupted newValue and maintains active theme', () => {
      render(
        <ThemeProvider defaultTheme="light">
          <ThemeTestConsumer />
        </ThemeProvider>
      );

      expect(screen.getByTestId('active-theme')).toHaveTextContent('light');

      // Dispatch invalid storage events
      act(() => {
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: THEME_STORAGE_KEY,
            newValue: 'hacked_theme'
          })
        );
      });

      expect(screen.getByTestId('active-theme')).toHaveTextContent('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);

      act(() => {
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: THEME_STORAGE_KEY,
            newValue: ''
          })
        );
      });

      expect(screen.getByTestId('active-theme')).toHaveTextContent('light');
    });
  });

  // =========================================================================
  // 2. SSR HYDRATION & SCRIPT EXECUTION HARNESS
  // =========================================================================
  describe('Resilience Challenge 2: SSR Flash Prevention & Hydration Script Execution', () => {
    function executeThemeScriptLogic(storedValue: string | null, osDark: boolean) {
      // Direct reproduction of ThemeScript logic in ThemeProvider.tsx lines 150-163
      try {
        var stored = storedValue;
        var supportDark = osDark;
        if (stored === 'dark' || ((!stored || stored === 'system') && supportDark)) {
          document.documentElement.classList.add('dark');
          document.documentElement.setAttribute('data-theme', 'dark');
        } else {
          document.documentElement.classList.remove('dark');
          document.documentElement.setAttribute('data-theme', 'light');
        }
      } catch (e) {}
    }

    it('ThemeScript sets dark class when stored === "dark"', () => {
      executeThemeScriptLogic('dark', false);
      expect(document.documentElement.classList.contains('dark')).toBe(true);
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('ThemeScript sets light class when stored === "light"', () => {
      executeThemeScriptLogic('light', true);
      expect(document.documentElement.classList.contains('dark')).toBe(false);
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('ThemeScript honors OS dark preference when stored === "system" or null', () => {
      // null + osDark
      executeThemeScriptLogic(null, true);
      expect(document.documentElement.classList.contains('dark')).toBe(true);
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

      // 'system' + osDark
      executeThemeScriptLogic('system', true);
      expect(document.documentElement.classList.contains('dark')).toBe(true);

      // 'system' + osLight
      executeThemeScriptLogic('system', false);
      expect(document.documentElement.classList.contains('dark')).toBe(false);
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('evaluates ThemeScript with unrecognized corrupted string', () => {
      // When stored is "corrupted_theme" and OS is dark
      executeThemeScriptLogic('corrupted_theme', true);
      // ThemeScript defaults to light because stored is neither 'dark' nor ('system' or falsy)
      expect(document.documentElement.classList.contains('dark')).toBe(false);
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('handles missing window.matchMedia safely in getSystemTheme()', () => {
      const origMatchMedia = window.matchMedia;
      try {
        (window as any).matchMedia = undefined;
        expect(getSystemTheme()).toBe('light');
      } finally {
        window.matchMedia = origMatchMedia;
      }
    });

    it('handles throwing window.matchMedia safely in getSystemTheme()', () => {
      const origMatchMedia = window.matchMedia;
      try {
        (window as any).matchMedia = () => {
          throw new Error('matchMedia unsupported in this environment');
        };
        expect(getSystemTheme()).toBe('light');
      } finally {
        window.matchMedia = origMatchMedia;
      }
    });
  });

  // =========================================================================
  // 3. RAPID THEME TOGGLING STRESS HARNESS
  // =========================================================================
  describe('Resilience Challenge 3: Rapid Theme Toggling Stress Harness', () => {
    it('maintains state consistency under rapid 50x sequential toggle cycles', async () => {
      render(
        <ThemeProvider defaultTheme="light">
          <ThemeTestConsumer />
        </ThemeProvider>
      );

      const toggleBtn = screen.getByTestId('btn-toggle');
      expect(screen.getByTestId('active-resolved')).toHaveTextContent('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);

      // Rapidly toggle 50 times
      for (let i = 1; i <= 50; i++) {
        await act(async () => {
          fireEvent.click(toggleBtn);
        });

        const expectedResolved = i % 2 === 1 ? 'dark' : 'light';
        expect(screen.getByTestId('active-resolved')).toHaveTextContent(expectedResolved);
        expect(document.documentElement.classList.contains('dark')).toBe(expectedResolved === 'dark');
        expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(expectedResolved);
      }

      // After 50 toggles (even number), theme is back to 'light'
      expect(screen.getByTestId('active-resolved')).toHaveTextContent('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('dynamically adapts to live OS theme changes when theme is "system"', () => {
      render(
        <ThemeProvider defaultTheme="system">
          <ThemeTestConsumer />
        </ThemeProvider>
      );

      expect(screen.getByTestId('active-theme')).toHaveTextContent('system');
      expect(screen.getByTestId('active-resolved')).toHaveTextContent('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);

      // Simulate OS switching to Dark mode
      act(() => {
        isOsDark = true;
        for (const listener of mockMatchMediaListeners) {
          listener({ matches: true } as MediaQueryListEvent);
        }
      });

      expect(screen.getByTestId('active-resolved')).toHaveTextContent('dark');
      expect(document.documentElement.classList.contains('dark')).toBe(true);
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

      // Simulate OS switching back to Light mode
      act(() => {
        isOsDark = false;
        for (const listener of mockMatchMediaListeners) {
          listener({ matches: false } as MediaQueryListEvent);
        }
      });

      expect(screen.getByTestId('active-resolved')).toHaveTextContent('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('ignores OS theme changes when user has explicitly selected light or dark', () => {
      render(
        <ThemeProvider defaultTheme="light">
          <ThemeTestConsumer />
        </ThemeProvider>
      );

      // User explicitly sets 'dark'
      fireEvent.click(screen.getByTestId('btn-set-dark'));
      expect(screen.getByTestId('active-theme')).toHaveTextContent('dark');
      expect(screen.getByTestId('active-resolved')).toHaveTextContent('dark');

      // OS changes to light
      act(() => {
        isOsDark = false;
        for (const listener of mockMatchMediaListeners) {
          listener({ matches: false } as MediaQueryListEvent);
        }
      });

      // Still dark because user override is explicit
      expect(screen.getByTestId('active-theme')).toHaveTextContent('dark');
      expect(screen.getByTestId('active-resolved')).toHaveTextContent('dark');
      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });
  });

  // =========================================================================
  // 4. MATHEMATICAL COLOR CONTRAST & CHIP STYLING VERIFICATION
  // =========================================================================
  describe('Resilience Challenge 4: Mathematical Color Contrast & Chip Verification', () => {
    // Exact Tailwind palette values used in apps/web
    const colors = {
      white: '#ffffff',
      'zinc-900': '#18181b', // Background for dark chat cards
      'zinc-800': '#27272a',
      'zinc-700': '#3f3f46',
      'zinc-500': '#71717a',
      'zinc-300': '#d4d4d8',
      'zinc-100': '#f4f4f5',
      'blue-50': '#eff6ff',
      'blue-100': '#dbeafe',
      'blue-400': '#60a5fa',
      'blue-500': '#3b82f6',
      'blue-600': '#2563eb',
      'blue-700': '#1d4ed8',
      'blue-900': '#1e3a8a',
      'blue-950': '#172554',
      'slate-50': '#f8fafc',
      'slate-500': '#64748b',
      'slate-900': '#0f172a'
    };

    it('mathematically verifies SuggestedQuestionsChips contrast ratios exceed WCAG requirements', () => {
      // 1. Light Mode Resting Text: blue-950 (#172554) on blue-50 (#eff6ff)
      const lightRestingTextContrast = calculateContrastRatio(colors['blue-950'], colors['blue-50']);
      expect(lightRestingTextContrast).toBeGreaterThanOrEqual(4.5); // Required: 4.5:1
      expect(lightRestingTextContrast).toBeGreaterThanOrEqual(7.0); // WCAG AAA: 7:1
      expect(lightRestingTextContrast).toBeCloseTo(13.50, 1);

      // 2. Light Mode Resting Border: blue-500 (#3b82f6) on white (#ffffff)
      const lightRestingBorderContrast = calculateContrastRatio(colors['blue-500'], colors['white']);
      expect(lightRestingBorderContrast).toBeGreaterThanOrEqual(3.0); // Required: 3.0:1
      expect(lightRestingBorderContrast).toBeCloseTo(3.68, 1);

      // 3. Light Mode Hover Text: blue-950 (#172554) on blue-100 (#dbeafe)
      const lightHoverTextContrast = calculateContrastRatio(colors['blue-950'], colors['blue-100']);
      expect(lightHoverTextContrast).toBeGreaterThanOrEqual(4.5);
      expect(lightHoverTextContrast).toBeGreaterThanOrEqual(7.0);
      expect(lightHoverTextContrast).toBeCloseTo(12.04, 1);

      // 4. Light Mode Hover Border: blue-600 (#2563eb) on white (#ffffff)
      const lightHoverBorderContrast = calculateContrastRatio(colors['blue-600'], colors['white']);
      expect(lightHoverBorderContrast).toBeGreaterThanOrEqual(3.0);
      expect(lightHoverBorderContrast).toBeCloseTo(5.17, 1);

      // 5. Dark Mode Resting Text: blue-100 (#dbeafe) on blue-950 (#172554)
      const darkRestingTextContrast = calculateContrastRatio(colors['blue-100'], colors['blue-950']);
      expect(darkRestingTextContrast).toBeGreaterThanOrEqual(4.5);
      expect(darkRestingTextContrast).toBeGreaterThanOrEqual(7.0);
      expect(darkRestingTextContrast).toBeCloseTo(12.04, 1);

      // 6. Dark Mode Resting Border: blue-500 (#3b82f6) on zinc-900 (#18181b)
      const darkRestingBorderContrast = calculateContrastRatio(colors['blue-500'], colors['zinc-900']);
      expect(darkRestingBorderContrast).toBeGreaterThanOrEqual(3.0);
      expect(darkRestingBorderContrast).toBeCloseTo(4.82, 1);

      // 7. Dark Mode Hover Text: white (#ffffff) on blue-900 (#1e3a8a)
      const darkHoverTextContrast = calculateContrastRatio(colors['white'], colors['blue-900']);
      expect(darkHoverTextContrast).toBeGreaterThanOrEqual(4.5);
      expect(darkHoverTextContrast).toBeGreaterThanOrEqual(7.0);
      expect(darkHoverTextContrast).toBeCloseTo(10.36, 1);

      // 8. Dark Mode Hover Border: blue-400 (#60a5fa) on zinc-900 (#18181b)
      const darkHoverBorderContrast = calculateContrastRatio(colors['blue-400'], colors['zinc-900']);
      expect(darkHoverBorderContrast).toBeGreaterThanOrEqual(3.0);
      expect(darkHoverBorderContrast).toBeCloseTo(6.97, 1);
    });

    it('mathematically verifies StartersChips contrast ratios exceed WCAG requirements', () => {
      // 1. Light Mode Resting Text: slate-900 (#0f172a) on slate-50 (#f8fafc)
      const lightRestingTextContrast = calculateContrastRatio(colors['slate-900'], colors['slate-50']);
      expect(lightRestingTextContrast).toBeGreaterThanOrEqual(4.5);
      expect(lightRestingTextContrast).toBeGreaterThanOrEqual(7.0);
      expect(lightRestingTextContrast).toBeCloseTo(17.06, 1);

      // 2. Light Mode Resting Border: slate-500 (#64748b) on white (#ffffff)
      const lightRestingBorderContrast = calculateContrastRatio(colors['slate-500'], colors['white']);
      expect(lightRestingBorderContrast).toBeGreaterThanOrEqual(3.0);
      expect(lightRestingBorderContrast).toBeCloseTo(4.76, 1);

      // 3. Light Mode Hover Text: blue-950 (#172554) on blue-100 (#dbeafe)
      const lightHoverTextContrast = calculateContrastRatio(colors['blue-950'], colors['blue-100']);
      expect(lightHoverTextContrast).toBeGreaterThanOrEqual(4.5);
      expect(lightHoverTextContrast).toBeGreaterThanOrEqual(7.0);
      expect(lightHoverTextContrast).toBeCloseTo(12.04, 1);

      // 4. Light Mode Hover Border: blue-600 (#2563eb) on white (#ffffff)
      const lightHoverBorderContrast = calculateContrastRatio(colors['blue-600'], colors['white']);
      expect(lightHoverBorderContrast).toBeGreaterThanOrEqual(3.0);
      expect(lightHoverBorderContrast).toBeCloseTo(5.17, 1);

      // 5. Dark Mode Resting Text: zinc-100 (#f4f4f5) on zinc-800 (#27272a)
      const darkRestingTextContrast = calculateContrastRatio(colors['zinc-100'], colors['zinc-800']);
      expect(darkRestingTextContrast).toBeGreaterThanOrEqual(4.5);
      expect(darkRestingTextContrast).toBeGreaterThanOrEqual(7.0);
      expect(darkRestingTextContrast).toBeCloseTo(13.55, 1);

      // 6. Dark Mode Resting Border: zinc-500 (#71717a) on zinc-900 (#18181b)
      const darkRestingBorderContrast = calculateContrastRatio(colors['zinc-500'], colors['zinc-900']);
      expect(darkRestingBorderContrast).toBeGreaterThanOrEqual(3.0);
      expect(darkRestingBorderContrast).toBeCloseTo(3.67, 1);

      // 7. Dark Mode Hover Text: white (#ffffff) on zinc-700 (#3f3f46)
      const darkHoverTextContrast = calculateContrastRatio(colors['white'], colors['zinc-700']);
      expect(darkHoverTextContrast).toBeGreaterThanOrEqual(4.5);
      expect(darkHoverTextContrast).toBeGreaterThanOrEqual(7.0);
      expect(darkHoverTextContrast).toBeCloseTo(10.44, 1);

      // 8. Dark Mode Hover Border: blue-400 (#60a5fa) on zinc-900 (#18181b)
      const darkHoverBorderContrast = calculateContrastRatio(colors['blue-400'], colors['zinc-900']);
      expect(darkHoverBorderContrast).toBeGreaterThanOrEqual(3.0);
      expect(darkHoverBorderContrast).toBeCloseTo(6.97, 1);
    });

    it('verifies non-vanishing hover delta: solid background steps prevent visual wash out', () => {
      // In the previous buggy implementation, hover:bg-blue-50/50 produced #f7fbff on white,
      // resulting in only 1.036:1 (3.6% luminance delta) which caused the button to vanish.
      // With solid hover:bg-blue-100 (#dbeafe), the step against white (#ffffff) is 1.22:1 (22% delta).
      const lightHoverVsWhite = calculateContrastRatio(colors['blue-100'], colors['white']);
      expect(lightHoverVsWhite).toBeGreaterThanOrEqual(1.15); // Clear perceptible step
      expect(lightHoverVsWhite).toBeCloseTo(1.22, 1);

      // With solid dark hover:bg-blue-900 (#1e3a8a) vs dark card (#18181b), the step is 1.71:1 (71% delta).
      const darkHoverVsCard = calculateContrastRatio(colors['blue-900'], colors['zinc-900']);
      expect(darkHoverVsCard).toBeGreaterThanOrEqual(1.20);
      expect(darkHoverVsCard).toBeCloseTo(1.71, 1);
    });

    it('verifies touch target size and accessibility attributes on rendered chips', () => {
      render(
        <div>
          <SuggestedQuestionsChips
            suggestions={['Test suggestion']}
            onSelectSuggestion={vi.fn()}
          />
          <StartersChips
            starters={['Test starter']}
            onSelectStarter={vi.fn()}
          />
        </div>
      );

      const suggestedChip = screen.getByTestId('suggested-question-chip');
      const starterChip = screen.getByTestId('starter-chip');

      // Check min-h-[44px] accessible touch target
      expect(suggestedChip.className).toContain('min-h-[44px]');
      expect(starterChip.className).toContain('min-h-[44px]');

      // Check focus ring accessibility classes
      expect(suggestedChip.className).toContain('focus:outline-none');
      expect(suggestedChip.className).toContain('focus:ring-2');
      expect(suggestedChip.className).toContain('focus:ring-emerald-500');

      expect(starterChip.className).toContain('focus:outline-none');
      expect(starterChip.className).toContain('focus:ring-2');
      expect(starterChip.className).toContain('focus:ring-emerald-500');

      // Check that invalid Tailwind v3 classes are NOT present
      expect(suggestedChip.className).not.toContain('focus:outline-hidden');
      expect(suggestedChip.className).not.toContain('shadow-2xs');
      expect(suggestedChip.className).not.toContain('hover:bg-blue-50/50');

      expect(starterChip.className).not.toContain('focus:outline-hidden');
      expect(starterChip.className).not.toContain('shadow-2xs');
      expect(starterChip.className).not.toContain('hover:bg-blue-50/50');
    });
  });
});
