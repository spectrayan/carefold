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
import { AuthProvider, useAuth } from '@/lib/auth';
import { getStorageUserId, setStorageUserId } from '@/lib/storageNamespace';

function TestAuthConsumer({ onReady }: { onReady: (auth: ReturnType<typeof useAuth>) => void }) {
  const auth = useAuth();
  React.useEffect(() => {
    if (!auth.isLoading) {
      onReady(auth);
    }
  }, [auth, onReady]);

  return (
    <div>
      <span data-testid="username">{auth.user?.username || 'anonymous'}</span>
      <span data-testid="is-authenticated">{auth.isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="is-loading">{auth.isLoading ? 'loading' : 'ready'}</span>
    </div>
  );
}

describe('AuthProvider Logout Lifecycle & Session Revocation', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setStorageUserId(null);

    // Seed browser URL
    if (typeof window !== 'undefined') {
      window.location.href = 'http://localhost:3000/settings';
    }

    // Seed cookies
    if (typeof document !== 'undefined') {
      document.cookie = 'carefold_session=initial_sess_token_123; path=/';
      document.cookie = 'carefold_active_profile=prof_me_456; path=/';
    }

    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setStorageUserId(null);
    vi.restoreAllMocks();
  });

  it('executes full logout lifecycle: calls /api/v1/auth/logout with credentials, deletes cookies, clears storage, resets user, and navigates to /login', async () => {
    let authRef: any = null;
    let logoutCallUrl = '';
    let logoutCallInit: any = undefined;

    vi.mocked(fetch).mockImplementation(async (url: any, init: any) => {
      const urlStr = String(url);
      const method = init?.method || 'GET';

      if (urlStr.includes('/auth/providers')) {
        return {
          ok: true,
          json: async () => ({
            active_provider: 'local',
            sso_providers: [],
            registration_enabled: true
          })
        } as any;
      }
      if (urlStr.includes('/auth/me')) {
        return {
          ok: true,
          json: async () => ({
            user: {
              id: 'usr-patient-1',
              username: 'jane_doe',
              email: 'jane@example.com',
              full_name: 'Jane Doe',
              role: 'member',
              status: 'active',
              auth_provider: 'local',
              created_at: '2026-10-01T00:00:00Z'
            }
          })
        } as any;
      }
      if (urlStr.includes('/auth/logout') && method === 'POST') {
        logoutCallUrl = urlStr;
        logoutCallInit = init;
        return {
          ok: true,
          json: async () => ({ success: true })
        } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <TestAuthConsumer onReady={(auth) => { authRef = auth; }} />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('is-loading').textContent).toBe('ready');
      expect(screen.getByTestId('is-authenticated').textContent).toBe('yes');
    });

    expect(screen.getByTestId('username').textContent).toBe('jane_doe');

    // Pre-seed namespaced storage for the logged-in user
    localStorage.setItem('carefold_usr-patient-1_consultations', 'dossier-123');
    localStorage.setItem('carefold_msgs_usr-patient-1', 'hello doctor');
    expect(localStorage.getItem('carefold_usr-patient-1_consultations')).toBe('dossier-123');

    // Trigger logout
    await act(async () => {
      await authRef?.logout();
    });

    // 1. Verify backend API contract
    expect(logoutCallUrl).toContain('/api/v1/auth/logout');
    expect(logoutCallInit).toBeDefined();
    expect(logoutCallInit?.method).toBe('POST');
    expect(logoutCallInit?.credentials).toBe('include');

    // 2. Verify client cookies deleted
    expect(document.cookie).not.toContain('carefold_session=initial_sess_token_123');
    expect(document.cookie).not.toContain('carefold_active_profile=prof_me_456');

    // 3. Verify user storage detached
    expect(localStorage.getItem('carefold_usr-patient-1_consultations')).toBeNull();
    expect(localStorage.getItem('carefold_msgs_usr-patient-1')).toBeNull();
    expect(getStorageUserId()).toBeNull();

    // 4. Verify React state reset to null
    expect(authRef?.user).toBeNull();
    expect(authRef?.isAuthenticated).toBe(false);
    expect(screen.getByTestId('username').textContent).toBe('anonymous');
    expect(screen.getByTestId('is-authenticated').textContent).toBe('no');

    // 5. Verify hard window navigation to /login
    expect(window.location.href).toBe('http://localhost:3000/login');
  });

  it('unconditionally sets user to null on logout even when active provider is disabled (no fallback to default persona)', async () => {
    let authRef: any = null;

    vi.mocked(fetch).mockImplementation(async (url: any, init: any) => {
      const urlStr = String(url);
      const method = init?.method || 'GET';

      if (urlStr.includes('/auth/providers')) {
        return {
          ok: true,
          json: async () => ({
            active_provider: 'disabled',
            sso_providers: [],
            registration_enabled: true
          })
        } as any;
      }
      if (urlStr.includes('/auth/me')) {
        return {
          ok: true,
          json: async () => ({
            user: {
              id: 'steward-id',
              username: 'care_steward',
              email: 'steward@carefold.local',
              full_name: 'Care Steward',
              role: 'admin',
              status: 'active',
              auth_provider: 'disabled',
              created_at: '2026-10-01T00:00:00Z'
            }
          })
        } as any;
      }
      if (urlStr.includes('/auth/logout') && method === 'POST') {
        return { ok: true, json: async () => ({ success: true }) } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <TestAuthConsumer onReady={(auth) => { authRef = auth; }} />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('is-loading').textContent).toBe('ready');
      expect(screen.getByTestId('is-authenticated').textContent).toBe('yes');
    });

    // Trigger logout in disabled provider mode
    await act(async () => {
      await authRef?.logout();
    });

    // User must be null, NOT reset to DEFAULT_STEWARD_USER
    expect(authRef?.user).toBeNull();
    expect(authRef?.isAuthenticated).toBe(false);
    expect(screen.getByTestId('username').textContent).toBe('anonymous');
    expect(screen.getByTestId('is-authenticated').textContent).toBe('no');
    expect(window.location.href).toBe('http://localhost:3000/login');
  });

  it('guarantees client-side storage detachment, cookie clearance, and /login navigation even when backend logout fails with 500 error or network outage', async () => {
    let authRef: any = null;

    vi.mocked(fetch).mockImplementation(async (url: any, init: any) => {
      const urlStr = String(url);
      const method = init?.method || 'GET';

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
            user: {
              id: 'usr-offline-1',
              username: 'offline_user',
              role: 'member',
              auth_provider: 'local'
            }
          })
        } as any;
      }
      if (urlStr.includes('/auth/logout') && method === 'POST') {
        // Backend returns 500 or throws TypeError('Network Error')
        throw new TypeError('Failed to fetch: Network partition');
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <TestAuthConsumer onReady={(auth) => { authRef = auth; }} />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('is-authenticated').textContent).toBe('yes');
    });

    localStorage.setItem('carefold_usr-offline-1_notes', 'confidential draft');

    // Trigger logout with network outage
    await act(async () => {
      await expect(authRef?.logout()).resolves.toBeUndefined();
    });

    // Resilient local cleanup must still succeed
    expect(document.cookie).not.toContain('carefold_session=initial_sess_token_123');
    expect(document.cookie).not.toContain('carefold_active_profile=prof_me_456');
    expect(localStorage.getItem('carefold_usr-offline-1_notes')).toBeNull();
    expect(authRef?.user).toBeNull();
    expect(authRef?.isAuthenticated).toBe(false);
    expect(window.location.href).toBe('http://localhost:3000/login');
  });
});
