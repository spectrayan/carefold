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

/**
 * Frontend Browser Storage User Namespacing & Scoping Module.
 *
 * Requirements (R1 #166):
 * - Namespaces browser storage keys by authenticated user ID: `carefold_{userId}_*`
 * - Enforces zero data leakage between user sessions on shared devices
 * - Graceful fallback to `carefold_guest_*` when unauthenticated
 * - Session detachment and scoped clearing on user logout
 * - SSR-safe, QuotaExceededError-resilient, corrupted-JSON tolerant
 */

export const STORAGE_DETACHED_EVENT = 'carefold:storage-detached';

export interface ScopedStorageOptions {
  userId?: string | null;
  storage?: Storage | null;
}

let activeStorageUserId: string | null = null;

/**
 * Sets the active global storage user ID.
 */
export function setStorageUserId(userId: string | null | undefined): void {
  activeStorageUserId = userId && userId.trim() ? userId.trim() : null;
}

/**
 * Gets the active global storage user ID.
 */
export function getStorageUserId(): string | null {
  return activeStorageUserId;
}

/**
 * Resolves effective user ID string or 'guest'.
 */
export function resolveStorageUserId(userId?: string | null): string {
  const effective = userId !== undefined ? userId : activeStorageUserId;
  return effective && effective.trim() ? effective.trim() : 'guest';
}

/**
 * Generates correctly namespaced storage key with `carefold_{userId}_*` format.
 * Supports both signatures: (userId, baseKey) and (baseKey, userId).
 */
export function getScopedStorageKey(
  arg1?: string | null,
  arg2?: string | null
): string {
  let userId: string | null | undefined;
  let baseKey: string;

  if (arg2 === undefined) {
    // Single argument: baseKey, uses activeStorageUserId
    baseKey = arg1 || '';
    userId = activeStorageUserId;
  } else {
    // Two arguments: (arg1, arg2)
    // If arg1 is undefined, userId was omitted in caller signature -> fall back to activeStorageUserId
    if (arg1 === undefined) {
      userId = activeStorageUserId;
      baseKey = arg2 || '';
    } else if (arg1 === null || !arg1.trim()) {
      // Explicit null or empty string indicates unauthenticated guest
      userId = null;
      baseKey = arg2 || '';
    } else {
      const clean1 = arg1.trim();
      const clean2 = arg2 ? arg2.trim() : '';
      // If arg1 starts with usr- or is a UUID, it's userId
      if (clean1.startsWith('usr-') || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(clean1)) {
        userId = arg1;
        baseKey = arg2 || '';
      } else if (clean2.startsWith('usr-') || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(clean2)) {
        userId = arg2;
        baseKey = arg1;
      } else {
        // Standard signature: getScopedStorageKey(userId, baseKey)
        userId = arg1;
        baseKey = arg2 || '';
      }
    }
  }

  const cleanBase = baseKey.replace(/^carefold_/, '');
  if (!userId || !userId.trim()) {
    return `carefold_guest_${cleanBase}`;
  }
  return `carefold_${userId.trim()}_${cleanBase}`;
}

/**
 * Scoped storage client providing namespaced localStorage operations.
 */
export class ScopedStorage {
  private userId: string | null;
  private storage: Storage | null;

  constructor(options: ScopedStorageOptions = {}) {
    this.userId = options.userId !== undefined ? (options.userId?.trim() || null) : activeStorageUserId;
    this.storage = options.storage !== undefined
      ? options.storage
      : (typeof window !== 'undefined' ? window.localStorage : null);
  }

  setUserId(userId: string | null) {
    this.userId = userId && userId.trim() ? userId.trim() : null;
  }

  getUserId(): string | null {
    return this.userId;
  }

  getKey(baseKey: string): string {
    return getScopedStorageKey(this.userId, baseKey);
  }

  getItem<T = any>(baseKey: string, defaultValue: T | null = null): T | null {
    if (!this.storage) return defaultValue;
    try {
      const key = this.getKey(baseKey);
      const raw = this.storage.getItem(key);
      if (raw === null) return defaultValue;
      try {
        return JSON.parse(raw);
      } catch {
        // Return raw string if not valid JSON
        return raw as unknown as T;
      }
    } catch {
      return defaultValue;
    }
  }

  setItem<T = any>(baseKey: string, value: T): boolean {
    if (!this.storage) return false;
    try {
      const key = this.getKey(baseKey);
      const serialized = typeof value === 'string' ? value : JSON.stringify(value);
      this.storage.setItem(key, serialized);
      return true;
    } catch {
      return false;
    }
  }

