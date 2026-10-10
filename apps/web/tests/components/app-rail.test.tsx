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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { AppRail } from '@/components/layout/AppRail';
import { MobileTopBar } from '@/components/layout/MobileTopBar';
import { MobileTabBar } from '@/components/layout/MobileTabBar';
import type { CareProfile } from '@/app/p/[profileId]/HomeDashboardClient';

const mockProfile: CareProfile = {
  id: 'rosa',
  name: 'Rosa Rivera',
  relationship: 'Mom',
  colorSlot: 3,
  role: 'You manage'
};

describe('Navigation Shell (AppRail, MobileTopBar, MobileTabBar)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe('AppRail Component', () => {
    it('renders expanded rail with 256px width (w-64) by default', () => {
      render(
        <AppRail activeProfile={mockProfile} collapsed={false} />
      );

      const aside = screen.getByRole('navigation', { name: /primary application/i });
      expect(aside).toBeInTheDocument();
      expect(aside.className).toContain('w-64');
      expect(screen.getByTestId('app-rail')).toBeInTheDocument();
    });

    it('renders collapsed rail with 72px width when collapsed=true', () => {
      render(
        <AppRail activeProfile={mockProfile} collapsed={true} />
      );

      const aside = screen.getByRole('navigation', { name: /primary application/i });
      expect(aside.className).toContain('w-[72px]');
    });

    it('displays active profile name and relationship in profile switcher trigger', () => {
      render(
        <AppRail activeProfile={mockProfile} collapsed={false} />
      );

      expect(screen.getByText('Rosa Rivera')).toBeInTheDocument();
      expect(screen.getByText('Mom')).toBeInTheDocument();
    });

    it('triggers onToggleCollapse when collapse button is clicked', () => {
      const toggleFn = vi.fn();
      render(
        <AppRail activeProfile={mockProfile} collapsed={false} onToggleCollapse={toggleFn} />
      );

      const collapseBtn = screen.getByLabelText(/collapse sidebar/i);
      fireEvent.click(collapseBtn);
      expect(toggleFn).toHaveBeenCalledTimes(1);
    });

    it('renders Caring for [Person] section and Household section', () => {
      render(
        <AppRail activeProfile={mockProfile} collapsed={false} />
      );

      expect(screen.getByText(/caring for rosa/i)).toBeInTheDocument();
      expect(screen.getByText(/household/i)).toBeInTheDocument();
    });

    it('includes essential navigation links to profile home, chat, helpers, and settings', () => {
      render(
        <AppRail activeProfile={mockProfile} collapsed={false} />
      );

      expect(screen.getByRole('link', { name: /home/i })).toHaveAttribute('href', '/p/rosa');
      expect(screen.getByRole('link', { name: /chats/i })).toHaveAttribute('href', '/p/rosa/chat');
      expect(screen.getByRole('link', { name: /agents/i })).toHaveAttribute('href', '/agents');
      expect(screen.getByRole('link', { name: /family & profiles/i })).toHaveAttribute('href', '/family');
      expect(screen.getByRole('link', { name: /settings/i })).toHaveAttribute('href', '/settings');
    });

    it('renders safety disclaimer and data residency status badge', () => {
      render(
        <AppRail activeProfile={mockProfile} collapsed={false} />
      );

      expect(screen.getByText(/carefold helps you prepare/i)).toBeInTheDocument();
      const badge = screen.getByTestId('provider-status-badge');
      expect(badge).toBeInTheDocument();
    });

    it('guarantees >= 44px min-height touch targets on interactive rail links', () => {
      render(
        <AppRail activeProfile={mockProfile} collapsed={false} />
      );

      const links = screen.getAllByRole('link');
      links.forEach((link) => {
        expect(link.className).toContain('min-h-[44px]');
      });
    });
  });

  describe('MobileTopBar Component', () => {
    it('renders mobile top bar with 56px height (h-14) and brand mark', () => {
      render(
        <MobileTopBar activeProfile={mockProfile} />
      );

      const header = screen.getByRole('banner');
      expect(header).toBeInTheDocument();
      expect(header.className).toContain('h-14');
      expect(screen.getByText('Carefold')).toBeInTheDocument();
    });

    it('renders profile switcher button displaying active profile name', () => {
      const clickFn = vi.fn();
      render(
        <MobileTopBar activeProfile={mockProfile} onProfileClick={clickFn} />
      );

      const switcherBtn = screen.getByRole('button', { name: /switch care profile/i });
      expect(switcherBtn).toBeInTheDocument();
      expect(screen.getByText('Rosa')).toBeInTheDocument();

      fireEvent.click(switcherBtn);
      expect(clickFn).toHaveBeenCalledTimes(1);
    });

    it('provides settings link with >= 44px touch target', () => {
      render(
        <MobileTopBar activeProfile={mockProfile} />
      );

      const settingsLink = screen.getByRole('link', { name: /open settings/i });
      expect(settingsLink).toHaveAttribute('href', '/settings');
      expect(settingsLink.className).toContain('min-h-[44px]');
    });
  });

  describe('MobileTabBar Component', () => {
    it('renders mobile tab bar with 64px height (h-16) and 5 primary tabs', () => {
      render(
        <MobileTabBar activeProfile={mockProfile} />
      );

      const nav = screen.getByRole('navigation', { name: /mobile navigation/i });
      expect(nav).toBeInTheDocument();
      expect(nav.className).toContain('h-16');

      const tabs = screen.getAllByRole('link');
      expect(tabs.length).toBe(5);

      const tabLabels = tabs.map((t) => t.textContent?.trim());
      expect(tabLabels).toContain('Home');
      expect(tabLabels).toContain('Chat');
      expect(tabLabels).toContain('Agents');
      expect(tabLabels).toContain('Family');
      expect(tabLabels).toContain('Settings');
    });

    it('routes Chat tab to active profile chat /p/rosa/chat', () => {
      render(
        <MobileTabBar activeProfile={mockProfile} />
      );

      const chatTab = screen.getByRole('link', { name: /chat/i });
      expect(chatTab).toHaveAttribute('href', '/p/rosa/chat');
    });
  });
});
