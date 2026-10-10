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
import { AlertTriangle, ShieldCheck, X } from 'lucide-react';

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
      data-testid="safety-disclaimer-header"
      aria-label="Safety Disclaimer"
      className="bg-amber-500 text-slate-950 px-4 py-2 text-xs md:text-sm font-semibold shadow-sm border-b border-amber-600 flex items-center justify-between transition-all"
    >
      <div className="max-w-7xl mx-auto w-full min-w-0 flex items-center justify-center gap-2 text-center pl-6 sm:pl-0">
        <AlertTriangle className="w-4 h-4 text-slate-950 shrink-0" aria-hidden="true" />
        <span>
          <strong>Wellness / navigation / admin help — not diagnosis or treatment.</strong>{' '}
          <span className="hidden sm:inline font-normal text-slate-900">
            Carefold agents run locally and cannot prescribe medications or replace emergency care.
          </span>
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <div className="hidden md:flex items-center gap-1 text-xs font-medium bg-amber-400/80 px-2 py-0.5 rounded text-slate-900 border border-amber-600/30">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-800" />
          <span>Local-First Sandbox</span>
        </div>
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Dismiss safety disclaimer"
          data-testid="dismiss-safety-disclaimer"
          className="p-2 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-md text-slate-950 hover:bg-amber-600/40 active:scale-95 transition cursor-pointer"
          title="Dismiss banner"
        >
          <X className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>
    </aside>
  );
}

export const DisclaimerHeader = SafetyDisclaimerBanner;
