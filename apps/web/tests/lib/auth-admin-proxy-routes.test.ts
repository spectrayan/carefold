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

/**
 * @vitest-environment node
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NextRequest } from 'next/server';
import {
  GET as getAuth,
  POST as postAuth,
  PUT as putAuth,
  PATCH as patchAuth,
  DELETE as deleteAuth
} from '@/app/api/auth/[...path]/route';
import {
  GET as getAdmin,
  PUT as putAdmin,
  DELETE as deleteAdmin
} from '@/app/api/admin/[...path]/route';

describe('Catch-All Auth & Admin Proxy Routes', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe('1. Auth Catch-All Proxy: Cookie Forwarding & Propagation', () => {
    it('forwards incoming Cookie header to backend fetch call', async () => {
      let capturedHeaders: Headers | undefined;
      let capturedUrl = '';

      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((url: string, init: RequestInit) => {
          capturedUrl = url;
          capturedHeaders = init.headers as Headers;
          return Promise.resolve(
            new Response(JSON.stringify({ username: 'testuser', role: 'member' }), {
              status: 200,
              headers: { 'Content-Type': 'application/json' }
            })
          );
        })
      );

      const incomingCookie = 'carefold_session=sess_abc123xyz; theme=dark; tz=UTC';
      const req = new NextRequest('http://localhost:3000/api/auth/me', {
        headers: {
          cookie: incomingCookie,
          authorization: 'Bearer token-789'
        }
      });

      const res = await getAuth(req, { params: Promise.resolve({ path: ['me'] }) });

      expect(res.status).toBe(200);
      expect(capturedUrl).toContain('/api/v1/auth/me');
      expect(capturedHeaders).toBeDefined();
      expect(capturedHeaders?.get('cookie')).toBe(incomingCookie);
      expect(capturedHeaders?.get('authorization')).toBe('Bearer token-789');
      expect(capturedHeaders?.get('accept')).toBe('application/json');
    });

    it('does not set cookie header on fetch if incoming request has no cookies', async () => {
      let capturedHeaders: Headers | undefined;

      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((_url: string, init: RequestInit) => {
          capturedHeaders = init.headers as Headers;
          return Promise.resolve(
            new Response(JSON.stringify({ detail: 'Not authenticated' }), {
              status: 401,
              headers: { 'Content-Type': 'application/json' }
            })
          );
        })
      );

      const req = new NextRequest('http://localhost:3000/api/auth/me');
      const res = await getAuth(req, { params: Promise.resolve({ path: ['me'] }) });

      expect(res.status).toBe(401);
      expect(capturedHeaders?.get('cookie')).toBeNull();
    });

    it('preserves and maps multiple Set-Cookie headers from backend via getSetCookie()', async () => {
      const backendHeaders = new Headers();
      backendHeaders.append('set-cookie', 'carefold_session=session_token_123; Path=/; HttpOnly; SameSite=Lax');
      backendHeaders.append('set-cookie', 'carefold_refresh=refresh_token_456; Path=/; HttpOnly; SameSite=Strict');
      backendHeaders.set('content-type', 'application/json');

      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ user: { id: 'u-1', username: 'alice' } }), {
            status: 200,
            headers: backendHeaders
          })
        )
      );

      const req = new NextRequest('http://localhost:3000/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username_or_email: 'alice', password: 'Password123!' })
      });

      const res = await postAuth(req, { params: Promise.resolve({ path: ['login'] }) });

      expect(res.status).toBe(200);
      const setCookies = res.headers.getSetCookie();
      expect(setCookies).toBeDefined();
      expect(setCookies.length).toBe(2);
      expect(setCookies[0]).toContain('carefold_session=session_token_123');
      expect(setCookies[1]).toContain('carefold_refresh=refresh_token_456');
    });

    it('falls back to single set-cookie header if backend headers lack getSetCookie', async () => {
      const mockBackendRes = {
        status: 200,
        text: () => Promise.resolve(JSON.stringify({ success: true })),
        headers: {
          get: (name: string) => {
            if (name.toLowerCase() === 'set-cookie') {
              return 'carefold_session=fallback_cookie; Path=/; HttpOnly';
            }
            if (name.toLowerCase() === 'content-type') {
              return 'application/json';
            }
            return null;
          },
          getSetCookie: undefined
        }
      };

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockBackendRes));

      const req = new NextRequest('http://localhost:3000/api/auth/logout', { method: 'POST' });
      const res = await postAuth(req, { params: Promise.resolve({ path: ['logout'] }) });

      expect(res.status).toBe(200);
      expect(res.headers.get('set-cookie')).toContain('carefold_session=fallback_cookie');
    });
  });

  describe('2. Auth Route Error Handling & Unauthenticated /api/auth/me', () => {
    it('returns 401 without 500 when unauthenticated client calls /api/auth/me in local mode', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ detail: 'Not authenticated' }), {
            status: 401,
            headers: { 'Content-Type': 'application/json' }
          })
        )
      );

      const req = new NextRequest('http://localhost:3000/api/auth/me');
      const res = await getAuth(req, { params: Promise.resolve({ path: ['me'] }) });

      expect(res.status).toBe(401);
      const body = await res.json();
      expect(body).toEqual({ detail: 'Not authenticated' });
    });

    it('returns stewardship defaults (200) without error when backend is in disabled mode', async () => {
      const stewardProfile = {
        id: '00000000-0000-0000-0000-000000000001',
        email: 'steward@carefold.local',
        username: 'steward',
        full_name: 'Local Care Steward',
        role: 'admin',
        status: 'active',
        auth_provider: 'disabled'
      };

      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify(stewardProfile), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          })
        )
      );

      const req = new NextRequest('http://localhost:3000/api/auth/me');
      const res = await getAuth(req, { params: Promise.resolve({ path: ['me'] }) });

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.username).toBe('steward');
      expect(body.role).toBe('admin');
      expect(body.auth_provider).toBe('disabled');
    });

    it('returns 503 BACKEND_UNREACHABLE without unhandled 500 when backend fetch fails', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockRejectedValue(new Error('connect ECONNREFUSED 127.0.0.1:8010'))
      );

      const req = new NextRequest('http://localhost:3000/api/auth/me');
      const res = await getAuth(req, { params: Promise.resolve({ path: ['me'] }) });

      expect(res.status).toBe(503);
      const body = await res.json();
      expect(body.code).toBe('BACKEND_UNREACHABLE');
      expect(body.error).toContain('ECONNREFUSED');
    });
  });

  describe('3. Auth Route HTTP Methods & Query Parameters', () => {
    it('preserves query parameters on proxied auth URL', async () => {
      let capturedUrl = '';
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((url: string) => {
          capturedUrl = url;
          return Promise.resolve(new Response(JSON.stringify({ providers: ['local'] }), { status: 200 }));
        })
      );

      const req = new NextRequest('http://localhost:3000/api/auth/providers?redirect=%2Fchat&mode=test');
      const res = await getAuth(req, { params: Promise.resolve({ path: ['providers'] }) });

      expect(res.status).toBe(200);
      expect(capturedUrl).toContain('/api/v1/auth/providers?redirect=%2Fchat&mode=test');
    });

    it('supports multi-segment path hierarchy (e.g. /oauth/callback/google)', async () => {
      let capturedUrl = '';
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((url: string) => {
          capturedUrl = url;
          return Promise.resolve(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }));
        })
      );

      const req = new NextRequest('http://localhost:3000/api/auth/oauth/callback/google');
      const res = await getAuth(req, { params: Promise.resolve({ path: ['oauth', 'callback', 'google'] }) });

      expect(res.status).toBe(200);
      expect(capturedUrl).toContain('/api/v1/auth/oauth/callback/google');
    });

    it('handles PUT, PATCH, and DELETE requests forwarding bodies', async () => {
      const capturedCalls: { method: string; url: string; body?: string }[] = [];

      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((url: string, init: RequestInit) => {
          capturedCalls.push({
            method: init.method || 'GET',
            url,
            body: init.body ? String(init.body) : undefined
          });
          return Promise.resolve(new Response(JSON.stringify({ success: true }), { status: 200 }));
        })
      );

      // PUT
      const putReq = new NextRequest('http://localhost:3000/api/auth/password', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old: 'Pass1', new: 'Pass2' })
      });
      await putAuth(putReq, { params: Promise.resolve({ path: ['password'] }) });

      // PATCH
      const patchReq = new NextRequest('http://localhost:3000/api/auth/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'New Name' })
      });
      await patchAuth(patchReq, { params: Promise.resolve({ path: ['profile'] }) });

      // DELETE
      const deleteReq = new NextRequest('http://localhost:3000/api/auth/sessions/active', {
        method: 'DELETE'
      });
      await deleteAuth(deleteReq, { params: Promise.resolve({ path: ['sessions', 'active'] }) });

      expect(capturedCalls.length).toBe(3);
      expect(capturedCalls[0].method).toBe('PUT');
      expect(capturedCalls[0].body).toContain('Pass2');
      expect(capturedCalls[1].method).toBe('PATCH');
      expect(capturedCalls[1].body).toContain('New Name');
      expect(capturedCalls[2].method).toBe('DELETE');
    });
  });

  describe('4. Admin Catch-All Proxy Route: Security & Cookie Propagation', () => {
    it('forwards cookies and authorization to backend admin endpoints', async () => {
      let capturedHeaders: Headers | undefined;
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((_url: string, init: RequestInit) => {
          capturedHeaders = init.headers as Headers;
          return Promise.resolve(
            new Response(JSON.stringify({ active_provider: 'local' }), { status: 200 })
          );
        })
      );

      const req = new NextRequest('http://localhost:3000/api/admin/settings', {
        headers: {
          cookie: 'carefold_session=admin_sess_999',
          authorization: 'Bearer admin-token'
        }
      });

      const res = await getAdmin(req, { params: Promise.resolve({ path: ['settings'] }) });

      expect(res.status).toBe(200);
      expect(capturedHeaders?.get('cookie')).toBe('carefold_session=admin_sess_999');
      expect(capturedHeaders?.get('authorization')).toBe('Bearer admin-token');
    });

    it('preserves multiple Set-Cookie headers on admin responses', async () => {
      const backendHeaders = new Headers();
      backendHeaders.append('set-cookie', 'admin_audit=audit_log_1; Path=/admin; HttpOnly');
      backendHeaders.append('set-cookie', 'admin_pref=dark; Path=/admin');
      backendHeaders.set('content-type', 'application/json');

      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ status: 'updated' }), {
            status: 200,
            headers: backendHeaders
          })
        )
      );

      const req = new NextRequest('http://localhost:3000/api/admin/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active_provider: 'local' })
      });

      const res = await putAdmin(req, { params: Promise.resolve({ path: ['settings'] }) });

      expect(res.status).toBe(200);
      const setCookies = res.headers.getSetCookie();
      expect(setCookies.length).toBe(2);
      expect(setCookies[0]).toContain('admin_audit=audit_log_1');
      expect(setCookies[1]).toContain('admin_pref=dark');
    });

    it('transparently passes 403 Forbidden to non-admin clients without 500 error', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ detail: 'Admin privileges required' }), {
            status: 403,
            headers: { 'Content-Type': 'application/json' }
          })
        )
      );

      const req = new NextRequest('http://localhost:3000/api/admin/users');
      const res = await getAdmin(req, { params: Promise.resolve({ path: ['users'] }) });

      expect(res.status).toBe(403);
      const body = await res.json();
      expect(body.detail).toBe('Admin privileges required');
    });

    it('returns 503 BACKEND_UNREACHABLE when admin backend is offline', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockRejectedValue(new Error('Connection failed'))
      );

      const req = new NextRequest('http://localhost:3000/api/admin/users/user-1', {
        method: 'DELETE'
      });
      const res = await deleteAdmin(req, { params: Promise.resolve({ path: ['users', 'user-1'] }) });

      expect(res.status).toBe(503);
      const body = await res.json();
      expect(body.code).toBe('BACKEND_UNREACHABLE');
    });
  });
});
