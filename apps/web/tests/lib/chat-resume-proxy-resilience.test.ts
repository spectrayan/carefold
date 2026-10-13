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
import { POST } from '@/app/api/chat/resume/route';

describe('Resilience Suite: POST /api/chat/resume Proxy Route', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe('1. Malformed and Boundary JSON Payloads', () => {
    it('rejects broken/unclosed JSON syntax with 400 INVALID_JSON', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{"thread_id": "t1", "approval_id": "a1", unclosed'
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.code).toBe('INVALID_JSON');
    });

    it('rejects empty string body with 400 INVALID_JSON', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: ''
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.code).toBe('INVALID_JSON');
    });

    it('rejects whitespace-only body with 400 INVALID_JSON', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '   \n\t  '
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.code).toBe('INVALID_JSON');
    });

    it('handles JSON numeric primitive "123" without crashing (400 MISSING_THREAD_ID)', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '123'
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.code).toBe('MISSING_THREAD_ID');
    });

    it('handles JSON boolean primitive "true" without crashing (400 MISSING_THREAD_ID)', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: 'true'
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.code).toBe('MISSING_THREAD_ID');
    });

    it('handles JSON array primitive "[]" without crashing (400 MISSING_THREAD_ID)', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '[]'
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.code).toBe('MISSING_THREAD_ID');
    });

    it('handles JSON "null" payload: surfaces unhandled TypeError due to missing object check (CF-RESUME-01)', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: 'null'
      });
      // Documents empirical observation: body is parsed as null, causing TypeError on body.thread_id
      await expect(POST(req)).rejects.toThrow(TypeError);
    });
  });

  describe('2. Empty Strings, Type Violations, and Whitespace', () => {
    it('rejects empty string thread_id', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: '', approval_id: 'app-1' })
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      expect((await res.json()).code).toBe('MISSING_THREAD_ID');
    });

    it('rejects whitespace-only thread_id', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: '   \t  ', approval_id: 'app-1' })
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      expect((await res.json()).code).toBe('MISSING_THREAD_ID');
    });

    it('rejects non-string thread_id (e.g. number or object)', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: 12345, approval_id: 'app-1' })
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      expect((await res.json()).code).toBe('MISSING_THREAD_ID');
    });

    it('rejects empty string approval_id', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: 'thread-1', approval_id: '' })
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      expect((await res.json()).code).toBe('MISSING_APPROVAL_ID');
    });

    it('rejects whitespace-only approval_id', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: 'thread-1', approval_id: '  \n  ' })
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      expect((await res.json()).code).toBe('MISSING_APPROVAL_ID');
    });

    it('rejects non-string approval_id', async () => {
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: 'thread-1', approval_id: { id: 'app-1' } })
      });
      const res = await POST(req);
      expect(res.status).toBe(400);
      expect((await res.json()).code).toBe('MISSING_APPROVAL_ID');
    });
  });

  describe('3. Null Bytes and Injection Boundary Payloads', () => {
    it('safely handles null bytes in thread_id and forwards cleanly', async () => {
      let forwardedBody: any = null;
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
          forwardedBody = JSON.parse(String(init?.body));
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
          thread_id: 'thread\u0000injected',
          approval_id: 'app_1'
        })
      });

      const res = await POST(req);
      expect(res.status).toBe(200);
      expect(forwardedBody.thread_id).toBe('thread\u0000injected');
    });

    it('safely handles null bytes in approval_id and forwards cleanly', async () => {
      let forwardedBody: any = null;
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
          forwardedBody = JSON.parse(String(init?.body));
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
          thread_id: 'thread_1',
          approval_id: 'app_\u0000escape'
        })
      });

      const res = await POST(req);
      expect(res.status).toBe(200);
      expect(forwardedBody.approval_id).toBe('app_\u0000escape');
    });
  });

  describe('4. Oversized Bodies and Heavy Payloads', () => {
    it('successfully processes large payload with 2MB edited_args', async () => {
      let forwardedPayloadSize = 0;
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
          forwardedPayloadSize = String(init?.body).length;
          return Promise.resolve(
            new Response(new ReadableStream(), {
              status: 200,
              headers: { 'Content-Type': 'text/event-stream' }
            })
          );
        })
      );

      const largeData = 'x'.repeat(2 * 1024 * 1024); // 2MB string
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          thread_id: 'thread_large',
          approval_id: 'app_large',
          edited_args: { largeBlob: largeData }
        })
      });

      const res = await POST(req);
      expect(res.status).toBe(200);
      expect(forwardedPayloadSize).toBeGreaterThan(2 * 1024 * 1024);
    });
  });

  describe('5. Network Abort & Signal Cancellation', () => {
    it('handles aborted request signal before fetch completes', async () => {
      const abortController = new AbortController();
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
          return new Promise((_, reject) => {
            if (init?.signal?.aborted) {
              const err = new Error('The operation was aborted.');
              err.name = 'AbortError';
              return reject(err);
            }
            init?.signal?.addEventListener('abort', () => {
              const err = new Error('The operation was aborted.');
              err.name = 'AbortError';
              reject(err);
            });
          });
        })
      );

      abortController.abort();

      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abortController.signal,
        body: JSON.stringify({
          thread_id: 'thread_abort',
          approval_id: 'app_abort'
        })
      });

      const res = await POST(req);
      expect(res.status).toBe(503);
      const data = await res.json();
      expect(data.code).toBe('CHAT_RESUME_ERROR');
      expect(data.error).toContain('aborted');
    });

    it('passes client abort signal through to backend fetch call', async () => {
      let passedSignal: AbortSignal | null | undefined = null;
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
          passedSignal = init?.signal;
          return Promise.resolve(
            new Response(new ReadableStream(), {
              status: 200,
              headers: { 'Content-Type': 'text/event-stream' }
            })
          );
        })
      );

      const controller = new AbortController();
      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          thread_id: 'thread_signal',
          approval_id: 'app_signal'
        })
      });

      const res = await POST(req);
      expect(res.status).toBe(200);
      expect(passedSignal).toBe(controller.signal);
    });
  });

  describe('6. Error Code Propagation (400, 404, 500, 502, 503)', () => {
    it('propagates 400 Bad Request from backend with JSON body', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response(
            JSON.stringify({ detail: 'Invalid parameters provided to backend.' }),
            { status: 400, headers: { 'Content-Type': 'application/json' } }
          )
        )
      );

      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: 't1', approval_id: 'a1' })
      });

      const res = await POST(req);
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.detail).toBe('Invalid parameters provided to backend.');
    });

    it('propagates 404 Not Found from backend with JSON body', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response(
            JSON.stringify({ detail: 'Approval record app_123 not found or expired.' }),
            { status: 404, headers: { 'Content-Type': 'application/json' } }
          )
        )
      );

      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: 't1', approval_id: 'a1' })
      });

      const res = await POST(req);
      expect(res.status).toBe(404);
      const data = await res.json();
      expect(data.detail).toContain('not found or expired');
    });

    it('propagates 502 Bad Gateway with raw non-JSON text payload', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response('<html><body>502 Bad Gateway from upstream gateway</body></html>', {
            status: 502,
            headers: { 'Content-Type': 'text/html' }
          })
        )
      );

      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: 't1', approval_id: 'a1' })
      });

      const res = await POST(req);
      expect(res.status).toBe(502);
      const data = await res.json();
      expect(data.error).toContain('502 Bad Gateway');
    });

    it('returns 502 EMPTY_BACKEND_BODY when backend returns 200 with null body', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: true,
          status: 200,
          body: null
        })
      );

      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: 't1', approval_id: 'a1' })
      });

      const res = await POST(req);
      expect(res.status).toBe(502);
      const data = await res.json();
      expect(data.code).toBe('EMPTY_BACKEND_BODY');
    });

    it('returns 503 BACKEND_UNREACHABLE when fetch throws network connection refused', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockRejectedValue(new Error('connect ECONNREFUSED 127.0.0.1:8010'))
      );

      const req = new Request('http://localhost:3000/api/chat/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: 't1', approval_id: 'a1' })
      });

      const res = await POST(req);
      expect(res.status).toBe(503);
      const data = await res.json();
      expect(data.code).toBe('BACKEND_UNREACHABLE');
      expect(data.error).toContain('Carefold Python backend is unreachable');
    });
  });
});
