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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { SecurityProfilePanel } from '@/components/settings/SecurityProfilePanel';
import { AuthProvider } from '@/lib/auth';

describe('SecurityProfilePanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders disabled mode notice and local profile in default mode', async () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
      const urlStr = String(url);
      if (urlStr.includes('/auth/providers')) {
        return {
          ok: true,
          json: async () => ({ active_provider: 'disabled', sso_providers: [], registration_enabled: true })
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
        <SecurityProfilePanel />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('security-profile-panel')).toBeInTheDocument();
    });

    expect(screen.getByTestId('disabled-auth-notice')).toBeInTheDocument();
    expect(screen.getByTestId('user-role-badge')).toHaveTextContent('admin');
  });

  it('renders change password form and allows updating password for local auth user', async () => {
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
            id: 'doc-user-1',
            username: 'doc_jones',
            email: 'jones@clinic.org',
            full_name: 'Dr. Jones',
            role: 'clinician',
            status: 'active',
            auth_provider: 'local',
            created_at: '2026-10-01T00:00:00Z'
          })
        } as any;
      }
      if (urlStr.includes('/auth/change-password') && method === 'POST') {
        return {
          ok: true,
          json: async () => ({ detail: 'Password updated successfully.' })
        } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    });

    render(
      <AuthProvider>
        <SecurityProfilePanel />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Dr. Jones')).toBeInTheDocument();
    });

    expect(screen.getByTestId('user-role-badge')).toHaveTextContent('clinician');
    expect(screen.getByTestId('profile-sign-out-btn')).toBeInTheDocument();

    const currentPassInput = screen.getByTestId('current-password-input');
    const newPassInput = screen.getByTestId('new-password-input');
    const confirmPassInput = screen.getByTestId('confirm-password-input');
    const submitBtn = screen.getByTestId('update-password-submit-btn');

    expect(submitBtn).toBeDisabled();

    fireEvent.change(currentPassInput, { target: { value: 'OldPass123!' } });
    fireEvent.change(newPassInput, { target: { value: 'NewSuperPass456!' } });
    fireEvent.change(confirmPassInput, { target: { value: 'NewSuperPass456!' } });

    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText('Password updated successfully.')).toBeInTheDocument();
    });
  });

  it('keeps update button disabled when newPassword and confirmPassword do not match', async () => {
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
            id: 'doc-user-1',
            username: 'doc_jones',
            email: 'jones@clinic.org',
            full_name: 'Dr. Jones',
            role: 'clinician',
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
        <SecurityProfilePanel />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Dr. Jones')).toBeInTheDocument();
    });

    const currentPassInput = screen.getByTestId('current-password-input');
    const newPassInput = screen.getByTestId('new-password-input');
    const confirmPassInput = screen.getByTestId('confirm-password-input');
    const submitBtn = screen.getByTestId('update-password-submit-btn');

    fireEvent.change(currentPassInput, { target: { value: 'OldPass123!' } });
    fireEvent.change(newPassInput, { target: { value: 'NewSuperPass456!' } });
    fireEvent.change(confirmPassInput, { target: { value: 'MismatchPass789!' } });

    // Submit button must remain disabled
    expect(submitBtn).toBeDisabled();

    // Now correct confirm password to match
    fireEvent.change(confirmPassInput, { target: { value: 'NewSuperPass456!' } });
    expect(submitBtn).not.toBeDisabled();
  });
});
