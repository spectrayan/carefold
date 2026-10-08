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
import { render, screen, act, waitFor } from '@testing-library/react';
import React from 'react';
import { AuthProvider, useAuth, DEFAULT_STEWARD_USER } from '@/lib/auth';

function AuthConsumer({ onMount }: { onMount?: (auth: ReturnType<typeof useAuth>) => void }) {
  const auth = useAuth();
  React.useEffect(() => {
    if (onMount) onMount(auth);
  }, [auth, onMount]);

  return (
    <div>
      <span data-testid="username">{auth.user?.username || 'anonymous'}</span>
      <span data-testid="is-authenticated">{auth.isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="role">{auth.user?.role || 'none'}</span>
      <span data-testid="active-provider">{auth.activeProvider}</span>
      <span data-testid="is-loading">{auth.isLoading ? 'loading' : 'ready'}</span>
    </div>
  );
}

describe('AuthProvider & useAuth', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('provides safe fallback user when used outside AuthProvider', () => {
    render(<AuthConsumer />);
    expect(screen.getByTestId('username').textContent).toBe(DEFAULT_STEWARD_USER.username);
    expect(screen.getByTestId('is-authenticated').textContent).toBe('yes');
    expect(screen.getByTestId('role').textContent).toBe('admin');
    expect(screen.getByTestId('active-provider').textContent).toBe('disabled');
  });

  it('initializes in disabled auth mode with DEFAULT_STEWARD_USER', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/auth/providers')) {
        return {
          ok: true,
          json: async () => ({
            active_provider: 'disabled',
            sso_providers: [],
            registration_enabled: true
          })
        } as any;
      }
      if (urlStr.includes('/api/auth/me')) {
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
        <AuthConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('is-loading').textContent).toBe('ready');
    });

    expect(screen.getByTestId('username').textContent).toBe('steward');
    expect(screen.getByTestId('is-authenticated').textContent).toBe('yes');
    expect(screen.getByTestId('active-provider').textContent).toBe('disabled');
  });

  it('initializes in local mode unauthenticated when no session exists', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/auth/providers')) {
        return {
          ok: true,
          json: async () => ({
            active_provider: 'local',
            sso_providers: [],
            registration_enabled: true
          })
        } as any;
      }
      if (urlStr.includes('/api/auth/me')) {
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
        <AuthConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('is-loading').textContent).toBe('ready');
    });

    expect(screen.getByTestId('username').textContent).toBe('anonymous');
    expect(screen.getByTestId('is-authenticated').textContent).toBe('no');
    expect(screen.getByTestId('active-provider').textContent).toBe('local');
  });

  it('handles login, changePassword, and logout lifecycle in local mode', async () => {
    let authRef: ReturnType<typeof useAuth> | null = null;

    vi.mocked(fetch).mockImplementation(async (url: any, init: any) => {
      const urlStr = String(url);
      const method = init?.method || 'GET';

      if (urlStr.includes('/api/auth/providers')) {
        return {
          ok: true,
          json: async () => ({
            active_provider: 'local',
            sso_providers: [],
            registration_enabled: true
          })
        } as any;
      }
      if (urlStr.includes('/api/auth/me')) {
        return {
          ok: false,
          status: 401,
          json: async () => ({ detail: 'Not authenticated' })
        } as any;
      }
      if (urlStr.includes('/api/auth/login') && method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            user: {
              id: 'user-123',
              username: 'doctor_smith',
              email: 'smith@hospital.org',
              full_name: 'Dr. Smith',
              role: 'clinician',
              status: 'active',
              auth_provider: 'local',
              created_at: '2026-10-01T00:00:00Z'
            }
          })
        } as any;
      }
      if (urlStr.includes('/api/auth/change-password') && method === 'POST') {
        return {
          ok: true,
          json: async () => ({ detail: 'Password updated successfully' })
        } as any;
      }
      if (urlStr.includes('/api/auth/logout') && method === 'POST') {
        return {
          ok: true,
          json: async () => ({ detail: 'Logged out' })
        } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <AuthConsumer onMount={(auth) => { authRef = auth; }} />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('is-loading').textContent).toBe('ready');
    });

    expect(screen.getByTestId('is-authenticated').textContent).toBe('no');

    // Perform Login
    await act(async () => {
      await authRef?.login('doctor_smith', 'Secret1234!');
    });

    expect(screen.getByTestId('username').textContent).toBe('doctor_smith');
    expect(screen.getByTestId('is-authenticated').textContent).toBe('yes');
    expect(screen.getByTestId('role').textContent).toBe('clinician');

    // Change Password
    await act(async () => {
      await authRef?.changePassword('Secret1234!', 'NewSecret999!');
    });

    // Logout
    await act(async () => {
      await authRef?.logout();
    });

    expect(screen.getByTestId('username').textContent).toBe('anonymous');
    expect(screen.getByTestId('is-authenticated').textContent).toBe('no');
  });

  it('handles register action invoking /api/auth/register', async () => {
    let authRef: ReturnType<typeof useAuth> | null = null;

    vi.mocked(fetch).mockImplementation(async (url: any, init: any) => {
      const urlStr = String(url);
      const method = init?.method || 'GET';

      if (urlStr.includes('/api/auth/providers')) {
        return {
          ok: true,
          json: async () => ({
            active_provider: 'local',
            sso_providers: [],
            registration_enabled: true
          })
        } as any;
      }
      if (urlStr.includes('/api/auth/me')) {
        return {
          ok: false,
          status: 401,
          json: async () => ({ detail: 'Not authenticated' })
        } as any;
      }
      if (urlStr.includes('/api/auth/register') && method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            user: {
              id: 'user-new',
              username: 'new_user',
              email: 'new@carefold.org',
              full_name: 'New User',
              role: 'user',
              status: 'active',
              auth_provider: 'local',
              created_at: '2026-10-01T00:00:00Z'
            }
          })
        } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <AuthConsumer onMount={(auth) => { authRef = auth; }} />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('is-loading').textContent).toBe('ready');
    });

    let registeredUser: any = null;
    await act(async () => {
      registeredUser = await authRef?.register({
        email: 'new@carefold.org',
        username: 'new_user',
        password: 'Password123!',
        fullName: 'New User'
      });
    });

    expect(registeredUser).toBeDefined();
    expect(registeredUser?.username).toBe('new_user');
  });
});
