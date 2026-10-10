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

import React, { useEffect, useRef, useState } from 'react';
import { ShieldAlert, CheckCircle2, Ban, Phone, X } from 'lucide-react';
import { sanitizeAgentDescription } from '@/lib/utils';
import { DEFAULT_FORBIDDEN_INTENTS, describeForbiddenIntent } from '@/lib/clinicalConsent';

/*
 * SAFETY REVIEW REQUIRED: the wording in this dialog is patient-facing consent copy.
 * Any change must be reviewed by a maintainer and a Clinical AI Reviewer (see #87).
 */

export interface ClinicalConsentAgent {
  id: string;
  title: string;
  description?: string;
  forbidden?: string[];
}

export interface ClinicalConsentDialogProps {
  isOpen: boolean;
  agent: ClinicalConsentAgent;
  onAccept: () => void;
  onDecline: () => void;
}

const GENERAL_HELP_ITEMS = [
  'Prepare questions and a checklist for your next appointment.',
  'Organize symptoms, readings, and records you choose to share.',
  'Explain medical terms and care options in plain language.'
];

export function ClinicalConsentDialog({ isOpen, agent, onAccept, onDecline }: ClinicalConsentDialogProps) {
  const [acknowledged, setAcknowledged] = useState(false);
  const checkboxRef = useRef<HTMLInputElement>(null);

  // Reset acknowledgement whenever the dialog opens for an agent
  useEffect(() => {
    if (isOpen) {
      setAcknowledged(false);
      checkboxRef.current?.focus();
    }
  }, [isOpen, agent.id]);

  // Escape declines (never silently grants)
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDecline();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onDecline]);

  if (!isOpen) return null;

  const description = sanitizeAgentDescription(agent.description);
  const forbidden = (agent.forbidden && agent.forbidden.length > 0 ? agent.forbidden : [...DEFAULT_FORBIDDEN_INTENTS])
    .map(describeForbiddenIntent)
    .filter(Boolean);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="clinical-consent-title"
      aria-describedby="clinical-consent-intro"
      data-testid="clinical-consent-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm overflow-y-auto"
    >
      <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-200 dark:border-zinc-800 bg-slate-50 dark:bg-zinc-800/80 flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-400 flex items-center justify-center shrink-0">
              <ShieldAlert className="w-4 h-4" />
            </div>
            <div>
              <h2 id="clinical-consent-title" className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                Before you chat with {agent.title}
              </h2>
              <p className="text-xs text-slate-500 dark:text-zinc-400">Clinical assist agent — your consent is required</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close without giving consent"
            data-testid="clinical-consent-close"
            onClick={onDecline}
            className="p-1.5 rounded-lg text-slate-400 dark:text-zinc-400 hover:text-slate-700 dark:hover:text-zinc-200 hover:bg-slate-200 dark:hover:bg-zinc-700 transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 text-xs text-slate-700 dark:text-zinc-300 leading-relaxed">
          <p id="clinical-consent-intro">
            {agent.title} helps you get ready for care and understand health information. It is an AI assistant, not a
            doctor or nurse, and it can make mistakes. Please review anything it gives you with your healthcare provider
            before you act on it.
          </p>

          <section aria-labelledby="clinical-consent-can">
            <h3 id="clinical-consent-can" className="font-bold text-slate-900 dark:text-zinc-100 mb-1.5">
              What it can help with
            </h3>
            {description && <p className="mb-1.5">{description}</p>}
            <ul className="space-y-1" data-testid="clinical-consent-can-list">
              {GENERAL_HELP_ITEMS.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="clinical-consent-wont">
            <h3 id="clinical-consent-wont" className="font-bold text-slate-900 dark:text-zinc-100 mb-1.5">
              What it will not do
            </h3>
            <ul className="space-y-1" data-testid="clinical-consent-forbidden-list">
              {forbidden.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <Ban className="w-3.5 h-3.5 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>

          <section
            aria-labelledby="clinical-consent-emergency"
            data-testid="clinical-consent-emergency"
            className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-rose-900 dark:text-rose-200"
          >
            <h3 id="clinical-consent-emergency" className="font-bold flex items-center gap-1.5 mb-1">
              <Phone className="w-3.5 h-3.5" />
              <span>In an emergency, do not use this chat</span>
            </h3>
            <p>
              If you have chest pain, trouble breathing, signs of a stroke, a severe allergic reaction, or thoughts of
              harming yourself, call <strong>911</strong> (or your local emergency number) now. For a mental health
              crisis in the US, call or text <strong>988</strong>.
            </p>
          </section>

          <label className="flex items-start gap-2 p-3 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800/60 cursor-pointer">
            <input
              ref={checkboxRef}
              type="checkbox"
              data-testid="clinical-consent-ack"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="mt-0.5 accent-emerald-600"
            />
            <span>
              I understand that {agent.title} gives information only, is not medical advice, and does not replace my
              healthcare provider or emergency services.
            </span>
          </label>

          <p className="text-xs text-slate-500 dark:text-zinc-400">
            Your choice is saved only in this browser. You can withdraw it at any time in Settings.
          </p>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-slate-200 dark:border-zinc-800 flex items-center justify-end gap-2">
          <button
            type="button"
            data-testid="clinical-consent-decline"
            onClick={onDecline}
            className="px-3.5 py-2 text-xs font-medium text-slate-700 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-zinc-100 rounded-xl hover:bg-slate-100 dark:hover:bg-zinc-800 transition cursor-pointer"
          >
            Not now
          </button>
          <button
            type="button"
            data-testid="clinical-consent-accept"
            disabled={!acknowledged}
            onClick={onAccept}
            className="px-4 py-2 text-xs font-semibold text-white bg-emerald-700 hover:bg-emerald-800 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] rounded-xl shadow-sm transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            I understand, continue
          </button>
        </div>
      </div>
    </div>
  );
}
