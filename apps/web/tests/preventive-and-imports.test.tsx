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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import {
  ScheduleSourceSelector,
  PreventiveChecklist,
} from '@/components/preventive';
import {
  ImportStagingReviewTable,
  ClinicalImportWizard,
} from '@/components/imports';
import {
  fetchPreventiveItems,
  updatePreventiveStatus,
  updateScheduleSource,
  triggerPreventiveAction,
} from '@/lib/preventiveClient';
import {
  stageClinicalImport,
  commitImportBatch,
  discardImportBatch,
} from '@/lib/importsClient';
import type { PreventiveItem } from '@/types/preventive';
import type { ImportBatchResponse } from '@/types/imports';

const SAMPLE_PREVENTIVE_ITEMS: PreventiveItem[] = [
  {
    rule_id: 'uspstf_bp_screening_adult',
    title: 'Hypertension Blood Pressure Screening',
    category: 'screening',
    status: 'due',
    clinical_summary:
      'Annual blood pressure screening recommended for adults aged 40+ or those at increased risk.',
    source: 'USPSTF',
    citation_url: 'https://www.uspreventiveservicestaskforce.org',
    reviewed_by: 'Clinical Safety Board',
    reviewed_at: '2026-02-01',
  },
  {
    rule_id: 'aap_mmr_dose_1',
    title: 'MMR Immunisation (Dose 1)',
    category: 'immunisation',
    status: 'completed',
    schedule_variant: 'aap_2026',
    clinical_summary:
      'First dose of Measles, Mumps, and Rubella vaccine at 12–15 months.',
    source: 'AAP Bright Futures 2026',
    citation_url: 'https://www.aap.org',
    reviewed_by: 'Pediatric Review Committee',
    reviewed_at: '2026-02-01',
    completed_at: '2026-09-10T10:00:00Z',
  },
  {
    rule_id: 'cdc_well_child_24m',
    title: '24-Month Well-Child Visit',
    category: 'well_visit',
    status: 'declined',
    clinical_summary:
      'Comprehensive developmental surveillance and autism spectrum disorder screening.',
    source: 'CDC',
    citation_url: 'https://www.cdc.gov',
    reviewed_by: 'Pediatric Review Committee',
    reviewed_at: '2026-02-01',
  },
];

const SAMPLE_IMPORT_BATCH: ImportBatchResponse = {
  batch_id: 'import_set-101',
  profile_id: 'prof-1',
  format: 'fhir_r4',
  source_name: 'MyChart',
  status: 'staged',
  created_at: '2026-10-13T12:00:00Z',
  summary: {
    conditions: 1,
    medications: 1,
    allergies: 1,
    immunizations: 2,
    vitals: 3,
    apple_health_summaries: 7,
    total: 15,
  },
  records: [
    {
      index: 0,
      resource_type: 'Condition',
      category: 'conditions',
      display_title: 'Essential Hypertension (I10)',
      effective_date: '2026-10-13',
      source_name: 'MyChart',
    },
    {
      index: 1,
      resource_type: 'MedicationStatement',
      category: 'medications',
      display_title: 'Lisinopril 10 mg Oral Tablet',
      effective_date: '2026-10-13',
      source_name: 'MyChart',
    },
  ],
};