  removeItem(baseKey: string): boolean {
    if (!this.storage) return false;
    try {
      const key = this.getKey(baseKey);
      this.storage.removeItem(key);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Clears all storage keys belonging exclusively to this scoped user ID.
   * Does NOT touch other users' keys or non-carefold keys.
   */
  clearUserData(): number {
    if (!this.storage) return 0;
    try {
      const prefix = this.userId && this.userId.trim()
        ? `carefold_${this.userId.trim()}_`
        : 'carefold_guest_';
      const keysToRemove: string[] = [];

      for (let i = 0; i < this.storage.length; i++) {
        const k = this.storage.key(i);
        if (k && k.startsWith(prefix)) {
          keysToRemove.push(k);
        }
      }

      for (const k of keysToRemove) {
        this.storage.removeItem(k);
      }
      return keysToRemove.length;
    } catch {
      return 0;
    }
  }

  /**
   * Lists all scoped base keys for the current user.
   */
  listUserKeys(): string[] {
    if (!this.storage) return [];
    try {
      const prefix = this.userId && this.userId.trim()
        ? `carefold_${this.userId.trim()}_`
        : 'carefold_guest_';
      const keys: string[] = [];

      for (let i = 0; i < this.storage.length; i++) {
        const k = this.storage.key(i);
        if (k && k.startsWith(prefix)) {
          keys.push(k.substring(prefix.length));
        }
      }
      return keys;
    } catch {
      return [];
    }
  }
}

/**
 * Migrates keys from source namespace (e.g., guest) to target user namespace.
 */
export function migrateUserStorage(
  sourceUserId: string | null | undefined,
  targetUserId: string,
  storage?: Storage | null
): number {
  const store = storage !== undefined
    ? storage
    : (typeof window !== 'undefined' ? window.localStorage : null);
  if (!store || !targetUserId || !targetUserId.trim()) return 0;

  try {
    const sourceStore = new ScopedStorage({ userId: sourceUserId, storage: store });
    const targetStore = new ScopedStorage({ userId: targetUserId, storage: store });
    const keys = sourceStore.listUserKeys();
    let migratedCount = 0;

    for (const baseKey of keys) {
      const val = sourceStore.getItem(baseKey);
      if (val !== null) {
        if (targetStore.setItem(baseKey, val)) {
          sourceStore.removeItem(baseKey);
          migratedCount++;
        }
      }
    }
    return migratedCount;
  } catch {
    return 0;
  }
}

/**
 * Detaches the current user session:
 * Clears user's scoped storage from shared device, resets active user,
 * and notifies active components to clear in-memory cache.
 */
export function detachUserSession(userId?: string | null): void {
  const targetId = userId !== undefined ? userId : activeStorageUserId;
  const store = new ScopedStorage({ userId: targetId });
  store.clearUserData();
  activeStorageUserId = null;
  scopedStorage.setUserId(null);

  if (typeof window !== 'undefined' && window.localStorage) {
    try {
      const keysToRemove: string[] = [];
      for (let i = 0; i < window.localStorage.length; i++) {
        const k = window.localStorage.key(i);
        if (k && (
          k.startsWith('carefold_msgs_') ||
          k.startsWith('carefold_thread_') ||
          (targetId && k.startsWith(`carefold_${targetId}_`))
        )) {
          keysToRemove.push(k);
        }
      }
      for (const k of keysToRemove) {
        window.localStorage.removeItem(k);
      }
    } catch {
      // Storage protection
    }
  }

  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      if (targetId) {
        const prefix = `carefold_${targetId}_`;
        const sessionKeys: string[] = [];
        for (let i = 0; i < window.sessionStorage.length; i++) {
          const k = window.sessionStorage.key(i);
          if (k && (k.startsWith(prefix) || k.startsWith('carefold_memory_paused_'))) {
            sessionKeys.push(k);
          }
        }
        for (const k of sessionKeys) {
          window.sessionStorage.removeItem(k);
        }
      }
    } catch {
      // Storage protection
    }
  }

  if (typeof window !== 'undefined') {
    try {
      window.dispatchEvent(new CustomEvent(STORAGE_DETACHED_EVENT, { detail: { userId: targetId } }));
    } catch {
      // Non-DOM
    }
  }
}

/**
 * Default scoped storage instance bound to active global user.
 */
export const scopedStorage = new ScopedStorage();
