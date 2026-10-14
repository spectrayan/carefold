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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { GET as getNotesList } from '@/app/api/notes/route';
import { GET as getNoteDetail } from '@/app/api/notes/[slug]/route';

describe('Workspace Notes API Proxy Routes (Issue #95)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe('GET /api/notes', () => {
    it('proxies request to backend and returns notes list', async () => {
      const mockNotes = [
        {
          slug: 'visit-agenda',
          title: 'Visit Agenda',
          agent: 'visit-steward',
          created_at: '2026-10-07T12:00:00Z',
          size_bytes: 512
        }
      ];

      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: true,
          status: 200,
          json: () => Promise.resolve(mockNotes)
        })
      );

      const res = await getNotesList();
      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data).toEqual(mockNotes);
    });

    it('returns 503 BACKEND_UNREACHABLE when backend fetch fails', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockRejectedValue(new Error('Connection refused'))
      );

      const res = await getNotesList();
      expect(res.status).toBe(503);
      const data = await res.json();
      expect(data.code).toBe('BACKEND_UNREACHABLE');
    });
  });

  describe('GET /api/notes/[slug]', () => {
    it('rejects path traversal and invalid characters with HTTP 400 without contacting backend', async () => {
      const fetchSpy = vi.fn();
      vi.stubGlobal('fetch', fetchSpy);

      const invalidSlugs = [
        '../../etc/passwd',
        '../note',
        'note/escape',
        'note\\escape',
        'note%00',
        'note with spaces',
        'note;command'
      ];

      for (const slug of invalidSlugs) {
        const res = await getNoteDetail(
          new Request(`http://localhost:3000/api/notes/${encodeURIComponent(slug)}`),
          { params: Promise.resolve({ slug }) }
        );
        expect(res.status).toBe(400);
        const data = await res.json();
        expect(data.code).toBe('INVALID_SLUG');
      }

      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('proxies valid slug to backend and returns note detail', async () => {
      const mockDetail = {
        slug: 'cardiac-notes',
        title: 'Cardiac Notes',
        agent: 'cardiology-guide',
        created_at: '2026-10-07T12:00:00Z',
        size_bytes: 256,
        content: '# Notes',
        raw_content: '---\ntitle: "Cardiac Notes"\n---\n# Notes',
        metadata: { title: 'Cardiac Notes' },
        path: 'workspace/notes/cardiac-notes.md'
      };

      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockDetail)
      });
      vi.stubGlobal('fetch', fetchSpy);

      const res = await getNoteDetail(
        new Request('http://localhost:3000/api/notes/cardiac-notes'),
        { params: Promise.resolve({ slug: 'cardiac-notes' }) }
      );

      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data).toEqual(mockDetail);
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/notes/cardiac-notes'),
        expect.anything()
      );
    });

    it('handles .md extension gracefully in slug', async () => {
      const mockDetail = {
        slug: 'cardiac-notes',
        title: 'Cardiac Notes'
      };

      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockDetail)
      });
      vi.stubGlobal('fetch', fetchSpy);

      const res = await getNoteDetail(
        new Request('http://localhost:3000/api/notes/cardiac-notes.md'),
        { params: Promise.resolve({ slug: 'cardiac-notes.md' }) }
      );

      expect(res.status).toBe(200);
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/notes/cardiac-notes'),
        expect.anything()
      );
    });

    it('returns 404 when backend returns 404', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: false,
          status: 404,
          json: () => Promise.resolve({ detail: 'Note not found' })
        })
      );

      const res = await getNoteDetail(
        new Request('http://localhost:3000/api/notes/non-existent'),
        { params: Promise.resolve({ slug: 'non-existent' }) }
      );

      expect(res.status).toBe(404);
    });
  });
});
