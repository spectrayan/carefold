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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import AdminClient from '@/app/admin/AdminClient';
import { AuthProvider } from '@/lib/auth';

const mockReplace = vi.fn();
vi.mock('next/navigation', () => ({
  usePathname: () => '/admin',
  useRouter: () => ({ push: vi.fn(), replace: mockReplace, prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));

describe('AdminClient Authorization & Redirection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', vi.fn());
  });

  it('redirects unauthenticated visitor to /login?redirect=/admin and renders 403 card', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/auth/providers')) {
        return {
          ok: true,
          json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
        } as any;
      }
      if (urlStr.includes('/auth/me')) {
        return { ok: false, status: 401, json: async () => ({ detail: 'Unauthorized' }) } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <AdminClient />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith('/login?redirect=/admin');
    });

    expect(screen.getByTestId('admin-forbidden-card')).toBeInTheDocument();
  });

  it('renders inline 403 Forbidden card when visitor is authenticated as member (non-admin)', async () => {
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
            id: 'mem-1',
            username: 'patient_jane',
            email: 'jane@example.com',
            full_name: 'Jane Patient',
            role: 'member',
            status: 'active',
            auth_provider: 'local',
            created_at: '2026-10-01T00:00:00Z'
          })
        } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <AdminClient />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('admin-forbidden-card')).toBeInTheDocument();
    });

    expect(mockReplace).not.toHaveBeenCalled();
    expect(screen.getByText(/403 — Administrator Privileges Required/i)).toBeInTheDocument();
    expect(screen.getByTestId('forbidden-return-chat-btn')).toHaveAttribute('href', '/chat');
    expect(screen.getByTestId('forbidden-return-login-btn')).toHaveAttribute('href', '/login');
  });
});
