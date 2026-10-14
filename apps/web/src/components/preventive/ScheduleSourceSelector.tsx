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
import { ShieldCheck, Info, CalendarCheck2 } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';
import type { ScheduleSource } from '@/types/preventive';

export interface ScheduleSourceSelectorProps {
  value: ScheduleSource;
  onChange: (nextSource: ScheduleSource) => void;
  disabled?: boolean;
  versionDate?: string;
  className?: string;
}

const SCHEDULE_OPTIONS: Array<{
  id: ScheduleSource;
  label: string;
  authority: string;
  badgeText: string;
  description: string;
}> = [
  {
    id: 'aap_2026',
    label: 'AAP 2026',
    authority: 'American Academy of Pediatrics (Bright Futures 2026)',
    badgeText: 'Default • 2026.1',
    description:
      'Evidence-based pediatric immunisation and periodicity schedule endorsed by the AAP.',
  },
  {
    id: 'cdc',
    label: 'CDC ACIP',
    authority: 'CDC Advisory Committee on Immunization Practices',
    badgeText: 'Federal ACIP • 2026.1',
    description:
      'Standardized federal immunisation schedule for children, adolescents, and catch-up intervals.',
  },
];

export function ScheduleSourceSelector({
  value,
  onChange,
  disabled = false,
  versionDate = 'Reviewed 2026-02-01',
  className,
}: ScheduleSourceSelectorProps) {
  return (
    <Card
      data-testid="schedule-source-selector"
      className={cn('p-4 space-y-3 shadow-sm', className)}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-emerald-600/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
            <CalendarCheck2 className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Pediatric Immunisation Schedule Source
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Select the authoritative guideline used to evaluate immunisation rules
            </p>
          </div>
        </div>

        <Badge
          data-testid="schedule-version-badge"
          variant="info"
          size="sm"
          icon={<ShieldCheck className="w-3 h-3" />}
        >
          {versionDate}
        </Badge>
      </div>

      <div
        role="radiogroup"
        aria-label="Immunisation schedule source"
        className="grid grid-cols-1 sm:grid-cols-2 gap-2.5"
      >
        {SCHEDULE_OPTIONS.map((opt) => {
          const isSelected = value === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              role="radio"
              aria-checked={isSelected}
              disabled={disabled}
              data-testid={`schedule-source-option-${opt.id}`}
              onClick={() => {
                if (!disabled && opt.id !== value) {
                  onChange(opt.id);
                }
              }}
              className={cn(
                'text-left p-3 rounded-xl border transition-all',
                isSelected
                  ? 'border-emerald-600 bg-emerald-50/60 dark:bg-emerald-950/30 ring-1 ring-emerald-600'
                  : 'border-[var(--cf-border)] bg-[var(--cf-surface)] hover:bg-[var(--cf-surface-2)]',
                disabled && 'opacity-60 cursor-not-allowed'
              )}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="font-semibold text-sm text-[var(--cf-fg)]">
                  {opt.label}
                </span>
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)] border border-[var(--cf-border)]">
                  {opt.badgeText}
                </span>
              </div>
              <p className="text-xs font-medium text-[var(--cf-fg-subtle)] mb-1">
                {opt.authority}
              </p>
              <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed">
                {opt.description}
              </p>
            </button>
          );
        })}
      </div>

      <div
        data-testid="schedule-guidance-note"
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-50/70 dark:bg-amber-950/30 border border-amber-200/80 dark:border-amber-900/50 text-xs text-amber-800 dark:text-amber-200"
      >
        <Info className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <span>
          <strong>Educational Guidance:</strong> Items marked as due indicate{' '}
          <em>&ldquo;Possibly due, confirm with your pediatrician&rdquo;</em> or primary care clinician.
        </span>
      </div>
    </Card>
  );
}
