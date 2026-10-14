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
  HeartPulse,
  Activity,
  Droplet,
  Wind,
  Scale,
  Eye,
  EyeOff,
  Plus,
  TrendingUp,
  TrendingDown,
  Sun,
  Moon,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';
import type { LatestVitalsState } from '@/types/vitals';

export interface VitalsSummaryCardsProps {
  vitals: LatestVitalsState;
  hideWeight?: boolean;
  onToggleHideWeight?: () => void;
  onLogVital?: (metric: string) => void;
  className?: string;
}

export function VitalsSummaryCards({
  vitals,
  hideWeight = false,
  onToggleHideWeight,
  onLogVital,
  className,
}: VitalsSummaryCardsProps) {
  const formatTime = (isoString?: string) => {
    if (!isoString) return 'No readings yet';
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  const bpBadgeVariant = (stage?: string) => {
    if (!stage) return 'neutral';
    if (stage === 'Normal') return 'success';
    if (stage === 'Elevated' || stage === 'Stage 1') return 'warning';
    return 'danger';
  };

  const hrBadgeVariant = (classification?: string) => {
    if (!classification) return 'neutral';
    if (classification.startsWith('Normal')) return 'success';
    return 'warning';
  };

  const glucBadgeVariant = (classification?: string) => {
    if (!classification) return 'neutral';
    if (classification.startsWith('Normal')) return 'success';
    if (classification.includes('Pre-diabetic')) return 'warning';
    return 'danger';
  };

  const spo2BadgeVariant = (classification?: string) => {
    if (!classification) return 'neutral';
    if (classification.startsWith('Normal')) return 'success';
    if (classification.includes('Borderline')) return 'warning';
    return 'danger';
  };

  const bmiBadgeVariant = (classification?: string) => {
    if (!classification) return 'neutral';
    if (classification.startsWith('Normal')) return 'success';
    return 'warning';
  };

  const isWeightMasked = hideWeight || vitals.weight?.weightHidden;

  return (
    <div
      data-testid="vitals-summary-cards"
      className={cn(
        'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4',
        className
      )}
    >
      {/* 1. Blood Pressure Card */}
      <Card
        data-testid="bp-summary-card"
        className={cn(
          'p-4 flex flex-col justify-between transition-all shadow-sm',
          !vitals.bloodPressure && 'border-dashed border-[var(--cf-border)] bg-[var(--cf-surface-2)]/40'
        )}
      >
        <div>
          <div className="flex items-center justify-between gap-2 mb-2">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--cf-fg-muted)]">
              <HeartPulse className="w-4 h-4 text-rose-500" />
              Blood Pressure
            </span>
            {vitals.bloodPressure?.isAM !== undefined && (
              <span className="flex items-center gap-1 text-xs font-medium text-[var(--cf-fg-subtle)]">
                {vitals.bloodPressure.isAM ? (
                  <>
                    <Sun className="w-3 h-3 text-amber-500" /> AM
                  </>
                ) : (
                  <>
                    <Moon className="w-3 h-3 text-indigo-500" /> PM
                  </>
                )}
              </span>
            )}
          </div>

          {vitals.bloodPressure ? (
            <div className="space-y-1">
              <div className="flex items-baseline gap-1.5">
                <span data-testid="bp-value" className="text-2xl font-bold font-mono text-[var(--cf-fg)] tracking-tight">
                  {vitals.bloodPressure.systolic}/{vitals.bloodPressure.diastolic}
                </span>
                <span className="text-xs text-[var(--cf-fg-subtle)] font-medium">mmHg</span>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Badge
                  data-testid="bp-stage-badge"
                  variant={bpBadgeVariant(vitals.bloodPressure.stage)}
                  size="sm"
                >
                  {vitals.bloodPressure.stage}
                </Badge>
                {vitals.bloodPressure.deltaSys !== undefined && (
                  <span className="flex items-center text-xs font-mono text-[var(--cf-fg-subtle)]">
                    {vitals.bloodPressure.deltaSys > 0 ? (
                      <TrendingUp className="w-3 h-3 text-rose-500 mr-0.5" />
                    ) : vitals.bloodPressure.deltaSys < 0 ? (
                      <TrendingDown className="w-3 h-3 text-emerald-500 mr-0.5" />
                    ) : null}
                    {vitals.bloodPressure.deltaSys >= 0 ? `+${vitals.bloodPressure.deltaSys}` : vitals.bloodPressure.deltaSys}/
                    {vitals.bloodPressure.deltaDia && vitals.bloodPressure.deltaDia >= 0 ? `+${vitals.bloodPressure.deltaDia}` : vitals.bloodPressure.deltaDia}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div className="py-2 text-center text-sm text-[var(--cf-fg-subtle)]">
              <p>No readings logged</p>
              {onLogVital && (
                <button
                  type="button"
                  onClick={() => onLogVital('bp')}
                  className="mt-2 text-xs font-semibold text-[var(--cf-primary)] hover:underline inline-flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> Log BP
                </button>
              )}
            </div>
          )}
        </div>
        <div className="pt-3 mt-3 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)] truncate">
          {formatTime(vitals.bloodPressure?.effectiveAt)}
        </div>
      </Card>

      {/* 2. Heart Rate Card */}
      <Card
        data-testid="hr-summary-card"
        className={cn(
          'p-4 flex flex-col justify-between transition-all shadow-sm',
          !vitals.heartRate && 'border-dashed border-[var(--cf-border)] bg-[var(--cf-surface-2)]/40'
        )}
      >
        <div>
          <div className="flex items-center justify-between gap-2 mb-2">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--cf-fg-muted)]">
              <Activity className="w-4 h-4 text-emerald-500" />
              Heart Rate
            </span>
          </div>

          {vitals.heartRate ? (
            <div className="space-y-1">
              <div className="flex items-baseline gap-1.5">
                <span data-testid="hr-value" className="text-2xl font-bold font-mono text-[var(--cf-fg)] tracking-tight">
                  {vitals.heartRate.value}
                </span>
                <span className="text-xs text-[var(--cf-fg-subtle)] font-medium">bpm</span>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Badge
                  data-testid="hr-stage-badge"
                  variant={hrBadgeVariant(vitals.heartRate.classification)}
                  size="sm"
                >
                  {vitals.heartRate.classification || 'Recorded'}
                </Badge>
                {vitals.heartRate.delta !== undefined && (
                  <span className="flex items-center text-xs font-mono text-[var(--cf-fg-subtle)]">
                    {vitals.heartRate.delta > 0 ? (
                      <TrendingUp className="w-3 h-3 text-rose-500 mr-0.5" />
                    ) : vitals.heartRate.delta < 0 ? (
                      <TrendingDown className="w-3 h-3 text-emerald-500 mr-0.5" />
                    ) : null}
                    {vitals.heartRate.delta >= 0 ? `+${vitals.heartRate.delta}` : vitals.heartRate.delta}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div className="py-2 text-center text-sm text-[var(--cf-fg-subtle)]">
              <p>No readings logged</p>
              {onLogVital && (
                <button
                  type="button"
                  onClick={() => onLogVital('hr')}
                  className="mt-2 text-xs font-semibold text-[var(--cf-primary)] hover:underline inline-flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> Log Pulse
                </button>
              )}
            </div>
          )}
        </div>
        <div className="pt-3 mt-3 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)] truncate">
          {formatTime(vitals.heartRate?.effectiveAt)}
        </div>
      </Card>

      {/* 3. Blood Glucose Card */}
      <Card
        data-testid="glucose-summary-card"
        className={cn(
          'p-4 flex flex-col justify-between transition-all shadow-sm',
          !vitals.bloodGlucose && 'border-dashed border-[var(--cf-border)] bg-[var(--cf-surface-2)]/40'
        )}
      >
        <div>
          <div className="flex items-center justify-between gap-2 mb-2">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--cf-fg-muted)]">
              <Droplet className="w-4 h-4 text-amber-500" />
              Blood Glucose
            </span>
          </div>

          {vitals.bloodGlucose ? (
            <div className="space-y-1">
              <div className="flex items-baseline gap-1.5">
                <span data-testid="glucose-value" className="text-2xl font-bold font-mono text-[var(--cf-fg)] tracking-tight">
                  {vitals.bloodGlucose.value}
                </span>
                <span className="text-xs text-[var(--cf-fg-subtle)] font-medium">
                  {vitals.bloodGlucose.unit || 'mg/dL'}
                </span>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Badge
                  data-testid="glucose-stage-badge"
                  variant={glucBadgeVariant(vitals.bloodGlucose.classification)}
                  size="sm"
                >
                  {vitals.bloodGlucose.classification || 'Recorded'}
                </Badge>
                {vitals.bloodGlucose.delta !== undefined && (
                  <span className="flex items-center text-xs font-mono text-[var(--cf-fg-subtle)]">
                    {vitals.bloodGlucose.delta > 0 ? (
                      <TrendingUp className="w-3 h-3 text-amber-500 mr-0.5" />
                    ) : (
                      <TrendingDown className="w-3 h-3 text-emerald-500 mr-0.5" />
                    )}
                    {vitals.bloodGlucose.delta >= 0 ? `+${vitals.bloodGlucose.delta}` : vitals.bloodGlucose.delta}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div className="py-2 text-center text-sm text-[var(--cf-fg-subtle)]">
              <p>No readings logged</p>
              {onLogVital && (
                <button
                  type="button"
                  onClick={() => onLogVital('glucose')}
                  className="mt-2 text-xs font-semibold text-[var(--cf-primary)] hover:underline inline-flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> Log Glucose
                </button>
              )}
            </div>
          )}
        </div>
        <div className="pt-3 mt-3 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)] truncate">
          {formatTime(vitals.bloodGlucose?.effectiveAt)}
        </div>
      </Card>

      {/* 4. Oxygen Saturation (SpO2) Card */}
      <Card
        data-testid="spo2-summary-card"
        className={cn(
          'p-4 flex flex-col justify-between transition-all shadow-sm',
          !vitals.spo2 && 'border-dashed border-[var(--cf-border)] bg-[var(--cf-surface-2)]/40'
        )}
      >
        <div>
          <div className="flex items-center justify-between gap-2 mb-2">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--cf-fg-muted)]">
              <Wind className="w-4 h-4 text-sky-500" />
              Oxygen (SpO2)
            </span>
          </div>

          {vitals.spo2 ? (
            <div className="space-y-1">
              <div className="flex items-baseline gap-1.5">
                <span data-testid="spo2-value" className="text-2xl font-bold font-mono text-[var(--cf-fg)] tracking-tight">
                  {vitals.spo2.value}
                </span>
                <span className="text-xs text-[var(--cf-fg-subtle)] font-medium">%</span>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Badge
                  data-testid="spo2-stage-badge"
                  variant={spo2BadgeVariant(vitals.spo2.classification)}
                  size="sm"
                >
                  {vitals.spo2.classification || 'Recorded'}
                </Badge>
                {vitals.spo2.delta !== undefined && (
                  <span className="flex items-center text-xs font-mono text-[var(--cf-fg-subtle)]">
                    {vitals.spo2.delta >= 0 ? `+${vitals.spo2.delta}` : vitals.spo2.delta}%
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div className="py-2 text-center text-sm text-[var(--cf-fg-subtle)]">
              <p>No readings logged</p>
              {onLogVital && (
                <button
                  type="button"
                  onClick={() => onLogVital('spo2')}
                  className="mt-2 text-xs font-semibold text-[var(--cf-primary)] hover:underline inline-flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> Log SpO2
                </button>
              )}
            </div>
          )}
        </div>
        <div className="pt-3 mt-3 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)] truncate">
          {formatTime(vitals.spo2?.effectiveAt)}
        </div>
      </Card>

      {/* 5. Body Weight & BMI Card */}
      <Card
        data-testid="weight-summary-card"
        className={cn(
          'p-4 flex flex-col justify-between transition-all shadow-sm',
          !vitals.weight && 'border-dashed border-[var(--cf-border)] bg-[var(--cf-surface-2)]/40'
        )}
      >
        <div>
          <div className="flex items-center justify-between gap-2 mb-2">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--cf-fg-muted)]">
              <Scale className="w-4 h-4 text-violet-500" />
              Body Weight
            </span>
            {onToggleHideWeight && (
              <button
                type="button"
                data-testid="toggle-hide-weight-btn"
                onClick={onToggleHideWeight}
                aria-label={isWeightMasked ? 'Reveal weight' : 'Hide weight'}
                title={isWeightMasked ? 'Reveal weight' : 'Hide weight'}
                className="p-1 rounded text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] transition-colors min-h-[32px] min-w-[32px] flex items-center justify-center"
              >
                {isWeightMasked ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              </button>
            )}
          </div>

          {vitals.weight ? (
            <div className="space-y-1">
              <div className="flex items-baseline gap-1.5">
                {isWeightMasked ? (
                  <span
                    data-testid="weight-masked-value"
                    className="text-2xl font-bold font-mono tracking-widest select-none text-[var(--cf-fg-muted)]"
                  >
                    ••••
                  </span>
                ) : (
                  <span data-testid="weight-value" className="text-2xl font-bold font-mono text-[var(--cf-fg)] tracking-tight">
                    {vitals.weight.valueKg ? vitals.weight.valueKg.toFixed(1) : '—'}
                  </span>
                )}
                <span className="text-xs text-[var(--cf-fg-subtle)] font-medium">kg</span>
              </div>
              <div className="flex items-center gap-2 pt-1">
                {isWeightMasked ? (
                  <Badge variant="neutral" size="sm">
                    Privacy Mode
                  </Badge>
                ) : (
                  <>
                    {vitals.weight.bmi !== undefined && vitals.weight.bmi !== null ? (
                      <Badge
                        data-testid="bmi-badge"
                        variant={bmiBadgeVariant(vitals.weight.classification)}
                        size="sm"
                      >
                        BMI {vitals.weight.bmi.toFixed(1)}
                      </Badge>
                    ) : (
                      <Badge variant="neutral" size="sm">
                        Recorded
                      </Badge>
                    )}
                    {vitals.weight.delta !== undefined && (
                      <span className="flex items-center text-xs font-mono text-[var(--cf-fg-subtle)]">
                        {vitals.weight.delta >= 0 ? `+${vitals.weight.delta.toFixed(1)}` : vitals.weight.delta.toFixed(1)} kg
                      </span>
                    )}
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="py-2 text-center text-sm text-[var(--cf-fg-subtle)]">
              <p>No readings logged</p>
              {onLogVital && (
                <button
                  type="button"
                  onClick={() => onLogVital('weight')}
                  className="mt-2 text-xs font-semibold text-[var(--cf-primary)] hover:underline inline-flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> Log Weight
                </button>
              )}
            </div>
          )}
        </div>
        <div className="pt-3 mt-3 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)] truncate">
          {formatTime(vitals.weight?.effectiveAt)}
        </div>
      </Card>
    </div>
  );
}
