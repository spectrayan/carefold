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
import { GET } from '@/app/api/agents/route';

describe('GET /api/agents', () => {
  it('returns list of bundled agents with metadata, risk_class, and starters', async () => {
    const res = await GET(new Request('http://localhost:3000/api/agents'));
    expect(res.status).toBe(200);

    const agents = await res.json();
    expect(Array.isArray(agents)).toBe(true);
    expect(agents.length).toBeGreaterThanOrEqual(3);

    const visitSteward = agents.find((a: any) => a.id === 'visit-steward');
    expect(visitSteward).toBeDefined();
    expect(visitSteward.title).toBe('Visit Steward');
    expect(visitSteward.risk_class).toBe('clinical_assist');
    expect(visitSteward.skills).toContain('visit-prep');
    expect(visitSteward.tools).toContain('attach-read');
    expect(Array.isArray(visitSteward.starters)).toBe(true);
    expect(visitSteward.starters.length).toBeGreaterThan(0);
  });

  it('returns single agent details when query param id is provided', async () => {
    const res = await GET(new Request('http://localhost:3000/api/agents?id=visit-steward'));
    expect(res.status).toBe(200);

    const agent = await res.json();
    expect(agent.id).toBe('visit-steward');
    expect(agent.effectiveTools).toEqual(expect.arrayContaining(['attach-read', 'workspace-note', 'skill-docs']));
  });

  it('returns 404 for unknown agent id', async () => {
    const res = await GET(new Request('http://localhost:3000/api/agents?id=nonexistent-agent'));
    expect(res.status).toBe(404);
  });
});
