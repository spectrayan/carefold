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

import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  Download,
  FileSpreadsheet,
  FlaskConical,
  ListChecks,
  ShieldCheck,
} from 'lucide-react';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import {
  DEFAULT_EHR_CHART_SNAPSHOT,
  EHR_CHART_INFORMATIONAL_NOTICE,
  createMockEhrChartAdapter,
  stageQuestionForVisit,
} from '../../lib/ehrChartClient';
import type {
  EhrChartDataSourceAdapter,
  EhrChartSnapshot,
  EhrClinicalItemBase,
  EhrExportFormat,
  EhrExportResult,
  EhrLabObservationItem,
  EhrResourceRevision,
} from '../../types/ehrChart';
import { IpsPatientSummaryTab } from './IpsPatientSummaryTab';
import { LabsAndDiagnosticsExplorer } from './LabsAndDiagnosticsExplorer';
import { ProvenanceHistoryDrawer } from './ProvenanceHistoryDrawer';
import { InteroperableExportModal } from './InteroperableExportModal';

export type EhrChartActiveTab = 'summary' | 'labs';

export interface EhrChartWorkspaceProps {
  profileId?: string;
  initialTab?: EhrChartActiveTab;
  initialSnapshot?: EhrChartSnapshot;
  adapter?: EhrChartDataSourceAdapter;
  onQuestionStaged?: (observation: EhrLabObservationItem, questionText: string) => void;
}

