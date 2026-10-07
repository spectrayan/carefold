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
    expect(backendCalls[0].url).toContain('/api/chat/threads/thread-123');
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
