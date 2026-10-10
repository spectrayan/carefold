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
import {
  setStorageUserId,
  getStorageUserId,
  detachUserSession
} from '@/lib/storageNamespace';

function AuthStateProbe({ onExpose }: { onExpose: (auth: ReturnType<typeof useAuth>) => void }) {
  const auth = useAuth();
  React.useEffect(() => {
    onExpose(auth);
  }, [auth, onExpose]);

  return (
    <div>
      <div data-testid="probe-user">{auth.user ? JSON.stringify(auth.user) : 'null'}</div>
      <div data-testid="probe-auth">{auth.isAuthenticated ? 'authenticated' : 'unauthenticated'}</div>
      <div data-testid="probe-loading">{auth.isLoading ? 'loading' : 'ready'}</div>
    </div>
  );
}

describe('Frontend Logout & Invalidation Stress Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setStorageUserId(null);

    if (typeof window !== 'undefined') {
      window.location.href = 'http://localhost:3000/p/me';
    }

    if (typeof document !== 'undefined') {
      document.cookie = 'carefold_session=adversarial_session_token; path=/';
      document.cookie = 'carefold_active_profile=profile_alice_789; path=/';
    }

    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setStorageUserId(null);
    vi.restoreAllMocks();
  });

  it('stress-tests error resilience: backend returns HTTP 500 Internal Server Error', async () => {
    let authProbe: any = null;

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
              id: 'usr-error-500',
              username: 'patient_500',
              role: 'member',
              auth_provider: 'local'
            }
          })
        } as any;
      }
      if (urlStr.includes('/auth/logout') && method === 'POST') {
        return {
          ok: false,
          status: 500,
          statusText: 'Internal Server Error',
          json: async () => ({ error: 'Database connection failed' })
        } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <AuthStateProbe onExpose={(a) => { authProbe = a; }} />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('probe-auth').textContent).toBe('authenticated');
    });

    // Seed multiple storage keys across namespaces
    localStorage.setItem('carefold_usr-error-500_notes', 'critical medical note');
    localStorage.setItem('carefold_msgs_usr-error-500', 'message history');
    localStorage.setItem('carefold_thread_123', 'thread draft');
    localStorage.setItem('other_app_key', 'unrelated data');

    // Trigger logout
    await act(async () => {
      await expect(authProbe.logout()).resolves.toBeUndefined();
    });

    // Verify cookies expired
    expect(document.cookie).not.toContain('carefold_session=adversarial_session_token');
    expect(document.cookie).not.toContain('carefold_active_profile=profile_alice_789');

    // Verify namespaced items cleared
    expect(localStorage.getItem('carefold_usr-error-500_notes')).toBeNull();
    expect(localStorage.getItem('carefold_msgs_usr-error-500')).toBeNull();
    expect(localStorage.getItem('carefold_thread_123')).toBeNull();
    expect(localStorage.getItem('other_app_key')).toBe('unrelated data');

    // Verify user is null
    expect(authProbe.user).toBeNull();
    expect(authProbe.isAuthenticated).toBe(false);
    expect(screen.getByTestId('probe-user').textContent).toBe('null');

    // Verify navigation
    expect(window.location.href).toBe('http://localhost:3000/login');
  });

  it('stress-tests error resilience: abrupt network disconnection (fetch throws TypeError)', async () => {
    let authProbe: any = null;

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
              id: 'usr-offline-drop',
              username: 'offline_dropper',
              role: 'member',
              auth_provider: 'local'
            }
          })
        } as any;
      }
      if (urlStr.includes('/auth/logout') && method === 'POST') {
        throw new TypeError('Failed to fetch: Network is down');
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <AuthStateProbe onExpose={(a) => { authProbe = a; }} />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('probe-auth').textContent).toBe('authenticated');
    });

    localStorage.setItem('carefold_usr-offline-drop_data', 'patient confidential');

    await act(async () => {
      await expect(authProbe.logout()).resolves.toBeUndefined();
    });

    expect(localStorage.getItem('carefold_usr-offline-drop_data')).toBeNull();
    expect(authProbe.user).toBeNull();
    expect(authProbe.isAuthenticated).toBe(false);
    expect(window.location.href).toBe('http://localhost:3000/login');
  });

  it('verifies detachUserSession directly handles null/undefined user safely and isolates other users data', () => {
    // Seed user A and user B
    localStorage.setItem('carefold_usr-A_consultation', 'data A');
    localStorage.setItem('carefold_usr-B_consultation', 'data B');
    localStorage.setItem('carefold_msgs_usr-A', 'msgs A');
    localStorage.setItem('carefold_thread_usr-A', 'thread A');

    // Detach user A
    detachUserSession('usr-A');

    // User A items purged
    expect(localStorage.getItem('carefold_usr-A_consultation')).toBeNull();
    expect(localStorage.getItem('carefold_msgs_usr-A')).toBeNull();
    expect(localStorage.getItem('carefold_thread_usr-A')).toBeNull();

    // User B items remain intact
    expect(localStorage.getItem('carefold_usr-B_consultation')).toBe('data B');
    expect(getStorageUserId()).toBeNull();
  });

  it('verifies that in disabled provider mode, logout still resets user to null and does NOT fallback to DEFAULT_STEWARD_USER', async () => {
    let authProbe: any = null;

    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/auth/providers')) {
        return {
          ok: true,
          json: async () => ({ active_provider: 'disabled', sso_providers: [], registration_enabled: false })
        } as any;
      }
      if (urlStr.includes('/auth/me')) {
        return {
          ok: true,
          json: async () => ({
            user: {
              id: '00000000-0000-0000-0000-000000000000',
              username: 'steward',
              full_name: 'Care Steward',
              role: 'admin',
              auth_provider: 'disabled'
            }
          })
        } as any;
      }
      if (urlStr.includes('/auth/logout')) {
        return { ok: true, json: async () => ({ success: true }) } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <AuthStateProbe onExpose={(a) => { authProbe = a; }} />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('probe-auth').textContent).toBe('authenticated');
    });

    await act(async () => {
      await authProbe.logout();
    });

    // User must be null, not DEFAULT_STEWARD_USER
    expect(authProbe.user).toBeNull();
    expect(authProbe.isAuthenticated).toBe(false);
    expect(screen.getByTestId('probe-user').textContent).toBe('null');
    expect(screen.getByTestId('probe-auth').textContent).toBe('unauthenticated');
    expect(window.location.href).toBe('http://localhost:3000/login');
  });
});
