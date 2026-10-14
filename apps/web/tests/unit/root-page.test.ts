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

/**
 * @vitest-environment node
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import RootPage from '@/app/page';

const mockRedirect = vi.fn();
vi.mock('next/navigation', () => ({
  redirect: (url: string) => mockRedirect(url)
}));

let mockCookieStore: Record<string, string | undefined> = {};
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({
    get: (key: string) => (mockCookieStore[key] ? { value: mockCookieStore[key] } : undefined),
  }))
}));

describe('RootPage Server Component (/page.tsx)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCookieStore = {};
  });

  it('redirects unauthenticated visitor to /login when carefold_session is missing', async () => {
    await RootPage();
    expect(mockRedirect).toHaveBeenCalledWith('/login');
  });

  it('redirects unauthenticated visitor to /login when carefold_session is empty whitespace', async () => {
    mockCookieStore['carefold_session'] = '   ';
    await RootPage();
    expect(mockRedirect).toHaveBeenCalledWith('/login');
  });

  it('redirects authenticated visitor to /p/me when carefold_active_profile is not set', async () => {
    mockCookieStore['carefold_session'] = 'valid-token';
    await RootPage();
    expect(mockRedirect).toHaveBeenCalledWith('/p/me');
  });

  it('redirects authenticated visitor to active profile ID when cookie is present', async () => {
    mockCookieStore['carefold_session'] = 'valid-token';
    mockCookieStore['carefold_active_profile'] = 'profile-active-uuid';
    await RootPage();
    expect(mockRedirect).toHaveBeenCalledWith('/p/profile-active-uuid');
  });
});
