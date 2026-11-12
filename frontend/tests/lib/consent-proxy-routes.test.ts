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
    body: JSON.stringify({ agentId: 'heart-care-coordinator', prompt: 'hi', ...body })
  });

describe('GET /api/agents proxy', () => {
  it('defaults allow_assist to false for list and single lookups', async () => {
    await listAgents(new Request('http://localhost:3000/api/agents'));
    await listAgents(new Request('http://localhost:3000/api/agents?id=heart-care-coordinator'));
    expect(new URL(backendCalls[0].url).searchParams.get('allow_assist')).toBe('false');
    expect(new URL(backendCalls[1].url).searchParams.get('allow_assist')).toBe('false');
  });

  it('forwards only an explicit true', async () => {
    await listAgents(new Request('http://localhost:3000/api/agents?id=heart-care-coordinator&allow_assist=true'));
    await listAgents(new Request('http://localhost:3000/api/agents?id=heart-care-coordinator&allow_assist=yes'));
    expect(new URL(backendCalls[0].url).searchParams.get('allow_assist')).toBe('true');
    expect(new URL(backendCalls[1].url).searchParams.get('allow_assist')).toBe('false');
  });
});

describe('GET /api/agents/[id] proxy', () => {
  const ctx = { params: Promise.resolve({ id: 'heart-care-coordinator' }) };

  it('defaults allow_assist to false', async () => {
    await getAgent(new Request('http://localhost:3000/api/agents/heart-care-coordinator'), ctx);
    expect(new URL(backendCalls[0].url).searchParams.get('allow_assist')).toBe('false');
  });

  it('forwards an explicit true and normalizes anything else', async () => {
    await getAgent(new Request('http://localhost:3000/api/agents/heart-care-coordinator?allow_assist=true'), ctx);
    await getAgent(new Request('http://localhost:3000/api/agents/heart-care-coordinator?allow_assist=1%26x%3Dy'), ctx);
    expect(new URL(backendCalls[0].url).searchParams.get('allow_assist')).toBe('true');
    expect(new URL(backendCalls[1].url).searchParams.get('allow_assist')).toBe('false');
    expect(new URL(backendCalls[1].url).searchParams.has('x')).toBe(false);
  });
});

describe('POST /api/chat proxy', () => {
  it('defaults allow_assist to false when the client omits it', async () => {
    await postChat(chatRequest({}));
    expect(backendCalls[0].body.allow_assist).toBe(false);
  });

  it('forwards explicit consent', async () => {
    await postChat(chatRequest({ allow_assist: true }));
    expect(backendCalls[0].body.allow_assist).toBe(true);
  });

  it('does not treat truthy non-boolean values as consent', async () => {
    await postChat(chatRequest({ allow_assist: 'false' }));
    await postChat(chatRequest({ allowAssist: 1 }));
    expect(backendCalls[0].body.allow_assist).toBe(false);
    expect(backendCalls[1].body.allow_assist).toBe(false);
  });

  it('forwards explicit profileId / profile_id and defaults to "me" when omitted', async () => {
    await postChat(chatRequest({}));
    await postChat(chatRequest({ profileId: 'prof-123' }));
    await postChat(chatRequest({ profile_id: 'prof-456' }));
    expect(backendCalls[0].body.profile_id).toBe('me');
    expect(backendCalls[0].body.profileId).toBe('me');
    expect(backendCalls[1].body.profile_id).toBe('prof-123');
    expect(backendCalls[1].body.profileId).toBe('prof-123');
    expect(backendCalls[2].body.profile_id).toBe('prof-456');
    expect(backendCalls[2].body.profileId).toBe('prof-456');
  });
});
