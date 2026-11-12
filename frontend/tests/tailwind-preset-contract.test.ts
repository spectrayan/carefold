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

import fs from 'node:fs';
import path from 'node:path';
import postcss from 'postcss';
import tailwindcss from 'tailwindcss';
import { describe, expect, it } from 'vitest';
import { yarvellePreset } from '@yarvelle/ui/tailwind-preset';
import { yarvelleUiContentGlob } from '@yarvelle/ui/tokens';
import tailwindConfig from '../tailwind.config';

const frontendDir = path.resolve(__dirname, '..');
const globalsCssPath = path.resolve(frontendDir, 'src/app/globals.css');

async function compileStylesheet(): Promise<string> {
  const globalsCss = fs.readFileSync(globalsCssPath, 'utf8');
  const result = await postcss([tailwindcss(tailwindConfig)]).process(globalsCss, {
    from: globalsCssPath
  });
  return result.css;
}

describe('Tailwind preset & content-scan contract (#342)', () => {
  it('extends yarvellePreset and scans both src/health-ui/** and @yarvelle/ui dist bundles', () => {
    expect(tailwindConfig.presets).toBeDefined();
    expect(tailwindConfig.presets).toContain(yarvellePreset);
    expect(tailwindConfig.darkMode).toBe('class');

    const contentEntries = Array.isArray(tailwindConfig.content)
      ? tailwindConfig.content.filter((entry): entry is string => typeof entry === 'string')
      : [];

    expect(contentEntries).toContain('./src/health-ui/**/*.{js,ts,jsx,tsx,mdx}');
    expect(contentEntries).toContain('./src/lib/**/*.{js,ts,jsx,tsx}');
    expect(contentEntries).toContain(yarvelleUiContentGlob());
    expect(yarvelleUiContentGlob()).toMatch(/\/dist\/\*\*\/\*\.{js,mjs}$/);
  });

  it('resolves explicit rootDir overrides via yarvelleUiContentGlob from @yarvelle/ui 0.2.5', () => {
    expect(yarvelleUiContentGlob('/app/frontend')).toBe(
      '/app/frontend/node_modules/@yarvelle/ui/dist/**/*.{js,mjs}'
    );
  });

  it('emits safety-critical src/health-ui/** and @yarvelle/ui utility rules with non-transparent styles', async () => {
    const css = await compileStylesheet();

    // Exclusive src/health-ui/** utilities (e.g., EmergencyEscalationCard.tsx)
    expect(css).toContain('.bg-emergency');
    expect(css).toMatch(/\.bg-emergency\s*\{[^}]*background-color:\s*var\(--ui-emergency\)/);
    expect(css).toContain('.text-emergency-fg');
    expect(css).toMatch(/\.text-emergency-fg\s*\{[^}]*color:\s*var\(--ui-emergency-fg\)/);
    expect(css).toContain('.bg-red-50\\/95');
    expect(css).toContain('.dark\\:bg-red-950\\/40:is(.dark *)');
    expect(css).toContain('.bg-amber-600');
    expect(css).toContain('.animate-ping');
    expect(css).toContain('.min-h-\\[44px\\]');
    expect(css).toContain('.min-w-\\[280px\\]');

    // Exclusive @yarvelle/ui dist utilities from yarvellePreset
    expect(css).toContain('.bg-surface');
    expect(css).toMatch(/\.bg-surface\s*\{[^}]*background-color:\s*var\(--ui-surface\)/);
    expect(css).toContain('.text-primary-fg');
    expect(css).toMatch(/\.text-primary-fg\s*\{[^}]*color:\s*var\(--ui-primary-fg\)/);
    expect(css).toContain('.border-border-strong');
    expect(css).toContain('.border-danger-border');
    expect(css).toContain('.border-info-border');
    expect(css).toContain('.bg-warn-bg');
    expect(css).toContain('.bg-overlay');
    expect(css).toContain('.shadow-1');
    expect(css).toContain('.shadow-2');

    // Next.js font-family override coexists alongside yarvellePreset
    expect(css).toContain('.font-display');
    expect(css).toMatch(/\.font-display\s*\{[^}]*var\(--font-fraunces\)/);
  });

  it('compiles Carefold domain risk, line, and animation theme extensions cleanly', async () => {
    const result = await postcss([
      tailwindcss({
        ...tailwindConfig,
        content: [
          {
            raw: '<div class="border-line bg-risk-wellness-bg text-risk-assist-text animate-pulse-dot" />',
            extension: 'html'
          }
        ]
      })
    ]).process('@tailwind utilities;', { from: undefined });

    expect(result.css).toContain('.border-line');
    expect(result.css).toContain('.bg-risk-wellness-bg');
    expect(result.css).toContain('.text-risk-assist-text');
    expect(result.css).toContain('.animate-pulse-dot');
  });

  it('defines every --ui-* custom property referenced by yarvellePreset in globals.css', () => {
    const globalsCss = fs.readFileSync(globalsCssPath, 'utf8');
    const definedVars = new Set(
      Array.from(globalsCss.matchAll(/(--ui-[a-z0-9-]+)\s*:/g), (match) => match[1])
    );

    const presetSerialized = JSON.stringify(
      yarvellePreset.theme?.extend ?? {},
      (_key, value) => (typeof value === 'function' ? value({}) : value)
    );
    const referencedVars = Array.from(
      new Set(Array.from(presetSerialized.matchAll(/var\((--ui-[a-z0-9-]+)\)/g), (match) => match[1]))
    );

    expect(referencedVars.length).toBeGreaterThan(40);
    const missing = referencedVars.filter((token) => !definedVars.has(token));
    expect(missing).toEqual([]);
  });
});
