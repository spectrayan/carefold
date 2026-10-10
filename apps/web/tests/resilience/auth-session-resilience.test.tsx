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
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import React from 'react';
import fs from 'node:fs';
import path from 'node:path';
import AdminClient from '@/app/admin/AdminClient';
import { AuthProvider } from '@/lib/auth';
import { GET as getChatThreadRoute } from '@/app/api/chat/threads/[id]/route';
import { GET as getMemoriesStatusRoute } from '@/app/api/memories/status/route';

vi.mock('next/navigation', () => ({
  usePathname: () => '/admin',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));

const MOCK_ADMIN_USER = {
  id: 'admin-1',
  username: 'carefold_admin',
  email: 'admin@carefold.io',
  full_name: 'Lead Admin',
  role: 'admin',
  status: 'active',
  auth_provider: 'local',
  created_at: '2026-10-01T00:00:00Z'
};

const MOCK_MEMBER_USER = {
  id: 'member-2',
  username: 'member_patient',
  email: 'patient@example.com',
  full_name: 'Jane Patient',
  role: 'member',
  status: 'active',
  auth_provider: 'local',
  created_at: '2026-10-02T00:00:00Z'
};

const MOCK_STEWARD_USER = {
  id: 'steward-3',
  username: 'steward_doctor',
  email: 'steward@clinic.org',
  full_name: 'Dr. Clinician',
  role: 'steward',
  status: 'active',
  auth_provider: 'local',
  created_at: '2026-10-03T00:00:00Z'
};

const MOCK_USERS_LIST = [
  MOCK_ADMIN_USER,
  MOCK_MEMBER_USER,
  MOCK_STEWARD_USER,
  {
    id: 'admin-clone',
    username: 'carefold_admin', // Same username, different ID
    email: 'admin2@carefold.io',
    full_name: 'Admin Clone',
    role: 'admin',
    status: 'active',
    auth_provider: 'local',
    created_at: '2026-10-04T00:00:00Z'
  }
];

describe('Auth Session Resilience Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. AdminClient Access Control & 403 Forbidden Gate
  // =========================================================================
  describe('1. AdminClient Access Control & Tab Rendering', () => {
    it('blocks unauthenticated visitors and renders 403 Forbidden card', async () => {
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
            ok: false,
            status: 401,
            json: async () => ({ detail: 'Not authenticated' })
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

      expect(screen.queryByTestId('admin-tab-identity')).not.toBeInTheDocument();
      expect(screen.queryByTestId('admin-tab-models')).not.toBeInTheDocument();
      expect(screen.queryByTestId('admin-tab-users')).not.toBeInTheDocument();
      expect(screen.queryByTestId('admin-tab-diagnostics')).not.toBeInTheDocument();
      expect(screen.getByTestId('forbidden-return-chat-btn')).toHaveAttribute('href', '/chat');
      expect(screen.getByTestId('forbidden-return-login-btn')).toHaveAttribute('href', '/login');
    });

    it('blocks member users and renders 403 Forbidden card', async () => {
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const urlStr = String(url);
        if (urlStr.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
          } as any;
        }
        if (urlStr.includes('/auth/me')) {
          return { ok: true, json: async () => MOCK_MEMBER_USER } as any;
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
      expect(screen.queryByTestId('admin-tab-identity')).not.toBeInTheDocument();
    });

    it('blocks steward users and renders 403 Forbidden card', async () => {
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const urlStr = String(url);
        if (urlStr.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
          } as any;
        }
        if (urlStr.includes('/auth/me')) {
          return { ok: true, json: async () => MOCK_STEWARD_USER } as any;
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
      expect(screen.queryByTestId('admin-tab-identity')).not.toBeInTheDocument();
    });

    it('blocks unexpected/malformed roles (fail-closed behavior)', async () => {
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
            json: async () => ({ ...MOCK_MEMBER_USER, role: 'unknown_role' })
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
      expect(screen.queryByTestId('admin-tab-identity')).not.toBeInTheDocument();
    });

    it('renders all 4 tabs and allows complete tab navigation cycle for admin user', async () => {
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const urlStr = String(url);
        if (urlStr.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
          } as any;
        }
        if (urlStr.includes('/auth/me')) {
          return { ok: true, json: async () => MOCK_ADMIN_USER } as any;
        }
        if (urlStr.includes('/admin/settings')) {
          return {
            ok: true,
            json: async () => ({ settings: { 'auth.active_provider': 'local' } })
          } as any;
        }
        if (urlStr.includes('/admin/users')) {
          return {
            ok: true,
            json: async () => ({ users: MOCK_USERS_LIST, total: MOCK_USERS_LIST.length })
          } as any;
        }
        if (urlStr.includes('/admin/diagnostics')) {
          return {
            ok: true,
            json: async () => ({
              status: 'ok',
              version: '0.4.0-beta.1',
              database: { dialect: 'sqlite', connected: true },
              table_counts: { users: 4, sessions: 2, password_resets: 1, system_settings: 5 },
              agents_count: 22,
              skills_count: 24
            })
          } as any;
        }
        if (urlStr.includes('/health')) {
          return {
            ok: true,
            json: async () => ({ status: 'ok', version: '0.4.0-beta.1' })
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
        expect(screen.getByTestId('admin-tab-identity')).toBeInTheDocument();
      });
      expect(screen.getByTestId('admin-tab-models')).toBeInTheDocument();
      expect(screen.getByTestId('admin-tab-users')).toBeInTheDocument();
      expect(screen.getByTestId('admin-tab-diagnostics')).toBeInTheDocument();

      // Check initial active tab is Identity
      expect(screen.getByTestId('admin-tab-identity')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByTestId('admin-tab-models')).toHaveAttribute('aria-selected', 'false');

      // Click Models
      await act(async () => {
        fireEvent.click(screen.getByTestId('admin-tab-models'));
      });
      expect(screen.getByTestId('admin-tab-models')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByTestId('admin-tab-identity')).toHaveAttribute('aria-selected', 'false');

      // Click Users
      await act(async () => {
        fireEvent.click(screen.getByTestId('admin-tab-users'));
      });
      expect(screen.getByTestId('admin-tab-users')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByTestId('admin-tab-models')).toHaveAttribute('aria-selected', 'false');

      // Click Diagnostics
      await act(async () => {
        fireEvent.click(screen.getByTestId('admin-tab-diagnostics'));
      });
      expect(screen.getByTestId('admin-tab-diagnostics')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByTestId('admin-tab-users')).toHaveAttribute('aria-selected', 'false');

      // Return to Identity
      await act(async () => {
        fireEvent.click(screen.getByTestId('admin-tab-identity'));
      });
      expect(screen.getByTestId('admin-tab-identity')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByTestId('admin-tab-diagnostics')).toHaveAttribute('aria-selected', 'false');
    });
  });

  // =========================================================================
  // 2. User Table Self-Deletion & Self-Status Safeguards
  // =========================================================================
  describe('2. User Table Self-Deletion & Safeguards', () => {
    it('disables delete button and status toggle for current logged-in admin (by id and username)', async () => {
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const urlStr = String(url);
        if (urlStr.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
          } as any;
        }
        if (urlStr.includes('/auth/me')) {
          return { ok: true, json: async () => MOCK_ADMIN_USER } as any;
        }
        if (urlStr.includes('/admin/settings')) {
          return { ok: true, json: async () => ({ settings: {} }) } as any;
        }
        if (urlStr.includes('/admin/users')) {
          return {
            ok: true,
            json: async () => ({ users: MOCK_USERS_LIST, total: MOCK_USERS_LIST.length })
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
        expect(screen.getByTestId('admin-tab-users')).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByTestId('admin-tab-users'));
      });

      await waitFor(() => {
        expect(screen.getByTestId('users-table')).toBeInTheDocument();
      });

      // Self-delete button for logged-in admin (by id) must be disabled
      const selfDeleteBtn = screen.getByTestId(`user-delete-btn-${MOCK_ADMIN_USER.id}`);
      expect(selfDeleteBtn).toBeDisabled();
      expect(selfDeleteBtn).toHaveAttribute('aria-disabled', 'true');
      expect(selfDeleteBtn).toHaveAttribute('title', 'Cannot delete own account');

      // Status toggle for self must also be disabled
      const selfStatusToggle = screen.getByTestId(`user-status-toggle-${MOCK_ADMIN_USER.id}`);
      expect(selfStatusToggle).toBeDisabled();

      // Clone with matching username (even different ID) must also be protected
      const cloneDeleteBtn = screen.getByTestId('user-delete-btn-admin-clone');
      expect(cloneDeleteBtn).toBeDisabled();
      expect(cloneDeleteBtn).toHaveAttribute('aria-disabled', 'true');

      // Other users (member-2, steward-3) delete buttons are ENABLED
      const memberDeleteBtn = screen.getByTestId(`user-delete-btn-${MOCK_MEMBER_USER.id}`);
      expect(memberDeleteBtn).not.toBeDisabled();
      expect(memberDeleteBtn).not.toHaveAttribute('aria-disabled', 'true');

      const stewardDeleteBtn = screen.getByTestId(`user-delete-btn-${MOCK_STEWARD_USER.id}`);
      expect(stewardDeleteBtn).not.toBeDisabled();

      // Clicking disabled self-delete button does NOT open modal
      await act(async () => {
        fireEvent.click(selfDeleteBtn);
      });
      expect(screen.queryByTestId('delete-user-modal')).not.toBeInTheDocument();

      // Clicking enabled delete button opens delete modal
      await act(async () => {
        fireEvent.click(memberDeleteBtn);
      });
      const modal = screen.getByTestId('delete-user-modal');
      expect(modal).toBeInTheDocument();
      expect(within(modal).getByText(/@member_patient/i)).toBeInTheDocument();
    });
  });

  // =========================================================================
  // 3. Proxy Routes Cookie Forwarding
  // =========================================================================
  describe('3. Proxy Routes Cookie Forwarding', () => {
    it('chat/threads/[id] forwards incoming Cookie header to backend', async () => {
      let forwardedHeaders: Record<string, string> | undefined;

      vi.mocked(fetch).mockImplementation(async (_url: any, init: any) => {
        forwardedHeaders = init?.headers;
        return {
          ok: true,
          json: async () => ({ id: 'thread-123', messages: [] })
        } as any;
      });

      // Use request double with custom headers object to bypass happy-dom forbidden cookie filter
      const mockReq = {
        headers: {
          get: (headerName: string) =>
            headerName.toLowerCase() === 'cookie'
              ? 'carefold_session=secret_token_abc123'
              : null
        }
      } as any;

      const res = await getChatThreadRoute(mockReq, {
        params: Promise.resolve({ id: 'thread-123' })
      });

      expect(res.status).toBe(200);
      expect(forwardedHeaders).toBeDefined();
      expect(forwardedHeaders?.['cookie']).toBe('carefold_session=secret_token_abc123');
    });

    it('chat/threads/[id] handles request without cookie cleanly', async () => {
      let forwardedHeaders: Record<string, string> | undefined;

      vi.mocked(fetch).mockImplementation(async (_url: any, init: any) => {
        forwardedHeaders = init?.headers;
        return {
          ok: true,
          json: async () => ({ id: 'thread-456', messages: [] })
        } as any;
      });

      const mockReq = {
        headers: {
          get: () => null
        }
      } as any;

      const res = await getChatThreadRoute(mockReq, {
        params: Promise.resolve({ id: 'thread-456' })
      });

      expect(res.status).toBe(200);
      expect(forwardedHeaders).toBeDefined();
      expect(forwardedHeaders?.['cookie']).toBeUndefined();
    });

    it('chat/threads/[id] rejects path traversal and malicious slug input', async () => {
      const maliciousSlugs = ['../../etc/passwd', 'thread..id', 'thread/sub', 'thread 123!'];

      for (const slug of maliciousSlugs) {
        const mockReq = {
          headers: {
            get: () => null
          }
        } as any;
        const res = await getChatThreadRoute(mockReq, {
          params: Promise.resolve({ id: slug })
        });
        expect(res.status).toBe(400);
        const data = await res.json();
        expect(data.code).toBe('INVALID_ID');
      }
    });

    it('memories/status forwards incoming Cookie header to backend', async () => {
      let forwardedHeaders: Record<string, string> | undefined;

      vi.mocked(fetch).mockImplementation(async (_url: any, init: any) => {
        forwardedHeaders = init?.headers;
        return {
          ok: true,
          json: async () => ({ backend: 'spector', healthy: true })
        } as any;
      });

      const mockReq = {
        headers: {
          get: (headerName: string) =>
            headerName.toLowerCase() === 'cookie'
              ? 'carefold_session=secret_token_xyz987'
              : null
        }
      } as any;

      const res = await getMemoriesStatusRoute(mockReq);

      expect(res.status).toBe(200);
      expect(forwardedHeaders).toBeDefined();
      expect(forwardedHeaders?.['cookie']).toBe('carefold_session=secret_token_xyz987');
    });

    it('memories/status handles missing request or missing cookie without crash', async () => {
      let forwardedHeaders: Record<string, string> | undefined;

      vi.mocked(fetch).mockImplementation(async (_url: any, init: any) => {
        forwardedHeaders = init?.headers;
        return {
          ok: true,
          json: async () => ({ backend: 'sqlite', healthy: true })
        } as any;
      });

      const res = await getMemoriesStatusRoute();

      expect(res.status).toBe(200);
      expect(forwardedHeaders).toBeDefined();
      expect(forwardedHeaders?.['cookie']).toBeUndefined();
    });
  });

  // =========================================================================
  // 4. Dead Shim Removal & Export Integrity
  // =========================================================================
  describe('4. Dead Shim SecurityProfilePanel Removal', () => {
    it('verifies dead shim file apps/web/src/components/SecurityProfilePanel.tsx is deleted', () => {
      const deadShimPath = path.resolve(
        process.cwd(),
        'src/components/SecurityProfilePanel.tsx'
      );
      expect(fs.existsSync(deadShimPath)).toBe(false);
    });

    it('verifies actual component exists at apps/web/src/components/settings/SecurityProfilePanel.tsx', () => {
      const realComponentPath = path.resolve(
        process.cwd(),
        'src/components/settings/SecurityProfilePanel.tsx'
      );
      expect(fs.existsSync(realComponentPath)).toBe(true);
    });
  });
});
