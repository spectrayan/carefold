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
  const hasError = request.nextUrl.searchParams.has('error');
  const isForce = request.nextUrl.searchParams.has('force');

  if (isAuthEntry) {
    if (hasError || isForce) {
      const response = NextResponse.next();
      response.cookies.delete('carefold_session');
      return response;
    }
    if (isAuthenticated) {
      const profileId = getActiveProfileId();
      return NextResponse.redirect(new URL(`/p/${profileId}`, request.url));
    }
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
