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

import React from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  EhrChartWorkspace,
  IpsPatientSummaryTab,
  LabsAndDiagnosticsExplorer,
  ProvenanceHistoryDrawer,
  InteroperableExportModal,
} from '../src/health-ui/chart';
import {
  DEFAULT_EHR_CHART_SNAPSHOT,
  EHR_CHART_INFORMATIONAL_NOTICE,
  createFhirR4RestAdapter,
  createMockEhrChartAdapter,
} from '../src/lib/ehrChartClient';
import { loadChecklist } from '../src/lib/checklistStorage';

describe('Issue 288 — Personal EHR Chart UI (IPS Summary, Labs Explorer, Provenance, Export)', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders IPS Patient Summary sections with standardized coding badges, provenance, and criticality flags', () => {
    const onInspect = vi.fn();
    render(
      <IpsPatientSummaryTab
        snapshot={DEFAULT_EHR_CHART_SNAPSHOT}
        onInspectItem={onInspect}
      />
    );

    expect(screen.getByTestId('ips-patient-summary-tab')).toBeInTheDocument();
    expect(screen.getByTestId('ips-loinc-badge')).toHaveTextContent('LOINC 60591-5');

    // Active Problems / Conditions
    expect(screen.getByTestId('ips-conditions-card')).toHaveTextContent(
      'Essential (Primary) Hypertension'
    );
    expect(screen.getByTestId('ips-conditions-card')).toHaveTextContent('ICD-10-CM I10');
    expect(screen.getByTestId('ips-conditions-card')).toHaveTextContent('SNOMED CT 59621000');
    expect(screen.getByTestId('provenance-badge-cond-htn-101')).toHaveTextContent(
      'From Northwestern MyChart, 2026-03-10'
    );

    // Active Medications
    expect(screen.getByTestId('ips-medications-card')).toHaveTextContent(
      'Lisinopril 10 MG Oral Tablet'
    );
    expect(screen.getByTestId('ips-medications-card')).toHaveTextContent('RxNorm 314076');
    expect(screen.getByTestId('ips-medications-card')).toHaveTextContent(
      '10 mg orally once daily'
    );

    // Allergies & Intolerances
    expect(screen.getByTestId('ips-allergies-card')).toHaveTextContent(
      'Penicillin G / Beta-Lactam Antibacterials'
    );
    expect(screen.getByTestId('allergy-criticality-badge-allergy-penicillin-301')).toHaveTextContent(
      'High Criticality'
    );

    // Immunizations & Encounters
    expect(screen.getByTestId('ips-immunizations-card')).toHaveTextContent(
      'Influenza, Seasonal, Injectable (Preservative Free)'
    );
    expect(screen.getByTestId('ips-immunizations-card')).toHaveTextContent('CVX 140');
    expect(screen.getByTestId('ips-encounters-card')).toHaveTextContent(
      'Outpatient Internal Medicine & Cardiometabolic Follow-Up'
    );

    fireEvent.click(screen.getByTestId('inspect-item-btn-cond-htn-101'));
    expect(onInspect).toHaveBeenCalledWith(DEFAULT_EHR_CHART_SNAPSHOT.conditions[0]);
  });

  it('renders Labs & Diagnostics Explorer with LOINC panels, reference flags, unit toggle, and visit question staging', () => {
    const onInspect = vi.fn();
    const onStageQuestion = vi.fn();

    render(
      <LabsAndDiagnosticsExplorer
        labPanels={DEFAULT_EHR_CHART_SNAPSHOT.labPanels}
        onStageQuestion={onStageQuestion}
        onInspectItem={onInspect}
      />
    );

    expect(screen.getByTestId('labs-diagnostics-explorer')).toBeInTheDocument();

    // Check Hemoglobin A1c panel & unit toggle (% <-> mmol/mol)
    expect(screen.getByTestId('lab-value-obs-hba1c-601')).toHaveTextContent('6.1');
    expect(screen.getByTestId('lab-unit-obs-hba1c-601')).toHaveTextContent('%');
    expect(screen.getByTestId('lab-flag-badge-obs-hba1c-601')).toHaveTextContent(
      'High Reference Flag'
    );

    fireEvent.click(screen.getByTestId('lab-unit-toggle-obs-hba1c-601'));
    expect(screen.getByTestId('lab-value-obs-hba1c-601')).toHaveTextContent('43');
    expect(screen.getByTestId('lab-unit-obs-hba1c-601')).toHaveTextContent('mmol/mol');

    // Check Serum Glucose unit toggle (mg/dL <-> mmol/L)
    expect(screen.getByTestId('lab-value-obs-glucose-602')).toHaveTextContent('106');
    expect(screen.getByTestId('lab-unit-obs-glucose-602')).toHaveTextContent('mg/dL');
    fireEvent.click(screen.getByTestId('lab-unit-toggle-obs-glucose-602'));
    expect(screen.getByTestId('lab-value-obs-glucose-602')).toHaveTextContent('5.88');
    expect(screen.getByTestId('lab-unit-obs-glucose-602')).toHaveTextContent('mmol/L');

    // Filter by category
    fireEvent.click(screen.getByTestId('labs-category-filter-lipids'));
    expect(screen.queryByTestId('lab-panel-card-panel-glycemic-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('lab-panel-card-panel-lipid-1')).toBeInTheDocument();

    // Reset filter and test abnormal-only filter
    fireEvent.click(screen.getByTestId('labs-category-filter-all'));
    fireEvent.click(screen.getByTestId('labs-abnormal-only-toggle'));
    expect(screen.queryByTestId('lab-observation-card-obs-ldl-604')).not.toBeInTheDocument();
    expect(screen.getByTestId('lab-observation-card-obs-hba1c-601')).toBeInTheDocument();

    // Stage Question for Visit
    fireEvent.click(screen.getByTestId('stage-question-btn-obs-hba1c-601'));
    expect(onStageQuestion).toHaveBeenCalledWith(
      DEFAULT_EHR_CHART_SNAPSHOT.labPanels[0].observations[0]
    );
  });

  it('opens ProvenanceHistoryDrawer with coding systems, cross-portal deduplication notice, and _history revisions', () => {
    const onClose = vi.fn();
    const conditionItem = DEFAULT_EHR_CHART_SNAPSHOT.conditions[0];

    render(<ProvenanceHistoryDrawer item={conditionItem} onClose={onClose} />);

    expect(screen.getByTestId('provenance-history-drawer')).toBeInTheDocument();
    expect(screen.getByTestId('drawer-resource-reference')).toHaveTextContent(
      'Condition/cond-htn-101'
    );
    expect(screen.getByTestId('drawer-current-version')).toHaveTextContent('ETag W/"2"');
    expect(screen.getByTestId('drawer-provenance-citation')).toHaveTextContent(
      'From Northwestern MyChart, 2026-03-10'
    );
    expect(screen.getByTestId('drawer-merged-portals')).toHaveTextContent(
      'Deduplicated across: Northwestern MyChart + Regional C-CDA Summary'
    );

    // Coding badges
    expect(screen.getByTestId('drawer-coding-item-ICD-10-CM-I10')).toHaveTextContent(
      'ICD-10-CM · I10'
    );
    expect(screen.getByTestId('drawer-coding-item-SNOMED CT-59621000')).toHaveTextContent(
      'Normalized from urn:oid:2.16.840.1.113883.6.96'
    );

    // _history versions
    expect(screen.getByTestId('drawer-history-version-1')).toHaveTextContent('v1 · CREATE');
    expect(screen.getByTestId('drawer-history-version-2')).toHaveTextContent('v2 · MERGE');

    fireEvent.click(screen.getByTestId('close-provenance-drawer-btn'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('enforces explicit user confirmation in InteroperableExportModal and sends X-Carefold-Confirm: true header', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        [
          JSON.stringify({ resourceType: 'Patient', id: 'profile-alpha' }),
          JSON.stringify({ resourceType: 'Condition', id: 'cond-htn-101' }),
        ].join('\n'),
    });
    vi.stubGlobal('fetch', mockFetch);

    // Stub URL.createObjectURL / revokeObjectURL for downloadBlob in jsdom
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:carefold-test');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});

    const restAdapter = createFhirR4RestAdapter('/api/v1/fhir/r4');
    const onClose = vi.fn();

    render(
      <InteroperableExportModal
        isOpen={true}
        profileId="profile-alpha"
        onClose={onClose}
        onExport={(format, confirmed) =>
          restAdapter.exportBundle('profile-alpha', format, confirmed)
        }
      />
    );

    // Attempt export without checking confirmation box -> error alert shown
    fireEvent.click(screen.getByTestId('confirm-download-export-btn'));
    expect(screen.getByTestId('export-error-alert')).toHaveTextContent(
      'Please confirm that you want to export unencrypted health records'
    );
    expect(mockFetch).not.toHaveBeenCalled();

    // Select Bulk NDJSON format and check explicit confirmation checkbox
    fireEvent.click(screen.getByTestId('export-format-option-bulk_ndjson'));
    fireEvent.click(screen.getByTestId('export-confirm-checkbox'));
    fireEvent.click(screen.getByTestId('confirm-download-export-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('export-success-banner')).toBeInTheDocument();
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = mockFetch.mock.calls[0];
    expect(String(requestUrl)).toContain('/api/v1/fhir/r4/Patient/profile-alpha/$export');
    expect((requestInit as RequestInit).headers).toMatchObject({
      Accept: 'application/fhir+ndjson',
      'X-Carefold-Confirm': 'true',
    });
    expect(screen.getByTestId('export-success-banner')).toHaveTextContent(
      'carefold-bulk-export-profile-alpha-'
    );
  });

  it('renders unified EhrChartWorkspace with informational notice, tab switching, visit question staging, and drawer', async () => {
    const mockAdapter = createMockEhrChartAdapter();
    render(<EhrChartWorkspace profileId="me" adapter={mockAdapter} />);

    expect(screen.getByTestId('ehr-chart-workspace')).toBeInTheDocument();
    expect(screen.getByTestId('ehr-chart-informational-notice')).toHaveTextContent(
      EHR_CHART_INFORMATIONAL_NOTICE
    );

    // Open Provenance drawer from IPS Summary
    fireEvent.click(screen.getByTestId('inspect-item-btn-cond-htn-101'));
    await waitFor(() => {
      expect(screen.getByTestId('provenance-history-drawer')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('close-provenance-drawer-btn'));

    // Switch to Labs & Diagnostics Explorer tab
    fireEvent.click(screen.getByTestId('ehr-tab-labs-explorer'));
    expect(screen.getByTestId('labs-diagnostics-explorer')).toBeInTheDocument();

    // Stage a visit question and verify checklist persistence + header badge
    fireEvent.click(screen.getByTestId('stage-question-btn-obs-hba1c-601'));
    expect(screen.getByTestId('staged-visit-questions-badge')).toHaveTextContent(
      '1 Visit Question Staged'
    );
    const checklist = loadChecklist('ehr-visit-prep-me', 'ehr-chart-staged', []);
    expect(checklist).toHaveLength(1);
    expect(checklist[0].text).toContain('Hemoglobin A1c (LOINC 4548-4)');
  });

  it('enforces zero raw hex colors and zero physical directional CSS utilities across all #288 chart files', () => {
    const filesToAudit = [
      'src/types/ehrChart.ts',
      'src/lib/ehrChartClient.ts',
      'src/health-ui/chart/EhrChartWorkspace.tsx',
      'src/health-ui/chart/IpsPatientSummaryTab.tsx',
      'src/health-ui/chart/LabsAndDiagnosticsExplorer.tsx',
      'src/health-ui/chart/ProvenanceHistoryDrawer.tsx',
      'src/health-ui/chart/InteroperableExportModal.tsx',
      'src/health-ui/chart/index.ts',
    ];

    const rawHexPattern = /#[0-9a-fA-F]{3,8}\b/;
    const physicalCssPattern =
      /\b(ml-|mr-|pl-|pr-|left-|right-|text-left|text-right|border-l-|border-r-|rounded-l-|rounded-r-)/;

    for (const relPath of filesToAudit) {
      const absPath = resolve(__dirname, '..', relPath);
      const source = readFileSync(absPath, 'utf-8');
      expect(source, `Raw hex color found in ${relPath}`).not.toMatch(rawHexPattern);
      expect(source, `Physical directional CSS utility found in ${relPath}`).not.toMatch(
        physicalCssPattern
      );
    }
  });
});
