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
  Pill,
  AlertTriangle,
  Syringe,
  Calendar,
  History,
  GitMerge,
} from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription } from '../../components/ui/Card';
import { Badge, type BadgeVariant } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { cn } from '../../lib/utils';
import { formatProvenanceBadge } from '../../lib/ehrChartClient';
import type {
  EhrChartSnapshot,
  EhrClinicalItemBase,
  EhrAllergyItem,
} from '../../types/ehrChart';

export interface IpsPatientSummaryTabProps {
  snapshot: EhrChartSnapshot;
  onInspectItem: (item: EhrClinicalItemBase) => void;
  className?: string;
}

function allergyCriticalityVariant(criticality: EhrAllergyItem['criticality']): BadgeVariant {
  if (criticality === 'High') return 'danger';
  if (criticality === 'Low') return 'warning';
  return 'neutral';
}

export function IpsPatientSummaryTab({
  snapshot,
  onInspectItem,
  className,
}: IpsPatientSummaryTabProps) {
  return (
    <div
      data-testid="ips-patient-summary-tab"
      className={cn('space-y-6 text-start', className)}
    >
      {/* IPS Header Metadata Banner */}
      <div
        data-testid="ips-composition-banner"
        className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-[var(--cf-radius-lg)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)]"
      >
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-[var(--cf-fg)]">
              HL7 International Patient Summary (IPS)
            </span>
            <Badge variant="info" size="sm" data-testid="ips-loinc-badge">
              LOINC {snapshot.ipsCompositionLoinc}
            </Badge>
          </div>
          <p className="text-xs text-[var(--cf-fg-muted)]">
            Structured longitudinal clinical summary across Active Problems, Medications, Allergies,
            Immunizations, and Encounters. Click any record to inspect source provenance and{' '}
            <code className="font-mono">_history</code> revisions.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* 1. Active Problems / Conditions (LOINC 11450-4) */}
        <Card data-testid="ips-conditions-card" className="p-5 space-y-4">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-[var(--cf-primary)] shrink-0" aria-hidden="true" />
                <CardTitle as="h3" className="text-base">
                  Active Problems &amp; Conditions
                </CardTitle>
              </div>
              <Badge variant="neutral" size="sm">
                LOINC 11450-4 · {snapshot.conditions.length}
              </Badge>
            </div>
            <CardDescription>
              Documented clinical conditions with ICD-10-CM and SNOMED CT coding.
            </CardDescription>
          </CardHeader>

          <div className="space-y-3">
            {snapshot.conditions.map((cond) => (
              <div
                key={cond.id}
                data-testid={`ips-condition-item-${cond.id}`}
                className="p-3.5 rounded-[var(--cf-radius-md)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-2.5"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="space-y-0.5">
                    <h4 className="text-sm font-semibold text-[var(--cf-fg)]">{cond.title}</h4>
                    {cond.subtitle && (
                      <p className="text-xs text-[var(--cf-fg-muted)]">{cond.subtitle}</p>
                    )}
                  </div>
                  <Badge
                    variant={cond.clinicalStatus === 'Active' ? 'success' : 'neutral'}
                    size="sm"
                  >
                    {cond.clinicalStatus}
                  </Badge>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {cond.codings.map((coding) => (
                    <Badge
                      key={`${coding.systemLabel}-${coding.code}`}
                      variant="info"
                      size="sm"
                      data-testid={`coding-badge-${coding.systemLabel}-${coding.code}`}
                    >
                      {coding.systemLabel} {coding.code}
                    </Badge>
                  ))}
                  {cond.provenance.mergedPortals && cond.provenance.mergedPortals.length > 1 && (
                    <Badge variant="warning" size="sm">
                      <GitMerge className="w-3 h-3 me-1 inline" aria-hidden="true" />
                      Merged ({cond.provenance.mergedPortals.length} sources)
                    </Badge>
                  )}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)]">
                  <span data-testid={`provenance-badge-${cond.id}`}>
                    {formatProvenanceBadge(cond.provenance.sourceName, cond.provenance.recordedDate)}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    data-testid={`inspect-item-btn-${cond.id}`}
                    onClick={() => onInspectItem(cond)}
                  >
                    <History className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
                    Provenance &amp; v{cond.provenance.versionId}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* 2. Active Medications (LOINC 10160-0) */}
        <Card data-testid="ips-medications-card" className="p-5 space-y-4">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Pill className="w-4 h-4 text-[var(--cf-primary)] shrink-0" aria-hidden="true" />
                <CardTitle as="h3" className="text-base">
                  Active Medications
                </CardTitle>
              </div>
              <Badge variant="neutral" size="sm">
                LOINC 10160-0 · {snapshot.medications.length}
              </Badge>
            </div>
            <CardDescription>
              Reported and prescribed medications normalized to RxNorm concepts.
            </CardDescription>
          </CardHeader>

          <div className="space-y-3">
            {snapshot.medications.map((med) => (
              <div
                key={med.id}
                data-testid={`ips-medication-item-${med.id}`}
                className="p-3.5 rounded-[var(--cf-radius-md)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-2.5"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="space-y-0.5">
                    <h4 className="text-sm font-semibold text-[var(--cf-fg)]">{med.title}</h4>
                    <p className="text-xs text-[var(--cf-fg-muted)]">{med.dosageInstruction}</p>
                    {med.prescriberDisplay && (
                      <p className="text-xs text-[var(--cf-fg-subtle)]">
                        Prescriber: {med.prescriberDisplay}
                      </p>
                    )}
                  </div>
                  <Badge variant={med.status === 'Active' ? 'success' : 'neutral'} size="sm">
                    {med.status}
                  </Badge>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {med.codings.map((coding) => (
                    <Badge
                      key={`${coding.systemLabel}-${coding.code}`}
                      variant="info"
                      size="sm"
                      data-testid={`coding-badge-${coding.systemLabel}-${coding.code}`}
                    >
                      {coding.systemLabel} {coding.code}
                    </Badge>
                  ))}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)]">
                  <span data-testid={`provenance-badge-${med.id}`}>
                    {formatProvenanceBadge(med.provenance.sourceName, med.provenance.recordedDate)}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    data-testid={`inspect-item-btn-${med.id}`}
                    onClick={() => onInspectItem(med)}
                  >
                    <History className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
                    Provenance &amp; v{med.provenance.versionId}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* 3. Allergies & Intolerances (LOINC 48765-2) */}
        <Card data-testid="ips-allergies-card" className="p-5 space-y-4">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-[var(--cf-warn-fg)] shrink-0" aria-hidden="true" />
                <CardTitle as="h3" className="text-base">
                  Allergies &amp; Intolerances
                </CardTitle>
              </div>
              <Badge variant="neutral" size="sm">
                LOINC 48765-2 · {snapshot.allergies.length}
              </Badge>
            </div>
            <CardDescription>
              Documented medication, food, and environmental sensitivities with criticality flags.
            </CardDescription>
          </CardHeader>

          <div className="space-y-3">
            {snapshot.allergies.map((allergy) => (
              <div
                key={allergy.id}
                data-testid={`ips-allergy-item-${allergy.id}`}
                className="p-3.5 rounded-[var(--cf-radius-md)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-2.5"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="space-y-0.5">
                    <h4 className="text-sm font-semibold text-[var(--cf-fg)]">{allergy.title}</h4>
                    <p className="text-xs text-[var(--cf-fg-muted)]">{allergy.reactionSummary}</p>
                  </div>
                  <Badge
                    data-testid={`allergy-criticality-badge-${allergy.id}`}
                    variant={allergyCriticalityVariant(allergy.criticality)}
                    size="sm"
                  >
                    {allergy.criticality} Criticality
                  </Badge>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {allergy.codings.map((coding) => (
                    <Badge
                      key={`${coding.systemLabel}-${coding.code}`}
                      variant="info"
                      size="sm"
                      data-testid={`coding-badge-${coding.systemLabel}-${coding.code}`}
                    >
                      {coding.systemLabel} {coding.code}
                    </Badge>
                  ))}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)]">
                  <span data-testid={`provenance-badge-${allergy.id}`}>
                    {formatProvenanceBadge(
                      allergy.provenance.sourceName,
                      allergy.provenance.recordedDate
                    )}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    data-testid={`inspect-item-btn-${allergy.id}`}
                    onClick={() => onInspectItem(allergy)}
                  >
                    <History className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
                    Provenance &amp; v{allergy.provenance.versionId}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* 4. Immunizations (LOINC 11369-6) & 5. Encounters */}
        <div className="space-y-5">
          <Card data-testid="ips-immunizations-card" className="p-5 space-y-4">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Syringe className="w-4 h-4 text-[var(--cf-primary)] shrink-0" aria-hidden="true" />
                  <CardTitle as="h3" className="text-base">
                    Immunizations
                  </CardTitle>
                </div>
                <Badge variant="neutral" size="sm">
                  LOINC 11369-6 · {snapshot.immunizations.length}
                </Badge>
              </div>
              <CardDescription>
                Vaccination history coded with CDC CVX vaccine identifiers.
              </CardDescription>
            </CardHeader>

            <div className="space-y-3">
              {snapshot.immunizations.map((imm) => (
                <div
                  key={imm.id}
                  data-testid={`ips-immunization-item-${imm.id}`}
                  className="p-3.5 rounded-[var(--cf-radius-md)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-2"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <h4 className="text-sm font-semibold text-[var(--cf-fg)]">{imm.title}</h4>
                      <p className="text-xs text-[var(--cf-fg-muted)]">
                        Administered {imm.administrationDate}
                        {imm.lotNumber ? ` · Lot ${imm.lotNumber}` : ''}
                      </p>
                    </div>
                    <Badge variant="success" size="sm">
                      {imm.status}
                    </Badge>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    {imm.codings.map((coding) => (
                      <Badge
                        key={`${coding.systemLabel}-${coding.code}`}
                        variant="info"
                        size="sm"
                      >
                        {coding.systemLabel} {coding.code}
                      </Badge>
                    ))}
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)]">
                    <span data-testid={`provenance-badge-${imm.id}`}>
                      {formatProvenanceBadge(imm.provenance.sourceName, imm.provenance.recordedDate)}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid={`inspect-item-btn-${imm.id}`}
                      onClick={() => onInspectItem(imm)}
                    >
                      <History className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
                      Provenance &amp; v{imm.provenance.versionId}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card data-testid="ips-encounters-card" className="p-5 space-y-4">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-[var(--cf-primary)] shrink-0" aria-hidden="true" />
                  <CardTitle as="h3" className="text-base">
                    Care Encounters
                  </CardTitle>
                </div>
                <Badge variant="neutral" size="sm">
                  {snapshot.encounters.length} Recorded
                </Badge>
              </div>
              <CardDescription>
                Scheduled and completed ambulatory or specialty visits.
              </CardDescription>
            </CardHeader>

            <div className="space-y-3">
              {snapshot.encounters.map((enc) => (
                <div
                  key={enc.id}
                  data-testid={`ips-encounter-item-${enc.id}`}
                  className="p-3.5 rounded-[var(--cf-radius-md)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-2"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <h4 className="text-sm font-semibold text-[var(--cf-fg)]">{enc.title}</h4>
                      <p className="text-xs text-[var(--cf-fg-muted)]">
                        {enc.facilityDisplay}
                        {enc.clinicianDisplay ? ` · ${enc.clinicianDisplay}` : ''}
                      </p>
                      <p className="text-xs text-[var(--cf-fg-subtle)]">
                        Date: {enc.periodStart} · {enc.reasonDisplay}
                      </p>
                    </div>
                    <Badge variant="info" size="sm">
                      {enc.status}
                    </Badge>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[var(--cf-border)] text-xs text-[var(--cf-fg-subtle)]">
                    <span data-testid={`provenance-badge-${enc.id}`}>
                      {formatProvenanceBadge(enc.provenance.sourceName, enc.provenance.recordedDate)}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid={`inspect-item-btn-${enc.id}`}
                      onClick={() => onInspectItem(enc)}
                    >
                      <History className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
                      Provenance &amp; v{enc.provenance.versionId}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
