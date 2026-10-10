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

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

/**
 * All protected application route prefixes requiring an active carefold_session.
 */
export const PROTECTED_PREFIXES = [
  '/p',
  '/agents',
  '/family',
  '/settings',
  '/admin',
  '/library',
  '/activity',
  '/chat',
  '/helpers',
] as const;

/**
 * Public authentication routes where authenticated users should be diverted to their active profile.
 */
export const AUTH_ENTRY_ROUTES = ['/login', '/register'] as const;

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const sessionCookie = request.cookies.get('carefold_session')?.value;
  const isAuthenticated = Boolean(sessionCookie && sessionCookie.trim());


  // Helper to extract active profile ID (or default to 'me')
  const getActiveProfileId = (): string => {
    const activeProfileCookie = request.cookies.get('carefold_active_profile')?.value;
    return (activeProfileCookie && activeProfileCookie.trim()) || 'me';
  };

  // 1. Root route evaluation at edge (Defense-in-depth with app/page.tsx)
  if (pathname === '/') {
    if (!isAuthenticated) {
      return NextResponse.redirect(new URL('/login', request.url));
    }
    const profileId = getActiveProfileId();
    return NextResponse.redirect(new URL(`/p/${profileId}`, request.url));
  }

  // 2. Protected routes evaluation
  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );

  if (isProtected && !isAuthenticated) {
    const loginUrl = new URL('/login', request.url);
    const targetPath = `${pathname}${search}`;
    loginUrl.searchParams.set('redirect', targetPath);
    return NextResponse.redirect(loginUrl);
  }

  // 3. Authenticated visitors accessing auth entrypoints (/login, /register)
  const isAuthEntry = AUTH_ENTRY_ROUTES.some((route) => pathname === route);
  if (isAuthEntry && isAuthenticated) {
    const profileId = getActiveProfileId();
    return NextResponse.redirect(new URL(`/p/${profileId}`, request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static build artifacts)
     * - _next/image (image optimization API)
     * - favicon.ico, sitemap.xml, robots.txt
     * - api/ (FastAPI reverse proxy routes and Next.js route handlers)
     * - Static asset file extensions (.svg, .png, .jpg, .jpeg, .gif, .webp, .ico, .woff, .woff2, .ttf, .css, .js)
     */
    '/((?!_next/static|_next/image|favicon.ico|api(?:/|$)|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|woff|woff2|ttf|css|js)$).*)',
  ],
};
