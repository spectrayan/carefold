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
import LoginPage, { sanitizeRedirect } from '@/app/login/page';
import { AuthProvider } from '@/lib/auth';

const mockPush = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => mockSearchParams,
}));

describe('Security: Redirect URI Sanitization & Open Redirect Defenses', () => {
  beforeEach(() => {
    mockPush.mockClear();
    mockSearchParams = new URLSearchParams();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe('sanitizeRedirect unit verification', () => {
    it('sanitizes null, empty, and whitespace strings to root path /', () => {
      expect(sanitizeRedirect(null)).toBe('/');
      expect(sanitizeRedirect('')).toBe('/');
      expect(sanitizeRedirect('   ')).toBe('/');
    });

    it('sanitizes external absolute URLs to root path /', () => {
      expect(sanitizeRedirect('https://evil.com/phish')).toBe('/');
      expect(sanitizeRedirect('http://attacker.org/login')).toBe('/');
      expect(sanitizeRedirect('ftp://evil.com')).toBe('/');
    });

    it('sanitizes protocol-relative URLs to root path /', () => {
      expect(sanitizeRedirect('//evil.com/phish')).toBe('/');
      expect(sanitizeRedirect('//localhost:3000')).toBe('/');
      expect(sanitizeRedirect('///evil.com')).toBe('/');
    });

    it('sanitizes javascript: and data: URIs to root path /', () => {
      expect(sanitizeRedirect('javascript:alert(1)')).toBe('/');
      expect(sanitizeRedirect('javascript:alert(document.cookie)')).toBe('/');
      expect(sanitizeRedirect('data:text/html,<script>alert(1)</script>')).toBe('/');
    });

    it('sanitizes backslash escapes and mixed backslash vectors to root path /', () => {
      expect(sanitizeRedirect('\\evil.com')).toBe('/');
      expect(sanitizeRedirect('/\\evil.com')).toBe('/');
      expect(sanitizeRedirect('\\\\evil.com')).toBe('/');
      expect(sanitizeRedirect('/p/me\\something')).toBe('/');
    });

    it('sanitizes targets containing null bytes or colon schemes to root path /', () => {
      expect(sanitizeRedirect('/login:attack')).toBe('/');
      expect(sanitizeRedirect('/p/me\0bad')).toBe('/');
      expect(sanitizeRedirect('/api/test\0')).toBe('/');
    });

    it('preserves legitimate application relative paths', () => {
      expect(sanitizeRedirect('/p/me')).toBe('/p/me');
      expect(sanitizeRedirect('/admin')).toBe('/admin');
      expect(sanitizeRedirect('/chat?agent=cardiology')).toBe('/chat?agent=cardiology');
      expect(sanitizeRedirect('/family')).toBe('/family');
      expect(sanitizeRedirect('/settings')).toBe('/settings');
      expect(sanitizeRedirect('/library')).toBe('/library');
      expect(sanitizeRedirect('/activity')).toBe('/activity');
    });
  });

  describe('LoginPage security integration tests', () => {
    it('sanitizes external open redirect (https://evil.com/phish) to root / in continue link', async () => {
      mockSearchParams = new URLSearchParams('redirect=https://evil.com/phish');
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const u = String(url);
        if (u.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true }),
          } as any;
        }
        if (u.includes('/auth/me')) {
          return {
            ok: true,
            json: async () => ({
              user: {
                id: 'user-1',
                username: 'victim_alice',
                email: 'alice@example.com',
                role: 'member',
                status: 'active',
                auth_provider: 'local',
              },
            }),
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      const link = await screen.findByRole('link', { name: /continue to application/i });
      expect(link.getAttribute('href')).toBe('/');
    });

    it('sanitizes protocol-relative open redirect (//evil.com/phish) to root / in continue link', async () => {
      mockSearchParams = new URLSearchParams('redirect=//evil.com/phish');
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const u = String(url);
        if (u.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true }),
          } as any;
        }
        if (u.includes('/auth/me')) {
          return {
            ok: true,
            json: async () => ({
              user: {
                id: 'user-1',
                username: 'victim_alice',
                email: 'alice@example.com',
                role: 'member',
                status: 'active',
                auth_provider: 'local',
              },
            }),
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      const link = await screen.findByRole('link', { name: /continue to application/i });
      expect(link.getAttribute('href')).toBe('/');
    });

    it('sanitizes external open redirect on successful login submission to root /', async () => {
      mockSearchParams = new URLSearchParams('redirect=https://evil.com/phish');
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const u = String(url);
        if (u.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true }),
          } as any;
        }
        if (u.includes('/auth/me')) {
          return { ok: false, status: 401, json: async () => ({}) } as any;
        }
        if (u.includes('/auth/login')) {
          return {
            ok: true,
            json: async () => ({
              user: {
                id: 'user-1',
                username: 'alice',
                email: 'alice@example.com',
                role: 'member',
                auth_provider: 'local',
              },
            }),
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByTestId('login-username-input'), { target: { value: 'alice' } });
      fireEvent.change(screen.getByTestId('login-password-input'), { target: { value: 'Password123!' } });
      fireEvent.click(screen.getByTestId('login-submit-btn'));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/');
      });
    });

    it('sanitizes protocol-relative open redirect on login submission to root /', async () => {
      mockSearchParams = new URLSearchParams('redirect=//evil.com/phish');
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const u = String(url);
        if (u.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true }),
          } as any;
        }
        if (u.includes('/auth/me')) {
          return { ok: false, status: 401, json: async () => ({}) } as any;
        }
        if (u.includes('/auth/login')) {
          return {
            ok: true,
            json: async () => ({
              user: {
                id: 'user-1',
                username: 'alice',
                email: 'alice@example.com',
                role: 'member',
                auth_provider: 'local',
              },
            }),
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByTestId('login-username-input'), { target: { value: 'alice' } });
      fireEvent.change(screen.getByTestId('login-password-input'), { target: { value: 'Password123!' } });
      fireEvent.click(screen.getByTestId('login-submit-btn'));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/');
      });
    });

    it('sanitizes javascript: URI target on login submission to root /', async () => {
      mockSearchParams = new URLSearchParams('redirect=javascript:alert(1)');
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const u = String(url);
        if (u.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true }),
          } as any;
        }
        if (u.includes('/auth/me')) {
          return { ok: false, status: 401, json: async () => ({}) } as any;
        }
        if (u.includes('/auth/login')) {
          return {
            ok: true,
            json: async () => ({
              user: {
                id: 'user-1',
                username: 'alice',
                email: 'alice@example.com',
                role: 'member',
                auth_provider: 'local',
              },
            }),
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByTestId('login-username-input'), { target: { value: 'alice' } });
      fireEvent.change(screen.getByTestId('login-password-input'), { target: { value: 'Password123!' } });
      fireEvent.click(screen.getByTestId('login-submit-btn'));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/');
      });
    });

    it('sanitizes backslash escape targets (\\evil.com) on login submission to root /', async () => {
      mockSearchParams = new URLSearchParams('redirect=\\evil.com');
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const u = String(url);
        if (u.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true }),
          } as any;
        }
        if (u.includes('/auth/me')) {
          return { ok: false, status: 401, json: async () => ({}) } as any;
        }
        if (u.includes('/auth/login')) {
          return {
            ok: true,
            json: async () => ({
              user: {
                id: 'user-1',
                username: 'alice',
                email: 'alice@example.com',
                role: 'member',
                auth_provider: 'local',
              },
            }),
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByTestId('login-username-input'), { target: { value: 'alice' } });
      fireEvent.change(screen.getByTestId('login-password-input'), { target: { value: 'Password123!' } });
      fireEvent.click(screen.getByTestId('login-submit-btn'));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/');
      });
    });

    it('preserves legitimate relative targets (/p/me, /admin, /chat?agent=cardiology)', async () => {
      mockSearchParams = new URLSearchParams('redirect=/chat?agent=cardiology');
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const u = String(url);
        if (u.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true }),
          } as any;
        }
        if (u.includes('/auth/me')) {
          return { ok: false, status: 401, json: async () => ({}) } as any;
        }
        if (u.includes('/auth/login')) {
          return {
            ok: true,
            json: async () => ({
              user: {
                id: 'user-1',
                username: 'alice',
                email: 'alice@example.com',
                role: 'member',
                auth_provider: 'local',
              },
            }),
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByTestId('login-username-input'), { target: { value: 'alice' } });
      fireEvent.change(screen.getByTestId('login-password-input'), { target: { value: 'Password123!' } });
      fireEvent.click(screen.getByTestId('login-submit-btn'));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/chat?agent=cardiology');
      });
    });

    it('preserves legitimate relative target in continue link when already authenticated', async () => {
      mockSearchParams = new URLSearchParams('redirect=/p/me');
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const u = String(url);
        if (u.includes('/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true }),
          } as any;
        }
        if (u.includes('/auth/me')) {
          return {
            ok: true,
            json: async () => ({
              user: {
                id: 'user-1',
                username: 'victim_alice',
                email: 'alice@example.com',
                role: 'member',
                status: 'active',
                auth_provider: 'local',
              },
            }),
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      const link = await screen.findByRole('link', { name: /continue to application/i });
      expect(link.getAttribute('href')).toBe('/p/me');
    });
  });
});
