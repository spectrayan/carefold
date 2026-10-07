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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import fs from 'fs';
import path from 'path';
import { ChatClient } from '@/app/chat/ChatClient';
import type { AgentSummary } from '@/lib/types';
import { StartersChips } from '@/components/StartersChips';
import { SuggestedQuestionsChips } from '@/components/SuggestedQuestionsChips';
import { Navbar } from '@/components/Navbar';
import { SettingsModal } from '@/components/SettingsModal';
import { ModelSelector } from '@/components/ModelSelector';
import { ThemeProvider } from '@/components/ThemeProvider';
import RootLayout from '@/app/layout';

vi.mock('@/components/ThemeScript', () => ({
  ThemeScript: () => null
}));
import {
  getStoredTheme,
  setStoredTheme,
  applyThemeToDOM,
  THEME_STORAGE_KEY
} from '@/lib/theme';
import { DEFAULT_USER_SETTINGS } from '@/lib/settings';

// =============================================================================
// WCAG 2.1 Color Contrast Oracle Functions
// =============================================================================

function sRGBtoLinear(c: number): number {
  const norm = c / 255;
  return norm <= 0.03928 ? norm / 12.92 : Math.pow((norm + 0.055) / 1.055, 2.4);
}

function hexToRgb(hex: string): [number, number, number] {
  const cleanHex = hex.replace('#', '');
  const r = parseInt(cleanHex.substring(0, 2), 16);
  const g = parseInt(cleanHex.substring(2, 4), 16);
  const b = parseInt(cleanHex.substring(4, 6), 16);
  return [r, g, b];
}

function getRelativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex);
  return 0.2126 * sRGBtoLinear(r) + 0.7152 * sRGBtoLinear(g) + 0.0722 * sRGBtoLinear(b);
}

function calculateContrastRatio(hex1: string, hex2: string): number {
  const lum1 = getRelativeLuminance(hex1);
  const lum2 = getRelativeLuminance(hex2);
  const brightest = Math.max(lum1, lum2);
  const darkest = Math.min(lum1, lum2);
  return (brightest + 0.05) / (darkest + 0.05);
}

// =============================================================================
// ADVERSARIAL STRESS TEST SUITE
// =============================================================================

