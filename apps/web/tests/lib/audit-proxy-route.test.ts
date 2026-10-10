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
import { GET as getAuditRoute } from '@/app/api/audit/route';

describe('Audit Proxy Route (apps/web/src/app/api/audit/route.ts)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('proxies GET /api/audit to backend with default limit 50 and full=false', async () => {
    const mockData = {
      total: 1,
      limit: 50,
      events: [
        {
          ts: '2026-10-07T12:00:00Z',
          agent_id: 'cardiology-guide',
          event: 'tool',
          tool: 'attach-read',
          allowed: true,
          duration_ms: 12.5
        }
      ]
    };

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockData)
    });
    vi.stubGlobal('fetch', fetchSpy);

    const req = new Request('http://localhost:3000/api/audit');
    const res = await getAuditRoute(req);

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual(mockData);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const calledUrl = fetchSpy.mock.calls[0][0];
    expect(calledUrl).toContain('/api/v1/audit?');
    expect(calledUrl).toContain('limit=50');
    expect(calledUrl).toContain('full=false');
  });

  it('clamps limit between [1, 1000] correctly', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ total: 0, limit: 50, events: [] })
    });
    vi.stubGlobal('fetch', fetchSpy);

    // Case 1: Limit exceeding 1000 -> clamped to 1000
    await getAuditRoute(new Request('http://localhost:3000/api/audit?limit=5000'));
    expect(fetchSpy.mock.calls[0][0]).toContain('limit=1000');

    // Case 2: Limit <= 0 -> clamped to 1
    await getAuditRoute(new Request('http://localhost:3000/api/audit?limit=0'));
    expect(fetchSpy.mock.calls[1][0]).toContain('limit=1');

    await getAuditRoute(new Request('http://localhost:3000/api/audit?limit=-25'));
    expect(fetchSpy.mock.calls[2][0]).toContain('limit=1');

    // Case 3: Invalid NaN limit -> defaults to 50
    await getAuditRoute(new Request('http://localhost:3000/api/audit?limit=invalid'));
    expect(fetchSpy.mock.calls[3][0]).toContain('limit=50');
  });

  it('forwards agent_id and event filters', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ total: 0, limit: 25, events: [] })
    });
    vi.stubGlobal('fetch', fetchSpy);

    const req = new Request(
      'http://localhost:3000/api/audit?limit=25&agent_id=neurology-guide&event=refuse'
    );
    await getAuditRoute(req);

    const calledUrl = fetchSpy.mock.calls[0][0];
    expect(calledUrl).toContain('limit=25');
    expect(calledUrl).toContain('agent_id=neurology-guide');
    expect(calledUrl).toContain('event=refuse');
    expect(calledUrl).toContain('full=false');
  });

  it('STRICT INVARIANT: rejects/overrides full=true and strips prompt/completion keys from response', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          total: 1,
          limit: 50,
          events: [
            {
              ts: '2026-10-07T12:00:00Z',
              agent_id: 'cardiology-guide',
              event: 'tool',
              tool: 'attach-read',
              allowed: true,
              prompt: 'SENSITIVE_PROMPT_BODY',
              completion: 'SENSITIVE_COMPLETION_BODY'
            }
          ]
        })
    });
    vi.stubGlobal('fetch', fetchSpy);

    // Incoming request tries to query full=true
    const req = new Request('http://localhost:3000/api/audit?full=true');
    const res = await getAuditRoute(req);

    expect(res.status).toBe(200);
    const body = await res.json();

    // Verify backend was queried with full=false, NOT full=true
    const calledUrl = fetchSpy.mock.calls[0][0];
    expect(calledUrl).toContain('full=false');
    expect(calledUrl).not.toContain('full=true');

    // Verify prompt and completion keys were purged from returned event
    expect(body.events[0].prompt).toBeUndefined();
    expect(body.events[0].completion).toBeUndefined();
    expect(body.events[0].tool).toBe('attach-read');
  });

  it('returns 503 BACKEND_UNREACHABLE when backend connection fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Connection refused (ECONNREFUSED)'))
    );

    const req = new Request('http://localhost:3000/api/audit');
    const res = await getAuditRoute(req);

    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body.code).toBe('BACKEND_UNREACHABLE');
    expect(body.error).toContain('Carefold Python backend is unreachable');
  });

  it('forwards error status and message when backend responds with non-200', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: () => Promise.resolve({ detail: 'Unprocessable Entity' })
      })
    );

    const req = new Request('http://localhost:3000/api/audit');
    const res = await getAuditRoute(req);

    expect(res.status).toBe(422);
    const body = await res.json();
    expect(body.detail).toBe('Unprocessable Entity');
  });
});
