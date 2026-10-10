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

import type { ChecklistItemState } from './types';
import { getScopedStorageKey } from '@/lib/storageNamespace';

export const CHECKLIST_STORAGE_PREFIX = 'carefold_checklist_';

/**
 * Returns standardized storage key for a thread and message checklist:
 * `carefold_{userId}_checklist_${threadId}_${messageId}`
 */
export function getChecklistKey(threadId?: string, messageId?: string, userId?: string | null): string {
  const cleanThread = (threadId || 'default').replace(/[^a-zA-Z0-9_\-]/g, '_');
  const cleanMsg = (messageId || 'default').replace(/[^a-zA-Z0-9_\-]/g, '_');
  return getScopedStorageKey(userId, `checklist_${cleanThread}_${cleanMsg}`);
}

/**
 * Loads checklist state from browser localStorage. If no stored state exists,
 * initializes items from the provided questions list.
 */
export function loadChecklist(
  threadId?: string,
  messageId?: string,
  initialQuestions?: string[],
  userId?: string | null
): ChecklistItemState[] {
  const fallback = (initialQuestions || []).map((q, idx) => ({
    id: `init-${idx}`,
    text: q,
    completed: false,
  }));

  if (typeof window === 'undefined' || !window.localStorage) {
    return fallback;
  }

  const key = getChecklistKey(threadId, messageId, userId);
  try {
    const cleanThread = (threadId || 'default').replace(/[^a-zA-Z0-9_\-]/g, '_');
    const cleanMsg = (messageId || 'default').replace(/[^a-zA-Z0-9_\-]/g, '_');
    const legacyKey = `${CHECKLIST_STORAGE_PREFIX}${cleanThread}_${cleanMsg}`;
    const raw = window.localStorage.getItem(key) || window.localStorage.getItem(legacyKey);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed as ChecklistItemState[];
      }
    }
  } catch {
    // Return initial questions on parse failure
  }

  return fallback;
}

/**
 * Saves checklist state to browser localStorage under the thread and message key.
 */
export function saveChecklist(
  threadId: string | undefined,
  messageId: string | undefined,
  items: ChecklistItemState[],
  userId?: string | null
): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  const key = getChecklistKey(threadId, messageId, userId);
  try {
    const val = JSON.stringify(items);
    window.localStorage.setItem(key, val);
    if (!userId) {
      const cleanThread = (threadId || 'default').replace(/[^a-zA-Z0-9_\-]/g, '_');
      const cleanMsg = (messageId || 'default').replace(/[^a-zA-Z0-9_\-]/g, '_');
      window.localStorage.setItem(`${CHECKLIST_STORAGE_PREFIX}${cleanThread}_${cleanMsg}`, val);
    }
  } catch {
    // Storage access or quota error protection
  }
}

/**
 * Toggles an item's completed state and persists the updated checklist to localStorage.
 */
export function toggleChecklistItem(
  threadId: string | undefined,
  messageId: string | undefined,
  itemId: string,
  currentItems?: ChecklistItemState[],
  userId?: string | null
): ChecklistItemState[] {
  const items = currentItems ? [...currentItems] : loadChecklist(threadId, messageId, undefined, userId);
  const updated = items.map((item) =>
    item.id === itemId ? { ...item, completed: !item.completed } : item
  );
  saveChecklist(threadId, messageId, updated, userId);
  return updated;
}

/**
 * Appends a custom question item to the checklist and persists to localStorage.
 * Uses cryptographically secure randomUUID when available to avoid CodeQL randomness warnings.
 */
export function addChecklistItem(
  threadId: string | undefined,
  messageId: string | undefined,
  text: string,
  currentItems?: ChecklistItemState[],
  userId?: string | null
): ChecklistItemState[] {
  const trimmed = text.trim();
  if (!trimmed) {
    return currentItems ? [...currentItems] : loadChecklist(threadId, messageId, undefined, userId);
  }
  const items = currentItems ? [...currentItems] : loadChecklist(threadId, messageId, undefined, userId);
  const id =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `item-${Date.now()}`;
  const updated = [...items, { id, text: trimmed, completed: false, isCustom: true }];
  saveChecklist(threadId, messageId, updated, userId);
  return updated;
}

/**
 * Clears all checklist localStorage keys belonging to a specific conversation thread.
 */
export function clearChecklistsForThread(threadId: string): void {
  if (typeof window === 'undefined' || !window.localStorage || !threadId) return;
  try {
    const cleanThread = threadId.replace(/[^a-zA-Z0-9_\-]/g, '_');
    const legacyPrefix = `${CHECKLIST_STORAGE_PREFIX}${cleanThread}_`;
    const needle = `checklist_${cleanThread}_`;
    const keysToRemove: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key && (key.startsWith(legacyPrefix) || key.includes(needle))) {
        keysToRemove.push(key);
      }
    }
    for (const key of keysToRemove) {
      window.localStorage.removeItem(key);
    }
  } catch {
    // Storage access protection
  }
}
