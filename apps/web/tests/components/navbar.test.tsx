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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within, act } from '@testing-library/react';
import React from 'react';
import { Navbar } from '@/components/Navbar';
import { ThemeProvider } from '@/components/ThemeProvider';

let currentPathname = '/';

vi.mock('next/navigation', () => ({
  usePathname: () => currentPathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));

function renderNavbar() {
  return render(
    <ThemeProvider defaultTheme="light">
      <Navbar />
    </ThemeProvider>
  );
}

describe('Navbar Mobile Navigation (Issue #89)', () => {
  beforeEach(() => {
    localStorage.clear();
    currentPathname = '/';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ollama: { reachable: true } })
    }));
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe('Desktop Navigation Preservation', () => {
    it('preserves desktop navigation container with hidden sm:flex', () => {
      const { container } = renderNavbar();
      const desktopNav = container.querySelector('nav.hidden.sm\\:flex');
      expect(desktopNav).toBeInTheDocument();
      expect(within(desktopNav as HTMLElement).getByRole('link', { name: /Marketplace/i })).toBeInTheDocument();
      expect(within(desktopNav as HTMLElement).getByRole('link', { name: /Library/i })).toBeInTheDocument();
      expect(within(desktopNav as HTMLElement).getByRole('link', { name: /Chat/i })).toBeInTheDocument();
    });
  });

  describe('Mobile Menu Toggle Button', () => {
    it('renders mobile menu toggle button with sm:hidden, data-testid="mobile-menu-toggle", aria-label, aria-expanded="false", and aria-controls="mobile-navigation"', () => {
      renderNavbar();
      const toggle = screen.getByTestId('mobile-menu-toggle');
      expect(toggle).toBeInTheDocument();
      expect(toggle.className).toContain('sm:hidden');
      expect(toggle).toHaveAttribute('aria-label', 'Toggle navigation menu');
      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      expect(toggle).toHaveAttribute('aria-controls', 'mobile-navigation');
    });

    it('does not render mobile disclosure panel initially', () => {
      renderNavbar();
      expect(screen.queryByTestId('mobile-navigation')).not.toBeInTheDocument();
    });
  });

  describe('Mobile Menu Disclosure & Touch Targets', () => {
    it('clicking toggle opens the mobile panel rendering Marketplace and Chat links with min-h-[44px] touch targets', () => {
      renderNavbar();
      const toggle = screen.getByTestId('mobile-menu-toggle');
      fireEvent.click(toggle);

      expect(toggle).toHaveAttribute('aria-expanded', 'true');
      const mobileNav = screen.getByTestId('mobile-navigation');
      expect(mobileNav).toBeInTheDocument();
      expect(mobileNav).toHaveAttribute('id', 'mobile-navigation');
      expect(mobileNav).toHaveAttribute('aria-label', 'Mobile navigation');

      const marketplaceLink = within(mobileNav).getByRole('link', { name: /Marketplace/i });
      const libraryLink = within(mobileNav).getByRole('link', { name: /Library/i });
      const chatLink = within(mobileNav).getByRole('link', { name: /Chat/i });

      expect(marketplaceLink).toBeInTheDocument();
      expect(libraryLink).toBeInTheDocument();
      expect(chatLink).toBeInTheDocument();
      expect(marketplaceLink).toHaveAttribute('href', '/');
      expect(libraryLink).toHaveAttribute('href', '/library');
      expect(chatLink).toHaveAttribute('href', '/chat');

      // Check min-h-[44px] touch targets
      expect(marketplaceLink.className).toContain('min-h-[44px]');
      expect(libraryLink.className).toContain('min-h-[44px]');
      expect(chatLink.className).toContain('min-h-[44px]');
    });

    it('clicking toggle a second time closes the mobile panel', () => {
      renderNavbar();
      const toggle = screen.getByTestId('mobile-menu-toggle');
      fireEvent.click(toggle);
      expect(screen.getByTestId('mobile-navigation')).toBeInTheDocument();

      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByTestId('mobile-navigation')).not.toBeInTheDocument();
    });
  });

  describe('Closing on Navigation & Keyboard Actions', () => {
    it('clicking a navigation link closes the menu', () => {
      renderNavbar();
      const toggle = screen.getByTestId('mobile-menu-toggle');
      fireEvent.click(toggle);

      const mobileNav = screen.getByTestId('mobile-navigation');
      const chatLink = within(mobileNav).getByRole('link', { name: /Chat/i });
      fireEvent.click(chatLink);

      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByTestId('mobile-navigation')).not.toBeInTheDocument();
    });

    it('pressing Escape closes the menu and returns focus to the toggle button', () => {
      renderNavbar();
      const toggle = screen.getByTestId('mobile-menu-toggle');
      toggle.focus();
      expect(toggle).toHaveFocus();

      fireEvent.click(toggle);
      expect(screen.getByTestId('mobile-navigation')).toBeInTheDocument();

      fireEvent.keyDown(window, { key: 'Escape' });

      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByTestId('mobile-navigation')).not.toBeInTheDocument();
      expect(toggle).toHaveFocus();
    });

    it('resizing window to >= 640px auto-closes the mobile panel', () => {
      renderNavbar();
      const toggle = screen.getByTestId('mobile-menu-toggle');
      fireEvent.click(toggle);
      expect(screen.getByTestId('mobile-navigation')).toBeInTheDocument();

      // Trigger resize >= 640px
      act(() => {
        window.innerWidth = 768;
        window.dispatchEvent(new Event('resize'));
      });

      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByTestId('mobile-navigation')).not.toBeInTheDocument();
    });
  });

  describe('Active Route Styling in Mobile Menu', () => {
    it('highlights the active route in mobile navigation', () => {
      currentPathname = '/chat';
      renderNavbar();

      const toggle = screen.getByTestId('mobile-menu-toggle');
      fireEvent.click(toggle);

      const mobileNav = screen.getByTestId('mobile-navigation');
      const chatLink = within(mobileNav).getByRole('link', { name: /Chat/i });
      const marketplaceLink = within(mobileNav).getByRole('link', { name: /Marketplace/i });

      expect(chatLink.className).toContain('bg-slate-100');
      expect(marketplaceLink.className).not.toContain('bg-slate-100');
    });
  });
});
