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

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  CAREFOLD_THREADS_INDEX_KEY,
  MAX_INDEXED_SESSIONS,
  listSessions,
  getSession,
  saveSession,
  upsertSessionFromMessages,
  renameSession,
  deleteSession,
  discoverAndMigrateLegacySessions,
  initSessionHistoryListeners,
  generateThreadId,
  extractAgentIdFromThread,
  type ChatSessionMeta
} from '@/lib/sessionHistory';

describe('sessionHistory Storage Index Library', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe('listSessions & getSession', () => {
    it('returns empty array when index does not exist or is invalid JSON', () => {
      expect(listSessions()).toEqual([]);

      localStorage.setItem(CAREFOLD_THREADS_INDEX_KEY, 'invalid json');
      expect(listSessions()).toEqual([]);
    });

    it('returns sessions sorted by updatedAt descending', () => {
      const s1: ChatSessionMeta = {
        id: 't-1',
        agentId: 'visit-steward',
        agentTitle: 'Visit Steward',
        title: 'Older Session',
        createdAt: '2026-10-01T10:00:00.000Z',
        updatedAt: '2026-10-01T10:00:00.000Z',
        messageCount: 2
      };
      const s2: ChatSessionMeta = {
        id: 't-2',
        agentId: 'cardiology-guide',
        agentTitle: 'Cardiology Guide',
        title: 'Newer Session',
        createdAt: '2026-10-02T10:00:00.000Z',
        updatedAt: '2026-10-02T12:00:00.000Z',
        messageCount: 4
      };

      saveSession(s1);
      saveSession(s2);

      const sessions = listSessions();
      expect(sessions.length).toBe(2);
      expect(sessions[0].id).toBe('t-2');
      expect(sessions[1].id).toBe('t-1');
    });

    it('filters sessions by agentId if specified', () => {
      const s1: ChatSessionMeta = {
        id: 't-1',
        agentId: 'visit-steward',
        title: 'Visit Session',
        createdAt: '2026-10-01T10:00:00.000Z',
        updatedAt: '2026-10-01T10:00:00.000Z',
        messageCount: 2
      };
      const s2: ChatSessionMeta = {
        id: 't-2',
        agentId: 'cardiology-guide',
        title: 'Cardio Session',
        createdAt: '2026-10-02T10:00:00.000Z',
        updatedAt: '2026-10-02T12:00:00.000Z',
        messageCount: 4
      };

      saveSession(s1);
      saveSession(s2);

      expect(listSessions('visit-steward')).toHaveLength(1);
      expect(listSessions('visit-steward')[0].id).toBe('t-1');
      expect(listSessions('cardiology-guide')).toHaveLength(1);
      expect(listSessions('cardiology-guide')[0].id).toBe('t-2');
    });

    it('retrieves single session by threadId or returns null', () => {
      const s1: ChatSessionMeta = {
        id: 't-target',
        agentId: 'visit-steward',
        title: 'Target Session',
        createdAt: '2026-10-01T10:00:00.000Z',
        updatedAt: '2026-10-01T10:00:00.000Z',
        messageCount: 1
      };
      saveSession(s1);

      expect(getSession('t-target')).toEqual(s1);
      expect(getSession('non-existent')).toBeNull();
    });
  });

  describe('upsertSessionFromMessages & auto-titling', () => {
    it('creates a new session with title auto-extracted from first user message up to 45 chars', () => {
      const messages = [
        { id: '1', role: 'user', content: 'Can you please review my cardiology referral and lab test results?' },
        { id: '2', role: 'assistant', content: 'Sure, let us review your referral.' }
      ];

      const meta = upsertSessionFromMessages(
        'thread-123',
        'cardiology-guide',
        messages,
        'Cardiology Guide'
      );

      expect(meta.id).toBe('thread-123');
      expect(meta.agentId).toBe('cardiology-guide');
      expect(meta.agentTitle).toBe('Cardiology Guide');
      expect(meta.messageCount).toBe(2);
      expect(meta.isCustomTitle).toBe(false);
      // Auto-title truncated cleanly
      expect(meta.title.length).toBeLessThanOrEqual(48); // with ellipsis if needed
      expect(meta.title).toContain('Can you please review my cardiology');

      // Check saved in index
      const saved = getSession('thread-123');
      expect(saved).not.toBeNull();
      expect(saved?.title).toBe(meta.title);
    });

    it('falls back to default title if messages contain no user message', () => {
      const messages = [
        { id: '1', role: 'assistant', content: 'Hello! How can I help you today?' }
      ];

      const meta = upsertSessionFromMessages('thread-no-user', 'visit-steward', messages, 'Visit Steward');
      expect(meta.title).toMatch(/Visit Steward Session|New Consultation/);
    });

    it('preserves user custom title across subsequent message upserts', () => {
      const messages1 = [
        { id: '1', role: 'user', content: 'Initial message' }
      ];
      upsertSessionFromMessages('thread-custom', 'visit-steward', messages1);

      // Rename session
      renameSession('thread-custom', 'My Custom Specialist Appointment');

      // Later messages arrive
      const messages2 = [
        ...messages1,
        { id: '2', role: 'assistant', content: 'Response' },
        { id: '3', role: 'user', content: 'Follow-up question about symptoms' }
      ];

      const updated = upsertSessionFromMessages('thread-custom', 'visit-steward', messages2);
      expect(updated.title).toBe('My Custom Specialist Appointment');
      expect(updated.isCustomTitle).toBe(true);
      expect(updated.messageCount).toBe(3);
    });
  });

  describe('renameSession', () => {
    it('updates session title and marks isCustomTitle without modifying stored message bodies', () => {
      const threadId = 'thread-rename-test';
      const originalMessages = [
        { id: '1', role: 'user', content: 'Initial message text' }
      ];
      localStorage.setItem(`carefold_msgs_${threadId}`, JSON.stringify(originalMessages));

      upsertSessionFromMessages(threadId, 'visit-steward', originalMessages);

      const renamed = renameSession(threadId, 'Brand New Custom Title');
      expect(renamed).toBe(true);

      const meta = getSession(threadId);
      expect(meta?.title).toBe('Brand New Custom Title');
      expect(meta?.isCustomTitle).toBe(true);

      // Messages in localStorage must remain completely unmodified
      const rawMsgs = localStorage.getItem(`carefold_msgs_${threadId}`);
      expect(rawMsgs).toBe(JSON.stringify(originalMessages));
    });

    it('returns false when renaming non-existent thread', () => {
      expect(renameSession('non-existent', 'New Title')).toBe(false);
    });
  });

  describe('deleteSession', () => {
    it('removes session from index and deletes carefold_msgs_${threadId} from localStorage', () => {
      const threadId = 'thread-delete-test';
      const messages = [{ id: '1', role: 'user', content: 'Test' }];

      localStorage.setItem(`carefold_msgs_${threadId}`, JSON.stringify(messages));
      upsertSessionFromMessages(threadId, 'visit-steward', messages);

      expect(getSession(threadId)).not.toBeNull();
      expect(localStorage.getItem(`carefold_msgs_${threadId}`)).not.toBeNull();

      const deleted = deleteSession(threadId, 'visit-steward');
      expect(deleted).toBe(true);

      expect(getSession(threadId)).toBeNull();
      expect(localStorage.getItem(`carefold_msgs_${threadId}`)).toBeNull();
    });

    it('returns false when deleting a non-existent session', () => {
      expect(deleteSession('non-existent')).toBe(false);
    });
  });

  describe('discoverAndMigrateLegacySessions', () => {
    it('scans localStorage for unindexed carefold_msgs_* keys and populates index', () => {
      const threadId = 'thread-visit-steward-legacy-99';
      const messages = [
        { id: 'm1', role: 'user', content: 'What questions to ask for annual physical?' },
        { id: 'm2', role: 'assistant', content: 'Here are 5 questions to ask.' }
      ];
      localStorage.setItem(`carefold_msgs_${threadId}`, JSON.stringify(messages));

      // Index is empty initially
      expect(listSessions()).toHaveLength(0);

      discoverAndMigrateLegacySessions();

      const sessions = listSessions();
      expect(sessions.length).toBeGreaterThanOrEqual(1);
      const migrated = sessions.find((s) => s.id === threadId);
      expect(migrated).toBeDefined();
      expect(migrated?.agentId).toBe('visit-steward');
      expect(migrated?.title).toContain('What questions to ask');
      expect(migrated?.messageCount).toBe(2);
    });
  });

  describe('Event synchronization', () => {
    it('clears index when carefold:conversations-cleared event is dispatched', () => {
      initSessionHistoryListeners();

      const meta: ChatSessionMeta = {
        id: 't-clear',
        agentId: 'visit-steward',
        title: 'To Clear',
        createdAt: '2026-10-01T10:00:00.000Z',
        updatedAt: '2026-10-01T10:00:00.000Z',
        messageCount: 1
      };
      saveSession(meta);
      expect(listSessions()).toHaveLength(1);

      window.dispatchEvent(new CustomEvent('carefold:conversations-cleared'));

      expect(listSessions()).toHaveLength(0);
    });
  });

  describe('generateThreadId & extractAgentIdFromThread', () => {
    it('generates a thread ID prefixed with thread-{agentId} and timestamp', () => {
      const threadId = generateThreadId('cardiology-guide');
      expect(threadId).toMatch(/^thread-cardiology-guide-\d+-[a-zA-Z0-9_\-]+$/);
    });

    it('defaults agentId to visit-steward when not provided', () => {
      const threadId = generateThreadId();
      expect(threadId).toMatch(/^thread-visit-steward-\d+-[a-zA-Z0-9_\-]+$/);
      expect(extractAgentIdFromThread(threadId)).toBe('visit-steward');
    });

    it('generates unique thread IDs across subsequent calls', () => {
      const id1 = generateThreadId('visit-steward');
      const id2 = generateThreadId('visit-steward');
      expect(id1).not.toBe(id2);
    });

    it('extracts agent ID cleanly from generated thread IDs for both known and custom agents', () => {
      const knownThread = generateThreadId('pulmonology-guide');
      expect(extractAgentIdFromThread(knownThread)).toBe('pulmonology-guide');

      const customThread = generateThreadId('specialist-pediatric');
      expect(extractAgentIdFromThread(customThread)).toBe('specialist-pediatric');
    });
  });

  describe('LRU Bounding & MAX_INDEXED_SESSIONS', () => {
    it('defines MAX_INDEXED_SESSIONS as 50', () => {
      expect(MAX_INDEXED_SESSIONS).toBe(50);
    });

    it('prunes index to exactly 50 sessions when more than 50 sessions are saved, evicting oldest', () => {
      // Add 60 sessions with increasing timestamps
      for (let i = 1; i <= 60; i++) {
        const timestamp = new Date(Date.UTC(2026, 0, 1, 0, i, 0)).toISOString();
        saveSession({
          id: `thread-session-${i}`,
          agentId: 'visit-steward',
          title: `Session ${i}`,
          createdAt: timestamp,
          updatedAt: timestamp,
          messageCount: 1
        });
      }

      const sessions = listSessions();
      expect(sessions).toHaveLength(50);

      // Newest should be session-60, oldest retained should be session-11
      expect(sessions[0].id).toBe('thread-session-60');
      expect(sessions[49].id).toBe('thread-session-11');

      // Sessions 1 to 10 should be evicted from the index
      expect(getSession('thread-session-1')).toBeNull();
      expect(getSession('thread-session-10')).toBeNull();
      expect(getSession('thread-session-11')).not.toBeNull();
    });

    it('prunes to MAX_INDEXED_SESSIONS during discoverAndMigrateLegacySessions', () => {
      // Store 60 unindexed legacy threads
      for (let i = 1; i <= 60; i++) {
        localStorage.setItem(
          `carefold_msgs_thread-legacy-bulk-${i}`,
          JSON.stringify([{ role: 'user', content: `Legacy consultation ${i}` }])
        );
      }

      discoverAndMigrateLegacySessions();

      const sessions = listSessions();
      expect(sessions.length).toBeLessThanOrEqual(50);
      expect(sessions).toHaveLength(50);
    });
  });
});
