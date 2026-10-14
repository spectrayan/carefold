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

'use client';

import React, { useState, useEffect } from 'react';
import { Server, Cpu, Database, RefreshCw } from 'lucide-react';
import { SetupChecklist } from '@/components/setup/SetupChecklist';
import { useI18n } from '@/i18n';

export default function DiagnosticsSettingsPage() {
  const { t } = useI18n();
  const [healthData, setHealthData] = useState<{
    status?: string;
    version?: string;
    modelReachable?: boolean;
    uptime?: number;
  } | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchHealth = async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/v1/health');
      if (res.ok) {
        const data = await res.json();
        setHealthData(data);
      }
    } catch {
      setHealthData(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
  }, []);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-[var(--cf-fg)] tracking-tight">
            {t('settings.diagnostics.title')}
          </h2>
          <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
            {t('settings.diagnostics.subtitle')}
          </p>
        </div>
        <button
          type="button"
          onClick={fetchHealth}
          disabled={isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-[var(--cf-border-strong)] text-xs font-semibold text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition min-h-[44px]"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          <span>{t('settings.diagnostics.refresh')}</span>
        </button>
      </div>

      {/* Runner Health Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="p-4 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]">
          <div className="flex items-center justify-between text-xs text-[var(--cf-fg-subtle)] font-medium">
            <span>{t('settings.diagnostics.runtime_backend')}</span>
            <Server className="w-4 h-4" />
          </div>
          <div className="text-base font-bold text-[var(--cf-fg)] mt-2 flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                healthData?.status === 'ok' ? 'bg-emerald-500' : 'bg-amber-500'
              }`}
            />
            <span>{healthData?.status === 'ok' ? t('settings.diagnostics.online') : t('settings.diagnostics.degraded')}</span>
          </div>
          <p className="text-xs text-[var(--cf-fg-subtle)] mt-1">
            {t('settings.diagnostics.version', { version: healthData?.version || '0.4.0-beta.1' })}
          </p>
        </div>

        <div className="p-4 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]">
          <div className="flex items-center justify-between text-xs text-[var(--cf-fg-subtle)] font-medium">
            <span>{t('settings.diagnostics.ollama_inference')}</span>
            <Cpu className="w-4 h-4" />
          </div>
          <div className="text-base font-bold text-[var(--cf-fg)] mt-2 flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                healthData?.modelReachable ? 'bg-emerald-500' : 'bg-amber-500'
              }`}
            />
            <span>{healthData?.modelReachable ? t('settings.diagnostics.connected') : t('settings.diagnostics.offline')}</span>
          </div>
          <p className="text-xs text-[var(--cf-fg-subtle)] mt-1">127.0.0.1:11434</p>
        </div>

        <div className="p-4 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]">
          <div className="flex items-center justify-between text-xs text-[var(--cf-fg-subtle)] font-medium">
            <span>{t('settings.diagnostics.fts5_search')}</span>
            <Database className="w-4 h-4" />
          </div>
          <div className="text-base font-bold text-[var(--cf-fg)] mt-2 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span>{t('settings.diagnostics.sqlite_active')}</span>
          </div>
          <p className="text-xs text-[var(--cf-fg-subtle)] mt-1">{t('settings.diagnostics.fts5_ranked')}</p>
        </div>
      </div>

      {/* Setup Checklist */}
      <div className="space-y-3 pt-2 border-t border-[var(--cf-border)]">
        <h3 className="text-sm font-semibold text-[var(--cf-fg)]">
          {t('settings.diagnostics.checklist_title')}
        </h3>
        <SetupChecklist isSettingsView={true} />
      </div>
    </div>
  );
}
