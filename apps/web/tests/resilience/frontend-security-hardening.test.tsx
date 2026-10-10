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
import fs from 'fs';
import path from 'path';

import { ProfileSwitcher } from '@/components/layout/ProfileSwitcher';
import { MobileTopBar } from '@/components/layout/MobileTopBar';
import { MobileTabBar } from '@/components/layout/MobileTabBar';
import { AppRail } from '@/components/layout/AppRail';
import { Dialog, DialogContent } from '@/components/ui/Dialog';
import { Sheet, SheetContent } from '@/components/ui/Sheet';
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/Popover';
import { calculateContrastRatio, DESIGN_TOKENS } from '../contrast.test';
import { saveHouseholdProfiles, type CareProfile } from '@/lib/familyProfiles';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    prefetch: vi.fn()
  }),
  usePathname: () => '/p/me',
  useSearchParams: () => new URLSearchParams()
}));

describe('Frontend Hardening & Invariants Suite', () => {
  const testProfiles: CareProfile[] = [
    {
      id: 'me',
      name: 'Sam Rivera',
      shortName: 'Sam',
      relationship: 'Self',
      role: 'self',
      colorSlot: 1
    },
    {
      id: 'rosa',
      name: 'Rosa Rivera',
      shortName: 'Rosa',
      relationship: 'Mom',
      role: 'guardian',
      colorSlot: 3,
      age: 78
    },
    {
      id: 'leo',
      name: 'Leo Rivera',
      shortName: 'Leo',
      relationship: 'Child',
      role: 'guardian',
      colorSlot: 4,
      age: 10
    }
  ];

  beforeEach(() => {
    localStorage.clear();
    saveHouseholdProfiles(testProfiles);
    mockPush.mockClear();
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ modelReachable: true, workspace: true })
      })
    );
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  // ===========================================================================
  // Dimension 1: Layout Viewport & Geometry Invariants
  // ===========================================================================
  describe('Dimension 1: Layout Viewport & Geometry Invariants', () => {
    const globalsCssPath = path.resolve(__dirname, '../../src/app/globals.css');

    it('asserts 100dvh flex layout bounds in globals.css for full-height chat studio', () => {
      expect(fs.existsSync(globalsCssPath)).toBe(true);
      const css = fs.readFileSync(globalsCssPath, 'utf8');

      // Body rule when on chat page
      const bodyChatMatch = css.match(/body:has\(\[data-chat-page\]\)\s*\{([^}]+)\}/);
      expect(bodyChatMatch).not.toBeNull();
      const bodyProps = bodyChatMatch![1];
      expect(bodyProps).toContain('overflow: hidden');
      expect(bodyProps).toContain('height: 100dvh');
      expect(bodyProps).toContain('max-height: 100dvh');

      // Main element isolation rule
      const mainChatMatch = css.match(/body:has\(\[data-chat-page\]\)\s+main\s*\{([^}]+)\}/);
      expect(mainChatMatch).not.toBeNull();
      const mainProps = mainChatMatch![1];
      expect(mainProps).toContain('overflow: hidden !important');
      expect(mainProps).toContain('flex: 1 1 0% !important');
      expect(mainProps).toContain('min-height: 0 !important');
      expect(mainProps).toContain('padding: 0 !important');
    });

    it('probes MobileTopBar at 390px mobile viewport width with long profile names', () => {
      const longProfile = {
        id: 'dr-alexander',
        name: 'Dr. Bartholomew Montgomery-Alexander III',
        shortName: 'Bartholomew',
        colorSlot: 2 as const
      };

      const { container } = render(
        <div style={{ width: 390, maxWidth: 390 }} data-testid="mobile-390-wrapper">
          <MobileTopBar activeProfile={longProfile} />
        </div>
      );

      const header = container.querySelector('header');
      expect(header).toBeInTheDocument();
      expect(header?.className).toContain('h-14');
      expect(header?.className).toContain('shrink-0');

      // Verify name is truncated so it does not overflow 390px
      const nameSpan = container.querySelector('button span.truncate');
      expect(nameSpan).toBeInTheDocument();
      expect(nameSpan?.className).toContain('max-w-[120px]');
    });

    it('probes MobileTabBar at 390px mobile viewport width across all 5 navigation tabs', () => {
      const { container } = render(
        <div style={{ width: 390, maxWidth: 390 }} data-testid="mobile-tabbar-390">
          <MobileTabBar activeProfileId="me" />
        </div>
      );

      const nav = container.querySelector('nav');
      expect(nav).toBeInTheDocument();
      expect(nav?.className).toContain('grid');
      expect(nav?.className).toContain('grid-cols-5');
      expect(nav?.className).toContain('h-16');

      const tabLinks = container.querySelectorAll('nav a');
      expect(tabLinks.length).toBe(5);

      tabLinks.forEach((link) => {
        // Must satisfy 44x44px minimum touch target
        expect(link.className).toContain('min-h-[44px]');
        expect(link.className).toContain('min-w-[44px]');
        const label = link.querySelector('span');
        expect(label?.className).toContain('truncate');
        expect(label?.className).toContain('max-w-[60px]');
      });
    });

    it('probes touch targets >= 44x44px across MobileTopBar controls', () => {
      render(<MobileTopBar />);

      const homeLink = screen.getByRole('link', { name: /carefold home/i });
      expect(homeLink.className).toContain('min-h-[44px]');

      const profilePill = screen.getByRole('button', { name: /switch care profile/i });
      expect(profilePill.className).toContain('min-h-[44px]');

      const settingsLink = screen.getByRole('link', { name: /open settings/i });
      expect(settingsLink.className).toContain('min-h-[44px]');
      expect(settingsLink.className).toContain('min-w-[44px]');

      const themeBtn = screen.getByRole('button', { name: /switch to/i });
      expect(themeBtn.className).toContain('min-h-[44px]');
      expect(themeBtn.className).toContain('min-w-[44px]');
    });

    it('probes touch targets >= 44x44px across AppRail navigation and utility items', async () => {
      await act(async () => {
        render(<AppRail activeProfile={testProfiles[0]} />);
      });

      const navLinks = screen.getAllByRole('link');
      navLinks.forEach((link) => {
        expect(link.className).toContain('min-h-[44px]');
      });

      const privacyCard = screen.getByTestId('provider-status-badge');
      expect(privacyCard.className).toContain('min-h-[44px]');

      const collapsedBadge = screen.getByTestId('provider-status-badge-collapsed');
      expect(collapsedBadge.className).toContain('min-h-[44px]');
      expect(collapsedBadge.className).toContain('min-w-[44px]');

      const themeBtn = screen.getByRole('button', { name: /switch to/i });
      expect(themeBtn.className).toContain('min-h-[44px]');
      expect(themeBtn.className).toContain('min-w-[44px]');
    });

    it('verifies 56px row height requirement in ProfileSwitcher trigger and options', () => {
      render(<ProfileSwitcher activeProfileId="me" defaultOpen={true} />);

      // Switcher trigger must be at least 56px
      const trigger = screen.getByTestId('profile-switcher-trigger');
      expect(trigger.className).toContain('min-h-[56px]');

      // All profile options inside the listbox must be at least 56px
      const options = screen.getAllByRole('option');
      expect(options.length).toBeGreaterThanOrEqual(3);
      options.forEach((opt) => {
        expect(opt.className).toContain('min-h-[56px]');
      });
    });
  });

  // ===========================================================================
  // Dimension 2: Keyboard Navigation & Accessibility Invariants
  // ===========================================================================
  describe('Dimension 2: Keyboard Shortcuts & Accessibility Invariants', () => {
    it('probes sequential "G then P" shortcut activation and boundary conditions', () => {
      render(<ProfileSwitcher activeProfileId="me" />);

      // Initially closed
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

      // Successful sequential G then P within 1000ms
      fireEvent.keyDown(window, { key: 'g' });
      fireEvent.keyDown(window, { key: 'p' });
      expect(screen.getByRole('listbox')).toBeInTheDocument();

      // Press Escape to close
      fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Escape' });
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });

    it('rejects "G then P" when timeout exceeds 1000ms', () => {
      vi.useFakeTimers();
      render(<ProfileSwitcher activeProfileId="me" />);

      fireEvent.keyDown(window, { key: 'g' });
      vi.advanceTimersByTime(1100); // Exceeds 1000ms threshold
      fireEvent.keyDown(window, { key: 'p' });

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
      vi.useRealTimers();
    });

    it('rejects "G then P" when modifier keys or text inputs are active', () => {
      render(
        <div>
          <input data-testid="chat-input" type="text" />
          <textarea data-testid="chat-textarea" />
          <ProfileSwitcher activeProfileId="me" />
        </div>
      );

      // Modifier key held (Meta/Cmd+G, Meta/Cmd+P)
      fireEvent.keyDown(window, { key: 'g', metaKey: true });
      fireEvent.keyDown(window, { key: 'p', metaKey: true });
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

      // Inside input element
      const input = screen.getByTestId('chat-input');
      fireEvent.keyDown(input, { key: 'g' });
      fireEvent.keyDown(input, { key: 'p' });
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

      // Inside textarea element
      const textarea = screen.getByTestId('chat-textarea');
      fireEvent.keyDown(textarea, { key: 'g' });
      fireEvent.keyDown(textarea, { key: 'p' });
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });

    it('probes Escape dismiss across Dialog, Sheet, and Popover primitives', () => {
      // 1. Dialog Escape dismiss
      const onDialogChange = vi.fn();
      const { unmount: unmountDialog } = render(
        <Dialog open={true} onOpenChange={onDialogChange}>
          <DialogContent>
            <p>Dialog Body</p>
          </DialogContent>
        </Dialog>
      );
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onDialogChange).toHaveBeenCalledWith(false);
      unmountDialog();

      // 2. Sheet Escape dismiss
      const onSheetChange = vi.fn();
      const { unmount: unmountSheet } = render(
        <Sheet open={true} onOpenChange={onSheetChange}>
          <SheetContent>
            <p>Sheet Body</p>
          </SheetContent>
        </Sheet>
      );
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onSheetChange).toHaveBeenCalledWith(false);
      unmountSheet();

      // 3. Popover Escape dismiss
      const onPopoverChange = vi.fn();
      const { unmount: unmountPopover } = render(
        <Popover open={true} onOpenChange={onPopoverChange}>
          <PopoverTrigger>Open</PopoverTrigger>
          <PopoverContent>Popover Body</PopoverContent>
        </Popover>
      );
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onPopoverChange).toHaveBeenCalledWith(false);
      unmountPopover();
    });

    it('probes Tab trapping in DialogContent with forward and backward wrap-around', () => {
      render(
        <Dialog open={true}>
          <DialogContent>
            <button data-testid="first-btn">First</button>
            <input data-testid="mid-input" type="text" />
            <button data-testid="last-btn">Last</button>
          </DialogContent>
        </Dialog>
      );

      const firstBtn = screen.getByTestId('first-btn');
      const lastBtn = screen.getByTestId('last-btn');

      // Forward Tab from last button must wrap to first
      lastBtn.focus();
      expect(document.activeElement).toBe(lastBtn);
      fireEvent.keyDown(document, { key: 'Tab', shiftKey: false });
      expect(document.activeElement).toBe(firstBtn);

      // Backward Shift+Tab from first button must wrap to last
      firstBtn.focus();
      expect(document.activeElement).toBe(firstBtn);
      fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
      expect(document.activeElement).toBe(lastBtn);
    });

    it('probes live region announcements in ProfileSwitcher', () => {
      render(<ProfileSwitcher activeProfileId="me" defaultOpen={true} />);

      const liveRegion = screen.getByTestId('profile-switcher-live-region');
      expect(liveRegion).toHaveAttribute('aria-live', 'polite');
      expect(liveRegion).toHaveAttribute('aria-atomic', 'true');
      expect(liveRegion).toHaveAttribute('role', 'status');

      // Click Rosa
      const rosaOption = screen.getByTestId('profile-option-rosa');
      fireEvent.click(rosaOption);

      expect(liveRegion.textContent).toBe('Switched active profile to Rosa Rivera');
      expect(mockPush).toHaveBeenCalledWith('/p/rosa');
    });

    it('probes focus outlines and forced colors in globals.css', () => {
      const globalsCssPath = path.resolve(__dirname, '../../src/app/globals.css');
      const css = fs.readFileSync(globalsCssPath, 'utf8');

      // Global keyboard focus outline
      expect(css).toContain('outline: 2px solid var(--cf-focus)');
      expect(css).toContain('outline-offset: 2px');

      // Forced colors high-contrast support
      expect(css).toContain('@media (forced-colors: active)');
      expect(css).toContain('outline: 2px solid Highlight');
    });

    it('verifies WCAG AA programmatic contrast ratios for design tokens', () => {
      // 1. Emerald-700 on white surface (>= 4.5:1 requirement)
      const primaryRatio = calculateContrastRatio(
        DESIGN_TOKENS.light.primaryBtnBg,
        DESIGN_TOKENS.light.surface
      );
      expect(primaryRatio).toBeGreaterThanOrEqual(4.5);
      expect(primaryRatio).toBeCloseTo(5.48, 1);

      // 2. Input border on surface (>= 3.0:1 requirement)
      const borderRatio = calculateContrastRatio(
        DESIGN_TOKENS.light.borderStrong,
        DESIGN_TOKENS.light.surface
      );
      expect(borderRatio).toBeGreaterThanOrEqual(3.0);
      expect(borderRatio).toBeCloseTo(3.33, 1);

      // 3. Dark mode input border on dark surface (>= 3.0:1 requirement)
      const darkBorderRatio = calculateContrastRatio(
        DESIGN_TOKENS.dark.borderStrong,
        DESIGN_TOKENS.dark.surface
      );
      expect(darkBorderRatio).toBeGreaterThanOrEqual(3.0);
      expect(darkBorderRatio).toBeCloseTo(3.35, 1);

      // 4. Dark mode button text on mint button (>= 4.5:1 requirement)
      const darkBtnRatio = calculateContrastRatio(
        DESIGN_TOKENS.dark.primaryBtnText,
        DESIGN_TOKENS.dark.primaryBtnBg
      );
      expect(darkBtnRatio).toBeGreaterThanOrEqual(4.5);
      expect(darkBtnRatio).toBeCloseTo(6.75, 1);

      // 5. Light focus ring on white (>= 3.0:1 requirement)
      const focusRatio = calculateContrastRatio(
        DESIGN_TOKENS.light.focusRing,
        DESIGN_TOKENS.light.surface
      );
      expect(focusRatio).toBeGreaterThanOrEqual(3.0);
      expect(focusRatio).toBeCloseTo(5.48, 1);
    });
  });
});
