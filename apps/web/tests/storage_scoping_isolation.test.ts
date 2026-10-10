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
  getStorageUserId,
  detachUserSession,
} from '@/lib/storageNamespace';
import {
  loadSettings,
  saveSettings,
  CAREFOLD_SETTINGS_STORAGE_KEY,
  DEFAULT_USER_SETTINGS,
} from '@/lib/settings';
import {
  listSessions,
  saveSession,
  getSession,
  CAREFOLD_THREADS_INDEX_KEY,
} from '@/lib/sessionHistory';
import {
  loadClinicalConsents,
  grantClinicalConsent,
  hasClinicalConsent,
} from '@/lib/clinicalConsent';
import {
  loadChecklist,
  saveChecklist,
  getChecklistKey,
} from '@/lib/checklistStorage';
import {
  isSessionMemoryPaused,
  setSessionMemoryPaused,
} from '@/lib/memory';
import { DEFAULT_STEWARD_USER } from '@/lib/auth';

describe('Storage Scoping Isolation Suite (#166)', () => {
  const USER_A = 'usr-alice-123e4567';
  const USER_B = 'usr-bob-987f6543';

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setStorageUserId(null);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setStorageUserId(null);
  });

  // ===========================================================================
  // Attack 1: Session Detachment on Logout & Cross-User Data Isolation
  // ===========================================================================
  describe('Attack 1: Session Detachment on Logout & Cross-Account Isolation', () => {
    it('1.1: ScopedStorage strictly isolates User A from User B when explicit userId is provided', () => {
      const storeA = new ScopedStorage({ userId: USER_A });
      const storeB = new ScopedStorage({ userId: USER_B });

      storeA.setItem('draft_note', 'Alice secret cardiology note');
      expect(storeB.getItem('draft_note')).toBeNull();

      detachUserSession(USER_A);
      expect(storeA.getItem('draft_note')).toBeNull();
      expect(localStorage.getItem(`carefold_${USER_A}_draft_note`)).toBeNull();
    });

    it('1.2: Tests whether getScopedStorageKey respects activeStorageUserId when userId parameter is undefined', () => {
      setStorageUserId(USER_A);
      expect(getStorageUserId()).toBe(USER_A);

      // Single argument signature uses activeStorageUserId
      const keySingle = getScopedStorageKey('settings');
      expect(keySingle).toBe(`carefold_${USER_A}_settings`);

      // Two-argument signature where arg1 is undefined: e.g. getScopedStorageKey(undefined, 'settings')
      // as called by loadSettings(userId) or saveSettings(..., userId) when userId is omitted!
      const keyDoubleUndefined = getScopedStorageKey(undefined, 'settings');
      
      // CHALLENGE: If keyDoubleUndefined is 'carefold_guest_settings', then calling
      // loadSettings() or saveSettings() without userId while logged in as User A
      // will write/read to GUEST namespace instead of User A's namespace!
      console.log('keyDoubleUndefined result:', keyDoubleUndefined);
      expect(keyDoubleUndefined).toBe(`carefold_${USER_A}_settings`);
    });

    it('1.3: User A logs in, saves settings with API key, clinical consent, and session; logs out; User B logs in', () => {
      // Step 1: User A logs in
      setStorageUserId(USER_A);

      // User A saves settings with a sensitive API key
      saveSettings({ keys: { openai: 'sk-secret-alice-key-12345' } }, USER_A);

      // User A grants clinical consent
      grantClinicalConsent('cardiology-guide', new Date(), USER_A);

      // User A saves a session
      saveSession({
        id: 'thread-alice-1',
        agentId: 'cardiology-guide',
        title: 'Alice Private Cardiology Consult',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        messageCount: 5,
      });

      // Step 2: User A logs out
      detachUserSession(USER_A);

      // Step 3: User B logs in
      setStorageUserId(USER_B);

      // Assert User B CANNOT see User A's API key
      const bobSettings = loadSettings(USER_B);
      expect(bobSettings.keys.openai).toBe('');

      // Assert User B CANNOT see User A's clinical consent
      const bobHasConsent = hasClinicalConsent('cardiology-guide', USER_B);
      expect(bobHasConsent).toBe(false);

      // Assert User B CANNOT access User A's session in the index
      const bobSession = getSession('thread-alice-1');
      expect(bobSession).toBeNull();
    });

    it('1.3b: Realistic UI flow: User A logs in, grants consent via UI (without explicit userId), logs out; User B logs in and checks consent', () => {
      // Step 1: User A logs in (auth.tsx calls setStorageUserId)
      setStorageUserId(USER_A);

      // In ChatClient.tsx / AgentDetailClient.tsx, the UI calls:
      // grantClinicalConsent(agentId) -- without passing userId!
      grantClinicalConsent('cardiology-guide');

      // Step 2: User A logs out (auth.tsx calls detachUserSession)
      detachUserSession(USER_A);

      // Step 3: User B logs in (auth.tsx calls setStorageUserId)
      setStorageUserId(USER_B);

      // In ChatClient.tsx, the UI checks:
      // hasClinicalConsent(selectedAgentId) -- without passing userId!
      const bobHasConsent = hasClinicalConsent('cardiology-guide');

      // FAILURE: Bob inherits Alice's consent because it fell back to guest/un-namespaced storage!
      expect(bobHasConsent).toBe(false);
    });

    it('1.4: Tests chat messages & active thread persistence scoping on shared device', () => {
      // In ChatClient.tsx, messages are persisted with:
      // localStorage.setItem(`carefold_msgs_${threadId}`, JSON.stringify(messages));
      // localStorage.setItem(`carefold_thread_${agentId}`, threadId);

      setStorageUserId(USER_A);
      const aliceThreadId = 'thread-alice-cardio-999';
      localStorage.setItem(`carefold_msgs_${aliceThreadId}`, JSON.stringify([{ role: 'user', content: 'Alice symptoms' }]));
      localStorage.setItem('carefold_thread_cardiology-guide', aliceThreadId);

      // User A logs out
      detachUserSession(USER_A);

      // CHALLENGE: Are raw carefold_msgs_* or carefold_thread_* keys left behind in localStorage?
      const remainingMsgs = localStorage.getItem(`carefold_msgs_${aliceThreadId}`);
      const remainingThread = localStorage.getItem('carefold_thread_cardiology-guide');

      console.log('Remaining raw msgs after detachUserSession:', remainingMsgs);
      console.log('Remaining raw thread after detachUserSession:', remainingThread);

      // If these remain, any user who opens the browser next will resume Alice's session!
      expect(remainingMsgs).toBeNull();
      expect(remainingThread).toBeNull();
    });
  });

  // ===========================================================================
  // Attack 2: Storage Quota Overflow & Private Browsing Resilience
  // ===========================================================================
  describe('Attack 2: Storage Quota Overflow & Private Browsing Resilience', () => {
    it('2.1: ScopedStorage handles QuotaExceededError on setItem gracefully', () => {
      const mockStorage = {
        getItem: vi.fn(),
        setItem: vi.fn().mockImplementation(() => {
          const err = new Error('QuotaExceededError: DOM Exception 22');
          err.name = 'QuotaExceededError';
          throw err;
        }),
        removeItem: vi.fn(),
        clear: vi.fn(),
        key: vi.fn(),
        length: 0,
      } as unknown as Storage;

      const store = new ScopedStorage({ userId: USER_A, storage: mockStorage });
      expect(() => {
        const result = store.setItem('overflow_key', 'large_payload');
        expect(result).toBe(false);
      }).not.toThrow();
    });

    it('2.2: Subsystem functions handle QuotaExceededError without crashing', () => {
      const originalSetItem = localStorage.setItem.bind(localStorage);
      vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
        const err = new Error('QuotaExceededError');
        err.name = 'QuotaExceededError';
        throw err;
      });

      // Test saveSettings
      expect(() => {
        saveSettings({ provider: 'ollama' }, USER_A);
      }).not.toThrow();

      // Test grantClinicalConsent
      expect(() => {
        grantClinicalConsent('derma-guide', new Date(), USER_A);
      }).not.toThrow();

      // Test saveSession
      expect(() => {
        saveSession({
          id: 'th-overflow',
          agentId: 'derma-guide',
          title: 'Derma Consult',
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          messageCount: 1,
        });
      }).not.toThrow();

      // Test saveChecklist
      expect(() => {
        saveChecklist('th-overflow', 'msg-1', [{ id: '1', text: 'Task', completed: false }], USER_A);
      }).not.toThrow();

      // Test setSessionMemoryPaused
      expect(() => {
        setSessionMemoryPaused(true, USER_A);
      }).not.toThrow();

      vi.spyOn(localStorage, 'setItem').mockImplementation(originalSetItem);
    });

    it('2.3: Private browsing SecurityError on all storage access is handled safely', () => {
      vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
        throw new Error('SecurityError: The operation is insecure.');
      });
      vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
        throw new Error('SecurityError: The operation is insecure.');
      });
      vi.spyOn(sessionStorage, 'getItem').mockImplementation(() => {
        throw new Error('SecurityError: The operation is insecure.');
      });
      vi.spyOn(sessionStorage, 'setItem').mockImplementation(() => {
        throw new Error('SecurityError: The operation is insecure.');
      });

      // ScopedStorage
      const store = new ScopedStorage({ userId: USER_A });
      expect(store.getItem('key', 'defaultVal')).toBe('defaultVal');
      expect(store.setItem('key', 'val')).toBe(false);

      // Subsystems
      expect(loadSettings(USER_A)).toEqual(DEFAULT_USER_SETTINGS);
      expect(loadClinicalConsents(USER_A)).toEqual({});
      expect(hasClinicalConsent('cardiology-guide', USER_A)).toBe(false);
      expect(listSessions()).toEqual([]);
      expect(loadChecklist('t1', 'm1', ['Q1'], USER_A)).toEqual([{ id: 'init-0', text: 'Q1', completed: false }]);
      expect(isSessionMemoryPaused(USER_A)).toBe(false);
    });
  });

  // ===========================================================================
  // Attack 3: Corrupted Non-JSON Strings in Storage Keys
  // ===========================================================================
  describe('Attack 3: Corrupted Non-JSON Strings in Storage Keys', () => {
    it('3.1: ScopedStorage returns raw string for corrupted non-JSON content', () => {
      localStorage.setItem(`carefold_${USER_A}_broken`, 'MALFORMED{{{JSON');
      const store = new ScopedStorage({ userId: USER_A });
      expect(store.getItem('broken')).toBe('MALFORMED{{{JSON');
    });

    it('3.2: Settings gracefully falls back to default on corrupted JSON', () => {
      localStorage.setItem(`carefold_${USER_A}_user_settings_v1`, 'INVALID_SETTINGS_JSON: {[');
      const settings = loadSettings(USER_A);
      expect(settings).toEqual(DEFAULT_USER_SETTINGS);
    });

    it('3.3: Clinical Consent returns empty map on corrupted JSON or array payload', () => {
      localStorage.setItem(`carefold_${USER_A}_clinical_consent_v1`, 'CORRUPTED_STRING_NOT_JSON');
      expect(loadClinicalConsents(USER_A)).toEqual({});

      localStorage.setItem(`carefold_${USER_A}_clinical_consent_v1`, JSON.stringify(['not', 'an', 'object']));
      expect(loadClinicalConsents(USER_A)).toEqual({});
    });

    it('3.4: Session history handles corrupted index JSON by returning empty list', () => {
      localStorage.setItem(`carefold_${USER_A}_threads_index_v1`, 'MALFORMED_THREADS_INDEX{');
      localStorage.setItem(CAREFOLD_THREADS_INDEX_KEY, 'MALFORMED_THREADS_INDEX{');
      expect(listSessions()).toEqual([]);
    });

    it('3.5: Checklist storage handles corrupted JSON by returning initial fallback', () => {
      const key = getChecklistKey('th-1', 'msg-1', USER_A);
      localStorage.setItem(key, 'MALFORMED_CHECKLIST_JSON');
      const loaded = loadChecklist('th-1', 'msg-1', ['Question 1'], USER_A);
      expect(loaded).toEqual([{ id: 'init-0', text: 'Question 1', completed: false }]);
    });
  });

  // ===========================================================================
  // Attack 4: Single-User Desktop Workflow in Disabled Auth Mode
  // ===========================================================================
  describe('Attack 4: Single-User Desktop Workflow in Disabled Auth Mode', () => {
    it('4.1: Guest / default steward mode operates transparently with null/undefined userId', () => {
      setStorageUserId(null);

      // Writes in guest mode
      const saved = saveSettings({ provider: 'ollama', model: 'llama3.2' }, null);
      expect(saved.provider).toBe('ollama');

      // Dual-write ensures both carefold_guest_user_settings_v1 and legacy key are written
      expect(localStorage.getItem('carefold_guest_user_settings_v1')).not.toBeNull();
      expect(localStorage.getItem(CAREFOLD_SETTINGS_STORAGE_KEY)).not.toBeNull();

      // Read back
      const loaded = loadSettings(null);
      expect(loaded.provider).toBe('ollama');
      expect(loaded.model).toBe('llama3.2');
    });

    it('4.2: DEFAULT_STEWARD_USER is valid and can be used as effective storage user', () => {
      expect(DEFAULT_STEWARD_USER.id).toBe('00000000-0000-0000-0000-000000000000');
      setStorageUserId(DEFAULT_STEWARD_USER.id);

      const store = new ScopedStorage({ userId: DEFAULT_STEWARD_USER.id });
      store.setItem('steward_note', 'Local single-user desktop run');

      expect(localStorage.getItem(`carefold_${DEFAULT_STEWARD_USER.id}_steward_note`)).toBe('Local single-user desktop run');
      expect(store.getItem('steward_note')).toBe('Local single-user desktop run');
    });
  });
});
