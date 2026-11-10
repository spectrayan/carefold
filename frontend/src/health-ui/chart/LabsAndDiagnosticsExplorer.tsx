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
  FlaskConical,
  ArrowLeftRight,
  ListPlus,
  CheckCircle2,
  History,
  TrendingUp,
} from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription } from '../../components/ui/Card';
import { Badge, type BadgeVariant } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { cn } from '../../lib/utils';
import { formatProvenanceBadge } from '../../lib/ehrChartClient';
import type {
  EhrLabPanelGroup,
  EhrLabObservationItem,
  EhrClinicalItemBase,
  EhrReferenceFlag,
} from '../../types/ehrChart';

export interface LabsAndDiagnosticsExplorerProps {
  labPanels: EhrLabPanelGroup[];
  stagedObservationIds?: ReadonlySet<string>;
  onStageQuestion: (observation: EhrLabObservationItem) => void;
  onInspectItem: (item: EhrClinicalItemBase) => void;
  className?: string;
}

type CategoryFilter = 'all' | 'metabolic' | 'lipids' | 'endocrine' | 'hematology';

function referenceFlagVariant(flag: EhrReferenceFlag): BadgeVariant {
  if (flag === 'Normal') return 'success';
  if (flag === 'High') return 'warning';
  return 'danger';
}

