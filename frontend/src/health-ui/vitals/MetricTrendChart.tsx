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

import React, { useState, useMemo } from 'react';
import { Activity, Droplets, Heart, Scale, Wind, Thermometer } from 'lucide-react';
import { Card } from '../../components/ui/Card';
import type { VitalsObservationItem } from '../../types/vitals';

export interface MetricTrendChartProps {
  observations: VitalsObservationItem[];
  className?: string;
}

export type SupportedMetric =
  | 'heart_rate'
  | 'spo2'
  | 'glucose'
  | 'weight'
  | 'temperature'
  | 'respiratory_rate';

interface MetricConfig {
  id: SupportedMetric;
  label: string;
  unit: string;
  loinc: string;
  icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  color: string;
  minRange: number;
  maxRange: number;
}

const METRICS_CONFIG: MetricConfig[] = [
  {
    id: 'heart_rate',
    label: 'Heart Rate',
    unit: 'bpm',
    loinc: '8867-4',
    icon: Heart,
    color: '#ef4444',
    minRange: 40,
    maxRange: 160,
  },
  {
    id: 'spo2',
    label: 'Oxygen (SpO2)',
    unit: '%',
    loinc: '2708-6',
    icon: Wind,
    color: '#06b6d4',
    minRange: 80,
    maxRange: 100,
  },
  {
    id: 'glucose',
    label: 'Blood Glucose',
    unit: 'mg/dL',
    loinc: '2339-0',
    icon: Droplets,
    color: '#8b5cf6',
    minRange: 40,
    maxRange: 250,
  },
  {
    id: 'weight',
    label: 'Body Weight',
    unit: 'kg',
    loinc: '29463-7',
    icon: Scale,
    color: '#10b981',
    minRange: 40,
    maxRange: 140,
  },
  {
    id: 'temperature',
    label: 'Temperature',
    unit: '°F',
    loinc: '8310-5',
    icon: Thermometer,
    color: '#f97316',
    minRange: 94,
    maxRange: 104,
  },
  {
    id: 'respiratory_rate',
    label: 'Respiratory Rate',
    unit: 'br/min',
    loinc: '9279-1',
    icon: Activity,
    color: '#3b82f6',
    minRange: 8,
    maxRange: 32,
  },
];

