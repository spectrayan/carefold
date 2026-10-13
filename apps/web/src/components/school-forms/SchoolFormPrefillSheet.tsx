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

import React, { useState } from 'react';
import {
  FileText,
  Copy,
  Printer,
  Check,
  ShieldAlert,
  Syringe,
  AlertTriangle,
  Pill,
  HeartPulse,
  RefreshCw,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';
import type { SchoolFormItem } from '@/types/schoolForms';

export interface SchoolFormPrefillSheetProps {
  form: SchoolFormItem;
  onRegeneratePrefill?: (formId: string) => void | Promise<void>;
  onClose?: () => void;
  className?: string;
}

const DEFAULT_DISCLAIMER =
  'Draft prefill generated from your saved records for parent and clinician review. Never auto-submitted.';

export function SchoolFormPrefillSheet({
  form,
  onRegeneratePrefill,
  onClose,
  className,
}: SchoolFormPrefillSheetProps) {
  const [copied, setCopied] = useState(false);
  const draft = form.prefill_draft;

  const handleCopy = async () => {
    const summaryText = [
      `SCHOOL / CAMP HEALTH FORM DRAFT PREFILL`,
      `Form: ${form.title} (${form.institution_name})`,
      `Student: ${draft.student_name}`,
      draft.date_of_birth ? `DOB: ${draft.date_of_birth}` : null,
      `Disclaimer: ${draft.disclaimer || DEFAULT_DISCLAIMER}`,
      `Immunisations: ${(draft.immunisations || []).map((i) => `${i.name} (${i.status})`).join(', ') || 'None recorded'}`,
      `Allergies: ${(draft.allergies || []).map((a) => a.substance).join(', ') || 'None recorded'}`,
      `Medications: ${(draft.active_medications || []).map((m) => m.name).join(', ') || 'None recorded'}`,
    ]
      .filter(Boolean)
      .join('\n');

    try {
      await navigator.clipboard?.writeText(summaryText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(true);
    }
  };

  const handlePrint = () => {
    if (typeof window !== 'undefined' && typeof window.print === 'function') {
      window.print();
    }
  };

  return (
    <Card
      data-testid="school-form-prefill-sheet"
      className={cn('p-5 space-y-4 shadow-sm', className)}
    >
      {/* Prominent Non-Clinical Disclaimer Banner */}
      <div
        data-testid="school-form-disclaimer-banner"
        className="flex items-start gap-2.5 p-3.5 rounded-xl bg-amber-50/90 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800 text-xs text-amber-900 dark:text-amber-200"
      >
        <ShieldAlert className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5" />
        <div className="space-y-0.5">
          <div className="font-bold">Non-Clinical Draft Prefill Notice</div>
          <p data-testid="school-form-disclaimer-text">
            {draft?.disclaimer || DEFAULT_DISCLAIMER}
          </p>
        </div>
      </div>

      {/* Header & Actions */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-[var(--cf-border)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-violet-600/10 text-violet-600 dark:text-violet-400 flex items-center justify-center shrink-0">
            <FileText className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              {form.title} — {form.institution_name}
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Student: <strong>{draft?.student_name || 'Unknown'}</strong>
              {draft?.date_of_birth ? ` • DOB: ${draft.date_of_birth}` : ''}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          {onRegeneratePrefill && (
            <Button
              size="sm"
              variant="ghost"
              data-testid="regenerate-prefill-btn"
              leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
              onClick={() => onRegeneratePrefill(form.id)}
            >
              Refresh from Profile
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            data-testid="copy-prefill-btn"
            leftIcon={
              copied ? (
                <Check className="w-3.5 h-3.5 text-emerald-600" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )
            }
            onClick={handleCopy}
          >
            {copied ? 'Copied' : 'Copy'}
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid="print-prefill-btn"
            leftIcon={<Printer className="w-3.5 h-3.5" />}
            onClick={handlePrint}
          >
            Print
          </Button>
          {onClose && (
            <Button
              size="sm"
              variant="ghost"
              data-testid="close-prefill-btn"
              onClick={onClose}
            >
              Close
            </Button>
          )}
        </div>
      </div>

      {/* Compiled Sections Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Recorded Immunisations */}
        <div
          data-testid="prefill-section-immunisations"
          className="p-3.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]/50 space-y-2"
        >
          <div className="flex items-center gap-1.5 text-xs font-bold text-[var(--cf-fg)]">
            <Syringe className="w-3.5 h-3.5 text-violet-500" />
            <span>Recorded Immunisations</span>
          </div>
          {!draft?.immunisations || draft.immunisations.length === 0 ? (
            <p className="text-xs text-[var(--cf-fg-muted)]">
              No immunisations recorded in profile.
            </p>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {draft.immunisations.map((imm, idx) => (
                <li
                  key={idx}
                  className="flex items-center justify-between gap-2 p-2 rounded-lg bg-[var(--cf-surface)] border border-[var(--cf-border)]"
                >
                  <div>
                    <span className="font-semibold text-[var(--cf-fg)]">
                      {imm.name}
                    </span>
                    {imm.date && (
                      <span className="text-[var(--cf-fg-muted)] ml-1.5">
                        ({imm.date})
                      </span>
                    )}
                  </div>
                  <Badge variant="success" size="sm">
                    {imm.status}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Allergies */}
        <div
          data-testid="prefill-section-allergies"
          className="p-3.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]/50 space-y-2"
        >
          <div className="flex items-center gap-1.5 text-xs font-bold text-[var(--cf-fg)]">
            <AlertTriangle className="w-3.5 h-3.5 text-rose-500" />
            <span>Documented Allergies</span>
          </div>
          {!draft?.allergies || draft.allergies.length === 0 ? (
            <p className="text-xs text-[var(--cf-fg-muted)]">
              No known allergies recorded.
            </p>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {draft.allergies.map((al, idx) => (
                <li
                  key={idx}
                  className="flex items-center justify-between gap-2 p-2 rounded-lg bg-[var(--cf-surface)] border border-[var(--cf-border)]"
                >
                  <div>
                    <span className="font-semibold text-[var(--cf-fg)]">
                      {al.substance}
                    </span>
                    {al.reaction && (
                      <span className="text-[var(--cf-fg-muted)] ml-1.5">
                        — {al.reaction}
                      </span>
                    )}
                  </div>
                  {al.severity && (
                    <Badge variant="danger" size="sm">
                      {al.severity}
                    </Badge>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Active Medications */}
        <div
          data-testid="prefill-section-medications"
          className="p-3.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]/50 space-y-2"
        >
          <div className="flex items-center gap-1.5 text-xs font-bold text-[var(--cf-fg)]">
            <Pill className="w-3.5 h-3.5 text-blue-500" />
            <span>Active Medications</span>
          </div>
          {!draft?.active_medications || draft.active_medications.length === 0 ? (
            <p className="text-xs text-[var(--cf-fg-muted)]">
              No active medications recorded.
            </p>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {draft.active_medications.map((med, idx) => (
                <li
                  key={idx}
                  className="flex items-center justify-between gap-2 p-2 rounded-lg bg-[var(--cf-surface)] border border-[var(--cf-border)]"
                >
                  <span className="font-semibold text-[var(--cf-fg)]">
                    {med.name}
                  </span>
                  <span className="text-[var(--cf-fg-muted)]">
                    {[med.dosage, med.frequency].filter(Boolean).join(' • ')}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Latest Height / Weight / BP */}
        <div
          data-testid="prefill-section-vitals"
          className="p-3.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)]/50 space-y-2"
        >
          <div className="flex items-center gap-1.5 text-xs font-bold text-[var(--cf-fg)]">
            <HeartPulse className="w-3.5 h-3.5 text-emerald-500" />
            <span>Latest Height / Weight / Blood Pressure</span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="p-2 rounded-lg bg-[var(--cf-surface)] border border-[var(--cf-border)]">
              <div className="text-[10px] text-[var(--cf-fg-muted)]">Height</div>
              <div className="font-bold text-[var(--cf-fg)]">
                {draft?.latest_vitals?.height || '—'}
              </div>
            </div>
            <div className="p-2 rounded-lg bg-[var(--cf-surface)] border border-[var(--cf-border)]">
              <div className="text-[10px] text-[var(--cf-fg-muted)]">Weight</div>
              <div className="font-bold text-[var(--cf-fg)]">
                {draft?.latest_vitals?.weight || '—'}
              </div>
            </div>
            <div className="p-2 rounded-lg bg-[var(--cf-surface)] border border-[var(--cf-border)]">
              <div className="text-[10px] text-[var(--cf-fg-muted)]">BP</div>
              <div className="font-bold text-[var(--cf-fg)]">
                {draft?.latest_vitals?.blood_pressure || '—'}
              </div>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
