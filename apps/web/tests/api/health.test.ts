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
import { GET } from '@/app/api/health/route';
import pkg from '../../package.json';

describe('GET /api/health', () => {
  it('returns HTTP 200 with service health and version metadata', async () => {
    const res = await GET(new Request('http://localhost:3000/api/health'));
    expect(res.status).toBe(200);

    const data = await res.json();
    expect(typeof data.modelReachable).toBe('boolean');
    expect(data.workspace).toBeDefined();
  });

  it('reads the version from apps/web/package.json', async () => {
    const res = await GET(new Request('http://localhost:3000/api/health'));
    const data = await res.json();
    expect(data.version).toBe(pkg.version);
  });

  it('reports a status consistent with model reachability', async () => {
    const res = await GET(new Request('http://localhost:3000/api/health'));
    expect(res.status).toBe(200);

    const data = await res.json();
    expect(data.status).toBe(data.modelReachable ? 'ok' : 'degraded');
  });

  it('excludes underscore-prefixed system/template folders from workspace counts', async () => {
    const res = await GET(new Request('http://localhost:3000/api/health'));
    const data = await res.json();

    // Bundled workspace ships at least 20 specialist agents (agents/_system and
    // agents/_template excluded) and at least 22 skill packs (skills/_template excluded).
    expect(data.workspace.agentsCount).toBeGreaterThanOrEqual(20);
    expect(data.workspace.skillsCount).toBeGreaterThanOrEqual(22);
  });
});
