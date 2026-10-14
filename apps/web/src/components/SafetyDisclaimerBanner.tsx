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
import { ShieldCheck, X } from 'lucide-react';

const BANNER_STORAGE_KEY = 'carefold_safety_banner_dismissed';

export function SafetyDisclaimerBanner() {
  const [isDismissed, setIsDismissed] = useState(false);

  useEffect(() => {
    try {
      if (typeof window !== 'undefined' && window.sessionStorage) {
        if (sessionStorage.getItem(BANNER_STORAGE_KEY) === 'true') {
          setIsDismissed(true);
        }
      }
    } catch {
      // Ignore storage access errors
    }
  }, []);

  const handleDismiss = () => {
    setIsDismissed(true);
    try {
      if (typeof window !== 'undefined' && window.sessionStorage) {
        sessionStorage.setItem(BANNER_STORAGE_KEY, 'true');
      }
    } catch {
      // Ignore storage access errors
    }
  };

  if (isDismissed) {
    return null;
  }

  return (
    <aside
      data-testid="safety-disclaimer-banner"
      aria-label="Safety Disclaimer"
      className="bg-stone-100 dark:bg-slate-900 text-slate-700 dark:text-slate-300 px-4 py-1.5 text-xs border-b border-stone-200 dark:border-slate-800 transition-colors"
    >
      <div
        data-testid="safety-disclaimer-header"
        className="max-w-7xl mx-auto w-full min-w-0 flex flex-wrap items-center justify-between gap-2"
      >
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-400 shrink-0" aria-hidden="true" />
          <span>
            <strong className="font-semibold text-slate-800 dark:text-slate-200">
              Wellness and care navigation support — not diagnosis or treatment.
            </strong>{' '}
            <span>In an emergency, call 911.</span>
          </span>
          <details data-testid="safety-disclaimer-learn-more" className="inline-block">
            <summary className="cursor-pointer font-semibold text-emerald-700 dark:text-emerald-400 hover:underline select-none">
              Learn more
            </summary>
            <p className="mt-1 text-xs text-slate-600 dark:text-slate-400 leading-relaxed max-w-2xl">
              Carefold helpers organize questions, checklists, and health records locally on your device. They cannot diagnose conditions, adjust medication dosages, or replace a licensed clinician.
            </p>
          </details>
        </div>
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Dismiss safety disclaimer"
          data-testid="dismiss-safety-disclaimer"
          className="p-1.5 min-w-[32px] min-h-[32px] flex items-center justify-center rounded-md text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-stone-200/60 dark:hover:bg-slate-800 transition cursor-pointer shrink-0"
          title="Dismiss notice"
        >
          <X className="w-3.5 h-3.5" aria-hidden="true" />
        </button>
      </div>
    </aside>
  );
}

export const DisclaimerHeader = SafetyDisclaimerBanner;
