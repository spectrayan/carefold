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
