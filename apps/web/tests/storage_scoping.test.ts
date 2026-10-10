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
  ScopedStorage,
  getScopedStorageKey,
  setStorageUserId,
} from '@/lib/storageNamespace';

/**
 * Frontend Browser Storage User Namespacing & Scoping Test Suite.
 *
 * Requirements (R1 #166, TEST_INFRA.md Feature 6):
 * - Browser storage keys namespaced by user ID: `carefold_{userId}_*`
 * - Strict isolation: User A cannot read or overwrite User B's localStorage items
 * - Session detachment / clearing on logout to protect shared devices
 * - Fallback to guest / default steward mode when unauthenticated
 * - Fault tolerance: QuotaExceededError, private browsing, SSR safety, malformed JSON
 */


// =============================================================================
// TEST SUITE
// =============================================================================

describe('E2E Storage Scoping Suite: Browser Storage Namespacing & Isolation', () => {
  const USER_A = 'usr-alice-123e4567';
  const USER_B = 'usr-bob-987f6543';

  beforeEach(() => {
    localStorage.clear();
    setStorageUserId(null);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
    setStorageUserId(null);
  });

  // ---------------------------------------------------------------------------
  // Tier 1: Feature Coverage (Key generation, read/write, user isolation, clear on logout)
  // ---------------------------------------------------------------------------
  describe('Tier 1: Feature Coverage — User Scoping & Storage Namespacing', () => {
    it('f-storage-01: generates correctly namespaced storage keys with carefold_{userId}_* format', () => {
      const keyA = getScopedStorageKey(USER_A, 'user_settings_v1');
      const keyB = getScopedStorageKey(USER_B, 'user_settings_v1');

      expect(keyA).toBe(`carefold_${USER_A}_user_settings_v1`);
      expect(keyB).toBe(`carefold_${USER_B}_user_settings_v1`);
      expect(keyA).not.toBe(keyB);
    });

    it('f-storage-02: stores and retrieves user state under the authenticated user namespace', () => {
      const storeA = new ScopedStorage({ userId: USER_A });
      const settingsData = { theme: 'dark', model: 'llama3.2:3b' };

      const saved = storeA.setItem('settings', settingsData);
      expect(saved).toBe(true);

      // Verify physical key in localStorage
      const physicalVal = localStorage.getItem(`carefold_${USER_A}_settings`);
      expect(physicalVal).not.toBeNull();
      expect(JSON.parse(physicalVal!)).toEqual(settingsData);

      // Retrieve via instance
      const retrieved = storeA.getItem('settings');
      expect(retrieved).toEqual(settingsData);
    });

    it('f-storage-03: strictly isolates User A data from User B (zero data leakage)', () => {
      const storeA = new ScopedStorage({ userId: USER_A });
      const storeB = new ScopedStorage({ userId: USER_B });

      storeA.setItem('threads', [{ id: 'thread-1', title: "Alice's Cardiology Prep" }]);
      storeB.setItem('threads', [{ id: 'thread-2', title: "Bob's Orthopedic Review" }]);

      // User A reads only User A data
      const threadsA = storeA.getItem('threads');
      expect(threadsA).toHaveLength(1);
      expect(threadsA[0].title).toBe("Alice's Cardiology Prep");

      // User B reads only User B data
      const threadsB = storeB.getItem('threads');
      expect(threadsB).toHaveLength(1);
      expect(threadsB[0].title).toBe("Bob's Orthopedic Review");
    });

    it('f-storage-04: clears all User A storage keys on session detachment / logout without affecting User B', () => {
      const storeA = new ScopedStorage({ userId: USER_A });
      const storeB = new ScopedStorage({ userId: USER_B });

      storeA.setItem('settings', { theme: 'light' });
      storeA.setItem('threads', ['t1', 't2']);
      storeB.setItem('settings', { theme: 'dark' });
      storeB.setItem('threads', ['tb1']);

      // User A logs out -> clear User A keys
      const removedCount = storeA.clearUserData();
      expect(removedCount).toBe(2);

      // User A keys are gone
      expect(storeA.getItem('settings')).toBeNull();
      expect(storeA.getItem('threads')).toBeNull();

      // User B keys remain 100% untouched
      expect(storeB.getItem('settings')).toEqual({ theme: 'dark' });
      expect(storeB.getItem('threads')).toEqual(['tb1']);
    });

    it('f-storage-05: supports removing individual scoped items cleanly', () => {
      const store = new ScopedStorage({ userId: USER_A });
      store.setItem('draft_message', 'Hello doctor');
      expect(store.getItem('draft_message')).toBe('Hello doctor');

      const removed = store.removeItem('draft_message');
      expect(removed).toBe(true);
      expect(store.getItem('draft_message')).toBeNull();
    });
  });

  // ---------------------------------------------------------------------------
  // Tier 2: Boundary & Corner Cases (Guest fallback, QuotaExceeded, Private browsing, SSR)
  // ---------------------------------------------------------------------------
  describe('Tier 2: Boundary & Corner Cases — Resilience & Fallbacks', () => {
    it('b-storage-01: falls back cleanly to carefold_guest_* when userId is null, undefined, or empty', () => {
      const keyNull = getScopedStorageKey(null, 'settings');
      const keyUndefined = getScopedStorageKey(undefined, 'settings');
      const keyEmpty = getScopedStorageKey('   ', 'settings');

      expect(keyNull).toBe('carefold_guest_settings');
      expect(keyUndefined).toBe('carefold_guest_settings');
      expect(keyEmpty).toBe('carefold_guest_settings');

      const guestStore = new ScopedStorage({ userId: null });
      guestStore.setItem('guest_note', 'Temporary note');
      expect(localStorage.getItem('carefold_guest_guest_note')).not.toBeNull();
    });

    it('b-storage-02: recovers gracefully from QuotaExceededError without throwing unhandled exceptions', () => {
      const mockStorage = {
        getItem: vi.fn(),
        setItem: vi.fn().mockImplementation(() => {
          const err = new Error('QuotaExceededError');
          err.name = 'QuotaExceededError';
          throw err;
        }),
        removeItem: vi.fn(),
        clear: vi.fn(),
        key: vi.fn(),
        length: 0,
      } as unknown as Storage;

      const store = new ScopedStorage({ userId: USER_A, storage: mockStorage });
      const success = store.setItem('large_data', { huge: 'payload' });
      expect(success).toBe(false); // Does not throw, returns false gracefully
    });

    it('b-storage-03: handles private browsing / restricted browser where localStorage throws on access', () => {
      const mockStorage = {
        getItem: vi.fn().mockImplementation(() => {
          throw new Error('SecurityError: The operation is insecure.');
        }),
        setItem: vi.fn().mockImplementation(() => {
          throw new Error('SecurityError: The operation is insecure.');
        }),
        removeItem: vi.fn(),
        clear: vi.fn(),
        key: vi.fn(),
        length: 0,
      } as unknown as Storage;

      const store = new ScopedStorage({ userId: USER_A, storage: mockStorage });
      expect(store.getItem('key', 'defaultVal')).toBe('defaultVal');
      expect(store.setItem('key', 'val')).toBe(false);
    });

    it('b-storage-04: handles SSR environment where window.localStorage is undefined', () => {
      const ssrStore = new ScopedStorage({ userId: USER_A, storage: null });
      expect(ssrStore.getItem('any', 'fallback')).toBe('fallback');
      expect(ssrStore.setItem('any', 'val')).toBe(false);
      expect(ssrStore.removeItem('any')).toBe(false);
      expect(ssrStore.clearUserData()).toBe(0);
      expect(ssrStore.listUserKeys()).toEqual([]);
    });

    it('b-storage-05: handles corrupted / non-JSON values by returning raw string without crashing', () => {
      localStorage.setItem(`carefold_${USER_A}_corrupted`, 'NOT_VALID_JSON{:::');
      const store = new ScopedStorage({ userId: USER_A });
      const val = store.getItem('corrupted');
      expect(val).toBe('NOT_VALID_JSON{:::');
    });

    it('b-storage-06: safely trims whitespace and handles complex UUIDs in user IDs', () => {
      const messyId = '   550e8400-e29b-41d4-a716-446655440000   ';
      const key = getScopedStorageKey(messyId, 'data');
      expect(key).toBe('carefold_550e8400-e29b-41d4-a716-446655440000_data');
    });
  });

  // ---------------------------------------------------------------------------
  // Tier 3: Cross-Feature Integration (Settings, History, Clinical Consents, Checklists)
  // ---------------------------------------------------------------------------
  describe('Tier 3: Cross-Feature Combinations — Carefold Subsystem Storage', () => {
    it('c-storage-01: namespaces consultation checklist items per user and thread', () => {
      const storeA = new ScopedStorage({ userId: USER_A });
      const storeB = new ScopedStorage({ userId: USER_B });

      const threadId = 't-cardio-99';
      const msgId = 'msg-1';
      const checklistKey = `checklist_${threadId}_${msgId}`;

      storeA.setItem(checklistKey, [{ id: 1, text: 'Check blood pressure', completed: true }]);
      storeB.setItem(checklistKey, [{ id: 1, text: 'Check MRI results', completed: false }]);

      const checklistA = storeA.getItem(checklistKey);
      const checklistB = storeB.getItem(checklistKey);

      expect(checklistA[0].text).toBe('Check blood pressure');
      expect(checklistB[0].text).toBe('Check MRI results');
    });

    it('c-storage-02: namespaces clinical consent per user to prevent consent leakage', () => {
      const storeA = new ScopedStorage({ userId: USER_A });
      const storeB = new ScopedStorage({ userId: USER_B });

      // Alice consented to clinical assist
      storeA.setItem('clinical_consent_v1', { consented: true, timestamp: '2026-10-09T00:00:00Z' });

      // Bob has NOT consented
      expect(storeB.getItem('clinical_consent_v1')).toBeNull();

      const consentA = storeA.getItem('clinical_consent_v1');
      expect(consentA.consented).toBe(true);
    });

    it('c-storage-03: accurately lists only active user keys across multiple subsystems', () => {
      const storeA = new ScopedStorage({ userId: USER_A });
      const storeB = new ScopedStorage({ userId: USER_B });

      storeA.setItem('settings', { v: 1 });
      storeA.setItem('threads', ['t1']);
      storeA.setItem('consent', true);

      storeB.setItem('settings', { v: 2 });
      storeB.setItem('other', 'val');

      const keysA = storeA.listUserKeys();
      expect(keysA).toContain('settings');
      expect(keysA).toContain('threads');
      expect(keysA).toContain('consent');
      expect(keysA).not.toContain('other');
      expect(keysA).toHaveLength(3);
    });
  });

  // ---------------------------------------------------------------------------
  // Tier 4: Real-World Scenario (Shared Computer / Kiosk User Switching Journey)
  // ---------------------------------------------------------------------------
  describe('Tier 4: Real-World Scenarios — Shared Family Device Journey', () => {
    it('w-storage-01: simulates Alice and Bob alternating sessions on a shared family tablet', () => {
      // Step 1: Alice logs in
      const aliceStore = new ScopedStorage({ userId: USER_A });
      aliceStore.setItem('threads_index', [{ id: 'th-1', agent: 'cardiology-guide' }]);
      aliceStore.setItem('draft_note', 'Ask cardiologist about palpitations');

      // Step 2: Alice logs out (clearing local session cache on shared tablet)
      aliceStore.clearUserData();
      expect(aliceStore.listUserKeys()).toHaveLength(0);

      // Step 3: Bob logs in on same browser
      const bobStore = new ScopedStorage({ userId: USER_B });
      expect(bobStore.getItem('threads_index')).toBeNull(); // Clean slate, Bob sees zero Alice data
      bobStore.setItem('threads_index', [{ id: 'th-2', agent: 'derma-guide' }]);
      bobStore.setItem('draft_note', 'Inquire about rash');

      // Step 4: Bob finishes and logs out
      bobStore.clearUserData();
      expect(bobStore.listUserKeys()).toHaveLength(0);

      // Step 5: Verification that shared device is completely clean of sensitive health drafts
      expect(localStorage.getItem(`carefold_${USER_A}_draft_note`)).toBeNull();
      expect(localStorage.getItem(`carefold_${USER_B}_draft_note`)).toBeNull();
    });
  });
});
