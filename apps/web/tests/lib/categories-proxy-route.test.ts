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
import { GET as getCategories } from '@/app/api/agents/categories/route';

let backendCalls: Array<{ url: string; headers?: any }> = [];

beforeEach(() => {
  backendCalls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      backendCalls.push({ url: String(url), headers: init?.headers });
      const mockCategoryTree = {
        total: 22,
        domains: {
          clinical: { count: 15, categories: {} },
          navigation: { count: 6, categories: {} },
          wellness: { count: 1, categories: {} },
          therapy: { count: 0, categories: {} },
          education: { count: 0, categories: {} },
        },
      };
      return Promise.resolve(
        new Response(JSON.stringify(mockCategoryTree), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('GET /api/agents/categories proxy route', () => {
  it('proxies to backend /api/agents/categories endpoint', async () => {
    const res = await getCategories(new Request('http://localhost:3000/api/agents/categories'));
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.total).toBe(22);
    expect(data.domains.clinical.count).toBe(15);
    expect(backendCalls.length).toBe(1);
    expect(backendCalls[0].url).toContain('/api/v1/agents/categories');
  });

  it('returns 503 BACKEND_UNREACHABLE on backend connection failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Connection refused'))
    );
    const res = await getCategories(new Request('http://localhost:3000/api/agents/categories'));
    expect(res.status).toBe(503);
    const data = await res.json();
    expect(data.code).toBe('BACKEND_UNREACHABLE');
  });
});
