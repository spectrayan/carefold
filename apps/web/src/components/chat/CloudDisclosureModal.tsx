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

import React, { useEffect } from 'react';
import {
  ShieldAlert,
  Laptop,
  Globe,
  X
} from 'lucide-react';
import { PROVIDER_METADATA, type ProviderType } from '@/lib/settings';

export interface CloudDisclosureModalProps {
  isOpen: boolean;
  provider: ProviderType;
  model: string;
  onFallbackToLocal: () => void;
  onAuthorizeCloud: () => void;
  onCancel: () => void;
}

export function CloudDisclosureModal({
  isOpen,
  provider,
  model,
  onFallbackToLocal,
  onAuthorizeCloud,
  onCancel
}: CloudDisclosureModalProps) {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  const providerMeta = PROVIDER_METADATA[provider] || { label: provider };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="cloud-disclosure-title"
      data-testid="cloud-disclosure-modal"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
    >
      <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden flex flex-col duration-150">
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-200 dark:border-zinc-800 bg-amber-50 dark:bg-amber-950/40 flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300 flex items-center justify-center shrink-0">
              <ShieldAlert className="w-4 h-4" />
            </div>
            <div>
              <h2 id="cloud-disclosure-title" className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                Cloud Transmission Notice: Protected Health Information
              </h2>
              <p className="text-xs text-amber-800 dark:text-amber-300 font-medium">
                Local-Default Privacy Policy (AU-20)
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onCancel}
            aria-label="Close dialog"
            className="text-slate-400 hover:text-slate-700 dark:hover:text-zinc-200 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body Content */}
        <div className="p-5 space-y-4 text-xs text-slate-700 dark:text-zinc-300 leading-relaxed">
          <div className="p-3 rounded-xl border border-amber-200 dark:border-amber-900/60 bg-amber-50/50 dark:bg-amber-950/20 text-slate-800 dark:text-zinc-200 space-y-1.5">
            <p>
              Your active conversation contains <strong>Protected Health Information (PHI)</strong>, clinical records, or encrypted connector credentials.
            </p>
            <p>
              You have selected <strong>{providerMeta.label} ({model})</strong>, which transmits conversation text and attachments to third-party cloud servers over the network.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="font-semibold text-slate-900 dark:text-zinc-100">Carefold Local-First Default:</h3>
            <ul className="list-disc pl-4 space-y-1 text-slate-600 dark:text-zinc-400">
              <li>By default, sensitive medical data never leaves this machine.</li>
              <li>You can switch to local execution with Ollama with zero loss of privacy.</li>
              <li>If you proceed with cloud inference, your data will leave this device.</li>
            </ul>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="px-5 py-4 border-t border-slate-200 dark:border-zinc-800 bg-slate-50 dark:bg-zinc-800/80 flex flex-col sm:flex-row items-center justify-end gap-2.5">
          <button
            type="button"
            data-testid="switch-to-local-button"
            onClick={onFallbackToLocal}
            className="w-full sm:w-auto inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs shadow-sm transition cursor-pointer"
          >
            <Laptop className="w-3.5 h-3.5" />
            <span>Switch to Local Ollama (Recommended)</span>
          </button>

          <button
            type="button"
            data-testid="authorize-cloud-button"
            onClick={onAuthorizeCloud}
            className="w-full sm:w-auto inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-200 font-semibold text-xs shadow-sm transition cursor-pointer"
          >
            <Globe className="w-3.5 h-3.5" />
            <span>Authorize Cloud Inference</span>
          </button>
        </div>
      </div>
    </div>
  );
}
