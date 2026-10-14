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
import { GET as getThread } from '@/app/api/chat/threads/[id]/route';

let backendCalls: Array<{ url: string; headers?: any }> = [];

beforeEach(() => {
  backendCalls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      backendCalls.push({ url: String(url), headers: init?.headers });
      const threadId = String(url).split('/').pop();
      if (threadId === 'not-found') {
        return Promise.resolve(
          new Response(JSON.stringify({ error: 'Thread not found' }), {
            status: 404,
            headers: { 'Content-Type': 'application/json' }
          })
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            threadId,
            messages: [
              { role: 'user', content: 'Hello' },
              { role: 'assistant', content: 'Hi there' }
            ],
            count: 2
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          }
        )
      );
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('GET /api/chat/threads/[id] proxy route', () => {
  it('proxies to backend /api/chat/threads/{id} and returns thread data', async () => {
    const res = await getThread(
      new Request('http://localhost:3000/api/chat/threads/thread-123'),
      { params: Promise.resolve({ id: 'thread-123' }) }
    );

    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.threadId).toBe('thread-123');
    expect(data.count).toBe(2);
    expect(backendCalls[0].url).toContain('/api/v1/chat/threads/thread-123');
  });

  it('rejects invalid or traversal slugs with 400', async () => {
    const res = await getThread(
      new Request('http://localhost:3000/api/chat/threads/../etc/passwd'),
      { params: Promise.resolve({ id: '../etc/passwd' }) }
    );

    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.code).toBe('INVALID_ID');
  });

  it('returns 404 when backend returns 404', async () => {
    const res = await getThread(
      new Request('http://localhost:3000/api/chat/threads/not-found'),
      { params: Promise.resolve({ id: 'not-found' }) }
    );

    expect(res.status).toBe(404);
  });
});