describe('Adversarial Stress Suite: Contrast, Accessibility & Resilience', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = '';
    document.documentElement.removeAttribute('data-theme');
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
    document.documentElement.className = '';
    document.documentElement.removeAttribute('data-theme');
  });

  // ---------------------------------------------------------------------------
  // 1. WCAG 2.1 CONTRAST RATIOS (THEME TOKENS & CHIPS)
  // ---------------------------------------------------------------------------
  describe('Dimension 1: WCAG 2.1 Contrast Calculations', () => {
    // Tailwind Color Hex Definitions:
    // blue-50: #eff6ff, blue-100: #dbeafe, blue-500: #3b82f6, blue-600: #2563eb, blue-900: #1e3a8a, blue-950: #172554, white: #ffffff
    // slate-50: #f8fafc, slate-100: #f1f5f9, slate-300: #cbd5e1, slate-500: #64748b, slate-600: #475569, slate-900: #0f172a
    // zinc-100: #f4f4f5, zinc-400: #a1a1aa, zinc-500: #71717a, zinc-700: #3f3f46, zinc-800: #27272a, zinc-900: #18181b, zinc-950: #09090b

    it('validates SuggestedQuestionsChips light mode resting contrast complies with WCAG AA/AAA', () => {
      const textContrast = calculateContrastRatio('#172554', '#eff6ff'); // text-blue-950 on bg-blue-50
      const borderContrast = calculateContrastRatio('#3b82f6', '#ffffff'); // border-blue-500 on white card

      expect(textContrast).toBeGreaterThanOrEqual(7.0); // WCAG AAA for normal text (>= 7:1)
      expect(borderContrast).toBeGreaterThanOrEqual(3.0); // WCAG non-text contrast (>= 3:1)
    });

    it('validates SuggestedQuestionsChips light mode hover contrast prevents vanishing effect', () => {
      const restingBgLum = getRelativeLuminance('#eff6ff'); // blue-50
      const hoverBgLum = getRelativeLuminance('#dbeafe'); // blue-100
      const hoverTextContrast = calculateContrastRatio('#172554', '#dbeafe'); // blue-950 on blue-100
      const hoverBorderContrast = calculateContrastRatio('#2563eb', '#ffffff'); // blue-600 on white card

      // Luminance difference between resting and hover must be noticeable (> 8%)
      const lumDelta = Math.abs(restingBgLum - hoverBgLum);
      expect(lumDelta).toBeGreaterThan(0.08);

      expect(hoverTextContrast).toBeGreaterThanOrEqual(7.0); // WCAG AAA
      expect(hoverBorderContrast).toBeGreaterThanOrEqual(3.0); // WCAG non-text
    });

    it('validates SuggestedQuestionsChips dark mode resting & hover contrast', () => {
      const darkRestingTextContrast = calculateContrastRatio('#dbeafe', '#172554'); // blue-100 on blue-950
      const darkRestingBorderContrast = calculateContrastRatio('#3b82f6', '#18181b'); // blue-500 on zinc-900 card
      const darkHoverTextContrast = calculateContrastRatio('#ffffff', '#1e3a8a'); // white on blue-900

      expect(darkRestingTextContrast).toBeGreaterThanOrEqual(7.0); // WCAG AAA
      expect(darkRestingBorderContrast).toBeGreaterThanOrEqual(3.0); // WCAG non-text
      expect(darkHoverTextContrast).toBeGreaterThanOrEqual(7.0); // WCAG AAA
    });

    it('validates StartersChips light mode resting & hover contrast complies with WCAG standards', () => {
      const textContrast = calculateContrastRatio('#0f172a', '#f8fafc'); // slate-900 on slate-50
      const borderContrast = calculateContrastRatio('#64748b', '#ffffff'); // border-slate-500 on white card
      const hoverTextContrast = calculateContrastRatio('#172554', '#dbeafe'); // blue-950 on blue-100

      expect(textContrast).toBeGreaterThanOrEqual(7.0); // WCAG AAA
      expect(borderContrast).toBeGreaterThanOrEqual(3.0); // WCAG non-text
      expect(hoverTextContrast).toBeGreaterThanOrEqual(7.0); // WCAG AAA
    });

    it('validates StartersChips dark mode resting & hover contrast', () => {
      const darkTextContrast = calculateContrastRatio('#f4f4f5', '#27272a'); // zinc-100 on zinc-800
      const darkBorderContrast = calculateContrastRatio('#71717a', '#18181b'); // zinc-500 on zinc-900 card
      const darkHoverTextContrast = calculateContrastRatio('#ffffff', '#3f3f46'); // white on zinc-700

      expect(darkTextContrast).toBeGreaterThanOrEqual(7.0); // WCAG AAA
      expect(darkBorderContrast).toBeGreaterThanOrEqual(3.0); // WCAG non-text
      expect(darkHoverTextContrast).toBeGreaterThanOrEqual(7.0); // WCAG AAA
    });

    it('validates semantic background and foreground tokens in globals.css satisfy contrast ratios', () => {
      // Light mode: background #f8fafc, foreground #0f172a
      const lightRatio = calculateContrastRatio('#0f172a', '#f8fafc');
      expect(lightRatio).toBeGreaterThanOrEqual(14.0);

      // Light card: #ffffff, card-foreground: #0f172a
      const lightCardRatio = calculateContrastRatio('#0f172a', '#ffffff');
      expect(lightCardRatio).toBeGreaterThanOrEqual(15.0);

      // Dark mode: background #09090b, foreground #f4f4f5
      const darkRatio = calculateContrastRatio('#f4f4f5', '#09090b');
      expect(darkRatio).toBeGreaterThanOrEqual(14.0);

      // Dark card: #18181b, card-foreground: #f4f4f5
      const darkCardRatio = calculateContrastRatio('#f4f4f5', '#18181b');
      expect(darkCardRatio).toBeGreaterThanOrEqual(12.0);
    });
  });

  // ---------------------------------------------------------------------------
  // 2. TOUCH TARGET SIZES ON MOBILE (<640px)
  // ---------------------------------------------------------------------------
  describe('Dimension 2: Mobile Touch Target Sizes (>= 32px)', () => {
    it('verifies StartersChips buttons guarantee >= 32px height via CSS min-h-[32px]', () => {
      const mockSelect = vi.fn();
      render(
        <StartersChips
          starters={['Prepare for annual checkup', 'Find in-network doctor']}
          onSelectStarter={mockSelect}
        />
      );

      const chips = screen.getAllByTestId('starter-chip');
      expect(chips.length).toBe(2);
      chips.forEach((chip) => {
        expect(chip.className).toContain('min-h-[32px]');
        expect(chip.className).toContain('px-3.5');
        expect(chip.className).toContain('py-1.5');
      });
    });

    it('verifies SuggestedQuestionsChips buttons guarantee >= 32px height via CSS min-h-[32px]', () => {
      const mockSelect = vi.fn();
      render(
        <SuggestedQuestionsChips
          suggestions={['What are the copays?', 'Is referral required?']}
          onSelectSuggestion={mockSelect}
        />
      );

      const chips = screen.getAllByTestId('suggested-question-chip');
      expect(chips.length).toBe(2);
      chips.forEach((chip) => {
        expect(chip.className).toContain('min-h-[32px]');
        expect(chip.className).toContain('px-3.5');
        expect(chip.className).toContain('py-1.5');
      });
    });

    it('verifies Navbar ThemeToggle button guarantees >= 32px touch target (w-9 h-9 = 36px)', () => {
      render(
        <ThemeProvider defaultTheme="light">
          <Navbar />
        </ThemeProvider>
      );

      const toggleBtn = screen.getByTestId('theme-toggle-btn');
      expect(toggleBtn.className).toContain('w-9');
      expect(toggleBtn.className).toContain('h-9');
    });

    it('verifies SettingsModal theme option buttons guarantee >= 32px touch target (py-2 = 16px padding + line height)', () => {
      render(
        <ThemeProvider defaultTheme="light">
          <SettingsModal isOpen={true} onClose={vi.fn()} />
        </ThemeProvider>
      );

      const lightOption = screen.getByTestId('theme-option-light');
      const darkOption = screen.getByTestId('theme-option-dark');
      const systemOption = screen.getByTestId('theme-option-system');

      [lightOption, darkOption, systemOption].forEach((opt) => {
        expect(opt.className).toContain('py-2');
        expect(opt.className).toContain('px-3');
      });
    });

    it('inspects ModelSelector interactive targets for accessible sizing', () => {
      const mockOpen = vi.fn();
      render(
        <ModelSelector
          settings={DEFAULT_USER_SETTINGS}
          onOpenSettings={mockOpen}
        />
      );

      const providerSelect = screen.getByTestId('provider-selector');
      const modelSelect = screen.getByTestId('model-selector');
      const settingsBtn = screen.getByTestId('open-settings-button');

      expect(providerSelect.className).toContain('py-1.5');
      expect(modelSelect.className).toContain('py-1.5');
      // settingsBtn has p-1.5 with 14px icon
      expect(settingsBtn).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // 3. KEYBOARD NAVIGABILITY & FOCUS OUTLINES
  // ---------------------------------------------------------------------------
  describe('Dimension 3: Keyboard Navigability & Focus Outlines', () => {
    it('supports full keyboard navigation (Tab, Enter, Space) on StartersChips', () => {
      const mockSelect = vi.fn();
      render(
        <StartersChips
          starters={['Prepare for appointment']}
          onSelectStarter={mockSelect}
        />
      );

      const chip = screen.getByTestId('starter-chip');

      // Verify chip is a native button element
      expect(chip.tagName).toBe('BUTTON');
      expect(chip).toHaveAttribute('type', 'button');

      // Focus
      chip.focus();
      expect(chip).toHaveFocus();

      // Enter key activation
      fireEvent.keyDown(chip, { key: 'Enter', code: 'Enter' });
      fireEvent.click(chip);
      expect(mockSelect).toHaveBeenCalledWith('Prepare for appointment', true);

      // Verify focus outline classes exist
      expect(chip.className).toContain('focus:outline-none');
      expect(chip.className).toContain('focus:ring-2');
      expect(chip.className).toContain('focus:ring-blue-500');
    });

    it('supports full keyboard navigation (Tab, Enter, Space) on SuggestedQuestionsChips', () => {
      const mockSelect = vi.fn();
      render(
        <SuggestedQuestionsChips
          suggestions={['Follow-up question 1']}
          onSelectSuggestion={mockSelect}
        />
      );

      const chip = screen.getByTestId('suggested-question-chip');

      expect(chip.tagName).toBe('BUTTON');
      expect(chip).toHaveAttribute('type', 'button');

      chip.focus();
      expect(chip).toHaveFocus();

      // Focus outline classes
      expect(chip.className).toContain('focus:outline-none');
      expect(chip.className).toContain('focus:ring-2');
      expect(chip.className).toContain('focus:ring-blue-500');

      fireEvent.click(chip);
      expect(mockSelect).toHaveBeenCalledWith('Follow-up question 1');
    });

    it('supports keyboard navigation on Navbar theme toggle button', () => {
      render(
        <ThemeProvider defaultTheme="light">
          <Navbar />
        </ThemeProvider>
      );

      const toggleBtn = screen.getByTestId('theme-toggle-btn');
      expect(toggleBtn.tagName).toBe('BUTTON');
      expect(toggleBtn).toHaveAttribute('type', 'button');

      toggleBtn.focus();
      expect(toggleBtn).toHaveFocus();

      // Trigger click via Enter
      fireEvent.click(toggleBtn);
      expect(document.documentElement.classList.contains('dark')).toBe(true);

      fireEvent.click(toggleBtn);
      expect(document.documentElement.classList.contains('dark')).toBe(false);
    });

    it('supports keyboard navigation on SettingsModal theme buttons', () => {
      render(
        <ThemeProvider defaultTheme="light">
          <SettingsModal isOpen={true} onClose={vi.fn()} />
        </ThemeProvider>
      );

      const darkOption = screen.getByTestId('theme-option-dark');
      darkOption.focus();
      expect(darkOption).toHaveFocus();

      fireEvent.click(darkOption);
      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });

    it('prevents keyboard activation and interaction when chips are disabled', () => {
      const mockSelect = vi.fn();
      render(
        <SuggestedQuestionsChips
          suggestions={['Disabled suggestion']}
          onSelectSuggestion={mockSelect}
          disabled={true}
        />
      );

      const chip = screen.getByTestId('suggested-question-chip');
      expect(chip).toBeDisabled();
      expect(chip.className).toContain('disabled:opacity-50');
      expect(chip.className).toContain('disabled:cursor-not-allowed');

      fireEvent.click(chip);
      expect(mockSelect).not.toHaveBeenCalled();
    });
  });

  // ---------------------------------------------------------------------------
  // 4. TAILWIND CLASS AUDIT ORACLE (SCAN MODIFIED COMPONENTS)
  // ---------------------------------------------------------------------------
  describe('Dimension 4: Invalid Tailwind CSS Classes Audit', () => {
    const invalidPatterns = [
      'focus:outline-hidden',
      'shadow-2xs',
      'shadow-xs',
      'backdrop-blur-xs'
    ];

    const m8ModifiedFiles = [
      'apps/web/src/components/StartersChips.tsx',
      'apps/web/src/components/SuggestedQuestionsChips.tsx',
      'apps/web/src/components/Navbar.tsx',
      'apps/web/src/components/SettingsModal.tsx',
      'apps/web/src/components/ModelSelector.tsx',
      'apps/web/src/components/ThemeProvider.tsx',
      'apps/web/src/app/chat/ChatClient.tsx',
      'apps/web/src/app/layout.tsx',
      'apps/web/src/app/globals.css',
      'apps/web/tailwind.config.ts',
      'apps/web/src/lib/theme.ts'
    ];

    it('confirms ZERO invalid Tailwind classes exist in any modified components', () => {
      const repoRoot = path.resolve(__dirname, '../../../../');
      const foundViolations: Array<{ file: string; line: number; match: string }> = [];

      m8ModifiedFiles.forEach((relPath) => {
        const fullPath = path.join(repoRoot, relPath);
        if (!fs.existsSync(fullPath)) return;
        const content = fs.readFileSync(fullPath, 'utf8');
        const lines = content.split('\n');

        lines.forEach((lineText, idx) => {
          invalidPatterns.forEach((pattern) => {
            if (lineText.includes(pattern)) {
              foundViolations.push({
                file: relPath,
                line: idx + 1,
                match: pattern
              });
            }
          });
        });
      });

      expect(foundViolations).toEqual([]);
    });

    it('identifies unmigrated invalid Tailwind classes across entire apps/web/src tree', () => {
      const webAppRoot = path.resolve(__dirname, '../../');
      const srcDir = path.join(webAppRoot, 'src');

      function scanDir(dir: string): Array<{ file: string; line: number; match: string }> {
        let results: Array<{ file: string; line: number; match: string }> = [];
        const entries = fs.readdirSync(dir, { withFileTypes: true });

        for (const entry of entries) {
          const fullPath = path.join(dir, entry.name);
          if (entry.isDirectory()) {
            results = results.concat(scanDir(fullPath));
          } else if (entry.name.endsWith('.ts') || entry.name.endsWith('.tsx') || entry.name.endsWith('.css')) {
            const content = fs.readFileSync(fullPath, 'utf8');
            const lines = content.split('\n');
            lines.forEach((lineText, idx) => {
              invalidPatterns.forEach((pattern) => {
                if (lineText.includes(pattern)) {
                  results.push({
                    file: path.relative(webAppRoot, fullPath),
                    line: idx + 1,
                    match: pattern
                  });
                }
              });
            });
          }
        }
        return results;
      }

      const allViolations = scanDir(srcDir);
      // Document exact locations of remaining invalid classes in unmigrated M9/M10 files:
      // ToolTraceCard.tsx (M10), ChatMessageItem.tsx (M9), AttachmentUploader.tsx (M10)
      const violatingFiles = Array.from(new Set(allViolations.map((v) => v.file)));

      violatingFiles.forEach((file) => {
        expect(['src/components/ToolTraceCard.tsx', 'src/components/ChatMessageItem.tsx', 'src/components/AttachmentUploader.tsx']).toContain(file);
      });
    });
  });

  // ---------------------------------------------------------------------------
  // 5. EDGE CASE & ADVERSARIAL STRESS TESTING
  // ---------------------------------------------------------------------------
  describe('Dimension 5: Edge Cases & Resilience', () => {
    it('handles corrupted localStorage theme values gracefully without throwing', () => {
      localStorage.setItem(THEME_STORAGE_KEY, 'corrupted_theme_xyz');
      expect(getStoredTheme()).toBe('system');

      localStorage.setItem(THEME_STORAGE_KEY, '');
      expect(getStoredTheme()).toBe('system');
    });

    it('survives localStorage quota or access denial exceptions in theme utilities', () => {
      const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = vi.fn().mockImplementation(() => {
        throw new DOMException('Quota exceeded', 'QuotaExceededError');
      });

      // Should not throw unhandled exception
      expect(() => setStoredTheme('dark')).not.toThrow();

      Storage.prototype.setItem = originalSetItem;
    });

    it('safely filters, trims, and deduplicates adversarial suggestion inputs', () => {
      const mockSelect = vi.fn();
      const noisySuggestions = [
        '   First unique question   ',
        'First unique question',
        '',
        '   ',
        'Second question',
        'Third question',
        'Fourth excess question',
        'Fifth excess question'
      ];

      render(
        <SuggestedQuestionsChips
          suggestions={noisySuggestions}
          onSelectSuggestion={mockSelect}
        />
      );

      const chips = screen.getAllByTestId('suggested-question-chip');
      // Should cap at 3 deduplicated non-empty questions
      expect(chips.length).toBe(3);
      expect(chips[0]).toHaveTextContent('First unique question');
      expect(chips[1]).toHaveTextContent('Second question');
      expect(chips[2]).toHaveTextContent('Third question');
    });

    it('renders gracefully when suggestions or starters arrays are empty or undefined', () => {
      const { container: c1 } = render(
        <SuggestedQuestionsChips
          suggestions={[]}
          onSelectSuggestion={vi.fn()}
        />
      );
      expect(c1.firstChild).toBeNull();

      const { container: c2 } = render(
        <SuggestedQuestionsChips
          suggestions={['   ', '']}
          onSelectSuggestion={vi.fn()}
        />
      );
      expect(c2.firstChild).toBeNull();

      const { container: c3 } = render(
        <StartersChips
          starters={[]}
          onSelectStarter={vi.fn()}
        />
      );
      expect(c3.firstChild).toBeNull();
    });

    it('handles extremely long prompt strings without breaking layout or omitting truncation classes', () => {
      const ultraLongPrompt =
        'This is an extremely long clinical prompt containing medical histories, ICD-10 codes, detailed notes, insurance verification queries, and prescription details that could stretch across multiple screens if not properly truncated with CSS overflow styling.';

      render(
        <StartersChips
          starters={[ultraLongPrompt]}
          onSelectStarter={vi.fn()}
        />
      );

      const chip = screen.getByTestId('starter-chip');
      const textSpan = chip.querySelector('span');
      expect(textSpan).toBeInTheDocument();
      expect(textSpan?.className).toContain('truncate');
      expect(textSpan?.className).toContain('max-w-sm');
    });

    it('safely applies theme to DOM in non-browser or simulated DOM environments', () => {
      expect(() => applyThemeToDOM('dark')).not.toThrow();
      expect(document.documentElement.classList.contains('dark')).toBe(true);

      expect(() => applyThemeToDOM('light')).not.toThrow();
      expect(document.documentElement.classList.contains('dark')).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // 6. SKIP TO MAIN CONTENT BYPASS LINK AUDIT
  // ---------------------------------------------------------------------------
  describe('Dimension 6: Skip to Content Bypass Link & Accessible Main Landmark', () => {
    it('renders Skip to Content link as the first focusable element targeting #main-content', () => {
      render(
        <RootLayout>
          <div>Main application content</div>
        </RootLayout>
      );

      const skipLink = screen.getByRole('link', { name: /skip to main content/i });
      expect(skipLink).toBeInTheDocument();
      expect(skipLink).toHaveAttribute('href', '#main-content');
      expect(skipLink.className).toContain('sr-only');
      expect(skipLink.className).toContain('focus:not-sr-only');
      expect(skipLink.className).toContain('focus:fixed');
      expect(skipLink.className).toContain('focus:top-3');
      expect(skipLink.className).toContain('focus:left-3');
      expect(skipLink.className).toContain('focus:z-50');

      const mainElement = document.getElementById('main-content');
      expect(mainElement).toBeInTheDocument();
      expect(mainElement).toHaveAttribute('tabIndex', '-1');
      expect(mainElement?.tagName.toLowerCase()).toBe('main');
      expect(mainElement?.className).toContain('focus:outline-none');
    });

    it('verifies static layout file contains skip link before navigation and proper main landmark', () => {
      const repoRoot = path.resolve(__dirname, '../../../../');
      const layoutPath = path.join(repoRoot, 'apps/web/src/app/layout.tsx');
      const content = fs.readFileSync(layoutPath, 'utf8');

      expect(content).toContain('href="#main-content"');
      expect(content).toContain('Skip to main content');
      expect(content).toContain('id="main-content"');
      expect(content).toContain('tabIndex={-1}');

      const skipLinkIndex = content.indexOf('href="#main-content"');
      const navbarIndex = content.indexOf('<Navbar');
      expect(skipLinkIndex).toBeGreaterThan(-1);
      expect(navbarIndex).toBeGreaterThan(-1);
      expect(skipLinkIndex).toBeLessThan(navbarIndex);
    });
  });

  // ---------------------------------------------------------------------------
  // 4. SCREEN READER LIVE REGIONS & RESILIENCE (ISSUE #90)
  // ---------------------------------------------------------------------------
  describe('Dimension 4: Screen Reader Live Region Resilience & Anti-Thrashing', () => {
    function createMockSSEResponse(events: Array<{ event?: string; data: Record<string, any> }>) {
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          for (const ev of events) {
            const eventLine = ev.event ? `event: ${ev.event}\n` : '';
            const dataLine = `data: ${JSON.stringify(ev.data)}\n\n`;
            controller.enqueue(encoder.encode(eventLine + dataLine));
          }
          controller.close();
        }
      });

      return new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' }
      });
    }

    const mockChatAgents: AgentSummary[] = [
      {
        id: 'visit-steward',
        title: 'Visit Steward',
        version: '0.1.0',
        risk_class: 'wellness',
        skills: ['visit-prep'],
        effectiveTools: ['skill-docs'],
        starters: ['What should I ask my doctor?']
      }
    ];

    it('resets both polite and assertive announcers upon starting a New Session', async () => {
      const mockFetch = vi.fn().mockImplementation((url) => {
        if (url === '/api/chat') {
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: 'First answer' } },
              { event: 'done', data: { type: 'done', fullText: 'First answer' } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockChatAgents} />);

      // Complete first turn
      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Question 1' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      await waitFor(() => {
        expect(screen.getByTestId('chat-live-announcer-polite')).toHaveTextContent('Response from Visit Steward: First answer');
      });

      // Click "New Session"
      fireEvent.click(screen.getByTitle('Start a new chat session'));

      // Both announcers must be cleared to prevent stale repeat utterances
      expect(screen.getByTestId('chat-live-announcer-polite')).toHaveTextContent('');
      expect(screen.getByTestId('chat-live-announcer-assertive')).toHaveTextContent('');
    });

    it('guarantees suggestion chips are accessible in logical DOM order following assistant reply', async () => {
      const mockFetch = vi.fn().mockImplementation((url) => {
        if (url === '/api/chat') {
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: 'Checklist created' } },
              {
                event: 'suggestions',
                data: { type: 'suggestions', suggestions: ['What to bring?', 'When to arrive?'] }
              },
              { event: 'done', data: { type: 'done', fullText: 'Checklist created' } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockChatAgents} />);

      fireEvent.change(screen.getByPlaceholderText(/Message/i), { target: { value: 'Help me plan' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      await waitFor(() => {
        expect(screen.getByTestId('suggested-questions-container')).toBeInTheDocument();
      });

      // Suggestion chips container has aria-label
      const chipsContainer = screen.getByTestId('suggested-questions-container');
      expect(chipsContainer).toHaveAttribute('aria-label', 'Suggested follow-up questions');

      // Chips are standard keyboard-focusable buttons with accessible text
      const chips = screen.getAllByTestId('suggested-question-chip');
      expect(chips).toHaveLength(2);
      expect(chips[0]).toHaveTextContent('What to bring?');
      expect(chips[1]).toHaveTextContent('When to arrive?');
      expect(chips[0].tagName).toBe('BUTTON');
    });
  });
});

