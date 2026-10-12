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
import { NextRequest } from 'next/server';
import { GET, POST } from '@/app/api/chat/resume/route';

let backendCalls: Array<{ url: string; method?: string; headers?: Headers; body?: any }> = [];

describe('POST /api/chat/resume Proxy Route (AU-18)', () => {
  beforeEach(() => {
    backendCalls = [];
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('proxies POST /api/chat/resume to backend /api/v1/chat/resume and returns SSE stream', async () => {
    const encoder = new TextEncoder();
    const mockStream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode('event: token\ndata: {"type":"token","delta":"Tool output completed."}\n\n')
        );
        controller.enqueue(encoder.encode('event: tool_end\ndata: {"type":"tool_end"}\n\n'));
        controller.enqueue(encoder.encode('event: done\ndata: {"type":"done"}\n\n'));
        controller.close();
      }
    });

    const mockResponse = new Response(mockStream, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive'
      }
    });

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        backendCalls.push({
          url: String(url),
          method: init?.method,
          headers: init?.headers as Headers,
          body: init?.body ? JSON.parse(String(init.body)) : undefined
        });
        return Promise.resolve(mockResponse);
      })
    );

    const req = new NextRequest('http://localhost:3000/api/chat/resume', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        authorization: 'Bearer auth_token_abc'
      },
      body: JSON.stringify({
        thread_id: 'thread-test-1',
        approval_id: 'app_test_1',
        decision: 'approved',
        profile_id: 'prof-test-1'
      })
    });
    req.cookies.set('carefold_session', 'session_test_123');

    const res = await POST(req);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('text/event-stream');

    // Verify backend call details
    expect(backendCalls).toHaveLength(1);
    expect(backendCalls[0].url).toContain('/api/v1/chat/resume');
    expect(backendCalls[0].method).toBe('POST');
    expect(backendCalls[0].body).toEqual({
      thread_id: 'thread-test-1',
      approval_id: 'app_test_1',
      decision: 'approved',
      profile_id: 'prof-test-1'
    });
    expect(backendCalls[0].headers?.get('cookie')).toBe('carefold_session=session_test_123');
    expect(backendCalls[0].headers?.get('authorization')).toBe('Bearer auth_token_abc');
    expect(backendCalls[0].headers?.get('accept')).toBe('text/event-stream');

    // Read and verify stream chunks
    const reader = res.body?.getReader();
    expect(reader).toBeDefined();
    const decoder = new TextDecoder();
    let streamText = '';
    while (true) {
      const { done, value } = await reader!.read();
      if (done) break;
      streamText += decoder.decode(value);
    }
    expect(streamText).toContain('event: token');
    expect(streamText).toContain('Tool output completed.');
    expect(streamText).toContain('event: tool_end');
    expect(streamText).toContain('event: done');
  });

  it('supports camelCase field names and forwards edited_args', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        backendCalls.push({
          url: String(url),
          method: init?.method,
          body: init?.body ? JSON.parse(String(init.body)) : undefined
        });
        return Promise.resolve(
          new Response(new ReadableStream(), {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' }
          })
        );
      })
    );

    const req = new Request('http://localhost:3000/api/chat/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        threadId: 'thread-camel',
        approvalId: 'app-camel',
        editedArgs: { date: '2026-11-01', provider: 'Dr. Adams' },
        profileId: 'prof-camel'
      })
    });

    const res = await POST(req);
    expect(res.status).toBe(200);
    expect(backendCalls[0].body).toEqual({
      thread_id: 'thread-camel',
      approval_id: 'app-camel',
      decision: 'approved',
      edited_args: { date: '2026-11-01', provider: 'Dr. Adams' },
      profile_id: 'prof-camel'
    });
  });

  it('rejects missing thread_id with HTTP 400', async () => {
    const req = new Request('http://localhost:3000/api/chat/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approval_id: 'app-1' })
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.code).toBe('MISSING_THREAD_ID');
  });

  it('rejects missing approval_id with HTTP 400', async () => {
    const req = new Request('http://localhost:3000/api/chat/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ thread_id: 'thread-1' })
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.code).toBe('MISSING_APPROVAL_ID');
  });

  it('rejects invalid JSON body with HTTP 400', async () => {
    const req = new Request('http://localhost:3000/api/chat/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{invalid json'
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.code).toBe('INVALID_JSON');
  });

  it('forwards backend error status and body when backend returns non-200', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: 'Approval record not found or already consumed' }),
          { status: 404, headers: { 'Content-Type': 'application/json' } }
        )
      )
    );

    const req = new Request('http://localhost:3000/api/chat/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: 'thread-1',
        approval_id: 'non-existent'
      })
    });

    const res = await POST(req);
    expect(res.status).toBe(404);
    const data = await res.json();
    expect(data.detail).toContain('Approval record not found');
  });

  it('returns HTTP 503 BACKEND_UNREACHABLE on network connection refusal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Connection refused (ECONNREFUSED)'))
    );

    const req = new Request('http://localhost:3000/api/chat/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: 'thread-1',
        approval_id: 'app-1'
      })
    });

    const res = await POST(req);
    expect(res.status).toBe(503);
    const data = await res.json();
    expect(data.code).toBe('BACKEND_UNREACHABLE');
    expect(data.error).toContain('Carefold Python backend is unreachable');
  });

  it('handles GET health probe with HTTP 200', async () => {
    const res = await GET();
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.status).toBe('ok');
    expect(data.service).toBe('chat-resume');
  });
});
