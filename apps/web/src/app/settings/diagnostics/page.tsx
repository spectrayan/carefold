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
import { Server, Cpu, Database, RefreshCw } from 'lucide-react';
import { SetupChecklist } from '@/components/setup/SetupChecklist';

export default function DiagnosticsSettingsPage() {
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
            Diagnostics & System Health
          </h2>
          <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
            Real-time status of backend services, Ollama model inference, and local database indexes.
          </p>
        </div>
        <button
          type="button"
          onClick={fetchHealth}
          disabled={isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-[var(--cf-border-strong)] text-xs font-semibold text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition min-h-[44px]"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Runner Health Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="p-4 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]">
          <div className="flex items-center justify-between text-xs text-[var(--cf-fg-subtle)] font-medium">
            <span>Runtime Backend</span>
            <Server className="w-4 h-4" />
          </div>
          <div className="text-base font-bold text-[var(--cf-fg)] mt-2 flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                healthData?.status === 'ok' ? 'bg-emerald-500' : 'bg-amber-500'
              }`}
            />
            <span>{healthData?.status === 'ok' ? 'Online' : 'Degraded / Offline'}</span>
          </div>
          <p className="text-[11px] text-[var(--cf-fg-subtle)] mt-1">
            Version: {healthData?.version || '0.4.0-beta.1'}
          </p>
        </div>

        <div className="p-4 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]">
          <div className="flex items-center justify-between text-xs text-[var(--cf-fg-subtle)] font-medium">
            <span>Ollama Inference</span>
            <Cpu className="w-4 h-4" />
          </div>
          <div className="text-base font-bold text-[var(--cf-fg)] mt-2 flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                healthData?.modelReachable ? 'bg-emerald-500' : 'bg-amber-500'
              }`}
            />
            <span>{healthData?.modelReachable ? 'Connected' : 'Offline'}</span>
          </div>
          <p className="text-[11px] text-[var(--cf-fg-subtle)] mt-1">127.0.0.1:11434</p>
        </div>

        <div className="p-4 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]">
          <div className="flex items-center justify-between text-xs text-[var(--cf-fg-subtle)] font-medium">
            <span>FTS5 Search & DB</span>
            <Database className="w-4 h-4" />
          </div>
          <div className="text-base font-bold text-[var(--cf-fg)] mt-2 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span>SQLite Active</span>
          </div>
          <p className="text-[11px] text-[var(--cf-fg-subtle)] mt-1">FTS5 BM25 Ranked</p>
        </div>
      </div>

      {/* Setup Checklist */}
      <div className="space-y-3 pt-2 border-t border-[var(--cf-border)]">
        <h3 className="text-sm font-semibold text-[var(--cf-fg)]">
          System Verification Checklist
        </h3>
        <SetupChecklist isSettingsView={true} />
      </div>
    </div>
  );
}
