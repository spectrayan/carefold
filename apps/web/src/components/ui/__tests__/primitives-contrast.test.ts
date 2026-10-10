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
import { calculateContrastRatio } from '../../../../tests/contrast.test';

describe('UI Primitives Design Token Contrast (WCAG 2.1 AA)', () => {
  describe('Primary Button Contrast', () => {
    it('Light mode: white text on primary emerald-700 (#047857) meets WCAG AA (>= 4.5:1)', () => {
      const ratio = calculateContrastRatio('#ffffff', '#047857');
      expect(ratio).toBeGreaterThanOrEqual(4.5);
      expect(ratio).toBeCloseTo(5.48, 1);
    });

    it('Light mode: white text on primary hover (#065f46) meets WCAG AAA (>= 7.0:1)', () => {
      const ratio = calculateContrastRatio('#ffffff', '#065f46');
      expect(ratio).toBeGreaterThanOrEqual(7.0);
    });

    it('Dark mode: dark ink (#04201a) on primary mint (#10b981) meets WCAG AA (>= 4.5:1)', () => {
      const ratio = calculateContrastRatio('#04201a', '#10b981');
      expect(ratio).toBeGreaterThanOrEqual(4.5);
      expect(ratio).toBeCloseTo(6.75, 1);
    });

    it('Dark mode: dark ink (#04201a) on hover mint (#34d399) meets WCAG AAA (>= 7.0:1)', () => {
      const ratio = calculateContrastRatio('#04201a', '#34d399');
      expect(ratio).toBeGreaterThanOrEqual(7.0);
    });
  });

  describe('UI Boundaries & Focus Rings (Non-Text >= 3.0:1)', () => {
    it('Light input/card border-strong (#7f8ea3) against white surface >= 3.0:1', () => {
      const ratio = calculateContrastRatio('#7f8ea3', '#ffffff');
      expect(ratio).toBeGreaterThanOrEqual(3.0);
    });

    it('Dark input/card border-strong (#5b6e8a) against dark surface (#111a2b) >= 3.0:1', () => {
      const ratio = calculateContrastRatio('#5b6e8a', '#111a2b');
      expect(ratio).toBeGreaterThanOrEqual(3.0);
    });

    it('Light focus ring (#047857) against white canvas >= 3.0:1', () => {
      const ratio = calculateContrastRatio('#047857', '#ffffff');
      expect(ratio).toBeGreaterThanOrEqual(3.0);
    });

    it('Dark focus ring (#34d399) against dark canvas (#0b1220) >= 3.0:1', () => {
      const ratio = calculateContrastRatio('#34d399', '#0b1220');
      expect(ratio).toBeGreaterThanOrEqual(3.0);
    });
  });

  describe('Status Badges & Alerts (>= 4.5:1)', () => {
    it('Light warning text (#92400e) on warning background (#fffbeb) >= 4.5:1', () => {
      const ratio = calculateContrastRatio('#92400e', '#fffbeb');
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('Light danger text (#b91c1c) on danger background (#fef2f2) >= 4.5:1', () => {
      const ratio = calculateContrastRatio('#b91c1c', '#fef2f2');
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('Light info text (#3730a3) on info background (#eef2ff) >= 4.5:1', () => {
      const ratio = calculateContrastRatio('#3730a3', '#eef2ff');
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('Light success text (#065f46) on success background (#ecfdf5) >= 4.5:1', () => {
      const ratio = calculateContrastRatio('#065f46', '#ecfdf5');
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('Emergency escalation white on red (#b91c1c) >= 4.5:1', () => {
      const ratio = calculateContrastRatio('#ffffff', '#b91c1c');
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });
  });

  describe('Family Member Avatars (1-5) (>= 4.5:1)', () => {
    const avatars = [
      { name: 'Member 1 (Emerald)', light: ['#065f46', '#d1fae5'], dark: ['#a7f3d0', '#064e3b'] },
      { name: 'Member 2 (Violet)', light: ['#5b21b6', '#ede9fe'], dark: ['#ddd6fe', '#3b2a6e'] },
      { name: 'Member 3 (Amber)', light: ['#92400e', '#fef3c7'], dark: ['#fde68a', '#5a3410'] },
      { name: 'Member 4 (Sky)', light: ['#075985', '#e0f2fe'], dark: ['#bae6fd', '#0c3a55'] },
      { name: 'Member 5 (Rose)', light: ['#9f1239', '#ffe4e6'], dark: ['#fecdd3', '#5b1426'] }
    ];

    avatars.forEach(({ name, light, dark }) => {
      it(`${name} meets WCAG AA in light mode`, () => {
        const ratio = calculateContrastRatio(light[0], light[1]);
        expect(ratio).toBeGreaterThanOrEqual(4.5);
      });

      it(`${name} meets WCAG AA in dark mode`, () => {
        const ratio = calculateContrastRatio(dark[0], dark[1]);
        expect(ratio).toBeGreaterThanOrEqual(4.5);
      });
    });
  });
});
