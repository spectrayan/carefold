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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NextRequest } from 'next/server';

// Route Handlers
import { GET as getProfiles, POST as postProfiles } from '@/app/api/profiles/route';
import { GET as getProfilesCatchAll } from '@/app/api/profiles/[...path]/route';
import { GET as getNotes, POST as postNotes } from '@/app/api/notes/route';
import {
  GET as getNoteDetail,
  PUT as putNoteDetail,
  DELETE as deleteNoteDetail,
} from '@/app/api/notes/[slug]/route';
import { GET as getAttachments } from '@/app/api/attachments/route';
import { GET as getAttachmentCatchAll } from '@/app/api/attachments/[...path]/route';
import { GET as getAgents } from '@/app/api/agents/route';
import { GET as getAgentCategories } from '@/app/api/agents/categories/route';
import { GET as getSkills } from '@/app/api/skills/route';
import { GET as getSkillDetail } from '@/app/api/skills/[id]/route';
import { GET as getThread } from '@/app/api/chat/threads/[id]/route';
import { POST as postChat } from '@/app/api/chat/route';
import { GET as getAudit } from '@/app/api/audit/route';
import { GET as getMemories } from '@/app/api/memories/route';
import { GET as getMemoryStatus } from '@/app/api/memories/status/route';

interface CapturedFetch {
  url: string;
  method?: string;
  headers?: any;
  body?: any;
}

let capturedFetches: CapturedFetch[] = [];

function setupMockFetch(responseFactory?: (req: CapturedFetch) => Response) {
  capturedFetches = [];
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const captured: CapturedFetch = {
        url: String(url),
        method: init?.method || 'GET',
        headers: init?.headers,
        body: init?.body,
      };
      capturedFetches.push(captured);

      if (responseFactory) {
        return Promise.resolve(responseFactory(captured));
      }

      return Promise.resolve(
        new Response(JSON.stringify({ ok: true, data: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );
    })
  );
}

function getHeader(headers: any, name: string): string | null {
  if (!headers) return null;
  const target = name.toLowerCase();
  if (headers instanceof Headers) {
    return headers.get(target);
  }
  if (typeof headers.get === 'function') {
    return headers.get(target);
  }
  for (const [k, v] of Object.entries(headers)) {
    if (k.toLowerCase() === target) {
      return String(v);
    }
  }
  return null;
}