export function EhrChartWorkspace({
  profileId = 'me',
  initialTab = 'summary',
  initialSnapshot = DEFAULT_EHR_CHART_SNAPSHOT,
  adapter,
  onQuestionStaged,
}: EhrChartWorkspaceProps) {
  const activeAdapter = useMemo(
    () => adapter ?? createMockEhrChartAdapter(initialSnapshot),
    [adapter, initialSnapshot]
  );

  const [activeTab, setActiveTab] = useState<EhrChartActiveTab>(initialTab);
  const [snapshot, setSnapshot] = useState<EhrChartSnapshot>(() => ({
    ...initialSnapshot,
    profileId,
  }));
  const [inspectedItem, setInspectedItem] = useState<EhrClinicalItemBase | null>(null);
  const [inspectedRevisions, setInspectedRevisions] = useState<EhrResourceRevision[] | undefined>(
    undefined
  );
  const [isExportModalOpen, setIsExportModalOpen] = useState<boolean>(false);
  const [stagedObservationIds, setStagedObservationIds] = useState<Set<string>>(() => new Set());
  const [stagedQuestionCount, setStagedQuestionCount] = useState<number>(0);

  useEffect(() => {
    let mounted = true;
    activeAdapter
      .getChartSnapshot(profileId)
      .then((loaded) => {
        if (mounted) {
          setSnapshot(loaded);
        }
      })
      .catch(() => {
        // Keep initial snapshot if adapter fetch fails
      });
    return () => {
      mounted = false;
    };
  }, [activeAdapter, profileId]);

  const handleInspectItem = async (item: EhrClinicalItemBase) => {
    setInspectedItem(item);
    setInspectedRevisions(item.history);
    try {
      const revisions = await activeAdapter.getResourceHistory(
        profileId,
        item.resourceType,
        item.id
      );
      if (revisions.length > 0) {
        setInspectedRevisions(revisions);
      }
    } catch {
      // Keep item.history fallback
    }
  };

  const handleStageQuestion = (observation: EhrLabObservationItem) => {
    const updatedChecklist = stageQuestionForVisit(
      profileId,
      observation.suggestedVisitQuestion
    );
    setStagedObservationIds((prev) => {
      const next = new Set(prev);
      next.add(observation.id);
      return next;
    });
    setStagedQuestionCount(updatedChecklist.length);
    onQuestionStaged?.(observation, observation.suggestedVisitQuestion);
  };

  const handleExport = async (
    format: EhrExportFormat,
    confirmed: boolean
  ): Promise<EhrExportResult> => {
    return activeAdapter.exportBundle(profileId, format, confirmed);
  };

  return (
    <section
      aria-label="Personal EHR Chart Workspace"
      data-testid="ehr-chart-workspace"
      data-profile-id={profileId}
      className="space-y-5 rounded-[var(--cf-radius-lg)] border border-[var(--cf-border)] bg-[var(--cf-surface)] p-5 text-[var(--cf-fg)] text-start shadow-sm"
    >
      {/* Patient & Non-Clinical Boundary Banner */}
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--cf-border)] pb-4">
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="info" size="sm">
              <Activity className="w-3.5 h-3.5 me-1 inline" aria-hidden="true" />
              HL7 FHIR R4 + IPS Personal Chart
            </Badge>
            <Badge variant="success" size="sm" data-testid="ehr-profile-scope-badge">
              <ShieldCheck className="w-3.5 h-3.5 me-1 inline" aria-hidden="true" />
              Profile: {snapshot.profileId}
            </Badge>
            <Badge variant="neutral" size="sm" data-testid="ehr-adapter-kind-badge">
              Adapter: {activeAdapter.kind}
            </Badge>
          </div>

          <h2 className="text-xl font-bold text-[var(--cf-fg)]">
            {snapshot.patientDisplayName} — Longitudinal Health Chart
          </h2>

          <p
            data-testid="ehr-chart-informational-notice"
            className="text-xs text-[var(--cf-fg-muted)]"
          >
            {EHR_CHART_INFORMATIONAL_NOTICE}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {stagedQuestionCount > 0 && (
            <Badge
              variant="info"
              size="md"
              data-testid="staged-visit-questions-badge"
            >
              <ListChecks className="w-3.5 h-3.5 me-1.5 inline" aria-hidden="true" />
              {stagedQuestionCount} Visit {stagedQuestionCount === 1 ? 'Question' : 'Questions'} Staged
            </Badge>
          )}

          <Button
            variant="primary"
            size="sm"
            data-testid="open-export-modal-btn"
            onClick={() => setIsExportModalOpen(true)}
          >
            <Download className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
            Export IPS / FHIR Records
          </Button>
        </div>
      </header>

      {/* Accessible Tab Bar */}
      <div
        role="tablist"
        aria-label="Personal EHR Chart Views"
        className="flex flex-wrap items-center gap-2 border-b border-[var(--cf-border)] pb-3"
      >
        <Button
          role="tab"
          aria-selected={activeTab === 'summary'}
          variant={activeTab === 'summary' ? 'primary' : 'secondary'}
          size="sm"
          data-testid="ehr-tab-ips-summary"
          onClick={() => setActiveTab('summary')}
        >
          <FileSpreadsheet className="w-4 h-4 me-1.5" aria-hidden="true" />
          IPS Patient Summary (LOINC {snapshot.ipsCompositionLoinc})
        </Button>

        <Button
          role="tab"
          aria-selected={activeTab === 'labs'}
          variant={activeTab === 'labs' ? 'primary' : 'secondary'}
          size="sm"
          data-testid="ehr-tab-labs-explorer"
          onClick={() => setActiveTab('labs')}
        >
          <FlaskConical className="w-4 h-4 me-1.5" aria-hidden="true" />
          Labs &amp; Diagnostics Explorer ({snapshot.labPanels.length} Panels)
        </Button>
      </div>

      {/* Active Tab Content */}
      {activeTab === 'summary' ? (
        <IpsPatientSummaryTab
          snapshot={snapshot}
          onInspectItem={(item) => void handleInspectItem(item)}
        />
      ) : (
        <LabsAndDiagnosticsExplorer
          labPanels={snapshot.labPanels}
          stagedObservationIds={stagedObservationIds}
          onStageQuestion={handleStageQuestion}
          onInspectItem={(item) => void handleInspectItem(item)}
        />
      )}

      {/* Provenance & Revision History Drawer */}
      <ProvenanceHistoryDrawer
        item={inspectedItem}
        revisions={inspectedRevisions}
        onClose={() => {
          setInspectedItem(null);
          setInspectedRevisions(undefined);
        }}
      />

      {/* Interoperable Export Modal */}
      <InteroperableExportModal
        isOpen={isExportModalOpen}
        profileId={snapshot.profileId}
        onClose={() => setIsExportModalOpen(false)}
        onExport={handleExport}
      />
    </section>
  );
}
