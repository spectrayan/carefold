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

import React, { useState } from 'react';
import {
  CheckCircle2,
  Trash2,
  FileCheck2,
  AlertTriangle,
  Database,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import type { ImportBatchResponse } from '@/types/imports';

export interface ImportStagingReviewTableProps {
  batch: ImportBatchResponse;
  onCommit: (batchId: string, selectedIndices: number[]) => void | Promise<void>;
  onDiscard: (batchId: string) => void | Promise<void>;
  isSubmitting?: boolean;
  className?: string;
}

export function ImportStagingReviewTable({
  batch,
  onCommit,
  onDiscard,
  isSubmitting = false,
  className,
}: ImportStagingReviewTableProps) {
  const [selectedIndices, setSelectedIndices] = useState<number[]>(() =>
    (batch.records || []).map((r) => r.index)
  );

  const toggleIndex = (idx: number) => {
    setSelectedIndices((prev) =>
      prev.includes(idx) ? prev.filter((i) => i !== idx) : [...prev, idx]
    );
  };

  const formattedDate = batch.created_at
    ? batch.created_at.slice(0, 10)
    : 'Unknown date';

  const summaryItems = [
    {
      key: 'conditions',
      label: 'Conditions',
      count: batch.summary?.conditions ?? 0,
    },
    {
      key: 'medications',
      label: 'Medications',
      count: batch.summary?.medications ?? 0,
    },
    {
      key: 'allergies',
      label: 'Allergies',
      count: batch.summary?.allergies ?? 0,
    },
    {
      key: 'immunizations',
      label: 'Immunizations',
      count: batch.summary?.immunizations ?? 0,
    },
    {
      key: 'vitals',
      label: 'Vitals',
      count: batch.summary?.vitals ?? 0,
    },
    {
      key: 'apple_health_summaries',
      label: 'Apple Health Daily Summaries',
      count: batch.summary?.apple_health_summaries ?? 0,
    },
  ];

  return (
    <Card
      data-testid="import-staging-review-table"
      className={cn('p-5 space-y-4 shadow-sm', className)}
    >
      {/* Header & Provenance Badge */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-[var(--cf-border)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600/10 text-blue-600 dark:text-blue-400 flex items-center justify-center shrink-0">
            <FileCheck2 className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Review-Before-Save Staged Clinical Import
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Inspect parsed clinical records and wearable summaries before saving to your profile
            </p>
          </div>
        </div>

        <Badge
          data-testid="import-provenance-badge"
          variant="info"
          size="md"
          icon={<Database className="w-3.5 h-3.5" />}
        >
          {`From ${batch.source_name}, ${formattedDate}`}
        </Badge>
      </div>

      {/* Breakdown Counts */}
      <div
        data-testid="import-summary-counts"
        className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5"
      >
        {summaryItems.map((item) => (
          <div
            key={item.key}
            data-testid={`import-count-${item.key}`}
            className="p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] text-center"
          >
            <div className="text-lg font-bold text-[var(--cf-fg)]">
              {item.count}
            </div>
            <div className="text-xs font-medium text-[var(--cf-fg-muted)]">
              {item.label}
            </div>
          </div>
        ))}
      </div>

      {/* Warnings if any */}
      {batch.warnings && batch.warnings.length > 0 && (
        <div
          data-testid="import-staging-warnings"
          className="p-3 rounded-xl bg-amber-50/80 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/50 text-xs text-amber-800 dark:text-amber-200 space-y-1"
        >
          {batch.warnings.map((w, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-amber-600" />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* Staged Records Table */}
      <div className="overflow-x-auto rounded-xl border border-[var(--cf-border)]">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)] border-b border-[var(--cf-border)]">
              <th className="py-2.5 px-3 w-10">Include</th>
              <th className="py-2.5 px-3">Resource Type</th>
              <th className="py-2.5 px-3">Summary</th>
              <th className="py-2.5 px-3">Effective Date</th>
              <th className="py-2.5 px-3">Provenance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--cf-border)]">
            {(batch.records || []).map((rec) => {
              const checked = selectedIndices.includes(rec.index);
              const recDate = rec.effective_date
                ? rec.effective_date.slice(0, 10)
                : formattedDate;
              return (
                <tr
                  key={rec.index}
                  data-testid={`staged-record-row-${rec.index}`}
                  className={cn(
                    'transition-colors',
                    checked
                      ? 'bg-[var(--cf-surface)]'
                      : 'bg-[var(--cf-surface-2)]/50 opacity-60'
                  )}
                >
                  <td className="py-2.5 px-3">
                    <input
                      type="checkbox"
                      aria-label={`Select ${rec.display_title}`}
                      checked={checked}
                      onChange={() => toggleIndex(rec.index)}
                      data-testid={`staged-record-checkbox-${rec.index}`}
                      className="rounded border-[var(--cf-border-strong)]"
                    />
                  </td>
                  <td className="py-2.5 px-3 font-medium text-[var(--cf-fg-subtle)]">
                    {rec.resource_type}
                  </td>
                  <td className="py-2.5 px-3 font-semibold text-[var(--cf-fg)]">
                    {rec.display_title}
                  </td>
                  <td className="py-2.5 px-3 text-[var(--cf-fg-muted)]">
                    {recDate}
                  </td>
                  <td className="py-2.5 px-3">
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/50">
                      {`From ${rec.source_name || batch.source_name}, ${recDate}`}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Commit / Discard Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-[var(--cf-border)]">
        <span className="text-xs text-[var(--cf-fg-muted)]">
          {selectedIndices.length} of {(batch.records || []).length} records selected for import
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="danger"
            size="sm"
            disabled={isSubmitting}
            data-testid="discard-import-batch-btn"
            leftIcon={<Trash2 className="w-3.5 h-3.5" />}
            onClick={() => onDiscard(batch.batch_id)}
          >
            Discard
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={isSubmitting}
            disabled={isSubmitting || selectedIndices.length === 0}
            data-testid="commit-import-batch-btn"
            leftIcon={<CheckCircle2 className="w-3.5 h-3.5" />}
            onClick={() => onCommit(batch.batch_id, selectedIndices)}
          >
            Confirm &amp; Save to Profile
          </Button>
        </div>
      </div>
    </Card>
  );
}
