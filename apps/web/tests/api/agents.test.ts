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

  it('returns single agent details when query param id is provided with explicit consent', async () => {
    const res = await GET(new Request('http://localhost:3000/api/agents?id=visit-steward&allow_clinical=true'));
    expect(res.status).toBe(200);

    const agent = await res.json();
    expect(agent.id).toBe('visit-steward');
    expect(agent.effectiveTools).toEqual(expect.arrayContaining(['attach-read', 'workspace-note', 'skill-docs']));
  });

  it('returns 403 for a clinical_assist agent when consent is not given', async () => {
    const res = await GET(new Request('http://localhost:3000/api/agents?id=visit-steward'));
    expect(res.status).toBe(403);
  });

  it('returns 404 for unknown agent id', async () => {
    const res = await GET(new Request('http://localhost:3000/api/agents?id=nonexistent-agent'));
    expect(res.status).toBe(404);
  });
});
