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
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ProfileSwitcher } from '@/components/layout/ProfileSwitcher';
import {
  switchProfileRoute,
  saveHouseholdProfiles,
  type CareProfile
} from '@/lib/familyProfiles';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    prefetch: vi.fn()
  }),
  usePathname: () => '/p/me/chat'
}));

describe('ProfileSwitcher Component & Route Sync', () => {
  const testProfiles: CareProfile[] = [
    {
      id: 'me',
      name: 'Sam Rivera',
      relationship: 'Self',
      role: 'self',
      colorSlot: 1
    },
    {
      id: 'rosa',
      name: 'Rosa Rivera',
      relationship: 'Mom',
      age: 78,
      role: 'guardian',
      colorSlot: 3
    },
    {
      id: 'leo',
      name: 'Leo Rivera',
      relationship: 'Child',
      age: 10,
      role: 'guardian',
      colorSlot: 4
    }
  ];

  beforeEach(() => {
    localStorage.clear();
    saveHouseholdProfiles(testProfiles);
    mockPush.mockClear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe('Group 1: Desktop Popover Trigger & Rendering', () => {
    it('renders active profile avatar, name, and relationship in trigger card', () => {
      render(<ProfileSwitcher activeProfileId="me" />);

      const trigger = screen.getByTestId('profile-switcher-trigger');
      expect(trigger).toBeInTheDocument();
      expect(trigger).toHaveAttribute('aria-haspopup', 'listbox');
      expect(trigger).toHaveAttribute('aria-expanded', 'false');
      expect(screen.getByText('Sam Rivera')).toBeInTheDocument();
      expect(screen.getByText('Self')).toBeInTheDocument();
    });

    it('expands popover on click with role="listbox" and 56px minimum row heights', () => {
      render(<ProfileSwitcher activeProfileId="me" />);

      const trigger = screen.getByTestId('profile-switcher-trigger');
      fireEvent.click(trigger);

      expect(trigger).toHaveAttribute('aria-expanded', 'true');
      const listbox = screen.getByRole('listbox', { name: /care profiles/i });
      expect(listbox).toBeInTheDocument();

      // Check all profile options rendered
      const options = screen.getAllByRole('option');
      expect(options.length).toBe(3);

      // Verify 56px minimum touch target / row height
      options.forEach((opt) => {
        expect(opt.className).toContain('min-h-[56px]');
      });
    });

    it('displays checkmark indicator on currently active profile option', () => {
      render(<ProfileSwitcher activeProfileId="me" defaultOpen={true} />);

      const meOption = screen.getByTestId('profile-option-me');
      expect(meOption).toHaveAttribute('aria-selected', 'true');

      const checkmark = screen.getByTestId('profile-active-check');
      expect(checkmark).toBeInTheDocument();

      const rosaOption = screen.getByTestId('profile-option-rosa');
      expect(rosaOption).toHaveAttribute('aria-selected', 'false');
    });
  });

  describe('Group 2: Keyboard Navigation & Sequential G then P Shortcut', () => {
    it('opens switcher popover when sequential G then P keys are pressed', () => {
      render(<ProfileSwitcher activeProfileId="me" />);

      const trigger = screen.getByTestId('profile-switcher-trigger');
      expect(trigger).toHaveAttribute('aria-expanded', 'false');

      // Press 'g' then 'p'
      fireEvent.keyDown(window, { key: 'g' });
      fireEvent.keyDown(window, { key: 'p' });

      expect(screen.getByRole('listbox')).toBeInTheDocument();
    });

    it('ignores sequential G then P when user is focused inside an input or textarea', () => {
      render(
        <div>
          <input data-testid="test-input" type="text" />
          <ProfileSwitcher activeProfileId="me" />
        </div>
      );

      const input = screen.getByTestId('test-input');
      input.focus();

      fireEvent.keyDown(input, { key: 'g' });
      fireEvent.keyDown(input, { key: 'p' });

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });

    it('supports ArrowDown, ArrowUp, and Enter to select an option', () => {
      const onSelect = vi.fn();
      render(<ProfileSwitcher activeProfileId="me" defaultOpen={true} onProfileSelect={onSelect} />);

      const listbox = screen.getByRole('listbox');
      // ArrowDown to move from 'me' (index 0) to 'rosa' (index 1)
      fireEvent.keyDown(listbox, { key: 'ArrowDown' });
      // Enter to select
      fireEvent.keyDown(listbox, { key: 'Enter' });

      expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'rosa' }));
      expect(mockPush).toHaveBeenCalledWith('/p/rosa/chat');
    });

    it('closes popover on Escape key press', () => {
      render(<ProfileSwitcher activeProfileId="me" defaultOpen={true} />);

      const listbox = screen.getByRole('listbox');
      fireEvent.keyDown(listbox, { key: 'Escape' });

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });
  });

  describe('Group 3: Route Synchronization Function', () => {
    it('preserves active subpath when switching between profiles', () => {
      expect(switchProfileRoute('/p/me/chat', 'rosa')).toBe('/p/rosa/chat');
      expect(switchProfileRoute('/p/rosa/library', 'leo')).toBe('/p/leo/library');
      expect(switchProfileRoute('/p/me/activity', 'rosa')).toBe('/p/rosa/activity');
      expect(switchProfileRoute('/p/me', 'rosa')).toBe('/p/rosa');
    });

    it('redirects global routes cleanly to profile home', () => {
      expect(switchProfileRoute('/family', 'rosa')).toBe('/p/rosa');
      expect(switchProfileRoute('/settings', 'leo')).toBe('/p/leo');
      expect(switchProfileRoute('/', 'me')).toBe('/p/me');
    });
  });

  describe('Group 4: Mobile Live Region Announcement', () => {
    it('announces profile switch via aria-live polite region', () => {
      render(<ProfileSwitcher activeProfileId="me" defaultOpen={true} />);

      const liveRegion = screen.getByTestId('profile-switcher-live-region');
      expect(liveRegion).toHaveAttribute('aria-live', 'polite');

      const rosaOption = screen.getByTestId('profile-option-rosa');
      fireEvent.click(rosaOption);

      expect(liveRegion.textContent).toBe('Switched active profile to Rosa Rivera');
    });
  });
});
