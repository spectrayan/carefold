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

import React from 'react';
import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Loader2,
  ShieldAlert,
  Clock,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { cn } from '@/lib/utils';
import type { SyncRunItem } from '@/types/connections';

export interface SyncHealthTableProps {
  runs: SyncRunItem[];
  connectionLabel?: string;
  isLoading?: boolean;
  className?: string;
}

function getStatusBadgeConfig(status: string) {
  switch (status) {
    case 'succeeded':
      return {
        label: 'succeeded',
        icon: CheckCircle2,
        classes:
          'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60',
      };
    case 'partial':
      return {
        label: 'partial',
        icon: AlertTriangle,
        classes:
          'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/60',
      };
    case 'failed':
      return {
        label: 'failed',
        icon: XCircle,
        classes:
          'bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/60',
      };
    default:
      return {
        label: status || 'running',
        icon: Loader2,
        classes:
          'bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800/60',
      };
  }
}

export function SyncHealthTable({
  runs,
  connectionLabel,
  isLoading = false,
  className,
}: SyncHealthTableProps) {
  return (
    <Card
      data-testid="sync-health-table"
      className={cn('p-4 space-y-3 shadow-sm', className)}
    >
      <div className="flex items-center justify-between gap-2 pb-2 border-b border-[var(--cf-border)]">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-emerald-600" />
          <h4 className="text-xs font-bold text-[var(--cf-fg)]">
            Sync Telemetry &amp; Quarantine Ledger
            {connectionLabel ? ` — ${connectionLabel}` : ''}
          </h4>
        </div>
        <span className="text-xs text-[var(--cf-fg-muted)]">
          {runs.length} {runs.length === 1 ? 'run' : 'runs'}
        </span>
      </div>

      {isLoading ? (
        <div
          data-testid="sync-health-loading"
          className="py-6 text-center text-xs text-[var(--cf-fg-muted)]"
        >
          Loading sync telemetry...
        </div>
      ) : runs.length === 0 ? (
        <div
          data-testid="sync-health-empty"
          className="py-6 text-center text-xs text-[var(--cf-fg-muted)]"
        >
          No sync runs recorded for this connection yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-[var(--cf-border)] text-xs text-[var(--cf-fg-muted)]">
                <th className="py-2 pr-3 font-semibold">Status</th>
                <th className="py-2 px-3 font-semibold">Stream</th>
                <th className="py-2 px-3 font-semibold">Fetched</th>
                <th className="py-2 px-3 font-semibold">Upserted</th>
                <th className="py-2 px-3 font-semibold">Quarantined</th>
                <th className="py-2 px-3 font-semibold">Duration</th>
                <th className="py-2 pl-3 font-semibold">Started At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--cf-border)]">
              {runs.map((run) => {
                const badge = getStatusBadgeConfig(run.status);
                const BadgeIcon = badge.icon;
                return (
                  <React.Fragment key={run.id}>
                    <tr
                      data-testid={`sync-run-row-${run.id}`}
                      className="hover:bg-[var(--cf-surface-2)]/60"
                    >
                      <td className="py-2.5 pr-3">
                        <span
                          data-testid={`sync-run-status-${run.id}`}
                          className={cn(
                            'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border',
                            badge.classes
                          )}
                        >
                          <BadgeIcon className="w-3 h-3 shrink-0" />
                          <span>{badge.label}</span>
                        </span>
                      </td>
                      <td
                        data-testid={`sync-run-stream-${run.id}`}
                        className="py-2.5 px-3 font-mono text-[var(--cf-fg)]"
                      >
                        {run.stream}
                      </td>
                      <td
                        data-testid={`sync-run-fetched-${run.id}`}
                        className="py-2.5 px-3 font-semibold text-[var(--cf-fg)]"
                      >
                        {run.records_fetched}
                      </td>
                      <td
                        data-testid={`sync-run-upserted-${run.id}`}
                        className="py-2.5 px-3 font-semibold text-emerald-700 dark:text-emerald-400"
                      >
                        {run.records_upserted}
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          data-testid={`sync-run-quarantined-${run.id}`}
                          className={cn(
                            'inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold border',
                            run.records_quarantined > 0
                              ? 'bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800/60'
                              : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border-[var(--cf-border)]'
                          )}
                        >
                          {run.records_quarantined > 0 && (
                            <ShieldAlert className="w-3 h-3 text-amber-600 shrink-0" />
                          )}
                          <span>{run.records_quarantined}</span>
                        </span>
                      </td>
                      <td
                        data-testid={`sync-run-duration-${run.id}`}
                        className="py-2.5 px-3 text-[var(--cf-fg-muted)] font-mono"
                      >
                        <span className="inline-flex items-center gap-1">
                          <Clock className="w-3 h-3 shrink-0" />
                          {run.duration_ms != null ? `${run.duration_ms} ms` : '—'}
                        </span>
                      </td>
                      <td
                        data-testid={`sync-run-started-${run.id}`}
                        className="py-2.5 pl-3 text-[var(--cf-fg-muted)] font-mono text-xs"
                      >
                        {run.started_at}
                      </td>
                    </tr>
                    {(run.error_message || run.error_code) && (
                      <tr data-testid={`sync-run-error-${run.id}`}>
                        <td colSpan={7} className="pb-2.5 pt-1">
                          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-xs text-rose-700 dark:text-rose-300">
                            <XCircle className="w-3.5 h-3.5 shrink-0" />
                            <span>
                              {run.error_code ? `[${run.error_code}] ` : ''}
                              {run.error_message || 'Sync run failed.'}
                            </span>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
