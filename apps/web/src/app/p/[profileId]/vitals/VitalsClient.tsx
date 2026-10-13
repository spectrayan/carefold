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

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  HeartPulse,
  Plus,
  Eye,
  EyeOff,
  RefreshCw,
  Loader2,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ScopedStorage } from '@/lib/storageNamespace';
import {
  VitalsSummaryCards,
  DiurnalTrendTable,
  BloodPressureTrendChart,
  LogVitalsModal,
} from '@/components/vitals';
import {
  fetchVitalsObservations,
  fetchVitalsTrends,
  extractLatestVitals,
} from '@/lib/vitalsClient';
import type {
  VitalsObservationItem,
  VitalsTrendsResponse,
  LatestVitalsState,
} from '@/types/vitals';
import type { BpChartPoint } from '@/components/vitals/BloodPressureTrendChart';

export interface VitalsClientProps {
  profileId: string;
}

export function VitalsClient({ profileId }: VitalsClientProps) {
  const [observations, setObservations] = useState<VitalsObservationItem[]>([]);
  const [trends, setTrends] = useState<VitalsTrendsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLogModalOpen, setIsLogModalOpen] = useState(false);
  const [hideWeight, setHideWeight] = useState(false);

  // Storage key for hide_weight persistence
  const storageKey = `vitals_hide_weight_${profileId}`;

  useEffect(() => {
    try {
      const storage = new ScopedStorage();
      const saved = storage.getItem(storageKey, false);
      if (saved) setHideWeight(Boolean(saved));
    } catch {
      // Graceful fallback
    }
  }, [storageKey]);

  const handleToggleHideWeight = () => {
    setHideWeight((prev) => {
      const next = !prev;
      try {
        const storage = new ScopedStorage();
        storage.setItem(storageKey, next);
      } catch {}
      return next;
    });
  };

  const loadData = useCallback(async () => {
    setError(null);
    try {
      const [obsRes, trendRes] = await Promise.all([
        fetchVitalsObservations(profileId, { limit: 100 }),
        fetchVitalsTrends(profileId).catch(() => null),
      ]);
      setObservations(obsRes.observations || []);
      setTrends(trendRes);
    } catch (err: any) {
      setError(err.message || 'Failed to load vitals data.');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [profileId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    loadData();
  };

  // Derive latest readings for summary cards
  const latestVitals: LatestVitalsState = useMemo(() => {
    return extractLatestVitals(observations);
  }, [observations]);

  // Derive BP points for trend chart
  const bpChartPoints: BpChartPoint[] = useMemo(() => {
    const bpObs = observations.filter((o) => {
      const code = o.data?.code?.coding?.[0]?.code;
      return code === '85354-9' || o.data?.component?.length >= 2;
    });

    return bpObs.map((o) => {
      const components = o.data?.component || [];
      let sys = 0;
      let dia = 0;
      for (const c of components) {
        const cCode = c.code?.coding?.[0]?.code;
        if (cCode === '8480-6') sys = c.valueQuantity?.value;
        if (cCode === '8462-4') dia = c.valueQuantity?.value;
      }
      const d = new Date(o.effective_at);
      const hour = d.getHours();
      const isAM = hour >= 5 && hour < 12;

      return {
        id: o.id,
        timestamp: o.effective_at,
        systolic: sys,
        diastolic: dia,
        isAM,
        classification: o.data?.interpretation?.[0]?.text,
      };
    }).filter((pt) => pt.systolic > 0 && pt.diastolic > 0);
  }, [observations]);

  return (
    <div className="space-y-6 max-w-7xl mx-auto py-2">
      {/* Top Header Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[var(--cf-border)]">
        <div>
          <h1
            data-testid="vitals-page-heading"
            className="text-2xl font-bold tracking-tight text-[var(--cf-fg)] flex items-center gap-2.5"
          >
            <HeartPulse className="w-6 h-6 text-rose-500" />
            Vitals & Biometrics
          </h1>
          <p className="text-xs sm:text-sm text-[var(--cf-fg-muted)] mt-1">
            Track physiological vital signs, diurnal blood pressure trends, and clinical safety thresholds.
          </p>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          {/* Privacy Toggle Button */}
          <button
            type="button"
            data-testid="privacy-hide-weight-btn"
            onClick={handleToggleHideWeight}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-semibold text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition-colors min-h-[40px]"
            title={hideWeight ? 'Reveal Weight & BMI' : 'Mask Weight & BMI'}
          >
            {hideWeight ? <EyeOff className="w-4 h-4 text-amber-500" /> : <Eye className="w-4 h-4" />}
            <span>{hideWeight ? 'Weight Hidden' : 'Hide Weight'}</span>
          </button>

          {/* Refresh Button */}
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="p-2 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition-colors min-h-[40px] min-w-[40px] flex items-center justify-center"
            title="Refresh vitals"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>

          {/* Log Vitals Modal Trigger */}
          <Button
            data-testid="log-vitals-open-btn"
            onClick={() => setIsLogModalOpen(true)}
            className="min-h-[40px]"
          >
            <Plus className="w-4 h-4 mr-1.5" />
            Log Reading
          </Button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-300 dark:border-rose-900 text-rose-800 dark:text-rose-200 text-xs">
          {error}
        </div>
      )}

      {isLoading ? (
        <div className="py-20 flex flex-col items-center justify-center gap-3 text-[var(--cf-fg-subtle)]">
          <Loader2 className="w-8 h-8 animate-spin text-[var(--cf-primary)]" />
          <p className="text-sm">Loading physiological records...</p>
        </div>
      ) : (
        <>
          {/* Summary Cards Grid */}
          <VitalsSummaryCards
            vitals={latestVitals}
            hideWeight={hideWeight}
            onToggleHideWeight={handleToggleHideWeight}
            onLogVital={() => setIsLogModalOpen(true)}
          />

          {/* Blood Pressure Trend Chart */}
          <BloodPressureTrendChart points={bpChartPoints} />

          {/* Diurnal Trend Table */}
          <DiurnalTrendTable trends={trends} />
        </>
      )}

      {/* Log Vitals Modal */}
      <LogVitalsModal
        isOpen={isLogModalOpen}
        onOpenChange={setIsLogModalOpen}
        profileId={profileId}
        onSuccess={loadData}
      />
    </div>
  );
}