describe('Preventive Care and Clinical Import Components Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('1. ScheduleSourceSelector Component', () => {
    it('renders AAP 2026 and CDC ACIP options with version badge and pediatric guidance note', () => {
      const onChange = vi.fn();
      render(<ScheduleSourceSelector value="aap_2026" onChange={onChange} />);

      expect(screen.getByTestId('schedule-source-selector')).toBeInTheDocument();
      expect(screen.getByTestId('schedule-version-badge')).toHaveTextContent(
        'Reviewed 2026-02-01'
      );
      expect(screen.getByTestId('schedule-guidance-note')).toHaveTextContent(
        /Possibly due, confirm with your pediatrician/i
      );

      const cdcBtn = screen.getByTestId('schedule-source-option-cdc');
      fireEvent.click(cdcBtn);
      expect(onChange).toHaveBeenCalledWith('cdc');
    });
  });

  describe('2. PreventiveChecklist Component', () => {
    it('displays items, filters by category and status, and triggers status and 1-click actions', () => {
      const onUpdateStatus = vi.fn();
      const onTriggerAction = vi.fn();

      render(
        <PreventiveChecklist
          items={SAMPLE_PREVENTIVE_ITEMS}
          onUpdateStatus={onUpdateStatus}
          onTriggerAction={onTriggerAction}
        />
      );

      // All 3 items visible initially
      expect(
        screen.getByTestId('preventive-item-uspstf_bp_screening_adult')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('preventive-item-aap_mmr_dose_1')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('preventive-item-cdc_well_child_24m')
      ).toBeInTheDocument();

      // Verify provenance badges
      expect(
        screen.getByTestId('preventive-source-badge-uspstf_bp_screening_adult')
      ).toHaveTextContent('USPSTF');
      expect(
        screen.getByTestId('preventive-source-badge-aap_mmr_dose_1')
      ).toHaveTextContent('AAP Bright Futures 2026');

      // Filter by Immunisations category
      fireEvent.click(screen.getByTestId('preventive-category-tab-immunisation'));
      expect(
        screen.getByTestId('preventive-item-aap_mmr_dose_1')
      ).toBeInTheDocument();
      expect(
        screen.queryByTestId('preventive-item-uspstf_bp_screening_adult')
      ).not.toBeInTheDocument();

      // Reset to All categories and filter by Due status
      fireEvent.click(screen.getByTestId('preventive-category-tab-all'));
      fireEvent.click(screen.getByTestId('preventive-status-tab-due'));
      expect(
        screen.getByTestId('preventive-item-uspstf_bp_screening_adult')
      ).toBeInTheDocument();
      expect(
        screen.queryByTestId('preventive-item-aap_mmr_dose_1')
      ).not.toBeInTheDocument();

      // Trigger status update and 1-click actions
      fireEvent.click(
        screen.getByTestId('mark-completed-uspstf_bp_screening_adult')
      );
      expect(onUpdateStatus).toHaveBeenCalledWith(
        'uspstf_bp_screening_adult',
        'completed'
      );

      fireEvent.click(
        screen.getByTestId('add-visit-prep-uspstf_bp_screening_adult')
      );
      expect(onTriggerAction).toHaveBeenCalledWith(
        'uspstf_bp_screening_adult',
        'add_to_visit_prep'
      );

      fireEvent.click(
        screen.getByTestId('set-reminder-uspstf_bp_screening_adult')
      );
      expect(onTriggerAction).toHaveBeenCalledWith(
        'uspstf_bp_screening_adult',
        'set_reminder'
      );
    });
  });

  describe('3. ImportStagingReviewTable & ClinicalImportWizard Components', () => {
    it('renders staged import breakdown counts, provenance badge, and handles commit/discard', () => {
      const onCommit = vi.fn();
      const onDiscard = vi.fn();

      render(
        <ImportStagingReviewTable
          batch={SAMPLE_IMPORT_BATCH}
          onCommit={onCommit}
          onDiscard={onDiscard}
        />
      );

      expect(screen.getByTestId('import-provenance-badge')).toHaveTextContent(
        'From MyChart, 2026-10-13'
      );
      expect(screen.getByTestId('import-count-conditions')).toHaveTextContent('1');
      expect(screen.getByTestId('import-count-medications')).toHaveTextContent(
        '1'
      );
      expect(
        screen.getByTestId('import-count-apple_health_summaries')
      ).toHaveTextContent('7');

      // Deselect index 1 and commit only index 0
      fireEvent.click(screen.getByTestId('staged-record-checkbox-1'));
      fireEvent.click(screen.getByTestId('commit-import-batch-btn'));
      expect(onCommit).toHaveBeenCalledWith('import_set-101', [0]);

      // Discard
      fireEvent.click(screen.getByTestId('discard-import-batch-btn'));
      expect(onDiscard).toHaveBeenCalledWith('import_set-101');
    });

    it('stages and commits a clinical export through ClinicalImportWizard', async () => {
      const fetchSpy = vi
        .spyOn(global, 'fetch')
        .mockResolvedValueOnce({
          ok: true,
          json: async () => SAMPLE_IMPORT_BATCH,
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            ...SAMPLE_IMPORT_BATCH,
            status: 'committed',
            committed_count: 2,
          }),
        } as Response);

      render(<ClinicalImportWizard profileId="prof-1" />);

      fireEvent.change(screen.getByTestId('import-content-textarea'), {
        target: { value: '{"resourceType":"Bundle","entry":[]}' },
      });

      fireEvent.click(screen.getByTestId('stage-import-btn'));

      await waitFor(() => {
        expect(
          screen.getByTestId('import-staging-review-table')
        ).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('commit-import-batch-btn'));

      await waitFor(() => {
        expect(
          screen.getByTestId('import-wizard-committed-banner')
        ).toHaveTextContent(/Successfully committed 2 records from MyChart/i);
      });

      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });
  });

  describe('4. Preventive & Imports API Client Helpers', () => {
    it('calls the expected /api/v1/profiles/:profileId endpoints', async () => {
      const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
        ok: true,
        json: async () => ({}),
      } as Response);

      await fetchPreventiveItems('prof-1', {
        category: 'screening',
        status: 'due',
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/preventive?category=screening&status=due',
        expect.objectContaining({ credentials: 'include' })
      );

      await updatePreventiveStatus('prof-1', 'rule-1', { status: 'completed' });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/preventive/rule-1',
        expect.objectContaining({ method: 'PATCH' })
      );

      await updateScheduleSource('prof-1', 'cdc');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/preventive/schedule-source',
        expect.objectContaining({ method: 'PUT' })
      );

      await triggerPreventiveAction('prof-1', 'rule-1', 'add_to_visit_prep');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/preventive/rule-1/actions',
        expect.objectContaining({ method: 'POST' })
      );

      await stageClinicalImport('prof-1', {
        format: 'fhir_r4',
        source_name: 'MyChart',
        content: '{}',
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/imports/stage',
        expect.objectContaining({ method: 'POST' })
      );

      await commitImportBatch('prof-1', 'import_set-1', [0, 1]);
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/imports/import_set-1/commit',
        expect.objectContaining({ method: 'POST' })
      );

      await discardImportBatch('prof-1', 'import_set-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/imports/import_set-1/discard',
        expect.objectContaining({ method: 'POST' })
      );
    });
  });
});
