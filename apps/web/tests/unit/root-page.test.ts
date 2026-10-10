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
