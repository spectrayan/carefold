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

import { describe, it, expect } from 'vitest';

/**
 * Programmatic WCAG 2.1 Color Contrast Ratio Verification Suite.
 *
 * Requirements:
 * - WCAG AA Normal Text: contrast ratio >= 4.5:1
 * - WCAG AA Large Text / Non-Text UI boundaries & focus rings: contrast ratio >= 3.0:1
 * - Primary interactive token: emerald-700 (#047857) text contrast >= 4.5:1
 * - Form input borders: >= 3.0:1 UI boundary contrast against surface
 */

// =============================================================================
// WCAG 2.1 Color Contrast Calculation Utilities
// =============================================================================

export function sRGBtoLinear(c: number): number {
  const norm = c / 255;
  return norm <= 0.03928 ? norm / 12.92 : Math.pow((norm + 0.055) / 1.055, 2.4);
}

export function hexToRgb(hex: string): [number, number, number] {
  const cleanHex = hex.replace('#', '').trim();
  if (cleanHex.length === 3) {
    const r = parseInt(cleanHex[0] + cleanHex[0], 16);
    const g = parseInt(cleanHex[1] + cleanHex[1], 16);
    const b = parseInt(cleanHex[2] + cleanHex[2], 16);
    return [r, g, b];
  }
  const r = parseInt(cleanHex.substring(0, 2), 16);
  const g = parseInt(cleanHex.substring(2, 4), 16);
  const b = parseInt(cleanHex.substring(4, 6), 16);
  return [r, g, b];
}

export function getRelativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex);
  return 0.2126 * sRGBtoLinear(r) + 0.7152 * sRGBtoLinear(g) + 0.0722 * sRGBtoLinear(b);
}

export function calculateContrastRatio(hex1: string, hex2: string): number {
  const lum1 = getRelativeLuminance(hex1);
  const lum2 = getRelativeLuminance(hex2);
  const brightest = Math.max(lum1, lum2);
  const darkest = Math.min(lum1, lum2);
  return (brightest + 0.05) / (darkest + 0.05);
}

// =============================================================================
// DESIGN SYSTEM TOKENS UNDER TEST
// =============================================================================

export const DESIGN_TOKENS = {
  light: {
    bg: '#f7faf8',
    surface: '#ffffff',
    textPrimary: '#0f172a',
    textMuted: '#475569',
    textSubtle: '#5b6b7f',
    // Primary interactive (Emerald-700)
    primaryBtnBg: '#047857',
    primaryBtnText: '#ffffff',
    primaryBtnHover: '#065f46',
    primaryLinkText: '#047857',
    primaryAccentText: '#065f46',
    primaryAccentBg: '#ecfdf5',
    // Input boundaries & rings
    borderStrong: '#7f8ea3',
    borderSubtle: '#cbd5e1',
    focusRing: '#047857',
    // Semantic alerts
    warningText: '#92400e',
    warningBg: '#fffbeb',
    dangerText: '#b91c1c',
    dangerBg: '#fef2f2',
    infoText: '#3730a3',
    infoBg: '#eef2ff',
    emergencyText: '#ffffff',
    emergencyBg: '#b91c1c',
    // Profile Avatars
    avatars: {
      emerald: { text: '#065f46', bg: '#d1fae5' },
      violet: { text: '#5b21b6', bg: '#ede9fe' },
      amber: { text: '#92400e', bg: '#fef3c7' },
      sky: { text: '#075985', bg: '#e0f2fe' },
      rose: { text: '#9f1239', bg: '#ffe4e6' },
    },
  },
  dark: {
    bg: '#0b1220',
    surface: '#111a2b',
    textPrimary: '#e2e8f0',
    textMuted: '#94a3b8',
    textSubtle: '#8291a7',
    brandText: '#34d399',
    // Primary interactive
    primaryBtnBg: '#10b981',
    primaryBtnText: '#04201a',
    primaryBtnHover: '#34d399',
    // Input boundaries & rings
    borderStrong: '#5b6e8a',
    borderSubtle: '#334155',
    focusRing: '#34d399',
    // Semantic alerts
    warningText: '#fcd34d',
    warningBg: '#111a2b',
    dangerText: '#fca5a5',
    dangerBg: '#111a2b',
    // Profile Avatars
    avatars: {
      emerald: { text: '#a7f3d0', bg: '#064e3b' },
      violet: { text: '#ddd6fe', bg: '#3b2a6e' },
      amber: { text: '#fde68a', bg: '#5a3410' },
      sky: { text: '#bae6fd', bg: '#0c3a55' },
      rose: { text: '#fecdd3', bg: '#5b1426' },
    },
  },
  legacy: {
    emerald600: '#059669',
    slate200Border: '#e2e8f0',
    zinc800Border: '#27272a',
    zinc900Bg: '#18181b',
  },
};

