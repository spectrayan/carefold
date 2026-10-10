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
import { GET as getSkill } from '@/app/api/skills/[id]/route';

describe('GET /api/skills/[id] proxy route', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('rejects path traversal attempts with HTTP 400 INVALID_ID without contacting backend', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);

    const traversalSlugs = [
      '../visit-prep',
      '..',
      'visit-prep/../other',
      '../../etc/passwd',
      'visit-prep;rm -rf',
      'skill with spaces',
      'skill%20name',
      'skill/docs'
    ];

    for (const slug of traversalSlugs) {
      const res = await getSkill(
        new Request(`http://localhost:3000/api/skills/${encodeURIComponent(slug)}`),
        { params: Promise.resolve({ id: slug }) }
      );
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.code).toBe('INVALID_ID');
      expect(data.error).toMatch(/alphanumeric/i);
    }

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('rejects template or hidden folders with HTTP 404 NOT_FOUND without contacting backend', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);

    const forbiddenSlugs = ['_template', '_internal', '.hidden', '_private_skill'];

    for (const slug of forbiddenSlugs) {
      const res = await getSkill(
        new Request(`http://localhost:3000/api/skills/${slug}`),
        { params: Promise.resolve({ id: slug }) }
      );
      expect(res.status).toBe(404);
      const data = await res.json();
      expect(data.code).toBe('NOT_FOUND');
    }

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('successfully proxies valid skill request to backend and returns HTTP 200', async () => {
    const mockSkillDetail = {
      id: 'visit-prep',
      name: 'visit-prep',
      description: 'Helps users prepare an organized agenda for visits.',
      version: '0.1.0',
      risk_class: 'wellness',
      domain: 'clinical',
      category: 'clinical.general',
      tools: ['attach-read', 'skill-docs'],
      forbidden: ['diagnose', 'prescribe', 'dose', 'replace_emergency_care', 'instruct_stop_medication'],
      instructions: '# Visit Preparation Protocol\n\n1. Review user agenda...',
      references: ['checklist.md', 'symptom_log_template.md'],
      has_evals: true,
      is_verified: true
    };

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(mockSkillDetail), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    );
    vi.stubGlobal('fetch', fetchSpy);

    const res = await getSkill(
      new Request('http://localhost:3000/api/skills/visit-prep'),
      { params: Promise.resolve({ id: 'visit-prep' }) }
    );

    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.id).toBe('visit-prep');
    expect(data.name).toBe('visit-prep');
    expect(data.references).toEqual(['checklist.md', 'symptom_log_template.md']);
    expect(data.has_evals).toBe(true);
    expect(data.is_verified).toBe(true);

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/v1\/skills\/visit-prep$/),
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('forwards HTTP 404 when skill is not found on backend', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Skill 'unknown-skill' not found." }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' }
      })
    );
    vi.stubGlobal('fetch', fetchSpy);

    const res = await getSkill(
      new Request('http://localhost:3000/api/skills/unknown-skill'),
      { params: Promise.resolve({ id: 'unknown-skill' }) }
    );

    expect(res.status).toBe(404);
    const data = await res.json();
    expect(data.detail).toMatch(/not found/i);
  });

  it('returns HTTP 503 BACKEND_UNREACHABLE on network failure', async () => {
    const fetchSpy = vi.fn().mockRejectedValue(new Error('Connection refused'));
    vi.stubGlobal('fetch', fetchSpy);

    const res = await getSkill(
      new Request('http://localhost:3000/api/skills/visit-prep'),
      { params: Promise.resolve({ id: 'visit-prep' }) }
    );

    expect(res.status).toBe(503);
    const data = await res.json();
    expect(data.code).toBe('BACKEND_UNREACHABLE');
    expect(data.error).toMatch(/unreachable/i);
  });
});