export function LabsAndDiagnosticsExplorer({
  labPanels,
  stagedObservationIds,
  onStageQuestion,
  onInspectItem,
  className,
}: LabsAndDiagnosticsExplorerProps) {
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all');
  const [abnormalOnly, setAbnormalOnly] = useState<boolean>(false);
  const [alternateUnitIds, setAlternateUnitIds] = useState<Record<string, boolean>>({});

  const toggleUnitSystem = (obsId: string) => {
    setAlternateUnitIds((prev) => ({
      ...prev,
      [obsId]: !prev[obsId],
    }));
  };

  const filteredPanels = labPanels
    .filter((panel) => categoryFilter === 'all' || panel.categoryKey === categoryFilter)
    .map((panel) => ({
      ...panel,
      observations: panel.observations.filter((obs) => !abnormalOnly || obs.flag !== 'Normal'),
    }))
    .filter((panel) => panel.observations.length > 0);

  return (
    <div
      data-testid="labs-diagnostics-explorer"
      className={cn('space-y-5 text-start', className)}
    >
      {/* Filter & Unit Controls Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-[var(--cf-radius-lg)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)]">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter laboratory panels by category">
          {(
            [
              { id: 'all', label: 'All Panels' },
              { id: 'endocrine', label: 'Glycemic & Endocrine' },
              { id: 'metabolic', label: 'Metabolic (CMP)' },
              { id: 'lipids', label: 'Lipid Panel' },
            ] as const
          ).map((tab) => (
            <Button
              key={tab.id}
              variant={categoryFilter === tab.id ? 'primary' : 'secondary'}
              size="sm"
              data-testid={`labs-category-filter-${tab.id}`}
              onClick={() => setCategoryFilter(tab.id)}
            >
              {tab.label}
            </Button>
          ))}
        </div>

        <Button
          variant={abnormalOnly ? 'primary' : 'outline'}
          size="sm"
          data-testid="labs-abnormal-only-toggle"
          aria-pressed={abnormalOnly}
          onClick={() => setAbnormalOnly((prev) => !prev)}
        >
          {abnormalOnly ? 'Showing Out-of-Range Only' : 'Filter Out-of-Range Flags'}
        </Button>
      </div>

      {/* LOINC Grouped Diagnostic Panels */}
      {filteredPanels.map((panel) => (
        <Card
          key={panel.panelId}
          data-testid={`lab-panel-card-${panel.panelId}`}
          className="p-5 space-y-4"
        >
          <CardHeader className="pb-2 border-b border-[var(--cf-border)]">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <FlaskConical
                  className="w-4 h-4 text-[var(--cf-primary)] shrink-0"
                  aria-hidden="true"
                />
                <CardTitle as="h3" className="text-base">
                  {panel.panelTitle}
                </CardTitle>
                <Badge variant="info" size="sm" data-testid={`panel-loinc-${panel.panelId}`}>
                  LOINC {panel.panelLoincCode}
                </Badge>
              </div>
              <span className="text-xs text-[var(--cf-fg-subtle)]">
                {formatProvenanceBadge(panel.provenance.sourceName, panel.provenance.recordedDate)}
              </span>
            </div>
            <CardDescription>
              Laboratory reference range flags are informational indicators reported by the performing laboratory.
            </CardDescription>
          </CardHeader>

          <div className="space-y-4">
            {panel.observations.map((obs) => {
              const useAlt = Boolean(alternateUnitIds[obs.id] && obs.alternateMeasurement);
              const activeMeasurement =
                useAlt && obs.alternateMeasurement
                  ? obs.alternateMeasurement
                  : obs.canonicalMeasurement;
              const isStaged = Boolean(stagedObservationIds?.has(obs.id));
              const captionId = `trend-caption-${obs.id}`;

              return (
                <div
                  key={obs.id}
                  data-testid={`lab-observation-card-${obs.id}`}
                  className="p-4 rounded-[var(--cf-radius-md)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-3"
                >
                  {/* Top Row: Analyte Name, Reference Range Flag Badge, Current Value & Unit Toggle */}
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className="text-sm font-semibold text-[var(--cf-fg)]">{obs.title}</h4>
                        <Badge
                          data-testid={`lab-flag-badge-${obs.id}`}
                          variant={referenceFlagVariant(obs.flag)}
                          size="sm"
                        >
                          {obs.flag} Reference Flag
                        </Badge>
                      </div>
                      {obs.subtitle && (
                        <p className="text-xs text-[var(--cf-fg-muted)]">{obs.subtitle}</p>
                      )}
                      <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                        {obs.codings.map((coding) => (
                          <Badge
                            key={`${coding.systemLabel}-${coding.code}`}
                            variant="info"
                            size="sm"
                            data-testid={`lab-coding-${obs.id}-${coding.systemLabel}`}
                          >
                            {coding.systemLabel} {coding.code}
                          </Badge>
                        ))}
                      </div>
                    </div>

                    <div className="flex flex-col items-end gap-1.5 text-end">
                      <div className="flex items-baseline gap-1.5">
                        <span
                          data-testid={`lab-value-${obs.id}`}
                          className="text-xl font-bold font-mono text-[var(--cf-fg)]"
                        >
                          {activeMeasurement.value}
                        </span>
                        <span
                          data-testid={`lab-unit-${obs.id}`}
                          className="text-xs font-mono text-[var(--cf-fg-subtle)]"
                        >
                          {activeMeasurement.unitDisplay}
                        </span>
                      </div>
                      <span
                        data-testid={`lab-ref-range-${obs.id}`}
                        className="text-xs text-[var(--cf-fg-muted)]"
                      >
                        Ref Range: {activeMeasurement.referenceRangeText}
                      </span>
                      {obs.alternateMeasurement && (
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid={`lab-unit-toggle-${obs.id}`}
                          onClick={() => toggleUnitSystem(obs.id)}
                        >
                          <ArrowLeftRight className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
                          {useAlt
                            ? `Switch to ${obs.canonicalMeasurement.unitDisplay}`
                            : `Switch to ${obs.alternateMeasurement.unitDisplay}`}
                        </Button>
                      )}
                    </div>
                  </div>

                  {/* Accessible Responsive Longitudinal Trend Table (modern-web-guidance: responsive-table) */}
                  <div
                    tabIndex={0}
                    role="region"
                    aria-labelledby={captionId}
                    data-testid={`lab-trend-region-${obs.id}`}
                    className="overflow-auto max-w-full rounded-[var(--cf-radius-md)] border border-[var(--cf-border)] bg-[var(--cf-surface)]"
                  >
                    <table className="w-full text-xs border-separate border-spacing-0">
                      <caption
                        id={captionId}
                        className="px-3 py-2 text-start font-medium text-[var(--cf-fg-muted)] bg-[var(--cf-surface-2)] border-b border-[var(--cf-border)]"
                      >
                        <span className="inline-flex items-center gap-1.5">
                          <TrendingUp className="w-3.5 h-3.5 text-[var(--cf-primary)]" aria-hidden="true" />
                          Longitudinal Trend ({activeMeasurement.unitDisplay})
                        </span>
                      </caption>
                      <thead className="sticky inset-block-start-0 z-10 bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)]">
                        <tr>
                          <th scope="col" className="px-3 py-2 text-start font-semibold border-b border-[var(--cf-border)]">
                            Date
                          </th>
                          <th scope="col" className="px-3 py-2 text-start font-semibold border-b border-[var(--cf-border)]">
                            Result ({activeMeasurement.unitDisplay})
                          </th>
                          <th scope="col" className="px-3 py-2 text-start font-semibold border-b border-[var(--cf-border)]">
                            Reference Flag
                          </th>
                          <th scope="col" className="px-3 py-2 text-start font-semibold border-b border-[var(--cf-border)]">
                            Reporting Source
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {obs.trend.map((pt) => {
                          const displayVal =
                            useAlt && pt.alternateValue !== undefined
                              ? pt.alternateValue
                              : pt.canonicalValue;
                          return (
                            <tr key={`${obs.id}-${pt.date}`}>
                              <th
                                scope="row"
                                className="sticky inset-inline-start-0 bg-[var(--cf-surface)] px-3 py-2 text-start font-mono font-medium text-[var(--cf-fg)] border-b border-[var(--cf-border)]"
                              >
                                {pt.date}
                              </th>
                              <td className="px-3 py-2 font-mono font-semibold text-[var(--cf-fg)] border-b border-[var(--cf-border)]">
                                {displayVal} {activeMeasurement.unitDisplay}
                              </td>
                              <td className="px-3 py-2 border-b border-[var(--cf-border)]">
                                <Badge variant={referenceFlagVariant(pt.flag)} size="sm">
                                  {pt.flag}
                                </Badge>
                              </td>
                              <td className="px-3 py-2 text-[var(--cf-fg-muted)] border-b border-[var(--cf-border)]">
                                {pt.sourceName}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* Bottom Action & Provenance Bar: Stage Question for Visit + Provenance/_history Inspector */}
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[var(--cf-border)]">
                    <span
                      data-testid={`provenance-badge-${obs.id}`}
                      className="text-xs text-[var(--cf-fg-subtle)]"
                    >
                      {formatProvenanceBadge(obs.provenance.sourceName, obs.provenance.recordedDate)}
                    </span>

                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        variant={isStaged ? 'secondary' : 'primary'}
                        size="sm"
                        data-testid={`stage-question-btn-${obs.id}`}
                        onClick={() => onStageQuestion(obs)}
                      >
                        {isStaged ? (
                          <>
                            <CheckCircle2 className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
                            Staged for Visit
                          </>
                        ) : (
                          <>
                            <ListPlus className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
                            Stage Question for Visit
                          </>
                        )}
                      </Button>

                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid={`inspect-item-btn-${obs.id}`}
                        onClick={() => onInspectItem(obs)}
                      >
                        <History className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
                        Provenance &amp; v{obs.provenance.versionId}
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      ))}
    </div>
  );
}