describe('Resilience Challenge: Next.js Proxy Routes Propagation & Streaming', () => {
  const TEST_COOKIE = 'carefold_session=sess_sec_99998888; theme=dark; test_csrf=xyz789';
  const TEST_AUTH = 'Bearer test_jwt_token_adv_chal_2026';

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    capturedFetches = [];
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe('1. Profiles Proxy Routes Query & Header Forwarding', () => {
    it('preserves query params and forwards cookie/auth on GET /api/profiles', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/profiles?limit=50&offset=10&profile_id=123',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getProfiles(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/profiles');
      expect(call.url).toContain('limit=50');
      expect(call.url).toContain('offset=10');
      expect(call.url).toContain('profile_id=123');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('forwards cookie/auth on POST /api/profiles', async () => {
      setupMockFetch();
      const req = new NextRequest('http://localhost:3000/api/profiles', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          cookie: TEST_COOKIE,
          authorization: TEST_AUTH,
        },
        body: JSON.stringify({ name: 'Grandma', role: 'dependent' }),
      });
      const res = await postProfiles(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/profiles');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('preserves nested paths, complex query params, and headers on /api/profiles/[...path]', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/profiles/p-123/invites?status=pending&role=viewer&limit=10',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getProfilesCatchAll(req, {
        params: Promise.resolve({ path: ['p-123', 'invites'] }),
      });
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/profiles/p-123/invites');
      expect(call.url).toContain('status=pending');
      expect(call.url).toContain('role=viewer');
      expect(call.url).toContain('limit=10');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('forwards global invitations on /api/profiles/invites to /api/v1/profiles/invites', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/profiles/invites?include_expired=false',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getProfilesCatchAll(req, {
        params: Promise.resolve({ path: ['invites'] }),
      });
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/profiles/invites');
      expect(call.url).toContain('include_expired=false');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });
  });

  describe('2. Notes Proxy Routes Query & Header Forwarding', () => {
    it('preserves query params (e.g. ?profile_id=123) and headers on GET /api/notes', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/notes?profile_id=prof_456&tag=cardio&limit=25',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getNotes(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/notes');
      expect(call.url).toContain('profile_id=prof_456');
      expect(call.url).toContain('tag=cardio');
      expect(call.url).toContain('limit=25');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('preserves query params and headers on POST /api/notes', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/notes?profile_id=prof_456',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            cookie: TEST_COOKIE,
            authorization: TEST_AUTH,
          },
          body: JSON.stringify({ title: 'Adversarial Note', content: 'Testing' }),
        }
      );
      const res = await postNotes(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/notes?profile_id=prof_456');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('preserves query params and headers on GET /api/notes/[slug]', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/notes/visit-agenda?profile_id=prof_456&revision=2',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getNoteDetail(req, {
        params: Promise.resolve({ slug: 'visit-agenda' }),
      });
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/notes/visit-agenda');
      expect(call.url).toContain('profile_id=prof_456');
      expect(call.url).toContain('revision=2');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('preserves query params and headers on PUT & DELETE /api/notes/[slug]', async () => {
      setupMockFetch();
      // PUT
      const putReq = new NextRequest(
        'http://localhost:3000/api/notes/visit-agenda?profile_id=prof_456',
        {
          method: 'PUT',
          headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH },
          body: JSON.stringify({ content: 'Updated' }),
        }
      );
      await putNoteDetail(putReq, { params: Promise.resolve({ slug: 'visit-agenda' }) });

      // DELETE
      const delReq = new NextRequest(
        'http://localhost:3000/api/notes/visit-agenda?profile_id=prof_456',
        {
          method: 'DELETE',
          headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH },
        }
      );
      await deleteNoteDetail(delReq, { params: Promise.resolve({ slug: 'visit-agenda' }) });

      expect(capturedFetches.length).toBe(2);
      expect(capturedFetches[0].url).toContain('/api/v1/notes/visit-agenda?profile_id=prof_456');
      expect(getHeader(capturedFetches[0].headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(capturedFetches[0].headers, 'authorization')).toBe(TEST_AUTH);

      expect(capturedFetches[1].url).toContain('/api/v1/notes/visit-agenda?profile_id=prof_456');
      expect(getHeader(capturedFetches[1].headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(capturedFetches[1].headers, 'authorization')).toBe(TEST_AUTH);
    });
  });

  describe('3. Attachments Proxy Routes Query & Header Forwarding', () => {
    it('preserves query params and headers on GET /api/attachments', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/attachments?profile_id=prof_99&mime=application/pdf',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getAttachments(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/attachments?profile_id=prof_99&mime=application/pdf');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('preserves query params and headers on GET /api/attachments/[...path]', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/attachments/att_123/download?disposition=attachment&filename=report.pdf',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getAttachmentCatchAll(req, {
        params: Promise.resolve({ path: ['att_123', 'download'] }),
      });
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/attachments/att_123/download');
      expect(call.url).toContain('disposition=attachment');
      expect(call.url).toContain('filename=report.pdf');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });
  });

  describe('4. Agents & Skills Proxy Routes Query & Header Forwarding', () => {
    it('preserves search queries (e.g. ?q=cardiology) and headers on GET /api/agents', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/agents?search=cardiology&domain=clinical&allow_clinical=true',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getAgents(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/agents');
      expect(call.url).toContain('search=cardiology');
      expect(call.url).toContain('domain=clinical');
      expect(call.url).toContain('allow_clinical=true');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('preserves query params and headers on GET /api/agents/categories', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/agents/categories?domain=clinical&depth=2',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getAgentCategories(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/agents/categories');
      expect(call.url).toContain('domain=clinical');
      expect(call.url).toContain('depth=2');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('preserves query params and headers on GET /api/skills', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/skills?q=cardiology&category=clinical_assist&page=1&per_page=10',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getSkills(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/skills');
      expect(call.url).toContain('q=cardiology');
      expect(call.url).toContain('category=clinical_assist');
      expect(call.url).toContain('per_page=10');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('preserves query params and headers on GET /api/skills/[id]', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/skills/cardio-prep?version=1.0.0&detailed=true',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getSkillDetail(req, {
        params: Promise.resolve({ id: 'cardio-prep' }),
      });
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/skills/cardio-prep');
      expect(call.url).toContain('version=1.0.0');
      expect(call.url).toContain('detailed=true');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });
  });

  describe('5. Chat Threads & Audit Proxy Routes', () => {
    it('preserves query params (?limit=50&offset=10) and headers on GET /api/chat/threads/[id]', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/chat/threads/th_test_123?limit=50&offset=10&order=desc',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getThread(req, {
        params: Promise.resolve({ id: 'th_test_123' }),
      });
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/chat/threads/th_test_123');
      expect(call.url).toContain('limit=50');
      expect(call.url).toContain('offset=10');
      expect(call.url).toContain('order=desc');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('preserves parsed queries (?limit=50&agent_id=cardiology-guide&event=message) and headers on GET /api/audit', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/audit?limit=50&agent_id=cardiology-guide&event=message',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getAudit(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/audit');
      expect(call.url).toContain('limit=50');
      expect(call.url).toContain('agent_id=cardiology-guide');
      expect(call.url).toContain('event=message');
      expect(call.url).toContain('full=false');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });
  });

  describe('6. Memories Proxy Routes Query & Header Forwarding', () => {
    it('preserves memory search params and headers on GET /api/memories', async () => {
      setupMockFetch();
      const req = new NextRequest(
        'http://localhost:3000/api/memories?query=cardiology&namespace=prof_123&tier=episodic&limit=25',
        { headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH } }
      );
      const res = await getMemories(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/memory');
      expect(call.url).toContain('query=cardiology');
      expect(call.url).toContain('namespace=prof_123');
      expect(call.url).toContain('tier=episodic');
      expect(call.url).toContain('limit=25');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });

    it('forwards cookie & auth headers on GET /api/memories/status', async () => {
      setupMockFetch();
      const req = new NextRequest('http://localhost:3000/api/memories/status', {
        headers: { cookie: TEST_COOKIE, authorization: TEST_AUTH },
      });
      const res = await getMemoryStatus(req);
      expect(res.status).toBe(200);

      expect(capturedFetches.length).toBe(1);
      const call = capturedFetches[0];
      expect(call.url).toContain('/api/v1/memory/status');
      expect(getHeader(call.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(call.headers, 'authorization')).toBe(TEST_AUTH);
    });
  });

  describe('7. SSE Streaming Pass-Through in chat/route.ts', () => {
    it('streams tokens transparently from ${backendUrl}/api/v1/chat without buffering or truncation', async () => {
      const chunks = [
        'data: {"token": "Hello"}\n\n',
        'data: {"token": " Dr. Smith"}\n\n',
        'data: {"token": ", my blood pressure is 120/80"}\n\n',
        'data: [DONE]\n\n',
      ];

      const stream = new ReadableStream({
        async start(controller) {
          for (const chunk of chunks) {
            controller.enqueue(new TextEncoder().encode(chunk));
          }
          controller.close();
        },
      });

      setupMockFetch(() => {
        return new Response(stream, {
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream; charset=utf-8',
            'Cache-Control': 'no-cache',
          },
        });
      });

      const chatReq = new NextRequest('http://localhost:3000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          cookie: TEST_COOKIE,
          authorization: TEST_AUTH,
        },
        body: JSON.stringify({
          agentId: 'cardiology-guide',
          prompt: 'Hello, what does 120/80 mean?',
          allow_clinical: true,
        }),
      });

      const response = await postChat(chatReq);

      expect(response.status).toBe(200);
      expect(response.headers.get('content-type')).toContain('text/event-stream');
      expect(response.headers.get('cache-control')).toContain('no-cache');
      expect(response.headers.get('x-accel-buffering')).toBe('no');

      // Verify backend was called with canonical /api/v1/chat
      expect(capturedFetches.length).toBe(1);
      const backendCall = capturedFetches[0];
      expect(backendCall.url).toContain('/api/v1/chat');
      expect(backendCall.method).toBe('POST');
      expect(getHeader(backendCall.headers, 'cookie')).toBe(TEST_COOKIE);
      expect(getHeader(backendCall.headers, 'authorization')).toBe(TEST_AUTH);

      // Verify stream body pass-through without truncation
      expect(response.body).toBeDefined();
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let streamedOutput = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        streamedOutput += decoder.decode(value, { stream: true });
      }

      expect(streamedOutput).toBe(chunks.join(''));
      expect(streamedOutput).toContain('Hello');
      expect(streamedOutput).toContain('Dr. Smith');
      expect(streamedOutput).toContain('120/80');
      expect(streamedOutput).toContain('[DONE]');
    });

    it('forwards error payloads faithfully from /api/v1/chat if backend responds with non-200', async () => {
      setupMockFetch(() => {
        return new Response(
          JSON.stringify({ error: 'Clinical consent required', code: 'CONSENT_REQUIRED' }),
          { status: 403, headers: { 'Content-Type': 'application/json' } }
        );
      });

      const chatReq = new NextRequest('http://localhost:3000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agentId: 'cardiology-guide',
          prompt: 'Prescribe me meds',
          allow_clinical: false,
        }),
      });

      const response = await postChat(chatReq);
      expect(response.status).toBe(403);
      const json = await response.json();
      expect(json.code).toBe('CONSENT_REQUIRED');
      expect(json.error).toBe('Clinical consent required');
    });
  });
});
