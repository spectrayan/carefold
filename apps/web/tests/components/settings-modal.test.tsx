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
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { SettingsModal } from '@/components/SettingsModal';
import {
  DEFAULT_USER_SETTINGS,
  CAREFOLD_SETTINGS_STORAGE_KEY,
  type CarefoldUserSettings,
  getBrowserStorageSummary,
  formatStorageSize,
  deleteCurrentConversation,
  deleteAllConversations,
  clearStoredApiKeys
} from '@/lib/settings';

describe('SettingsModal Component', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('does not render dialog in DOM when isOpen is false', () => {
    render(
      <SettingsModal
        isOpen={false}
        onClose={vi.fn()}
        initialSettings={DEFAULT_USER_SETTINGS}
      />
    );

    expect(screen.queryByTestId('settings-modal')).not.toBeInTheDocument();
  });

  it('renders accessible dialog with privacy guarantee when isOpen is true', () => {
    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        initialSettings={DEFAULT_USER_SETTINGS}
      />
    );

    const dialog = screen.getByTestId('settings-modal');
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute('role', 'dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');

    expect(screen.getByTestId('privacy-notice')).toHaveTextContent('Local-First Privacy Guarantee');
  });

  it('pre-fills input fields with provided settings', () => {
    const existingSettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      keys: {
        google: 'AIzaSyExistingKey',
        anthropic: 'sk-ant-existing',
        openai: 'sk-proj-existing',
        custom: 'custom-tok'
      },
      endpoints: {
        ollamaUrl: 'http://localhost:11434',
        customUrl: 'http://localhost:8000/v1'
      }
    };

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        initialSettings={existingSettings}
      />
    );

    expect(screen.getByTestId('ollama-url-input')).toHaveValue('http://localhost:11434');
    expect(screen.getByTestId('gemini-key-input')).toHaveValue('AIzaSyExistingKey');
    expect(screen.getByTestId('anthropic-key-input')).toHaveValue('sk-ant-existing');
    expect(screen.getByTestId('openai-key-input')).toHaveValue('sk-proj-existing');
    expect(screen.getByTestId('custom-url-input')).toHaveValue('http://localhost:8000/v1');
    expect(screen.getByTestId('custom-key-input')).toHaveValue('custom-tok');
  });

  it('toggles password visibility when eye icon button is clicked', () => {
    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        initialSettings={DEFAULT_USER_SETTINGS}
      />
    );

    const geminiInput = screen.getByTestId('gemini-key-input');
    const toggleBtn = screen.getByTestId('toggle-gemini-key');

    // Initially masked
    expect(geminiInput).toHaveAttribute('type', 'password');

    // Click to show
    fireEvent.click(toggleBtn);
    expect(geminiInput).toHaveAttribute('type', 'text');

    // Click again to hide
    fireEvent.click(toggleBtn);
    expect(geminiInput).toHaveAttribute('type', 'password');
  });

  it('saves updated settings to localStorage and triggers onSave callback', () => {
    const handleSave = vi.fn();
    const handleClose = vi.fn();

    render(
      <SettingsModal
        isOpen={true}
        onClose={handleClose}
        initialSettings={DEFAULT_USER_SETTINGS}
        onSave={handleSave}
      />
    );

    const geminiInput = screen.getByTestId('gemini-key-input');
    fireEvent.change(geminiInput, { target: { value: 'AIzaSyNewSavedKey123' } });

    const saveBtn = screen.getByTestId('save-settings-btn');
    fireEvent.click(saveBtn);

    // Verify onSave invoked
    expect(handleSave).toHaveBeenCalledWith(
      expect.objectContaining({
        keys: expect.objectContaining({
          google: 'AIzaSyNewSavedKey123'
        })
      })
    );

    // Verify localStorage persistence
    const savedRaw = localStorage.getItem(CAREFOLD_SETTINGS_STORAGE_KEY);
    expect(savedRaw).toBeTruthy();
    expect(JSON.parse(savedRaw!).keys.google).toBe('AIzaSyNewSavedKey123');

    // Verify success banner visible
    expect(screen.getByTestId('save-success-badge')).toBeInTheDocument();
  });

  it('calls onClose without saving when cancel button is clicked', () => {
    const handleClose = vi.fn();
    const handleSave = vi.fn();

    render(
      <SettingsModal
        isOpen={true}
        onClose={handleClose}
        initialSettings={DEFAULT_USER_SETTINGS}
        onSave={handleSave}
      />
    );

    const cancelBtn = screen.getByTestId('cancel-settings-btn');
    fireEvent.click(cancelBtn);

    expect(handleClose).toHaveBeenCalledTimes(1);
    expect(handleSave).not.toHaveBeenCalled();
    expect(localStorage.getItem(CAREFOLD_SETTINGS_STORAGE_KEY)).toBeNull();
  });

  it('closes modal when Escape key is pressed', () => {
    const handleClose = vi.fn();

    render(
      <SettingsModal
        isOpen={true}
        onClose={handleClose}
        initialSettings={DEFAULT_USER_SETTINGS}
      />
    );

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  describe('Privacy & Browser Data Settings (#92)', () => {
    it('renders privacy & browser data section with storage summary metrics and browser-only notice', () => {
      localStorage.setItem('carefold_msgs_thread-1', JSON.stringify([{ role: 'user', content: 'test symptoms' }]));
      localStorage.setItem('carefold_thread_cardiology-guide', 'thread-1');
      localStorage.setItem('carefold_theme', 'dark');
      localStorage.setItem('carefold_clinical_consents_v1', JSON.stringify({ 'cardiology-guide': '2026-10-07T00:00:00Z' }));

      const settingsWithKeys: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        keys: {
          google: 'AIzaSyGoogleKey',
          anthropic: '',
          openai: '',
          custom: ''
        }
      };

      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={settingsWithKeys}
        />
      );

      const privacySection = screen.getByTestId('privacy-data-section');
      expect(privacySection).toBeInTheDocument();
      expect(screen.getByText(/Privacy & Browser Data/i)).toBeInTheDocument();
      expect(privacySection).toHaveTextContent(/This clears browser data only/i);

      const convStat = screen.getByTestId('stored-conversations-stat');
      expect(convStat).toBeInTheDocument();
      expect(convStat).toHaveTextContent(/1 session/i);

      const keyStat = screen.getByTestId('stored-keys-stat');
      expect(keyStat).toBeInTheDocument();
      expect(keyStat).toHaveTextContent(/Google Gemini/i);
    });

    it('prompts confirmation dialog when clear conversations is clicked and cancels safely', () => {
      localStorage.setItem('carefold_msgs_thread-1', JSON.stringify([{ role: 'user', content: 'test symptoms' }]));
      localStorage.setItem('carefold_thread_cardiology-guide', 'thread-1');

      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={DEFAULT_USER_SETTINGS}
        />
      );

      const clearBtn = screen.getByTestId('clear-conversations-btn');
      expect(clearBtn).toBeInTheDocument();
      fireEvent.click(clearBtn);

      const confirmDialog = screen.getByRole('alertdialog');
      expect(confirmDialog).toBeInTheDocument();
      expect(confirmDialog).toHaveAttribute('aria-modal', 'true');
      expect(confirmDialog).toHaveTextContent(/Delete all conversations/i);
      expect(confirmDialog).toHaveTextContent(/This clears browser data only/i);

      // Cancel button inside alertdialog
      const cancelBtn = screen.getByTestId('confirm-cancel-btn');
      expect(cancelBtn).toBeInTheDocument();
      fireEvent.click(cancelBtn);

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(localStorage.getItem('carefold_msgs_thread-1')).not.toBeNull();
      expect(localStorage.getItem('carefold_thread_cardiology-guide')).not.toBeNull();
    });

    it('wipes all conversation records from localStorage and dispatches event on confirm', () => {
      localStorage.setItem('carefold_msgs_thread-1', JSON.stringify([{ role: 'user', content: 'test 1' }]));
      localStorage.setItem('carefold_msgs_thread-2', JSON.stringify([{ role: 'user', content: 'test 2' }]));
      localStorage.setItem('carefold_thread_cardiology-guide', 'thread-1');
      localStorage.setItem('carefold_thread_derma-guide', 'thread-2');
      localStorage.setItem('carefold_theme', 'dark');
      localStorage.setItem('carefold_clinical_consents_v1', JSON.stringify({ 'cardiology-guide': '2026-10-07T00:00:00Z' }));

      const clearedListener = vi.fn();
      window.addEventListener('carefold:conversations-cleared', clearedListener);

      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={DEFAULT_USER_SETTINGS}
        />
      );

      fireEvent.click(screen.getByTestId('clear-conversations-btn'));
      const destructiveBtn = screen.getByTestId('confirm-destructive-btn');
      fireEvent.click(destructiveBtn);

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(clearedListener).toHaveBeenCalledTimes(1);

      // Conversations purged
      expect(localStorage.getItem('carefold_msgs_thread-1')).toBeNull();
      expect(localStorage.getItem('carefold_msgs_thread-2')).toBeNull();
      expect(localStorage.getItem('carefold_thread_cardiology-guide')).toBeNull();
      expect(localStorage.getItem('carefold_thread_derma-guide')).toBeNull();

      // Preferences preserved
      expect(localStorage.getItem('carefold_theme')).toBe('dark');
      expect(localStorage.getItem('carefold_clinical_consents_v1')).not.toBeNull();

      // Feedback displayed
      expect(screen.getByTestId('privacy-action-feedback')).toHaveTextContent(/deleted/i);

      window.removeEventListener('carefold:conversations-cleared', clearedListener);
    });

    it('prompts confirmation and clears API keys while preserving other settings on confirm', () => {
      const initialSettings: CarefoldUserSettings = {
        provider: 'google',
        model: 'gemini-2.0-flash',
        customModelName: '',
        keys: {
          google: 'AIzaSyGoogleKey123',
          anthropic: 'sk-ant-test',
          openai: '',
          custom: ''
        },
        endpoints: {
          ollamaUrl: 'http://127.0.0.1:11434',
          customUrl: 'http://127.0.0.1:8000/v1'
        }
      };
      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify(initialSettings));

      const settingsChangedListener = vi.fn();
      window.addEventListener('carefold:settings-changed', settingsChangedListener);

      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={initialSettings}
        />
      );

      const clearKeysBtn = screen.getByTestId('clear-api-keys-btn');
      expect(clearKeysBtn).toBeInTheDocument();
      fireEvent.click(clearKeysBtn);

      const dialog = screen.getByRole('alertdialog');
      expect(dialog).toBeInTheDocument();
      expect(dialog).toHaveTextContent(/Remove saved API keys/i);

      fireEvent.click(screen.getByTestId('confirm-destructive-btn'));
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(settingsChangedListener).toHaveBeenCalledTimes(1);

      // Verify input fields cleared
      expect(screen.getByTestId('gemini-key-input')).toHaveValue('');
      expect(screen.getByTestId('anthropic-key-input')).toHaveValue('');

      // Verify localStorage preserves non-secret settings
      const savedRaw = localStorage.getItem(CAREFOLD_SETTINGS_STORAGE_KEY);
      expect(savedRaw).toBeTruthy();
      const saved = JSON.parse(savedRaw!);
      expect(saved.provider).toBe('google');
      expect(saved.model).toBe('gemini-2.0-flash');
      expect(saved.endpoints.ollamaUrl).toBe('http://127.0.0.1:11434');
      expect(saved.keys.google).toBe('');
      expect(saved.keys.anthropic).toBe('');

      window.removeEventListener('carefold:settings-changed', settingsChangedListener);
    });

    it('dismisses confirmation dialog on Escape key without executing action', () => {
      localStorage.setItem('carefold_msgs_thread-1', JSON.stringify([{ role: 'user', content: 'test' }]));

      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={DEFAULT_USER_SETTINGS}
        />
      );

      fireEvent.click(screen.getByTestId('clear-conversations-btn'));
      expect(screen.getByRole('alertdialog')).toBeInTheDocument();

      fireEvent.keyDown(window, { key: 'Escape' });
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(localStorage.getItem('carefold_msgs_thread-1')).not.toBeNull();
    });

    it('allows deleting current conversation when currentThreadId is passed', () => {
      localStorage.setItem('carefold_msgs_thread-current', JSON.stringify([{ role: 'user', content: 'current chat' }]));
      localStorage.setItem('carefold_msgs_thread-other', JSON.stringify([{ role: 'user', content: 'other chat' }]));
      localStorage.setItem('carefold_thread_cardiology-guide', 'thread-current');

      const deletedListener = vi.fn();
      window.addEventListener('carefold:conversation-deleted', deletedListener);

      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={DEFAULT_USER_SETTINGS}
          currentAgentId="cardiology-guide"
          currentThreadId="thread-current"
        />
      );

      const deleteCurrentBtn = screen.getByTestId('delete-current-conversation-btn');
      expect(deleteCurrentBtn).toBeInTheDocument();
      fireEvent.click(deleteCurrentBtn);

      const dialog = screen.getByRole('alertdialog');
      expect(dialog).toBeInTheDocument();
      expect(dialog).toHaveTextContent(/Delete current conversation/i);

      fireEvent.click(screen.getByTestId('confirm-destructive-btn'));
      expect(deletedListener).toHaveBeenCalledTimes(1);

      expect(localStorage.getItem('carefold_msgs_thread-current')).toBeNull();
      expect(localStorage.getItem('carefold_msgs_thread-other')).not.toBeNull();

      window.removeEventListener('carefold:conversation-deleted', deletedListener);
    });
  });

  describe('Storage Helper Functions & Edge Cases (#92)', () => {
    it('formatStorageSize formats 0, bytes, KB, and MB correctly', () => {
      expect(formatStorageSize(0)).toBe('0 B');
      expect(formatStorageSize(-10)).toBe('0 B');
      expect(formatStorageSize(500)).toBe('500 B');
      expect(formatStorageSize(1024)).toBe('1.0 KB');
      expect(formatStorageSize(2048)).toBe('2.0 KB');
      expect(formatStorageSize(1024 * 1024 * 2.5)).toBe('2.5 MB');
    });

    it('getBrowserStorageSummary correctly summarizes empty and populated storage', () => {
      const emptySummary = getBrowserStorageSummary(DEFAULT_USER_SETTINGS);
      expect(emptySummary.conversationCount).toBe(0);
      expect(emptySummary.approximateSizeBytes).toBe(0);
      expect(emptySummary.formattedSize).toBe('0 B');
      expect(emptySummary.hasStoredApiKeys).toBe(false);
      expect(emptySummary.storedKeyProviders).toEqual([]);

      localStorage.setItem('carefold_msgs_1', 'abc');
      localStorage.setItem('carefold_thread_1', 't1');

      const customSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        keys: {
          google: 'AIzaSy1',
          anthropic: 'sk-ant-1',
          openai: 'sk-proj-1',
          custom: 'tok-1'
        }
      };

      const populatedSummary = getBrowserStorageSummary(customSettings);
      expect(populatedSummary.conversationCount).toBe(1);
      expect(populatedSummary.approximateSizeBytes).toBeGreaterThan(0);
      expect(populatedSummary.hasStoredApiKeys).toBe(true);
      expect(populatedSummary.storedKeyProviders).toEqual([
        'Google Gemini',
        'Anthropic Claude',
        'OpenAI',
        'Custom'
      ]);
    });

    it('deleteCurrentConversation safely handles missing or non-matching thread keys', () => {
      expect(deleteCurrentConversation()).toBe(true);
      expect(deleteCurrentConversation('nonexistent-thread', 'nonexistent-agent')).toBe(true);

      localStorage.setItem('carefold_msgs_target', 'target msg');
      localStorage.setItem('carefold_thread_agent-a', 'target');
      deleteCurrentConversation('target', 'agent-a');

      expect(localStorage.getItem('carefold_msgs_target')).toBeNull();
      expect(localStorage.getItem('carefold_thread_agent-a')).toBeNull();
    });

    it('deleteAllConversations handles empty storage cleanly and reports 0 deleted', () => {
      const res = deleteAllConversations();
      expect(res.deletedCount).toBe(0);
    });

    it('clearStoredApiKeys preserves non-secret configuration and clears all keys', () => {
      const settingsWithCustomEndpoint: CarefoldUserSettings = {
        provider: 'custom',
        model: 'custom-model',
        customModelName: 'my-finetuned-llama',
        keys: {
          google: 'key1',
          anthropic: 'key2',
          openai: 'key3',
          custom: 'key4'
        },
        endpoints: {
          ollamaUrl: 'http://127.0.0.1:11434',
          customUrl: 'http://192.168.1.50:8000/v1'
        }
      };

      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify(settingsWithCustomEndpoint));

      const cleared = clearStoredApiKeys();
      expect(cleared.provider).toBe('custom');
      expect(cleared.model).toBe('custom-model');
      expect(cleared.customModelName).toBe('my-finetuned-llama');
      expect(cleared.endpoints.customUrl).toBe('http://192.168.1.50:8000/v1');
      expect(cleared.keys.google).toBe('');
      expect(cleared.keys.anthropic).toBe('');
      expect(cleared.keys.openai).toBe('');
      expect(cleared.keys.custom).toBe('');
    });
  });

  describe('Diagnostics Tab (#99)', () => {
    it('renders tab bar with Model & Providers and Diagnostics tabs', () => {
      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={DEFAULT_USER_SETTINGS}
        />
      );

      expect(screen.getByTestId('settings-tab-providers')).toBeInTheDocument();
      expect(screen.getByTestId('settings-tab-diagnostics')).toBeInTheDocument();
      expect(screen.getByTestId('settings-tab-providers')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByTestId('settings-tab-diagnostics')).toHaveAttribute('aria-selected', 'false');
    });

    it('switches to Diagnostics tab and renders SetupChecklist', () => {
      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={DEFAULT_USER_SETTINGS}
        />
      );

      fireEvent.click(screen.getByTestId('settings-tab-diagnostics'));

      expect(screen.getByTestId('settings-tab-diagnostics')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByTestId('settings-tab-providers')).toHaveAttribute('aria-selected', 'false');
      expect(screen.getByTestId('settings-diagnostics-panel')).toBeInTheDocument();
      expect(screen.getByTestId('setup-checklist')).toBeInTheDocument();
    });

    it('opens directly to Diagnostics tab when initialTab is diagnostics', () => {
      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={DEFAULT_USER_SETTINGS}
          initialTab="diagnostics"
        />
      );

      expect(screen.getByTestId('settings-tab-diagnostics')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByTestId('settings-diagnostics-panel')).toBeInTheDocument();
      expect(screen.getByTestId('setup-checklist')).toBeInTheDocument();
    });
  });
});