// =============================================================================
// TEST SUITE
// =============================================================================

describe('E2E Contrast Suite: Programmatic WCAG AA Contrast Checks', () => {
  // ---------------------------------------------------------------------------
  // Tier 1: Feature Coverage (Primary buttons, links, inputs, semantic text)
  // ---------------------------------------------------------------------------
  describe('Tier 1: Feature Coverage — Primary Interactive & Boundaries', () => {
    it('f-contrast-01: verifies emerald-700 #047857 text on white meets WCAG AA (>= 4.5:1)', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.light.primaryLinkText, DESIGN_TOKENS.light.surface);
      expect(cr).toBeGreaterThanOrEqual(4.5);
      expect(cr).toBeCloseTo(5.48, 1);
    });

    it('f-contrast-02: verifies white text on emerald-700 primary button meets WCAG AA (>= 4.5:1)', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.light.primaryBtnText, DESIGN_TOKENS.light.primaryBtnBg);
      expect(cr).toBeGreaterThanOrEqual(4.5);
      expect(cr).toBeCloseTo(5.48, 1);
    });

    it('f-contrast-03: verifies light input borders (border-strong #7f8ea3 on white) meet non-text UI contrast (>= 3.0:1)', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.light.borderStrong, DESIGN_TOKENS.light.surface);
      expect(cr).toBeGreaterThanOrEqual(3.0);
    });

    it('f-contrast-04: verifies dark input borders (border-strong #5b6e8a on surface #111a2b) meet UI contrast (>= 3.0:1)', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.dark.borderStrong, DESIGN_TOKENS.dark.surface);
      expect(cr).toBeGreaterThanOrEqual(3.0);
    });

    it('f-contrast-05: verifies dark primary button (#04201a ink on emerald-500 #10b981) meets WCAG AA (>= 4.5:1)', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.dark.primaryBtnText, DESIGN_TOKENS.dark.primaryBtnBg);
      expect(cr).toBeGreaterThanOrEqual(4.5);
    });

    it('f-contrast-06: verifies light focus ring (#047857 on white) meets non-text UI contrast (>= 3.0:1)', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.light.focusRing, DESIGN_TOKENS.light.surface);
      expect(cr).toBeGreaterThanOrEqual(3.0);
    });

    it('f-contrast-07: verifies dark focus ring (#34d399 on dark canvas #0b1220) meets non-text UI contrast (>= 3.0:1)', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.dark.focusRing, DESIGN_TOKENS.dark.bg);
      expect(cr).toBeGreaterThanOrEqual(3.0);
    });
  });

  // ---------------------------------------------------------------------------
  // Tier 2: Boundary & Corner Cases (Hover deltas, subtle text, black/white extremes)
  // ---------------------------------------------------------------------------
  describe('Tier 2: Boundary & Corner Cases', () => {
    it('b-contrast-01: verifies light primary hover (#ffffff on #065f46) provides increased contrast (>= 7.0:1 AAA)', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.light.primaryBtnText, DESIGN_TOKENS.light.primaryBtnHover);
      expect(cr).toBeGreaterThanOrEqual(7.0);
    });

    it('b-contrast-02: verifies dark primary hover (#04201a on #34d399) maintains contrast >= 4.5:1', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.dark.primaryBtnText, DESIGN_TOKENS.dark.primaryBtnHover);
      expect(cr).toBeGreaterThanOrEqual(4.5);
    });

    it('b-contrast-03: verifies light text-subtle (#5b6b7f on white) stays above strict 4.5:1 floor', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.light.textSubtle, DESIGN_TOKENS.light.surface);
      expect(cr).toBeGreaterThanOrEqual(4.5);
    });

    it('b-contrast-04: verifies dark text-subtle (#8291a7 on surface #111a2b) stays above strict 4.5:1 floor', () => {
      const cr = calculateContrastRatio(DESIGN_TOKENS.dark.textSubtle, DESIGN_TOKENS.dark.surface);
      expect(cr).toBeGreaterThanOrEqual(4.5);
    });

    it('b-contrast-05: verifies pure black #000000 on pure white #ffffff yields maximum 21:1 contrast ratio', () => {
      const cr = calculateContrastRatio('#000000', '#ffffff');
      expect(cr).toBeCloseTo(21.0, 1);
    });

    it('b-contrast-06: verifies identical colors yield 1:1 ratio without division by zero', () => {
      const cr = calculateContrastRatio('#047857', '#047857');
      expect(cr).toBeCloseTo(1.0, 2);
    });

    it('b-contrast-07: verifies 3-digit shorthand hex (#fff, #000) parses accurately', () => {
      const cr = calculateContrastRatio('#fff', '#000');
      expect(cr).toBeCloseTo(21.0, 1);
    });
  });

  // ---------------------------------------------------------------------------
  // Tier 3: Cross-Feature Combinations (Semantic badges, avatar chips, dark/light parity)
  // ---------------------------------------------------------------------------
  describe('Tier 3: Cross-Feature Combinations — Badges & Avatars', () => {
    it('c-contrast-01: verifies all light semantic status alerts meet WCAG AA (>= 4.5:1)', () => {
      const warningCr = calculateContrastRatio(DESIGN_TOKENS.light.warningText, DESIGN_TOKENS.light.warningBg);
      const dangerCr = calculateContrastRatio(DESIGN_TOKENS.light.dangerText, DESIGN_TOKENS.light.dangerBg);
      const infoCr = calculateContrastRatio(DESIGN_TOKENS.light.infoText, DESIGN_TOKENS.light.infoBg);
      const emergencyCr = calculateContrastRatio(DESIGN_TOKENS.light.emergencyText, DESIGN_TOKENS.light.emergencyBg);

      expect(warningCr).toBeGreaterThanOrEqual(4.5);
      expect(dangerCr).toBeGreaterThanOrEqual(4.5);
      expect(infoCr).toBeGreaterThanOrEqual(4.5);
      expect(emergencyCr).toBeGreaterThanOrEqual(4.5);
    });

    it('c-contrast-02: verifies all dark semantic status alerts meet WCAG AA (>= 4.5:1)', () => {
      const warningCr = calculateContrastRatio(DESIGN_TOKENS.dark.warningText, DESIGN_TOKENS.dark.warningBg);
      const dangerCr = calculateContrastRatio(DESIGN_TOKENS.dark.dangerText, DESIGN_TOKENS.dark.dangerBg);

      expect(warningCr).toBeGreaterThanOrEqual(4.5);
      expect(dangerCr).toBeGreaterThanOrEqual(4.5);
    });

    it('c-contrast-03: verifies all 5 light avatar tint chips (emerald, violet, amber, sky, rose) meet WCAG AA', () => {
      const avatars = DESIGN_TOKENS.light.avatars;
      for (const [key, pair] of Object.entries(avatars)) {
        const cr = calculateContrastRatio(pair.text, pair.bg);
        expect(cr, `Light avatar chip ${key} must meet 4.5:1`).toBeGreaterThanOrEqual(4.5);
      }
    });

    it('c-contrast-04: verifies all 5 dark avatar tint chips (emerald, violet, amber, sky, rose) meet WCAG AA', () => {
      const avatars = DESIGN_TOKENS.dark.avatars;
      for (const [key, pair] of Object.entries(avatars)) {
        const cr = calculateContrastRatio(pair.text, pair.bg);
        expect(cr, `Dark avatar chip ${key} must meet 4.5:1`).toBeGreaterThanOrEqual(4.5);
      }
    });
  });

  // ---------------------------------------------------------------------------
  // Tier 4: Real-World Workload Scenarios & Legacy Regression Guards
  // ---------------------------------------------------------------------------
  describe('Tier 4: Real-World Scenarios & Regression Proofs', () => {
    it('w-contrast-01: regression guard: confirms legacy emerald-600 #059669 failed WCAG AA (< 4.5:1) while #047857 passes', () => {
      const legacyCr = calculateContrastRatio(DESIGN_TOKENS.legacy.emerald600, '#ffffff');
      const newCr = calculateContrastRatio(DESIGN_TOKENS.light.primaryBtnBg, '#ffffff');

      // Legacy emerald-600 on white was ~3.77:1 (< 4.5:1, FAILING WCAG AA)
      expect(legacyCr).toBeLessThan(4.5);

      // New emerald-700 is >= 4.5:1 (PASSING WCAG AA)
      expect(newCr).toBeGreaterThanOrEqual(4.5);
    });

    it('w-contrast-02: regression guard: confirms legacy slate-200 border #e2e8f0 failed (< 3.0:1) while #7f8ea3 passes', () => {
      const legacyBorderCr = calculateContrastRatio(DESIGN_TOKENS.legacy.slate200Border, '#ffffff');
      const newBorderCr = calculateContrastRatio(DESIGN_TOKENS.light.borderStrong, '#ffffff');

      // Legacy slate-200 border was ~1.27:1 (FAILING)
      expect(legacyBorderCr).toBeLessThan(3.0);

      // New strong border is >= 3.0:1 (PASSING)
      expect(newBorderCr).toBeGreaterThanOrEqual(3.0);
    });

    it('w-contrast-03: regression guard: confirms legacy zinc-800 on zinc-900 failed (< 3.0:1) while slate token passes', () => {
      const legacyDarkBorderCr = calculateContrastRatio(
        DESIGN_TOKENS.legacy.zinc800Border,
        DESIGN_TOKENS.legacy.zinc900Bg
      );
      const newDarkBorderCr = calculateContrastRatio(
        DESIGN_TOKENS.dark.borderStrong,
        DESIGN_TOKENS.dark.surface
      );

      // Legacy zinc border on dark bg was ~1.36:1 (FAILING)
      expect(legacyDarkBorderCr).toBeLessThan(3.0);

      // New dark input border is >= 3.0:1 (PASSING)
      expect(newDarkBorderCr).toBeGreaterThanOrEqual(3.0);
    });

    it('w-contrast-04: end-to-end clinical consultation UI contrast path: validates full form surface journey', () => {
      // Step 1: User reads page title on canvas
      const titleOnBg = calculateContrastRatio(DESIGN_TOKENS.light.textPrimary, DESIGN_TOKENS.light.bg);
      expect(titleOnBg).toBeGreaterThanOrEqual(7.0); // Exceeds AAA

      // Step 2: User focuses input with strong boundary and emerald focus ring
      const inputBoundary = calculateContrastRatio(DESIGN_TOKENS.light.borderStrong, DESIGN_TOKENS.light.surface);
      const inputRing = calculateContrastRatio(DESIGN_TOKENS.light.focusRing, DESIGN_TOKENS.light.surface);
      expect(inputBoundary).toBeGreaterThanOrEqual(3.0);
      expect(inputRing).toBeGreaterThanOrEqual(3.0);

      // Step 3: User reads placeholder/subtle text
      const subtleOnSurface = calculateContrastRatio(DESIGN_TOKENS.light.textSubtle, DESIGN_TOKENS.light.surface);
      expect(subtleOnSurface).toBeGreaterThanOrEqual(4.5);

      // Step 4: User clicks primary submit button
      const buttonText = calculateContrastRatio(DESIGN_TOKENS.light.primaryBtnText, DESIGN_TOKENS.light.primaryBtnBg);
      expect(buttonText).toBeGreaterThanOrEqual(4.5);
    });

    it('w-contrast-05: regression guard: confirms 20% opacity focus ring emerald-500/20 fails WCAG 1.4.11 non-text contrast (< 3.0:1)', () => {
      // 20% alpha of emerald-500 (#10b981) blended over white (#ffffff)
      const blendedHex = '#cff1e6';
      const faintRingCr = calculateContrastRatio(blendedHex, '#ffffff');

      // Faint ring provides only ~1.21:1 contrast, strictly failing 3.0:1 non-text contrast
      expect(faintRingCr).toBeLessThan(3.0);
      expect(faintRingCr).toBeCloseTo(1.21, 1);

      // Solid emerald-700 focus outline provides 5.48:1, fully passing
      const solidRingCr = calculateContrastRatio(DESIGN_TOKENS.light.focusRing, '#ffffff');
      expect(solidRingCr).toBeGreaterThanOrEqual(3.0);
    });

    it('w-contrast-06: regression guard: confirms primary links in emerald-700 pass (>= 4.5:1) while legacy emerald-600 fails', () => {
      const legacyLinkCr = calculateContrastRatio(DESIGN_TOKENS.legacy.emerald600, '#ffffff');
      const newLinkCr = calculateContrastRatio(DESIGN_TOKENS.light.primaryLinkText, '#ffffff');

      expect(legacyLinkCr).toBeLessThan(4.5); // Legacy 3.77:1 fails
      expect(newLinkCr).toBeGreaterThanOrEqual(4.5); // New 5.48:1 passes
    });
  });
});

