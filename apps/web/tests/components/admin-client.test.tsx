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
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import React from 'react';
import AdminClient from '@/app/admin/AdminClient';
import { AuthProvider } from '@/lib/auth';

vi.mock('next/navigation', () => ({
  usePathname: () => '/admin',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));

const MOCK_ADMIN_USER = {
  id: 'admin-id-1',
  username: 'carefold_admin',
  email: 'admin@carefold.io',
  full_name: 'Lead Administrator',
  role: 'admin',
  status: 'active',
  auth_provider: 'local',
  created_at: '2026-10-01T00:00:00Z'
};

const MOCK_MEMBER_USER = {
  id: 'member-id-2',
  username: 'regular_patient',
  email: 'patient@example.com',
  full_name: 'Jane Patient',
  role: 'member',
  status: 'active',
  auth_provider: 'local',
  created_at: '2026-10-02T00:00:00Z'
};

const MOCK_USERS_LIST = [
  MOCK_ADMIN_USER,
  MOCK_MEMBER_USER,
  {
    id: 'steward-id-3',
    username: 'clinician_steward',
    email: 'steward@clinic.org',
    full_name: 'Dr. Clinician',
    role: 'steward',
    status: 'active',
    auth_provider: 'local',
    created_at: '2026-10-03T00:00:00Z'
  }
];

describe('AdminClient Component', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders 403 Forbidden Access Denied card when current user is not an admin', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/auth/providers')) {
        return {
          ok: true,
          json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
        } as any;
      }
      if (urlStr.includes('/api/auth/me')) {
        return {
          ok: true,
          json: async () => MOCK_MEMBER_USER
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

    expect(screen.getByText(/403 — Administrator Privileges Required/i)).toBeInTheDocument();
    expect(screen.getByTestId('forbidden-return-chat-btn')).toHaveAttribute('href', '/chat');
    expect(screen.getByTestId('forbidden-return-login-btn')).toHaveAttribute('href', '/login');
  });

  it('renders all 4 tabs and allows switching between them for admin users', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/auth/providers')) {
        return {
          ok: true,
          json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
        } as any;
      }
      if (urlStr.includes('/api/auth/me')) {
        return {
          ok: true,
          json: async () => MOCK_ADMIN_USER
        } as any;
      }
      if (urlStr.includes('/api/admin/settings')) {
        return {
          ok: true,
          json: async () => ({
            settings: {
              'auth.active_provider': 'local',
              'auth.registration_enabled': true,
              'models.default_provider': 'ollama',
              'models.ollama_url': 'http://127.0.0.1:11434'
            }
          })
        } as any;
      }
      if (urlStr.includes('/api/admin/users')) {
        return {
          ok: true,
          json: async () => ({ users: MOCK_USERS_LIST, total: MOCK_USERS_LIST.length })
        } as any;
      }
      if (urlStr.includes('/api/admin/diagnostics')) {
        return {
          ok: true,
          json: async () => ({
            status: 'ok',
            version: '0.4.0-beta.1',
            database: { dialect: 'sqlite', connected: true },
            table_counts: { users: 3, sessions: 2, password_resets: 1, system_settings: 5 },
            agents_count: 22,
            skills_count: 24
          })
        } as any;
      }
      if (urlStr.includes('/api/health')) {
        return {
          ok: true,
          json: async () => ({
            status: 'ok',
            version: '0.4.0-beta.1',
            workspace: { agentsCount: 22, skillsCount: 24 },
            ollama: { reachable: true, availableModels: ['llama3.2:3b'] }
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

    // Verify all 4 tabs exist
    await waitFor(() => {
      expect(screen.getByTestId('admin-tab-identity')).toBeInTheDocument();
    });
    expect(screen.getByTestId('admin-tab-models')).toBeInTheDocument();
    expect(screen.getByTestId('admin-tab-users')).toBeInTheDocument();
    expect(screen.getByTestId('admin-tab-diagnostics')).toBeInTheDocument();

    // Default tab is Identity
    expect(screen.getByTestId('admin-tab-identity')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('save-identity-settings-btn')).toBeInTheDocument();

    // Switch to Models tab
    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-tab-models'));
    });
    expect(screen.getByTestId('admin-tab-models')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('model-provider-select')).toBeInTheDocument();
    expect(screen.getByTestId('test-ollama-btn')).toBeInTheDocument();
    expect(screen.getByTestId('save-models-btn')).toBeInTheDocument();

    // Switch to Users tab
    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-tab-users'));
    });
    expect(screen.getByTestId('admin-tab-users')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('user-search-input')).toBeInTheDocument();
    expect(screen.getByTestId('open-create-user-modal-btn')).toBeInTheDocument();

    // Switch to Diagnostics tab
    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-tab-diagnostics'));
    });
    expect(screen.getByTestId('admin-tab-diagnostics')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('dialect-badge')).toBeInTheDocument();
    expect(screen.getByTestId('backend-health-badge')).toBeInTheDocument();
    expect(screen.getByTestId('stat-agents-count')).toHaveTextContent('22');
    expect(screen.getByTestId('stat-skills-count')).toHaveTextContent('24');
  });

  it('renders user directory and disables self-deletion button for current logged-in admin', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/auth/providers')) {
        return {
          ok: true,
          json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
        } as any;
      }
      if (urlStr.includes('/api/auth/me')) {
        return {
          ok: true,
          json: async () => MOCK_ADMIN_USER
        } as any;
      }
      if (urlStr.includes('/api/admin/settings')) {
        return {
          ok: true,
          json: async () => ({ settings: {} })
        } as any;
      }
      if (urlStr.includes('/api/admin/users')) {
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

    // Switch to Users directory tab
    await waitFor(() => {
      expect(screen.getByTestId('admin-tab-users')).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-tab-users'));
    });

    // Verify user table rendered
    await waitFor(() => {
      expect(screen.getByTestId('users-table')).toBeInTheDocument();
    });

    // Verify user rows exist
    expect(screen.getByTestId(`user-row-${MOCK_ADMIN_USER.id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`user-row-${MOCK_MEMBER_USER.id}`)).toBeInTheDocument();

    // Verify current admin user cannot delete their own account
    const selfDeleteBtn = screen.getByTestId(`user-delete-btn-${MOCK_ADMIN_USER.id}`);
    expect(selfDeleteBtn).toBeDisabled();
    expect(selfDeleteBtn).toHaveAttribute('aria-disabled', 'true');

    // Verify other member user CAN be deleted
    const otherDeleteBtn = screen.getByTestId(`user-delete-btn-${MOCK_MEMBER_USER.id}`);
    expect(otherDeleteBtn).not.toBeDisabled();
  });
});
