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

import type {
  MemoryRecord,
  MemoryTier,
  MemoryFilterParams,
  MemoryStatus,
  MemoryDeleteResponse,
  MemoryBulkDeleteResponse,
  MemoryUpdateRequest,
} from '@/types/api';

export type {
  MemoryRecord,
  MemoryTier,
  MemoryFilterParams,
  MemoryStatus,
  MemoryDeleteResponse,
  MemoryBulkDeleteResponse,
  MemoryUpdateRequest,
};

import { getScopedStorageKey } from '@/lib/storageNamespace';

export const SESSION_MEMORY_PAUSED_STORAGE_KEY = 'carefold_memory_paused_session';
export const MEMORY_PAUSE_EVENT = 'carefold:memory-pause-changed';

/**
 * Checks if episodic memory collection is paused for the current session.
 */
export function isSessionMemoryPaused(userId?: string | null): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const key = getScopedStorageKey(userId, SESSION_MEMORY_PAUSED_STORAGE_KEY);
    const sessionVal = sessionStorage.getItem(key) ?? sessionStorage.getItem(SESSION_MEMORY_PAUSED_STORAGE_KEY);
    if (sessionVal !== null) {
      return sessionVal === 'true';
    }
    const localVal = localStorage.getItem(key) ?? localStorage.getItem(SESSION_MEMORY_PAUSED_STORAGE_KEY);
    return localVal === 'true';
  } catch {
    return false;
  }
}

/**
 * Sets episodic memory pause state for the current session and dispatches notification event.
 */
export function setSessionMemoryPaused(paused: boolean, userId?: string | null): void {
  if (typeof window === 'undefined') return;
  try {
    const key = getScopedStorageKey(userId, SESSION_MEMORY_PAUSED_STORAGE_KEY);
    sessionStorage.setItem(key, String(paused));
    localStorage.setItem(key, String(paused));
    if (!userId) {
      sessionStorage.setItem(SESSION_MEMORY_PAUSED_STORAGE_KEY, String(paused));
      localStorage.setItem(SESSION_MEMORY_PAUSED_STORAGE_KEY, String(paused));
    }
    window.dispatchEvent(
      new CustomEvent(MEMORY_PAUSE_EVENT, { detail: { paused } })
    );
  } catch {
    // Ignore storage quota/security errors in restricted browser contexts
  }
}

/**
 * Fetches cognitive memories matching optional query, tier filter, and namespace.
 */
export async function fetchMemories(
  params: MemoryFilterParams = {}
): Promise<MemoryRecord[]> {
  const searchParams = new URLSearchParams();

  if (params.query && params.query.trim()) {
    searchParams.set('query', params.query.trim());
  }
  if (params.tier && params.tier !== 'all') {
    searchParams.set('tier', params.tier);
  }
  if (params.namespace && params.namespace.trim()) {
    searchParams.set('namespace', params.namespace.trim());
  }
  if (params.limit !== undefined && params.limit !== null) {
    searchParams.set('limit', String(params.limit));
  }

  const queryString = searchParams.toString();
  const url = queryString ? `/api/v1/memories?${queryString}` : '/api/v1/memories';

  const res = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const message = err?.error || err?.detail || `Failed to fetch memories (HTTP ${res.status})`;
    throw new Error(message);
  }

  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

/**
 * Fetches status of the cognitive memory backend (healthy, fallback, backend type).
 */
export async function fetchMemoryStatus(): Promise<MemoryStatus> {
  const res = await fetch('/api/v1/memories/status', {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const message = err?.error || err?.detail || `Failed to fetch memory status (HTTP ${res.status})`;
    throw new Error(message);
  }

  return res.json();
}

/**
 * Updates an existing memory record's value, tier, or metadata.
 */
export async function updateMemory(
  key: string,
  payload: MemoryUpdateRequest
): Promise<MemoryRecord> {
  if (!key || !key.trim()) {
    throw new Error('Memory key is required.');
  }

  const queryParams = payload.namespace ? `?namespace=${encodeURIComponent(payload.namespace)}` : '';
  const res = await fetch(`/api/v1/memories/${encodeURIComponent(key.trim())}${queryParams}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const message = err?.error || err?.detail || `Failed to update memory "${key}" (HTTP ${res.status})`;
    throw new Error(message);
  }

  return res.json();
}

/**
 * Deletes a single memory record identified by key in the specified namespace.
 */
export async function deleteMemory(
  key: string,
  namespace: string = 'default'
): Promise<MemoryDeleteResponse> {
  if (!key || !key.trim()) {
    throw new Error('Memory key is required.');
  }

  const queryParams = `?namespace=${encodeURIComponent(namespace)}`;
  const res = await fetch(`/api/v1/memories/${encodeURIComponent(key.trim())}${queryParams}`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const message = err?.error || err?.detail || `Failed to delete memory "${key}" (HTTP ${res.status})`;
    throw new Error(message);
  }

  return res.json();
}

/**
 * Bulk forgets/clears all memories within the specified namespace.
 */
export async function clearAllMemories(
  namespace: string = 'default'
): Promise<MemoryBulkDeleteResponse> {
  const queryParams = `?namespace=${encodeURIComponent(namespace)}`;
  const res = await fetch(`/api/v1/memories${queryParams}`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const message = err?.error || err?.detail || `Failed to clear memories (HTTP ${res.status})`;
    throw new Error(message);
  }

  return res.json();
}
