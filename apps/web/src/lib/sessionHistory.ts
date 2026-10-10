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

import { getScopedStorageKey, getStorageUserId } from '@/lib/storageNamespace';

export const CAREFOLD_THREADS_INDEX_KEY = 'carefold_threads_index_v1';
export const MAX_INDEXED_SESSIONS = 50;

export interface ChatSessionMeta {
  id: string;
  agentId: string;
  agentTitle?: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
  isCustomTitle?: boolean;
}

/**
 * Clean and truncate raw user prompt into a readable session title up to 45 chars.
 */
export function cleanAutoTitle(text: string): string {
  if (!text || typeof text !== 'string') return 'New Consultation';

  // Strip markdown headers, bold, italics, code ticks, blockquotes, and excessive whitespace
  const cleaned = text
    .replace(/^#+\s+/gm, '')
    .replace(/[*_~`>#]/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!cleaned) return 'New Consultation';

  if (cleaned.length <= 45) {
    return cleaned;
  }

  // Truncate cleanly at word boundary if possible
  const truncated = cleaned.slice(0, 45);
  const lastSpace = truncated.lastIndexOf(' ');
  if (lastSpace > 25) {
    return truncated.slice(0, lastSpace) + '...';
  }
  return truncated + '...';
}

function getRawIndex(userId?: string | null): ChatSessionMeta[] {
  if (typeof window === 'undefined' || !window.localStorage) return [];
  try {
    const effectiveUserId = userId !== undefined ? userId : getStorageUserId();
    const key = getScopedStorageKey(effectiveUserId, CAREFOLD_THREADS_INDEX_KEY);
    const raw = window.localStorage.getItem(key) || (!effectiveUserId ? window.localStorage.getItem(CAREFOLD_THREADS_INDEX_KEY) : null);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function setRawIndex(sessions: ChatSessionMeta[], userId?: string | null): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    const effectiveUserId = userId !== undefined ? userId : getStorageUserId();
    const key = getScopedStorageKey(effectiveUserId, CAREFOLD_THREADS_INDEX_KEY);
    const serialized = JSON.stringify(sessions);
    window.localStorage.setItem(key, serialized);
    if (!effectiveUserId) {
      window.localStorage.setItem(CAREFOLD_THREADS_INDEX_KEY, serialized);
    }
  } catch {
    // Storage access protection
  }
}

function notifySessionsChanged(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent('carefold:sessions-changed'));
}

/**
 * Lists all indexed sessions, sorted by updatedAt descending.
 * Optionally filters by agentId.
 */
export function listSessions(agentId?: string, userId?: string | null): ChatSessionMeta[] {
  const index = getRawIndex(userId);
  const sorted = [...index].sort((a, b) => {
    const tA = new Date(a.updatedAt || a.createdAt || 0).getTime();
    const tB = new Date(b.updatedAt || b.createdAt || 0).getTime();
    return tB - tA;
  });

  if (!agentId) return sorted;
  return sorted.filter((s) => s.agentId === agentId);
}

/**
 * Retrieves a single session by thread ID.
 */
export function getSession(threadId: string, userId?: string | null): ChatSessionMeta | null {
  const index = getRawIndex(userId);
  return index.find((s) => s.id === threadId) || null;
}

/**
 * Saves or updates a session metadata in the index.
 */
export function saveSession(meta: ChatSessionMeta, userId?: string | null): void {
  const index = getRawIndex(userId);
  const existingIdx = index.findIndex((s) => s.id === meta.id);

  if (existingIdx >= 0) {
    index[existingIdx] = { ...index[existingIdx], ...meta };
  } else {
    index.unshift(meta);
  }

  // Sort by updatedAt descending (most recent first) to maintain genuine LRU order
  index.sort((a, b) => {
    const tA = new Date(a.updatedAt || a.createdAt || 0).getTime();
    const tB = new Date(b.updatedAt || b.createdAt || 0).getTime();
    return tB - tA;
  });

  // LRU Pruning: bound index to MAX_INDEXED_SESSIONS
  const pruned = index.slice(0, MAX_INDEXED_SESSIONS);

  setRawIndex(pruned, userId);
  notifySessionsChanged();
}

/**
 * Creates or updates session metadata based on message array.
 * Extracts title from the first user message unless custom title was set.
 */
export function upsertSessionFromMessages(
  threadId: string,
  agentId: string,
  messages: Array<{ role: string; content: string }>,
  agentTitle?: string
): ChatSessionMeta {
  const existing = getSession(threadId);

  let title = existing?.title;
  let isCustomTitle = existing?.isCustomTitle ?? false;

  if (!isCustomTitle || !title) {
    const firstUserMsg = messages.find((m) => m.role === 'user');
    if (firstUserMsg && firstUserMsg.content) {
      title = cleanAutoTitle(firstUserMsg.content);
    } else if (!title) {
      title = agentTitle ? `${agentTitle} Session` : 'New Consultation';
    }
  }

  const now = new Date().toISOString();
  const meta: ChatSessionMeta = {
    id: threadId,
    agentId,
    agentTitle: agentTitle || existing?.agentTitle,
    title,
    createdAt: existing?.createdAt || now,
    updatedAt: now,
    messageCount: messages.length,
    isCustomTitle
  };

  saveSession(meta);
  return meta;
}

/**
 * Renames a session in the local index without modifying stored conversation messages.
 */
export function renameSession(threadId: string, newTitle: string): boolean {
  const index = getRawIndex();
  const session = index.find((s) => s.id === threadId);
  if (!session) return false;

  const trimmed = newTitle.trim();
  if (!trimmed) return false;

  session.title = trimmed;
  session.isCustomTitle = true;
  session.updatedAt = new Date().toISOString();

  setRawIndex(index);
  notifySessionsChanged();
  return true;
}

/**
 * Deletes a session by thread ID.
 * Purges carefold_msgs_${threadId}, removes from index, and fires deletion events.
 */
export function deleteSession(threadId: string, agentId?: string): boolean {
  const index = getRawIndex();
  const sessionIdx = index.findIndex((s) => s.id === threadId);
  if (sessionIdx < 0) return false;

  const session = index[sessionIdx];
  const targetAgentId = agentId || session.agentId;

  index.splice(sessionIdx, 1);
  setRawIndex(index);

  if (typeof window !== 'undefined' && window.localStorage) {
    try {
      window.localStorage.removeItem(`carefold_msgs_${threadId}`);
      window.localStorage.removeItem(getScopedStorageKey(`msgs_${threadId}`));
      const currentActive = window.localStorage.getItem(`carefold_thread_${targetAgentId}`) || window.localStorage.getItem(getScopedStorageKey(`thread_${targetAgentId}`));
      if (currentActive === threadId) {
        window.localStorage.removeItem(`carefold_thread_${targetAgentId}`);
        window.localStorage.removeItem(getScopedStorageKey(`thread_${targetAgentId}`));
      }
    } catch {
      // Storage protection
    }
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('carefold:conversation-deleted', {
        detail: { threadId, agentId: targetAgentId }
      })
    );
  }

  notifySessionsChanged();
  return true;
}

const KNOWN_AGENTS = [
  'visit-steward',
  'cardiology-guide',
  'pulmonology-guide',
  'derma-guide',
  'gastro-guide',
  'neurology-guide',
  'nephrology-guide',
  'endocrinology-guide',
  'rheuma-guide',
  'ortho-guide',
  'podiatry-guide',
  'urology-guide',
  'vascular-guide',
  'ent-guide',
  'eye-guide',
  'oncology-navigator',
  'benefits-guide',
  'claims-appeals-guide',
  'prior-auth-navigator',
  'formulary-guide',
  'records-coordinator',
  'habit-companion'
];

/**
 * Generates a cryptographically secure thread ID.
 * Employs crypto.randomUUID() when supported, with cryptographically secure fallback
 * to crypto.getRandomValues(). Prevents CWE-338 insecure randomness security alerts.
 */
export function generateThreadId(agentId: string = 'visit-steward'): string {
  const secureRandom =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID().slice(0, 8)
      : typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function'
      ? Array.from(crypto.getRandomValues(new Uint8Array(8)))
          .map((b) => b.toString(16).padStart(2, '0'))
          .join('')
          .slice(0, 8)
      : `${Date.now()}`;
  return `thread-${agentId}-${Date.now()}-${secureRandom}`;
}

/**
 * Extracts agent ID from thread ID string.
 */
export function extractAgentIdFromThread(threadId: string): string {
  if (!threadId) return 'visit-steward';

  // Check against known agents first
  for (const agentId of KNOWN_AGENTS) {
    if (
      threadId === `thread-${agentId}` ||
      threadId.startsWith(`thread-${agentId}-`) ||
      threadId.startsWith(agentId)
    ) {
      return agentId;
    }
  }

  // Fallback heuristic: strip "thread-" and trailing timestamp/random suffixes
  const stripped = threadId.startsWith('thread-') ? threadId.slice(7) : threadId;
  const match = stripped.match(/^([a-zA-Z0-9_\-]+?)(?:-\d{10,14}(?:-[a-zA-Z0-9_\-]+)?)?$/);
  if (match && match[1]) {
    return match[1];
  }
  return 'visit-steward';
}

/**
 * Auto-discovers and migrates legacy unindexed sessions from localStorage.
 */
export function discoverAndMigrateLegacySessions(): void {
  if (typeof window === 'undefined' || !window.localStorage) return;

  const index = getRawIndex();
  const existingIds = new Set(index.map((s) => s.id));
  let modified = false;

  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (!key || !key.startsWith('carefold_msgs_')) continue;

      const threadId = key.replace('carefold_msgs_', '');
      if (existingIds.has(threadId)) continue;

      try {
        const raw = window.localStorage.getItem(key);
        if (!raw) continue;
        const messages = JSON.parse(raw);
        if (!Array.isArray(messages) || messages.length === 0) continue;

        const agentId = extractAgentIdFromThread(threadId);

        const firstUserMsg = messages.find((m: any) => m.role === 'user');
        const title = firstUserMsg?.content
          ? cleanAutoTitle(firstUserMsg.content)
          : 'Past Consultation';

        const now = new Date().toISOString();
        index.push({
          id: threadId,
          agentId,
          title,
          createdAt: now,
          updatedAt: now,
          messageCount: messages.length,
          isCustomTitle: false
        });
        existingIds.add(threadId);
        modified = true;
      } catch {
        // Skip malformed entries
      }
    }

    if (modified) {
      index.sort((a, b) => {
        const tA = new Date(a.updatedAt || a.createdAt || 0).getTime();
        const tB = new Date(b.updatedAt || b.createdAt || 0).getTime();
        return tB - tA;
      });
      const pruned = index.slice(0, MAX_INDEXED_SESSIONS);
      setRawIndex(pruned);
      notifySessionsChanged();
    }
  } catch {
    // Storage access protection
  }
}

/**
 * Initializes global event listener to keep index in sync with settings actions.
 */
export function initSessionHistoryListeners(): () => void {
  if (typeof window === 'undefined') return () => {};

  const handleCleared = () => {
    try {
      window.localStorage.removeItem(CAREFOLD_THREADS_INDEX_KEY);
      window.localStorage.removeItem(getScopedStorageKey(CAREFOLD_THREADS_INDEX_KEY));
      notifySessionsChanged();
    } catch {
      // Storage access protection
    }
  };

  window.addEventListener('carefold:conversations-cleared', handleCleared);

  return () => {
    window.removeEventListener('carefold:conversations-cleared', handleCleared);
  };
}

// Auto-register listener in browser environment
if (typeof window !== 'undefined') {
  initSessionHistoryListeners();
}
