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
import { Sun, Moon } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Segmented } from '@/components/ui/Segmented';
import { cn } from '@/lib/utils';
import type { VitalsTrendsResponse, DiurnalTrendWindow } from '@/types/vitals';

export interface DiurnalTrendTableProps {
  trends?: VitalsTrendsResponse | null;
  className?: string;
}

export function DiurnalTrendTable({ trends, className }: DiurnalTrendTableProps) {
  const [selectedWindow, setSelectedWindow] = useState<'7_day' | '30_day' | '90_day'>('30_day');

  const currentTrend: DiurnalTrendWindow | undefined = trends?.trends?.[selectedWindow];
  const am = currentTrend?.am;
  const pm = currentTrend?.pm;

  const stageVariant = (stage?: string) => {
    if (!stage) return 'neutral';
    if (stage === 'Normal') return 'success';
    if (stage === 'Elevated' || stage === 'Stage 1') return 'warning';
    return 'danger';
  };

  const hasAm = Boolean(am && am.count > 0 && am.systolic && am.diastolic);
  const hasPm = Boolean(pm && pm.count > 0 && pm.systolic && pm.diastolic);
  const hasBoth = hasAm && hasPm;

  const pmDeltaSys = hasBoth && pm?.systolic && am?.systolic ? pm.systolic - am.systolic : 0;
  const pmDeltaDia = hasBoth && pm?.diastolic && am?.diastolic ? pm.diastolic - am.diastolic : 0;

  return (
    <Card
      data-testid="diurnal-trend-table-container"
      className={cn('p-5 shadow-sm', className)}
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 gap-4 border-b border-[var(--cf-border)]">
        <div>
          <h3 className="font-semibold text-base text-[var(--cf-fg)]">
            Diurnal Blood Pressure Moving Averages
          </h3>
          <p className="text-xs text-[var(--cf-fg-muted)] mt-0.5">
            AHA/ACC 2025 moving averages stratified into morning (AM 05:00–11:59) and evening (PM 12:00–22:00) readings.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Segmented
            aria-label="Diurnal trend window"
            value={selectedWindow}
            onChange={(val) => setSelectedWindow(val as any)}
            options={[
              { label: '7 Days', value: '7_day' },
              { label: '30 Days', value: '30_day' },
              { label: '90 Days', value: '90_day' },
            ]}
          />
        </div>
      </div>

      <div className="overflow-x-auto mt-4">
        <table
          className="w-full text-left text-sm"
          role="table"
          aria-label="Blood Pressure Diurnal Moving Averages"
        >
          <thead>
            <tr className="border-b border-[var(--cf-border)] text-xs uppercase tracking-wider text-[var(--cf-fg-muted)]">
              <th className="py-3 px-3">Period</th>
              <th className="py-3 px-3">Time Window</th>
              <th className="py-3 px-3 text-center">Readings (N)</th>
              <th className="py-3 px-3">Mean Blood Pressure</th>
              <th className="py-3 px-3">Systolic / Diastolic</th>
              <th className="py-3 px-3">AHA/ACC 2025 Stage</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--cf-border)]">
            {/* AM Row */}
            <tr data-testid="diurnal-am-row">
              <td className="py-3.5 px-3 font-medium text-[var(--cf-fg)] flex items-center gap-2">
                <Sun className="w-4 h-4 text-amber-500 shrink-0" />
                Morning (AM)
              </td>
              <td className="py-3.5 px-3 text-xs text-[var(--cf-fg-muted)]">05:00 – 11:59</td>
              <td data-testid="am-count" className="py-3.5 px-3 text-center font-mono text-xs">
                {am?.count ?? 0}
              </td>
              <td data-testid="am-mean-bp" className="py-3.5 px-3 font-semibold font-mono text-sm">
                {hasAm ? `${am!.systolic} / ${am!.diastolic} mmHg` : '—'}
              </td>
              <td className="py-3.5 px-3 font-mono text-xs text-[var(--cf-fg-muted)]">
                {hasAm ? `SBP: ${am!.systolic} | DBP: ${am!.diastolic}` : '—'}
              </td>
              <td className="py-3.5 px-3">
                {hasAm ? (
                  <Badge variant={stageVariant(am!.classification)} size="sm">
                    {am!.classification}
                  </Badge>
                ) : (
                  <span className="text-xs text-[var(--cf-fg-subtle)]">—</span>
                )}
              </td>
            </tr>

            {/* PM Row */}
            <tr data-testid="diurnal-pm-row">
              <td className="py-3.5 px-3 font-medium text-[var(--cf-fg)] flex items-center gap-2">
                <Moon className="w-4 h-4 text-indigo-500 shrink-0" />
                Evening (PM)
              </td>
              <td className="py-3.5 px-3 text-xs text-[var(--cf-fg-muted)]">12:00 – 22:00</td>
              <td data-testid="pm-count" className="py-3.5 px-3 text-center font-mono text-xs">
                {pm?.count ?? 0}
              </td>
              <td data-testid="pm-mean-bp" className="py-3.5 px-3 font-semibold font-mono text-sm">
                {hasPm ? `${pm!.systolic} / ${pm!.diastolic} mmHg` : '—'}
              </td>
              <td className="py-3.5 px-3 font-mono text-xs text-[var(--cf-fg-muted)]">
                {hasPm ? `SBP: ${pm!.systolic} | DBP: ${pm!.diastolic}` : '—'}
              </td>
              <td className="py-3.5 px-3">
                {hasPm ? (
                  <Badge variant={stageVariant(pm!.classification)} size="sm">
                    {pm!.classification}
                  </Badge>
                ) : (
                  <span className="text-xs text-[var(--cf-fg-subtle)]">—</span>
                )}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Diurnal Summary Footer */}
      <div className="mt-4 pt-3 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-muted)] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          {hasBoth ? (
            <span>
              <strong>Diurnal Difference (PM vs AM):</strong>{' '}
              <span data-testid="diurnal-spread" className="font-mono font-medium">
                {pmDeltaSys >= 0 ? `+${pmDeltaSys}` : pmDeltaSys} / {pmDeltaDia >= 0 ? `+${pmDeltaDia}` : pmDeltaDia} mmHg
              </span>
            </span>
          ) : (
            <span>Log both morning and evening readings to calculate nocturnal dipping and diurnal spread.</span>
          )}
        </div>
        <div className="text-[var(--cf-fg-subtle)]">
          Timezone: <strong>{trends?.timezone || 'Local'}</strong>
        </div>
      </div>
    </Card>
  );
}
