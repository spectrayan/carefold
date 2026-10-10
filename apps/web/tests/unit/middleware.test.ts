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

import { describe, it, expect } from 'vitest';
import { NextRequest } from 'next/server';
import { middleware, config } from '@/middleware';

describe('Edge Middleware Auth Route Guards', () => {
  const BASE_URL = 'http://localhost:3000';

  describe('1. Unauthenticated Access to Protected Routes', () => {
    it.each([
      ['/p/me', '/p/me'],
      ['/p/123/chat', '/p/123/chat'],
      ['/agents', '/agents'],
      ['/agents/cardiology-guide', '/agents/cardiology-guide'],
      ['/family', '/family'],
      ['/settings', '/settings'],
      ['/settings/model', '/settings/model'],
      ['/admin', '/admin'],
      ['/admin/users', '/admin/users'],
      ['/library', '/library'],
      ['/activity', '/activity'],
      ['/chat', '/chat'],
      ['/chat/thread-abc', '/chat/thread-abc'],
      ['/helpers', '/helpers'],
    ])('redirects unauthenticated %s to /login?redirect=%s', (path, expectedRedirect) => {
      const req = new NextRequest(new URL(path, BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      const location = res.headers.get('location');
      expect(location).toBe(`${BASE_URL}/login?redirect=${encodeURIComponent(expectedRedirect)}`);
    });

    it('preserves complex query parameters on redirect to /login', () => {
      const req = new NextRequest(new URL('/agents?category=cardiology&page=2&sort=asc', BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      const location = res.headers.get('location');
      expect(location).toBe(
        `${BASE_URL}/login?redirect=${encodeURIComponent('/agents?category=cardiology&page=2&sort=asc')}`
      );
    });

    it('redirects to /login if carefold_session is empty or whitespace', () => {
      const req = new NextRequest(new URL('/settings', BASE_URL), {
        headers: { cookie: 'carefold_session=   ' },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/login?redirect=%2Fsettings`);
    });
  });

  describe('2. Authenticated Access to Protected Routes', () => {
    it('allows access to protected routes when valid carefold_session cookie exists', () => {
      const req = new NextRequest(new URL('/settings/model', BASE_URL), {
        headers: { cookie: 'carefold_session=valid-session-jwt-123' },
      });
      const res = middleware(req);

      expect(res.status).toBe(200);
      expect(res.headers.get('x-middleware-next')).toBe('1');
    });
  });

  describe('3. Authenticated Access to Auth Pages (/login, /register)', () => {
    it('redirects authenticated user from /login to /p/me by default', () => {
      const req = new NextRequest(new URL('/login', BASE_URL), {
        headers: { cookie: 'carefold_session=valid-session-jwt-123' },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/p/me`);
    });

    it('redirects authenticated user from /login to active profile from cookie', () => {
      const req = new NextRequest(new URL('/login', BASE_URL), {
        headers: {
          cookie: 'carefold_session=valid-session-jwt-123; carefold_active_profile=prof-uuid-456',
        },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/p/prof-uuid-456`);
    });

    it('redirects authenticated user from /register to /p/me', () => {
      const req = new NextRequest(new URL('/register', BASE_URL), {
        headers: { cookie: 'carefold_session=valid-session-jwt-123' },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/p/me`);
    });

    it('allows unauthenticated visitors to view /login and /register', () => {
      const loginReq = new NextRequest(new URL('/login', BASE_URL));
      expect(middleware(loginReq).status).toBe(200);

      const registerReq = new NextRequest(new URL('/register', BASE_URL));
      expect(middleware(registerReq).status).toBe(200);
    });
  });

  describe('4. Root Path (/) Redirection at Edge', () => {
    it('redirects unauthenticated root visitors to /login', () => {
      const req = new NextRequest(new URL('/', BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/login`);
    });

    it('redirects authenticated root visitors to active profile', () => {
      const req = new NextRequest(new URL('/', BASE_URL), {
        headers: {
          cookie: 'carefold_session=valid-session-jwt-123; carefold_active_profile=prof-test-789',
        },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/p/prof-test-789`);
    });
  });

  describe('5. Matcher Configuration Invariants', () => {
    const matcherRegex = new RegExp('^' + config.matcher[0] + '$');

    it('matches protected pages', () => {
      expect(matcherRegex.test('/p/me')).toBe(true);
      expect(matcherRegex.test('/settings')).toBe(true);
      expect(matcherRegex.test('/login')).toBe(true);
    });

    it('excludes static assets and internal Next.js paths', () => {
      expect(matcherRegex.test('/_next/static/chunks/main.js')).toBe(false);
      expect(matcherRegex.test('/_next/image')).toBe(false);
      expect(matcherRegex.test('/favicon.ico')).toBe(false);
      expect(matcherRegex.test('/logo.svg')).toBe(false);
      expect(matcherRegex.test('/hero.png')).toBe(false);
      expect(matcherRegex.test('/fonts/inter.woff2')).toBe(false);
    });

    it('excludes API routes from middleware redirect handling', () => {
      expect(matcherRegex.test('/api/v1/auth/me')).toBe(false);
      expect(matcherRegex.test('/api/health')).toBe(false);
    });
  });
});
