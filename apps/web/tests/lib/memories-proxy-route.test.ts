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
import { GET as getMemoriesRoute, DELETE as deleteMemoriesRoute } from '@/app/api/memories/route';
import {
  GET as getSingleMemoryRoute,
  PUT as putSingleMemoryRoute,
  DELETE as deleteSingleMemoryRoute,
} from '@/app/api/memories/[id]/route';
import { GET as getMemoryStatusRoute } from '@/app/api/memories/status/route';

describe('Memories Proxy Routes', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe('GET /api/memories', () => {
    it('proxies GET /api/memories with default limit 50 and namespace default', async () => {
      const mockMemories = [
        {
          key: 'allergy_1',
          value: 'Penicillin allergy',
          tier: 'semantic',
          namespace: 'default',
        },
      ];

      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockMemories),
      });
      vi.stubGlobal('fetch', fetchSpy);

      const req = new Request('http://localhost:3000/api/memories');
      const res = await getMemoriesRoute(req);

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual(mockMemories);

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const calledUrl = fetchSpy.mock.calls[0][0];
      expect(calledUrl).toContain('/api/memory?');
      expect(calledUrl).toContain('limit=50');
      expect(calledUrl).toContain('namespace=default');
    });

    it('forwards query, tier, and clamps limit between 1 and 100', async () => {
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
      });
      vi.stubGlobal('fetch', fetchSpy);

      // limit 500 should be clamped to 100
      const req = new Request('http://localhost:3000/api/memories?query=rash&tier=episodic&namespace=user1&limit=500');
      const res = await getMemoriesRoute(req);
      expect(res.status).toBe(200);

      const calledUrl = fetchSpy.mock.calls[0][0];
      expect(calledUrl).toContain('query=rash');
      expect(calledUrl).toContain('tier=episodic');
      expect(calledUrl).toContain('namespace=user1');
      expect(calledUrl).toContain('limit=100');
    });

    it('returns 503 BACKEND_UNREACHABLE on fetch network error', async () => {
      const fetchSpy = vi.fn().mockRejectedValue(new Error('Connection refused'));
      vi.stubGlobal('fetch', fetchSpy);

      const req = new Request('http://localhost:3000/api/memories');
      const res = await getMemoriesRoute(req);

      expect(res.status).toBe(503);
      const body = await res.json();
      expect(body.code).toBe('BACKEND_UNREACHABLE');
      expect(body.error).toContain('Connection refused');
    });
  });

  describe('DELETE /api/memories (Bulk Delete)', () => {
    it('proxies bulk delete with namespace', async () => {
      const mockResponse = { deleted: true, deleted_count: 5, namespace: 'custom_ns' };
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockResponse),
      });
      vi.stubGlobal('fetch', fetchSpy);

      const req = new Request('http://localhost:3000/api/memories?namespace=custom_ns', {
        method: 'DELETE',
      });
      const res = await deleteMemoriesRoute(req);

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual(mockResponse);

      const calledUrl = fetchSpy.mock.calls[0][0];
      expect(calledUrl).toContain('/api/memory?namespace=custom_ns');
    });
  });

  describe('/api/memories/[id]', () => {
    it('rejects path traversal, null bytes, and control characters with 400 INVALID_KEY', async () => {
      const maliciousKeys = [
        '../evil',
        'sub/dir',
        'key\\escaped',
        'null\0byte',
        'cmd;injection',
        'percent%encoded',
      ];

      for (const key of maliciousKeys) {
        const req = new Request(`http://localhost:3000/api/memories/${key}`);
        const context = { params: Promise.resolve({ id: key }) };

        const getRes = await getSingleMemoryRoute(req, context);
        expect(getRes.status).toBe(400);
        const getBody = await getRes.json();
        expect(getBody.code).toBe('INVALID_KEY');

        const putRes = await putSingleMemoryRoute(req, context);
        expect(putRes.status).toBe(400);

        const delRes = await deleteSingleMemoryRoute(req, context);
        expect(delRes.status).toBe(400);
      }
    });

    it('proxies GET single memory by id', async () => {
      const mockRecord = { key: 'bp_fact', value: '120/80', tier: 'episodic', namespace: 'default' };
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockRecord),
      });
      vi.stubGlobal('fetch', fetchSpy);

      const req = new Request('http://localhost:3000/api/memories/bp_fact');
      const res = await getSingleMemoryRoute(req, { params: Promise.resolve({ id: 'bp_fact' }) });

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual(mockRecord);
    });

    it('proxies PUT update memory record', async () => {
      const updatedRecord = { key: 'bp_fact', value: '118/78', tier: 'episodic', namespace: 'default' };
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(updatedRecord),
      });
      vi.stubGlobal('fetch', fetchSpy);

      const req = new Request('http://localhost:3000/api/memories/bp_fact', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: '118/78', tier: 'episodic' }),
      });
      const res = await putSingleMemoryRoute(req, { params: Promise.resolve({ id: 'bp_fact' }) });

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual(updatedRecord);
    });

    it('rejects PUT when payload is missing value field', async () => {
      const req = new Request('http://localhost:3000/api/memories/bp_fact', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: 'episodic' }),
      });
      const res = await putSingleMemoryRoute(req, { params: Promise.resolve({ id: 'bp_fact' }) });

      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body.code).toBe('INVALID_PAYLOAD');
    });

    it('proxies DELETE single memory item', async () => {
      const mockDelete = { deleted: true, key: 'bp_fact', namespace: 'default' };
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockDelete),
      });
      vi.stubGlobal('fetch', fetchSpy);

      const req = new Request('http://localhost:3000/api/memories/bp_fact', { method: 'DELETE' });
      const res = await deleteSingleMemoryRoute(req, { params: Promise.resolve({ id: 'bp_fact' }) });

      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual(mockDelete);
    });
  });

  describe('GET /api/memories/status', () => {
    it('proxies status report from backend', async () => {
      const mockStatus = {
        backend: 'sqlite',
        healthy: true,
        fallback_active: false,
        spector_url: 'http://localhost:7070',
        cooldown_seconds: 0,
      };
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockStatus),
      });
      vi.stubGlobal('fetch', fetchSpy);

      const res = await getMemoryStatusRoute();
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body).toEqual(mockStatus);
    });
  });
});
