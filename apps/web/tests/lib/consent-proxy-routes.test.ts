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
 * Unit tests for the Next.js proxy routes' clinical-consent defaults (#87).
 * The backend is replaced with a fetch stub, so these run without a live server
 * (unlike tests/api/**, which are integration tests against FastAPI).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { GET as listAgents } from '@/app/api/agents/route';
import { GET as getAgent } from '@/app/api/agents/[id]/route';
import { POST as postChat } from '@/app/api/chat/route';

let backendCalls: Array<{ url: string; body?: any }> = [];

beforeEach(() => {
  backendCalls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      backendCalls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }));
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const chatRequest = (body: Record<string, unknown>, query = '') =>
  new Request(`http://localhost:3000/api/chat${query}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agentId: 'cardiology-guide', prompt: 'hi', ...body })
  });

describe('GET /api/agents proxy', () => {
  it('defaults allow_clinical to false for list and single lookups', async () => {
    await listAgents(new Request('http://localhost:3000/api/agents'));
    await listAgents(new Request('http://localhost:3000/api/agents?id=cardiology-guide'));
    expect(new URL(backendCalls[0].url).searchParams.get('allow_clinical')).toBe('false');
    expect(new URL(backendCalls[1].url).searchParams.get('allow_clinical')).toBe('false');
  });

  it('forwards only an explicit true', async () => {
    await listAgents(new Request('http://localhost:3000/api/agents?id=cardiology-guide&allow_clinical=true'));
    await listAgents(new Request('http://localhost:3000/api/agents?id=cardiology-guide&allow_clinical=yes'));
    expect(new URL(backendCalls[0].url).searchParams.get('allow_clinical')).toBe('true');
    expect(new URL(backendCalls[1].url).searchParams.get('allow_clinical')).toBe('false');
  });
});

describe('GET /api/agents/[id] proxy', () => {
  const ctx = { params: Promise.resolve({ id: 'cardiology-guide' }) };

  it('defaults allow_clinical to false', async () => {
    await getAgent(new Request('http://localhost:3000/api/agents/cardiology-guide'), ctx);
    expect(new URL(backendCalls[0].url).searchParams.get('allow_clinical')).toBe('false');
  });

  it('forwards an explicit true and normalizes anything else', async () => {
    await getAgent(new Request('http://localhost:3000/api/agents/cardiology-guide?allow_clinical=true'), ctx);
    await getAgent(new Request('http://localhost:3000/api/agents/cardiology-guide?allow_clinical=1%26x%3Dy'), ctx);
    expect(new URL(backendCalls[0].url).searchParams.get('allow_clinical')).toBe('true');
    expect(new URL(backendCalls[1].url).searchParams.get('allow_clinical')).toBe('false');
    expect(new URL(backendCalls[1].url).searchParams.has('x')).toBe(false);
  });
});

describe('POST /api/chat proxy', () => {
  it('defaults allow_clinical to false when the client omits it', async () => {
    await postChat(chatRequest({}));
    expect(backendCalls[0].body.allow_clinical).toBe(false);
  });

  it('forwards explicit consent', async () => {
    await postChat(chatRequest({ allow_clinical: true }));
    expect(backendCalls[0].body.allow_clinical).toBe(true);
  });

  it('does not treat truthy non-boolean values as consent', async () => {
    await postChat(chatRequest({ allow_clinical: 'false' }));
    await postChat(chatRequest({ allowClinical: 1 }));
    expect(backendCalls[0].body.allow_clinical).toBe(false);
    expect(backendCalls[1].body.allow_clinical).toBe(false);
  });
});
