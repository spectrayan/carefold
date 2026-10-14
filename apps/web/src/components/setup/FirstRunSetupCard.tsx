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
import { X, Sparkles } from 'lucide-react';
import { isSetupComplete, markSetupComplete } from '@/lib/setup';
import { SetupChecklist } from './SetupChecklist';

export interface FirstRunSetupCardProps {
  status?: 'READY' | 'ACTION_REQUIRED' | 'DEGRADED';
}

export function FirstRunSetupCard({ status }: FirstRunSetupCardProps = {}) {
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

      <SetupChecklist isSettingsView={false} initialStatus={status} onDismiss={handleDismiss} />
    </aside>
  );
}