export function MetricTrendChart({ observations, className }: MetricTrendChartProps) {
  const [selectedMetric, setSelectedMetric] = useState<SupportedMetric>('heart_rate');
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const activeConfig = useMemo(
    () => METRICS_CONFIG.find((m) => m.id === selectedMetric) || METRICS_CONFIG[0],
    [selectedMetric]
  );

  // Extract points for active metric
  const points = useMemo(() => {
    const pts: { id: string; date: Date; timestamp: string; value: number }[] = [];
    for (const obs of observations) {
      const code = obs.data?.code?.coding?.[0]?.code;
      if (code === activeConfig.loinc) {
        const val = obs.data?.valueQuantity?.value;
        if (typeof val === 'number') {
          pts.push({
            id: obs.id,
            date: new Date(obs.effective_at),
            timestamp: obs.effective_at,
            value: val,
          });
        }
      }
    }
    // Sort chronologically ascending
    pts.sort((a, b) => a.date.getTime() - b.date.getTime());
    return pts;
  }, [observations, activeConfig]);

  // Statistics calculation
  const stats = useMemo(() => {
    if (points.length === 0) return null;
    const values = points.map((p) => p.value);
    const mean = Number((values.reduce((acc, v) => acc + v, 0) / values.length).toFixed(1));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const latest = values[values.length - 1];
    return { count: values.length, mean, min, max, latest };
  }, [points]);

  // SVG dimensions
  const width = 640;
  const height = 220;
  const padding = { top: 20, right: 30, bottom: 35, left: 45 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const yDomain = useMemo(() => {
    if (points.length === 0) return [activeConfig.minRange, activeConfig.maxRange];
    const vals = points.map((p) => p.value);
    const minVal = Math.min(...vals, activeConfig.minRange);
    const maxVal = Math.max(...vals, activeConfig.maxRange);
    const margin = (maxVal - minVal) * 0.1 || 5;
    return [Math.floor(minVal - margin), Math.ceil(maxVal + margin)];
  }, [points, activeConfig]);

  const getY = (val: number) => {
    const [minY, maxY] = yDomain;
    const clamped = Math.max(minY, Math.min(maxY, val));
    return padding.top + plotHeight - ((clamped - minY) / (maxY - minY)) * plotHeight;
  };

  const getX = (idx: number, total: number) => {
    if (total <= 1) return padding.left + plotWidth / 2;
    return padding.left + (idx / (total - 1)) * plotWidth;
  };

  // Generate SVG path string
  const pathD = useMemo(() => {
    if (points.length < 2) return '';
    return points
      .map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${getX(idx, points.length).toFixed(1)} ${getY(p.value).toFixed(1)}`)
      .join(' ');
  }, [points, yDomain]);

  return (
    <Card
      data-testid="metric-trend-chart-container"
      className={`p-5 shadow-sm relative ${className || ''}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 gap-3 border-b border-[var(--cf-border)] mb-4">
        <div>
          <h3 className="font-semibold text-base text-[var(--cf-fg)] flex items-center gap-2">
            <activeConfig.icon className="w-5 h-5" style={{ color: activeConfig.color }} />
            {activeConfig.label} Trends
          </h3>
          <p className="text-xs text-[var(--cf-fg-muted)]">
            Historical observations and moving trajectory
          </p>
        </div>

        {/* Metric Selector Chips */}
        <div
          data-testid="metric-trend-selector"
          className="flex flex-wrap gap-1.5 p-1 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-xs"
        >
          {METRICS_CONFIG.map((cfg) => {
            const isSelected = cfg.id === selectedMetric;
            return (
              <button
                key={cfg.id}
                type="button"
                data-testid={`metric-tab-${cfg.id}`}
                onClick={() => setSelectedMetric(cfg.id)}
                className={`px-2.5 py-1 rounded-lg font-medium transition-all ${
                  isSelected
                    ? 'bg-[var(--cf-surface)] text-[var(--cf-fg)] shadow-xs border border-[var(--cf-border)]'
                    : 'text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-3)]'
                }`}
              >
                {cfg.label.split(' ')[0]}
              </button>
            );
          })}
        </div>
      </div>

      {/* Summary Statistics Ribbon */}
      {stats && (
        <div
          data-testid="metric-trend-stats"
          className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4 text-xs"
        >
          <div className="p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)]">
            <span className="text-[var(--cf-fg-subtle)] block text-[11px]">Latest</span>
            <span className="text-base font-bold text-[var(--cf-fg)] font-mono">
              {stats.latest} <span className="text-xs font-normal text-[var(--cf-fg-muted)]">{activeConfig.unit}</span>
            </span>
          </div>
          <div className="p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)]">
            <span className="text-[var(--cf-fg-subtle)] block text-[11px]">Average</span>
            <span className="text-base font-bold text-[var(--cf-fg)] font-mono">
              {stats.mean} <span className="text-xs font-normal text-[var(--cf-fg-muted)]">{activeConfig.unit}</span>
            </span>
          </div>
          <div className="p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)]">
            <span className="text-[var(--cf-fg-subtle)] block text-[11px]">Range</span>
            <span className="text-base font-bold text-[var(--cf-fg)] font-mono">
              {stats.min} – {stats.max}
            </span>
          </div>
          <div className="p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)]">
            <span className="text-[var(--cf-fg-subtle)] block text-[11px]">Readings</span>
            <span className="text-base font-bold text-[var(--cf-fg)] font-mono">
              {stats.count}
            </span>
          </div>
        </div>
      )}

      {/* SVG Sparkline/Chart */}
      {points.length === 0 ? (
        <div className="py-12 text-center text-xs text-[var(--cf-fg-subtle)]">
          No historical {activeConfig.label.toLowerCase()} observations recorded yet.
        </div>
      ) : (
        <div className="relative w-full overflow-x-auto">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="w-full h-auto max-h-[220px] select-none"
            aria-label={`${activeConfig.label} trend chart`}
          >
            {/* Gridlines */}
            {[0, 0.25, 0.5, 0.75, 1].map((pct) => {
              const y = padding.top + plotHeight * pct;
              const val = Math.round(yDomain[1] - pct * (yDomain[1] - yDomain[0]));
              return (
                <g key={pct}>
                  <line
                    x1={padding.left}
                    y1={y}
                    x2={width - padding.right}
                    y2={y}
                    stroke="var(--cf-border)"
                    strokeDasharray="3 3"
                    strokeWidth={0.8}
                  />
                  <text
                    x={padding.left - 8}
                    y={y + 3}
                    textAnchor="end"
                    className="text-[10px] fill-[var(--cf-fg-subtle)] font-mono"
                  >
                    {val}
                  </text>
                </g>
              );
            })}

            {/* Line Path */}
            {pathD && (
              <path
                d={pathD}
                fill="none"
                stroke={activeConfig.color}
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            )}

            {/* Data Points */}
            {points.map((pt, idx) => {
              const cx = getX(idx, points.length);
              const cy = getY(pt.value);
              const isHovered = hoveredIndex === idx;

              return (
                <g
                  key={pt.id || idx}
                  className="cursor-pointer"
                  onMouseEnter={() => setHoveredIndex(idx)}
                  onMouseLeave={() => setHoveredIndex(null)}
                >
                  <circle
                    cx={cx}
                    cy={cy}
                    r={isHovered ? 6 : 4}
                    fill={activeConfig.color}
                    stroke="var(--cf-surface)"
                    strokeWidth={2}
                    className="transition-all"
                  />
                  {isHovered && (
                    <g>
                      <rect
                        x={Math.max(10, Math.min(width - 90, cx - 45))}
                        y={Math.max(5, cy - 35)}
                        width={90}
                        height={24}
                        rx={6}
                        fill="var(--cf-fg)"
                        className="opacity-90"
                      />
                      <text
                        x={Math.max(10, Math.min(width - 90, cx - 45)) + 45}
                        y={Math.max(5, cy - 35) + 16}
                        textAnchor="middle"
                        fill="var(--cf-surface)"
                        className="text-[11px] font-mono font-bold"
                      >
                        {pt.value} {activeConfig.unit}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </Card>
  );
}
