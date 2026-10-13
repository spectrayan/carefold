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

import React, { useState, useMemo } from 'react';
import { Sun, Moon } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { cn } from '@/lib/utils';

export interface BpChartPoint {
  id: string;
  timestamp: string; // ISO UTC
  systolic: number;
  diastolic: number;
  isAM: boolean;
  classification?: string;
}

export interface BloodPressureTrendChartProps {
  points?: BpChartPoint[];
  className?: string;
}

export function BloodPressureTrendChart({
  points = [],
  className,
}: BloodPressureTrendChartProps) {
  const [hoveredPoint, setHoveredPoint] = useState<BpChartPoint | null>(null);

  // SVG Dimension Constants
  const width = 640;
  const height = 260;
  const padding = { top: 25, right: 30, bottom: 40, left: 45 };

  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  // Y-Scale: 50 mmHg to 200 mmHg
  const minY = 50;
  const maxY = 200;
  const getY = (val: number) => {
    const clamped = Math.max(minY, Math.min(maxY, val));
    return padding.top + plotHeight - ((clamped - minY) / (maxY - minY)) * plotHeight;
  };

  // Chronologically sort points
  const sortedPoints = useMemo(() => {
    return [...points].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
  }, [points]);

  // X-Scale: distribute evenly
  const getX = (idx: number, total: number) => {
    if (total <= 1) return padding.left + plotWidth / 2;
    return padding.left + (idx / (total - 1)) * plotWidth;
  };

  return (
    <Card
      data-testid="bp-trend-chart-container"
      className={cn('p-5 shadow-sm relative', className)}
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 gap-2 border-b border-[var(--cf-border)] mb-3">
        <div>
          <h3 className="font-semibold text-base text-[var(--cf-fg)]">
            Blood Pressure History & Target Range
          </h3>
          <p className="text-xs text-[var(--cf-fg-muted)]">
            Systolic and diastolic readings with diurnal AM/PM markers and clinical thresholds.
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs text-[var(--cf-fg-muted)]">
          <span className="inline-flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500" /> Morning (AM)
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-indigo-500" /> Evening (PM)
          </span>
        </div>
      </div>

      {sortedPoints.length === 0 ? (
        <div
          data-testid="bp-chart-empty"
          className="py-16 text-center text-sm text-[var(--cf-fg-subtle)] flex flex-col items-center justify-center gap-1"
        >
          <p className="font-medium text-[var(--cf-fg-muted)]">No blood pressure observations to plot</p>
          <p className="text-xs">Log readings to view systolic/diastolic trends over time.</p>
        </div>
      ) : (
        <div className="relative w-full aspect-[2.4/1] min-h-[220px]">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="w-full h-full select-none overflow-visible"
            role="img"
            aria-label="Blood pressure trends chart showing systolic and diastolic readings"
          >
            {/* 1. Target Normal Zone (SBP < 120, DBP < 80) Soft Emerald Tint */}
            <rect
              x={padding.left}
              y={getY(120)}
              width={plotWidth}
              height={getY(60) - getY(120)}
              fill="rgba(16, 185, 129, 0.07)"
              rx="4"
            />

            {/* 2. Grid lines & Reference Thresholds */}
            {[60, 80, 100, 120, 140, 180].map((val) => {
              const y = getY(val);
              const isCrisis = val === 180;
              const isStage2 = val === 140;
              const isElevated = val === 120;
              return (
                <g key={val}>
                  <line
                    x1={padding.left}
                    y1={y}
                    x2={width - padding.right}
                    y2={y}
                    stroke={
                      isCrisis
                        ? 'rgba(239, 68, 68, 0.5)'
                        : isStage2
                        ? 'rgba(249, 115, 22, 0.35)'
                        : isElevated
                        ? 'rgba(245, 158, 11, 0.25)'
                        : 'var(--cf-border)'
                    }
                    strokeDasharray={isCrisis || isStage2 ? '4 4' : undefined}
                    strokeWidth="1"
                  />
                  <text
                    x={padding.left - 8}
                    y={y + 3.5}
                    textAnchor="end"
                    className={cn(
                      'text-[10px] font-mono select-none',
                      isCrisis
                        ? 'fill-red-500 font-semibold'
                        : isStage2
                        ? 'fill-amber-600 font-medium'
                        : 'fill-[var(--cf-fg-subtle)]'
                    )}
                  >
                    {val}
                  </text>
                </g>
              );
            })}

            {/* 3. Range Bars & Points */}
            {sortedPoints.map((pt, idx) => {
              const x = getX(idx, sortedPoints.length);
              const ySys = getY(pt.systolic);
              const yDia = getY(pt.diastolic);
              const isHovered = hoveredPoint?.id === pt.id;
              const color = pt.isAM ? '#f59e0b' : '#6366f1';

              return (
                <g
                  key={pt.id || idx}
                  data-testid={`bp-chart-point-${idx}`}
                  onMouseEnter={() => setHoveredPoint(pt)}
                  onMouseLeave={() => setHoveredPoint(null)}
                  className="cursor-pointer transition-opacity"
                >
                  {/* Vertical Connector Candle Bar */}
                  <line
                    x1={x}
                    y1={ySys}
                    x2={x}
                    y2={yDia}
                    stroke={color}
                    strokeWidth={isHovered ? '3.5' : '2'}
                    strokeLinecap="round"
                    opacity={isHovered ? 1 : 0.8}
                  />
                  {/* Systolic Top Marker */}
                  <circle
                    cx={x}
                    cy={ySys}
                    r={isHovered ? 5.5 : 4}
                    fill={color}
                    stroke="var(--cf-surface)"
                    strokeWidth="1.5"
                  />
                  {/* Diastolic Bottom Marker */}
                  <circle
                    cx={x}
                    cy={yDia}
                    r={isHovered ? 4.5 : 3}
                    fill={color}
                    stroke="var(--cf-surface)"
                    strokeWidth="1.5"
                  />
                </g>
              );
            })}
          </svg>

          {/* 4. Interactive Hover Popover Tooltip */}
          {hoveredPoint && (
            <div
              data-testid="bp-chart-tooltip"
              className="absolute z-20 pointer-events-none transform -translate-x-1/2 -translate-y-full mb-3 bg-[var(--cf-surface)] border border-[var(--cf-border)] rounded-lg shadow-lg p-2.5 text-xs text-[var(--cf-fg)] whitespace-nowrap"
              style={{
                left: `${(getX(sortedPoints.indexOf(hoveredPoint), sortedPoints.length) / width) * 100}%`,
                top: `${(getY(hoveredPoint.systolic) / height) * 100}%`,
              }}
            >
              <div className="font-semibold flex items-center gap-1.5">
                {hoveredPoint.isAM ? (
                  <Sun className="w-3.5 h-3.5 text-amber-500" />
                ) : (
                  <Moon className="w-3.5 h-3.5 text-indigo-500" />
                )}
                <span>
                  {hoveredPoint.systolic} / {hoveredPoint.diastolic} mmHg
                </span>
              </div>
              <div className="text-[var(--cf-fg-muted)] text-[11px] mt-0.5">
                {new Date(hoveredPoint.timestamp).toLocaleString(undefined, {
                  month: 'short',
                  day: 'numeric',
                  hour: 'numeric',
                  minute: '2-digit',
                })}
              </div>
              {hoveredPoint.classification && (
                <div className="mt-1 font-semibold text-[var(--cf-primary)] text-[11px]">
                  {hoveredPoint.classification}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
