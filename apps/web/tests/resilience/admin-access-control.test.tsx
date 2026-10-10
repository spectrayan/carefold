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
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

import RootPage from '@/app/page';
import AdminClient from '@/app/admin/AdminClient';
import { AuthProvider } from '@/lib/auth';

// Navigation mocks
const mockRedirect = vi.fn();
const mockReplace = vi.fn();
const mockPush = vi.fn();

vi.mock('next/navigation', () => ({
  redirect: (url: string) => mockRedirect(url),
  usePathname: () => '/admin',
  useRouter: () => ({ push: mockPush, replace: mockReplace, prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));

// Cookie store mock for Server Component
let mockCookieStore: Record<string, string | undefined> = {};
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({
    get: (key: string) => (mockCookieStore[key] ? { value: mockCookieStore[key] } : undefined),
  }))
}));

describe('Root Page & Admin Authorization Separation Suite', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCookieStore = {};
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // =========================================================================
  // Section 1: Server Component Root Page (/app/page.tsx)
  // =========================================================================
  describe('1. Server Component Root Page (/page.tsx) Redirection', () => {
    it('redirects unauthenticated visitor to /login when carefold_session is missing', async () => {
      mockCookieStore = {};
      await RootPage();
      expect(mockRedirect).toHaveBeenCalledWith('/login');
    });

    it('redirects unauthenticated visitor to /login when carefold_session is empty whitespace', async () => {
      mockCookieStore = { carefold_session: '   ' };
      await RootPage();
      expect(mockRedirect).toHaveBeenCalledWith('/login');
    });

    it('redirects authenticated visitor to /p/me when carefold_active_profile is missing', async () => {
      mockCookieStore = { carefold_session: 'valid-session-sha256' };
      await RootPage();
      expect(mockRedirect).toHaveBeenCalledWith('/p/me');
    });

    it('redirects authenticated visitor to active profile ID from cookie', async () => {
      mockCookieStore = {
        carefold_session: 'valid-session-sha256',
        carefold_active_profile: 'prof-patient-daughter-777',
      };
      await RootPage();
      expect(mockRedirect).toHaveBeenCalledWith('/p/prof-patient-daughter-777');
    });
  });

  // =========================================================================
  // Section 2: Admin Access Separation & 403 Forbidden Gate
  // =========================================================================
  describe('2. AdminClient Access Separation & 403 Forbidden Defense', () => {
    it('redirects unauthenticated visitor to /login?redirect=/admin and renders 403 card', async () => {
      vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: any) => {
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
      }));

      render(
        <AuthProvider>
          <AdminClient />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(mockReplace).toHaveBeenCalledWith('/login?redirect=/admin');
      });

      expect(screen.getByTestId('admin-forbidden-card')).toBeInTheDocument();
      expect(screen.getByText(/403 — Administrator Privileges Required/i)).toBeInTheDocument();
      expect(screen.queryByTestId('admin-tab-identity')).not.toBeInTheDocument();
      expect(screen.queryByTestId('admin-tab-models')).not.toBeInTheDocument();
      expect(screen.queryByTestId('admin-tab-users')).not.toBeInTheDocument();
    });

    it('renders 403 Forbidden card for authenticated member role without redirecting away', async () => {
      vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: any) => {
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
              id: 'user-member-1',
              username: 'patient_alice',
              email: 'alice@example.com',
              full_name: 'Alice Patient',
              role: 'member',
              status: 'active',
              auth_provider: 'local',
              created_at: '2026-10-01T00:00:00Z',
            })
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      }));

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
      expect(screen.getByText('member')).toBeInTheDocument();
      expect(screen.getByTestId('forbidden-return-chat-btn')).toHaveAttribute('href', '/chat');
      expect(screen.getByTestId('forbidden-return-login-btn')).toHaveAttribute('href', '/login');
      expect(screen.queryByTestId('admin-tab-identity')).not.toBeInTheDocument();
    });

    it('renders 403 Forbidden card for authenticated steward role without redirecting away', async () => {
      vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: any) => {
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
              id: 'user-steward-1',
              username: 'doctor_bob',
              email: 'bob@example.com',
              full_name: 'Dr. Bob',
              role: 'steward',
              status: 'active',
              auth_provider: 'local',
              created_at: '2026-10-01T00:00:00Z',
            })
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      }));

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
      expect(screen.getByText('steward')).toBeInTheDocument();
      expect(screen.queryByTestId('admin-tab-identity')).not.toBeInTheDocument();
    });

    it('grants access and renders administrative control panel for authenticated admin role', async () => {
      vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: any) => {
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
              id: 'user-admin-1',
              username: 'super_admin',
              email: 'admin@carefold.io',
              full_name: 'Lead Admin',
              role: 'admin',
              status: 'active',
              auth_provider: 'local',
              created_at: '2026-10-01T00:00:00Z',
            })
          } as any;
        }
        if (urlStr.includes('/admin/settings')) {
          return {
            ok: true,
            json: async () => ({
              auth_provider: 'local',
              registration_enabled: true,
              default_model_provider: 'ollama'
            })
          } as any;
        }
        if (urlStr.includes('/admin/users')) {
          return {
            ok: true,
            json: async () => ({ users: [], total: 0 })
          } as any;
        }
        if (urlStr.includes('/admin/diagnostics')) {
          return {
            ok: true,
            json: async () => ({
              dialect: 'sqlite',
              connected: true,
              latencyMs: 1.5,
              tableCounts: { users: 1, sessions: 1, password_resets: 0, system_settings: 5 },
              agentsCount: 22,
              skillsCount: 23,
              status: 'healthy',
              version: '0.4.0-beta.1'
            })
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      }));

      render(
        <AuthProvider>
          <AdminClient />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.queryByTestId('admin-forbidden-card')).not.toBeInTheDocument();
      });

      expect(mockReplace).not.toHaveBeenCalled();
      expect(screen.getByText(/Admin Control Panel/i)).toBeInTheDocument();
      expect(screen.getByTestId('admin-tab-identity')).toBeInTheDocument();
    });
  });
});
