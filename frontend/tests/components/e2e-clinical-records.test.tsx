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
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { IpsPatientSummaryTab } from '@/health-ui/chart/IpsPatientSummaryTab';
import { EhrChartWorkspace } from '@/health-ui/chart/EhrChartWorkspace';
import {
  DEFAULT_EHR_CHART_SNAPSHOT,
  EHR_CHART_INFORMATIONAL_NOTICE,
} from '@/lib/ehrChartClient';

describe('E2E Governed Clinical Records & IPS Organizer UI (Feature 7 / Issue #357)', () => {
  it('renders IpsPatientSummaryTab with LOINC composition and all core clinical cards', () => {
    const handleInspect = vi.fn();
    render(
      <IpsPatientSummaryTab
        snapshot={DEFAULT_EHR_CHART_SNAPSHOT}
        onInspectItem={handleInspect}
      />
    );

    // IPS Header Banner
    expect(screen.getByTestId('ips-composition-banner')).toBeInTheDocument();
    expect(screen.getByTestId('ips-loinc-badge')).toHaveTextContent(/LOINC 60591-5/i);

    // 1. Conditions Card
    expect(screen.getByTestId('ips-conditions-card')).toBeInTheDocument();
    expect(screen.getByText('Essential (Primary) Hypertension')).toBeInTheDocument();
    expect(screen.getByText(/ICD-10-CM I10/i)).toBeInTheDocument();

    // 2. Medications Card
    expect(screen.getByTestId('ips-medications-card')).toBeInTheDocument();
    expect(screen.getByText(/Lisinopril 10 MG Oral Tablet/i)).toBeInTheDocument();

    // 3. Allergies Card
    expect(screen.getByTestId('ips-allergies-card')).toBeInTheDocument();
    expect(screen.getByText(/Penicillin G/i)).toBeInTheDocument();
    expect(screen.getByText(/High Criticality/i)).toBeInTheDocument();

    // 4. Immunizations Card
    expect(screen.getByTestId('ips-immunizations-card')).toBeInTheDocument();
    expect(screen.getByText(/Influenza, seasonal/i)).toBeInTheDocument();
  });

  it('triggers onInspectItem callback when clicking item provenance button in summary', () => {
    const handleInspect = vi.fn();
    render(
      <IpsPatientSummaryTab
        snapshot={DEFAULT_EHR_CHART_SNAPSHOT}
        onInspectItem={handleInspect}
      />
    );

    const inspectBtn = screen.getByTestId('inspect-item-btn-cond-htn-101');
    fireEvent.click(inspectBtn);

    expect(handleInspect).toHaveBeenCalledTimes(1);
    expect(handleInspect).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'cond-htn-101',
        title: 'Essential (Primary) Hypertension',
        resourceType: 'Condition',
      })
    );
  });

  it('renders EhrChartWorkspace with informational disclaimer and tab navigation', async () => {
    render(
      <EhrChartWorkspace
        profileId="rosa"
        initialSnapshot={DEFAULT_EHR_CHART_SNAPSHOT}
      />
    );

    // Disclaimer
    expect(screen.getByTestId('ehr-chart-informational-notice')).toHaveTextContent(
      EHR_CHART_INFORMATIONAL_NOTICE
    );

    // Tabs exist
    const summaryTab = screen.getByTestId('ehr-tab-ips-summary');
    const labsTab = screen.getByTestId('ehr-tab-labs-explorer');
    expect(summaryTab).toBeInTheDocument();
    expect(labsTab).toBeInTheDocument();

    // Switch to Labs Tab
    fireEvent.click(labsTab);
    expect(await screen.findByTestId('labs-diagnostics-explorer')).toBeInTheDocument();
  });

  it('opens ProvenanceHistoryDrawer when an item is inspected in EhrChartWorkspace', async () => {
    render(
      <EhrChartWorkspace
        profileId="rosa"
        initialSnapshot={DEFAULT_EHR_CHART_SNAPSHOT}
      />
    );

    const inspectBtn = await screen.findByTestId('inspect-item-btn-cond-htn-101');
    fireEvent.click(inspectBtn);

    // Drawer should open displaying provenance details
    const drawer = await screen.findByTestId('provenance-history-drawer');
    expect(drawer).toBeInTheDocument();
    expect(within(drawer).getByTestId('drawer-resource-reference')).toHaveTextContent('Condition/cond-htn-101');
    expect(within(drawer).getByRole('heading', { level: 2 })).toHaveTextContent(/Essential \(Primary\) Hypertension/i);
    expect(within(drawer).getByTestId('close-provenance-drawer-btn')).toBeInTheDocument();
  });

  it('opens InteroperableExportModal when clicking the Export Record button', async () => {
    render(
      <EhrChartWorkspace
        profileId="rosa"
        initialSnapshot={DEFAULT_EHR_CHART_SNAPSHOT}
      />
    );

    const exportBtn = screen.getByTestId('open-export-modal-btn');
    fireEvent.click(exportBtn);

    expect(await screen.findByTestId('interoperable-export-modal')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Interoperable FHIR R4 & IPS Export/i })).toBeInTheDocument();
  });
});
