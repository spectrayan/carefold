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

    // Bundled workspace ships 20 specialist agents (agents/_system and
    // agents/_template excluded) and 22 skill packs (skills/_template excluded).
    expect(data.workspace.agentsCount).toBe(20);
    expect(data.workspace.skillsCount).toBe(22);
  });
});
