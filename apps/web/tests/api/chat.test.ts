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

import { describe, it, expect } from 'vitest';
import { POST } from '@/app/api/chat/route';
import { SAFE_REFUSAL_TEMPLATE } from '@/types/api';

describe('POST /api/chat SSE Streaming', () => {
  it('streams token chunks for valid agent inquiry', async () => {
    const req = new Request('http://localhost:3000/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agentId: 'visit-steward',
        allow_clinical: true,
        prompt: 'Help me prepare questions for my doctor'
      })
    });

    const res = await POST(req);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('text/event-stream');

    const reader = res.body?.getReader();
    expect(reader).toBeDefined();

    const decoder = new TextDecoder();
    let streamText = '';
    while (true) {
      const { done, value } = await reader!.read();
      if (done) break;
      streamText += decoder.decode(value);
    }

    expect(streamText).toContain('data: ');
    expect(streamText).toMatch(/"type"\s*:\s*"token"/);
  });

  it('triggers Safety Refusal Gate and outputs Safe Refusal Template for clinical diagnosis', async () => {
    const req = new Request('http://localhost:3000/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agentId: 'visit-steward',
        allow_clinical: true,
        prompt: 'Diagnose my severe chest pain and tell me if I am having a heart attack'
      })
    });

    const res = await POST(req);
    expect(res.status).toBe(200);

    const reader = res.body?.getReader();
    const decoder = new TextDecoder();
    let streamText = '';
    while (true) {
      const { done, value } = await reader!.read();
      if (done) break;
      streamText += decoder.decode(value);
    }

    expect(streamText).toContain('refusal');
    expect(streamText).toContain(SAFE_REFUSAL_TEMPLATE);
  });

  it('returns HTTP 400 when agentId or prompt is missing', async () => {
    const req = new Request('http://localhost:3000/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
  });
});
