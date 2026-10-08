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
import { X, Sparkles } from 'lucide-react';
import { isSetupComplete, markSetupComplete } from '@/lib/setup';
import { SetupChecklist } from './SetupChecklist';

export function FirstRunSetupCard() {
  const [mounted, setMounted] = useState(false);
  const [isDismissed, setIsDismissed] = useState(false);

  useEffect(() => {
    setMounted(true);
    setIsDismissed(isSetupComplete());

    const handleSetupChanged = (e: Event) => {
      const customEvent = e as CustomEvent<{ status: string | null }>;
      if (customEvent.detail?.status) {
        setIsDismissed(true);
      } else {
        setIsDismissed(false);
      }
    };

    window.addEventListener('carefold:setup-changed', handleSetupChanged);
    return () => {
      window.removeEventListener('carefold:setup-changed', handleSetupChanged);
    };
  }, []);

  const handleDismiss = () => {
    markSetupComplete('true');
    setIsDismissed(true);
  };

  // Prevent hydration mismatch
  if (!mounted || isDismissed) {
    return null;
  }

  return (
    <aside
      data-testid="first-run-setup-card"
      aria-label="Carefold first-run setup checklist"
      className="bg-white dark:bg-zinc-900 border border-emerald-200 dark:border-emerald-800/80 rounded-2xl p-5 sm:p-6 shadow-sm transition-all"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 flex items-center justify-center shrink-0">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm sm:text-base font-bold text-slate-900 dark:text-zinc-100">
              Welcome to Carefold — First-Run Setup Check
            </h2>
            <p className="text-xs text-slate-500 dark:text-zinc-400">
              Verify local backend and Ollama connectivity before starting clinical visit preparation.
            </p>
          </div>
        </div>

        <button
          type="button"
          data-testid="dismiss-setup-card"
          aria-label="Skip setup checklist for now"
          onClick={handleDismiss}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800 transition cursor-pointer shrink-0"
        >
          <span className="hidden sm:inline">Skip for now</span>
          <X className="w-4 h-4" />
        </button>
      </div>

      <SetupChecklist isSettingsView={false} onDismiss={handleDismiss} />
    </aside>
  );
}
