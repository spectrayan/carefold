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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { Navbar } from '@/components/Navbar';
import { ThemeProvider } from '@/components/ThemeProvider';
import { AuthProvider } from '@/lib/auth';

vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));

function renderNavbarWithAuth() {
  return render(
    <ThemeProvider defaultTheme="light">
      <AuthProvider>
        <Navbar />
      </AuthProvider>
    </ThemeProvider>
  );
}

describe('Navbar Auth & Profile Integration', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders Local Mode badge in default disabled auth mode', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/auth/providers')) {
        return {
          ok: true,
          json: async () => ({ active_provider: 'disabled', sso_providers: [], registration_enabled: true })
        } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    renderNavbarWithAuth();

    await waitFor(() => {
      expect(screen.getByTestId('local-steward-badge')).toBeInTheDocument();
    });
    expect(screen.getByTestId('local-steward-badge')).toHaveTextContent(/Local Mode/i);
  });

  it('renders user button and dropdown menu when user is logged in', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/auth/providers')) {
        return {
          ok: true,
          json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
        } as any;
      }
      if (urlStr.includes('/auth/me')) {
        return {
          ok: true,
          json: async () => ({
            id: 'admin-id-1',
            username: 'sysadmin',
            email: 'admin@carefold.io',
            full_name: 'System Admin',
            role: 'admin',
            status: 'active',
            auth_provider: 'local',
            created_at: '2026-10-01T00:00:00Z'
          })
        } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    renderNavbarWithAuth();

    await waitFor(() => {
      expect(screen.getByTestId('user-profile-button')).toBeInTheDocument();
    });

    expect(screen.getByTestId('user-nav-role-badge')).toHaveTextContent('admin');

    // Click profile button to open dropdown
    fireEvent.click(screen.getByTestId('user-profile-button'));

    expect(screen.getByTestId('user-profile-dropdown')).toBeInTheDocument();
    expect(screen.getByTestId('nav-dropdown-admin-link')).toBeInTheDocument();
    expect(screen.getByTestId('nav-dropdown-settings-btn')).toBeInTheDocument();
    expect(screen.getByTestId('nav-dropdown-sign-out-btn')).toBeInTheDocument();
  });

  it('renders Sign In and Register links when in local mode and unauthenticated', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/auth/providers')) {
        return {
          ok: true,
          json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
        } as any;
      }
      if (urlStr.includes('/auth/me')) {
        return { ok: false, status: 401, json: async () => ({}) } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    renderNavbarWithAuth();

    await waitFor(() => {
      expect(screen.getByTestId('nav-sign-in-btn')).toBeInTheDocument();
    });
    expect(screen.getByTestId('nav-register-btn')).toBeInTheDocument();
    expect(screen.getByTestId('nav-sign-in-btn')).toHaveAttribute('href', '/login');
    expect(screen.getByTestId('nav-register-btn')).toHaveAttribute('href', '/register');
  });
});
