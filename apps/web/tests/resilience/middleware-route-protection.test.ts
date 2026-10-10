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
import { middleware, config, PROTECTED_PREFIXES, AUTH_ENTRY_ROUTES } from '@/middleware';

const BASE_URL = 'http://localhost:3000';

describe('Edge Middleware Route Guarding & Path Bypass Suite', () => {
  // =========================================================================
  // Section 1: Unauthorized Access Across All 9 Protected Route Prefixes
  // =========================================================================
  describe('1. Unauthorized Access Across All 9 Protected Route Prefixes', () => {
    it('verifies all 9 protected prefixes are explicitly registered', () => {
      const expected = [
        '/p',
        '/agents',
        '/family',
        '/settings',
        '/admin',
        '/library',
        '/activity',
        '/chat',
        '/helpers',
      ];
      expect(PROTECTED_PREFIXES).toHaveLength(9);
      for (const p of expected) {
        expect(PROTECTED_PREFIXES).toContain(p);
      }
    });

    const routeMatrix = [
      // /p prefix and subroutes
      { path: '/p', expectedRedirect: '/p' },
      { path: '/p/me', expectedRedirect: '/p/me' },
      { path: '/p/prof-uuid-1234', expectedRedirect: '/p/prof-uuid-1234' },
      { path: '/p/prof-uuid-1234/chat', expectedRedirect: '/p/prof-uuid-1234/chat' },
      { path: '/p/prof-uuid-1234/notes/slug-1', expectedRedirect: '/p/prof-uuid-1234/notes/slug-1' },

      // /agents prefix and subroutes
      { path: '/agents', expectedRedirect: '/agents' },
      { path: '/agents/cardiology-guide', expectedRedirect: '/agents/cardiology-guide' },
      { path: '/agents/pulmonology-guide', expectedRedirect: '/agents/pulmonology-guide' },

      // /family prefix and subroutes
      { path: '/family', expectedRedirect: '/family' },
      { path: '/family/invites', expectedRedirect: '/family/invites' },
      { path: '/family/members/edit', expectedRedirect: '/family/members/edit' },

      // /settings prefix and subroutes
      { path: '/settings', expectedRedirect: '/settings' },
      { path: '/settings/model', expectedRedirect: '/settings/model' },
      { path: '/settings/privacy', expectedRedirect: '/settings/privacy' },
      { path: '/settings/account', expectedRedirect: '/settings/account' },
      { path: '/settings/diagnostics', expectedRedirect: '/settings/diagnostics' },

      // /admin prefix and subroutes
      { path: '/admin', expectedRedirect: '/admin' },
      { path: '/admin/users', expectedRedirect: '/admin/users' },
      { path: '/admin/settings', expectedRedirect: '/admin/settings' },
      { path: '/admin/diagnostics', expectedRedirect: '/admin/diagnostics' },

      // /library prefix and subroutes
      { path: '/library', expectedRedirect: '/library' },
      { path: '/library/docs', expectedRedirect: '/library/docs' },
      { path: '/library/history', expectedRedirect: '/library/history' },

      // /activity prefix and subroutes
      { path: '/activity', expectedRedirect: '/activity' },
      { path: '/activity/logs', expectedRedirect: '/activity/logs' },
      { path: '/activity/telemetry', expectedRedirect: '/activity/telemetry' },

      // /chat prefix and subroutes
      { path: '/chat', expectedRedirect: '/chat' },
      { path: '/chat/thread-active-99', expectedRedirect: '/chat/thread-active-99' },
      { path: '/chat/new', expectedRedirect: '/chat/new' },

      // /helpers prefix and subroutes
      { path: '/helpers', expectedRedirect: '/helpers' },
      { path: '/helpers/cardiology-guide', expectedRedirect: '/helpers/cardiology-guide' },
      { path: '/helpers/skills', expectedRedirect: '/helpers/skills' },
    ];

    it.each(routeMatrix)(
      'intercepts unauthenticated request to $path and redirects to /login?redirect=$expectedRedirect',
      ({ path, expectedRedirect }) => {
        const req = new NextRequest(new URL(path, BASE_URL));
        const res = middleware(req);

        expect(res.status).toBe(307);
        const location = res.headers.get('location');
        expect(location).toBe(`${BASE_URL}/login?redirect=${encodeURIComponent(expectedRedirect)}`);
      }
    );

    it('rejects unauthenticated requests when session cookie contains only spaces or empty string', () => {
      const emptyValues = ['', '   ', '\t', '\n'];
      for (const val of emptyValues) {
        const req = new NextRequest(new URL('/p/me', BASE_URL), {
          headers: { cookie: `carefold_session=${val}` },
        });
        const res = middleware(req);
        expect(res.status).toBe(307);
        expect(res.headers.get('location')).toBe(`${BASE_URL}/login?redirect=%2Fp%2Fme`);
      }
    });

    it('allows access to all 9 protected prefixes when valid session cookie exists', () => {
      for (const prefix of PROTECTED_PREFIXES) {
        const req = new NextRequest(new URL(`${prefix}/section`, BASE_URL), {
          headers: { cookie: 'carefold_session=valid-session-jwt-hash' },
        });
        const res = middleware(req);

        expect(res.status).toBe(200);
        expect(res.headers.get('x-middleware-next')).toBe('1');
      }
    });
  });

  // =========================================================================
  // Section 2: URL Path Tampering & Boundary Attacks
  // =========================================================================
  describe('2. URL Path Tampering & Boundary Attacks', () => {
    it('normalizes path traversal attacks (/login/../admin) to protected /admin', () => {
      const req = new NextRequest(new URL('/login/../admin', BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/login?redirect=%2Fadmin`);
    });

    it('normalizes path traversal attacks (/p/../admin) to protected /admin', () => {
      const req = new NextRequest(new URL('/p/../admin', BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/login?redirect=%2Fadmin`);
    });

    it('normalizes path traversal attacks (/p/me/../../settings) to protected /settings', () => {
      const req = new NextRequest(new URL('/p/me/../../settings', BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/login?redirect=%2Fsettings`);
    });

    it('normalizes lowercase encoded dot traversal (/p/%2e%2e/admin) to protected /admin', () => {
      const req = new NextRequest(new URL('/p/%2e%2e/admin', BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/login?redirect=%2Fadmin`);
    });

    it('normalizes uppercase encoded dot traversal (/p/%2E%2E/chat) to protected /chat', () => {
      const req = new NextRequest(new URL('/p/%2E%2E/chat', BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/login?redirect=%2Fchat`);
    });

    it('protects routes with trailing slashes (/admin/, /chat/, /settings/)', () => {
      const trailingSlashRoutes = ['/admin/', '/chat/', '/settings/', '/agents/', '/family/'];
      for (const route of trailingSlashRoutes) {
        const req = new NextRequest(new URL(route, BASE_URL));
        const res = middleware(req);

        expect(res.status).toBe(307);
        expect(res.headers.get('location')).toBe(`${BASE_URL}/login?redirect=${encodeURIComponent(route)}`);
      }
    });

    it('handles protocol-relative / double slash URLs (//admin) by redirecting to /login', () => {
      // In WHATWG URL parsing, //admin treats admin as the host and / as the path.
      // NextRequest evaluates the pathname as / which triggers the root unauthenticated redirect to /login.
      const req = new NextRequest(new URL('//admin', BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toContain('/login');
    });
  });

  // =========================================================================
  // Section 3: Redirect Query Parameter Preservation
  // =========================================================================
  describe('3. Redirect Query Parameter Preservation', () => {
    it('preserves thread_id and agent query parameters on /chat', () => {
      const originalPath = '/chat?thread_id=xyz-987&agent=cardiology-guide';
      const req = new NextRequest(new URL(originalPath, BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      const location = res.headers.get('location')!;
      const parsedUrl = new URL(location);

      expect(parsedUrl.pathname).toBe('/login');
      expect(parsedUrl.searchParams.get('redirect')).toBe(originalPath);
    });

    it('preserves multi-filter, search, and pagination query params on /agents', () => {
      const originalPath = '/agents?query=heart&category=cardiology&page=3&sort=asc&verified=true';
      const req = new NextRequest(new URL(originalPath, BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      const parsedUrl = new URL(res.headers.get('location')!);
      expect(parsedUrl.searchParams.get('redirect')).toBe(originalPath);
    });

    it('preserves encoded characters and special symbols in query parameters', () => {
      const originalPath = '/helpers?search=diabetes%20type%202&filter=%23urgent&ref=test%26more';
      const req = new NextRequest(new URL(originalPath, BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      const parsedUrl = new URL(res.headers.get('location')!);
      expect(parsedUrl.searchParams.get('redirect')).toBe(originalPath);
    });
  });

  // =========================================================================
  // Section 4: Authenticated Visitors Accessing /login and /register
  // =========================================================================
  describe('4. Authenticated Visitors Accessing /login and /register', () => {
    it('redirects authenticated visitor on /login to active profile ID', () => {
      const req = new NextRequest(new URL('/login', BASE_URL), {
        headers: {
          cookie: 'carefold_session=valid-session; carefold_active_profile=prof-child-101',
        },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/p/prof-child-101`);
    });

    it('redirects authenticated visitor on /login to /p/me if active profile cookie is absent', () => {
      const req = new NextRequest(new URL('/login', BASE_URL), {
        headers: {
          cookie: 'carefold_session=valid-session',
        },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/p/me`);
    });

    it('redirects authenticated visitor on /register to active profile ID', () => {
      const req = new NextRequest(new URL('/register', BASE_URL), {
        headers: {
          cookie: 'carefold_session=valid-session; carefold_active_profile=prof-spouse-202',
        },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/p/prof-spouse-202`);
    });

    it('allows unauthenticated visitors to view /login and /register without redirection', () => {
      for (const route of AUTH_ENTRY_ROUTES) {
        const req = new NextRequest(new URL(route, BASE_URL));
        const res = middleware(req);

        expect(res.status).toBe(200);
        expect(res.headers.get('x-middleware-next')).toBe('1');
      }
    });
  });

  // =========================================================================
  // Section 5: Static Asset and API Bypass Invariants
  // =========================================================================
  describe('5. Static Asset and API Bypass Invariants', () => {
    const matcherRegex = new RegExp('^' + config.matcher[0] + '$');

    it('excludes Next.js static files (_next/static)', () => {
      expect(matcherRegex.test('/_next/static/chunks/main.js')).toBe(false);
      expect(matcherRegex.test('/_next/static/css/global.css')).toBe(false);
      expect(matcherRegex.test('/_next/static/media/font.woff2')).toBe(false);
    });

    it('excludes Next.js image optimization API (_next/image)', () => {
      expect(matcherRegex.test('/_next/image')).toBe(false);
      expect(matcherRegex.test('/_next/image?url=%2Flogo.png&w=128')).toBe(false);
    });

    it('excludes root metadata assets (favicon.ico)', () => {
      expect(matcherRegex.test('/favicon.ico')).toBe(false);
    });

    it('excludes all dual-mounted API routes (/api/* and /api/v1/*)', () => {
      const endpoints = [
        '/api/v1/auth/me',
        '/api/v1/auth/login',
        '/api/v1/auth/logout',
        '/api/v1/profiles',
        '/api/v1/chat',
        '/api/v1/notes',
        '/api/v1/attachments',
        '/api/v1/audit',
        '/api/v1/models',
        '/api/v1/health',
        '/api/auth/me',
        '/api/health',
        '/api/agents',
        '/api/skills',
      ];
      for (const ep of endpoints) {
        expect(matcherRegex.test(ep)).toBe(false);
      }
    });

    it('excludes static media and web assets by file extension', () => {
      const staticPaths = [
        '/images/logo.svg',
        '/images/banner.png',
        '/photos/doctor.jpg',
        '/photos/clinic.jpeg',
        '/loaders/spinner.gif',
        '/hero.webp',
        '/favicon.ico',
        '/fonts/inter.woff',
        '/fonts/inter.woff2',
        '/fonts/roboto.ttf',
        '/theme.css',
        '/bundle.js',
      ];
      for (const sp of staticPaths) {
        expect(matcherRegex.test(sp)).toBe(false);
      }
    });
  });

  // =========================================================================
  // Section 6: Root Page Redirection at Edge
  // =========================================================================
  describe('6. Root Page Redirection at Edge', () => {
    it('redirects unauthenticated root (/) visitor to /login', () => {
      const req = new NextRequest(new URL('/', BASE_URL));
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/login`);
    });

    it('redirects authenticated root (/) visitor to /p/me if active profile cookie is absent', () => {
      const req = new NextRequest(new URL('/', BASE_URL), {
        headers: { cookie: 'carefold_session=valid-session-jwt' },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/p/me`);
    });

    it('redirects authenticated root (/) visitor to active profile ID', () => {
      const req = new NextRequest(new URL('/', BASE_URL), {
        headers: {
          cookie: 'carefold_session=valid-session-jwt; carefold_active_profile=prof-root-555',
        },
      });
      const res = middleware(req);

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toBe(`${BASE_URL}/p/prof-root-555`);
    });
  });
});
