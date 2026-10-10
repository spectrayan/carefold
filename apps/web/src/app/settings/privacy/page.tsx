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

'use client';

import React, { useState, useEffect } from 'react';
import {
  ShieldAlert,
  AlertTriangle,
  Brain,
  HardDrive
} from 'lucide-react';
import {
  type CarefoldUserSettings,
  DEFAULT_USER_SETTINGS,
  loadSettings,
  getBrowserStorageSummary,
  deleteAllConversations,
  deleteCurrentConversation,
  clearStoredApiKeys,
  type BrowserStorageSummary
} from '@/lib/settings';
import { withdrawAllClinicalConsents, withdrawClinicalConsent } from '@/lib/clinicalConsent';
import { useClinicalConsents } from '@/lib/useClinicalConsents';
import { MemoryManagementPanel } from '@/components/memory/MemoryManagementPanel';

export default function PrivacySettingsPage() {
  const [settings, setSettings] = useState<CarefoldUserSettings>(DEFAULT_USER_SETTINGS);
  const [storageSummary, setStorageSummary] = useState<BrowserStorageSummary>({
    conversationCount: 0,
    approximateSizeBytes: 0,
    formattedSize: '0 B',
    hasStoredApiKeys: false,
    storedKeyProviders: []
  });
  const [confirmModalAction, setConfirmModalAction] = useState<'deleteAll' | 'deleteCurrent' | 'clearKeys' | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const { consents } = useClinicalConsents();

  useEffect(() => {
    const loaded = loadSettings();
    setSettings(loaded);
    setStorageSummary(getBrowserStorageSummary(loaded));
  }, []);

  const consentEntries = Object.entries(consents);

  const handleExecuteConfirmedAction = () => {
    if (confirmModalAction === 'deleteAll') {
      const res = deleteAllConversations();
      setStorageSummary(getBrowserStorageSummary(settings));
      setFeedbackMessage(
        res.deletedCount === 1
          ? '1 conversation deleted from browser'
          : `${res.deletedCount} conversations deleted from browser`
      );
    } else if (confirmModalAction === 'deleteCurrent') {
      deleteCurrentConversation();
      setStorageSummary(getBrowserStorageSummary(settings));
      setFeedbackMessage('Current conversation deleted from browser');
    } else if (confirmModalAction === 'clearKeys') {
      clearStoredApiKeys();
      const refreshed = loadSettings();
      setSettings(refreshed);
      setStorageSummary(getBrowserStorageSummary(refreshed));
      setFeedbackMessage('Saved API keys removed from browser');
    }
    setConfirmModalAction(null);
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-bold text-[var(--cf-fg)] tracking-tight">
          Privacy, Consent & Data Settings
        </h2>
        <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
          Review on-device data sovereignty, clinical consents, and manage local browser data.
        </p>
      </div>

      {feedbackMessage && (
        <div className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800 text-xs text-emerald-800 dark:text-emerald-300 font-semibold flex items-center justify-between">
          <span>{feedbackMessage}</span>
          <button
            type="button"
            onClick={() => setFeedbackMessage(null)}
            className="text-xs underline hover:no-underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Section 1: Clinical Assist Consent (#87) */}
      <div data-testid="clinical-consent-settings" className="space-y-3 pb-6 border-b border-[var(--cf-border)]">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-amber-600 dark:text-amber-400" />
            <span>Clinical Assist Consents</span>
          </h3>
          {consentEntries.length > 1 && (
            <button
              type="button"
              data-testid="withdraw-all-clinical-consent"
              onClick={() => withdrawAllClinicalConsents()}
              className="text-xs font-semibold text-rose-700 dark:text-rose-400 hover:underline min-h-[36px]"
            >
              Withdraw all
            </button>
          )}
        </div>
        <p className="text-xs text-[var(--cf-fg-muted)]">
          Clinical prep helpers only run after you give explicit consent. Withdrawing consent takes effect on your next message.
        </p>
        {consentEntries.length === 0 ? (
          <p data-testid="clinical-consent-empty" className="text-xs text-[var(--cf-fg-subtle)] italic py-2">
            You have not given consent to any clinical assist agents.
          </p>
        ) : (
          <ul className="space-y-2">
            {consentEntries.map(([agentId, record]) => (
              <li
                key={agentId}
                data-testid={`clinical-consent-entry-${agentId}`}
                className="flex items-center justify-between gap-3 p-3 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] text-xs"
              >
                <div className="min-w-0">
                  <div className="font-semibold text-[var(--cf-fg)] truncate capitalize">
                    {agentId.replace(/-/g, ' ')}
                  </div>
                  <div className="text-[11px] text-[var(--cf-fg-subtle)]">
                    Consent given {new Date(record.grantedAt).toLocaleString()}
                  </div>
                </div>
                <button
                  type="button"
                  data-testid={`withdraw-clinical-consent-${agentId}`}
                  aria-label={`Withdraw consent for ${agentId}`}
                  onClick={() => withdrawClinicalConsent(agentId)}
                  className="shrink-0 px-3 py-1.5 rounded-lg border border-rose-200 dark:border-rose-900/60 text-rose-700 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-xs font-semibold transition min-h-[36px]"
                >
                  Withdraw
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Section 2: Browser Storage & Data Purge (#92) */}
      <div data-testid="storage-overview-card" className="space-y-4 pb-6 border-b border-[var(--cf-border)]">
        <div>
          <h3 className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-[var(--cf-fg-subtle)]" />
            <span>Local Browser Data & Storage</span>
          </h3>
          <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
            Data is stored in your web browser. You can clear conversations or remove saved keys at any time.
          </p>
        </div>

        {/* Storage Stats Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="p-3.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]">
            <div className="text-[11px] font-semibold text-[var(--cf-fg-subtle)] uppercase tracking-wider">
              Stored Conversations
            </div>
            <div data-testid="stored-conversations-stat" className="text-lg font-bold text-[var(--cf-fg)] mt-1">
              {storageSummary.conversationCount}{' '}
              <span className="text-xs font-normal text-[var(--cf-fg-subtle)]">
                ({storageSummary.formattedSize})
              </span>
            </div>
          </div>

          <div className="p-3.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]">
            <div className="text-[11px] font-semibold text-[var(--cf-fg-subtle)] uppercase tracking-wider">
              Saved API Keys
            </div>
            <div data-testid="stored-keys-stat" className="text-lg font-bold text-[var(--cf-fg)] mt-1">
              {storageSummary.hasStoredApiKeys ? storageSummary.storedKeyProviders.length : 'None'}{' '}
              <span className="text-xs font-normal text-[var(--cf-fg-subtle)]">
                {storageSummary.hasStoredApiKeys ? `(${storageSummary.storedKeyProviders.join(', ')})` : ''}
              </span>
            </div>
          </div>
        </div>

        {/* Data Purge Actions */}
        <div className="flex flex-col sm:flex-row flex-wrap gap-2.5 pt-2">
          <button
            type="button"
            data-testid="delete-current-conversation-btn"
            onClick={() => setConfirmModalAction('deleteCurrent')}
            className="px-3.5 py-2 rounded-xl border border-[var(--cf-border-strong)] text-xs font-semibold text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition min-h-[44px]"
          >
            Delete current conversation
          </button>
          <button
            type="button"
            data-testid="clear-conversations-btn"
            onClick={() => setConfirmModalAction('deleteAll')}
            className="px-3.5 py-2 rounded-xl border border-rose-200 dark:border-rose-900/60 text-xs font-semibold text-rose-700 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition min-h-[44px]"
          >
            Clear all conversations
          </button>
          <button
            type="button"
            data-testid="clear-api-keys-btn"
            onClick={() => setConfirmModalAction('clearKeys')}
            className="px-3.5 py-2 rounded-xl border border-amber-200 dark:border-amber-900/60 text-xs font-semibold text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-950/40 transition min-h-[44px]"
          >
            Clear saved API keys
          </button>
        </div>
      </div>

      {/* Section 3: What Carefold Remembers (Episodic Memory Management) */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
          <Brain className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          <span>Episodic Memory Telemetry</span>
        </h3>
        <p className="text-xs text-[var(--cf-fg-muted)]">
          Inspect, modify, or purge what Carefold recalls across consultation sessions.
        </p>
        <div className="p-4 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)]">
          <MemoryManagementPanel />
        </div>
      </div>

      {/* Confirmation Dialog */}
      {confirmModalAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="p-6 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-xl max-w-sm w-full space-y-4">
            <div className="flex items-center gap-2.5 text-amber-600 dark:text-amber-400">
              <AlertTriangle className="w-5 h-5" />
              <h4 className="text-sm font-bold text-[var(--cf-fg)]">Confirm Data Deletion</h4>
            </div>
            <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed">
              {confirmModalAction === 'deleteAll'
                ? 'Are you sure you want to delete all saved conversations from this browser? This action cannot be undone.'
                : confirmModalAction === 'deleteCurrent'
                ? 'Are you sure you want to delete the active conversation?'
                : 'Are you sure you want to remove all saved cloud API keys from this browser?'}
            </p>
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setConfirmModalAction(null)}
                className="px-4 py-2 text-xs font-semibold rounded-xl border border-[var(--cf-border)] text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] min-h-[44px]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleExecuteConfirmedAction}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-rose-600 text-white hover:bg-rose-700 min-h-[44px]"
              >
                Confirm Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
