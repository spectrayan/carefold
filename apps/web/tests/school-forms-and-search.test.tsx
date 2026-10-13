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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import {
  SchoolFormPrefillSheet,
  SchoolFormsPanel,
} from '@/components/school-forms';
import { WebSearchPreviewCard } from '@/components/chat/WebSearchPreviewCard';
import {
  listSchoolForms,
  createSchoolForm,
  regenerateSchoolFormPrefill,
  deleteSchoolForm,
} from '@/lib/schoolFormsClient';
import type { SchoolFormItem } from '@/types/schoolForms';

const SAMPLE_SCHOOL_FORM: SchoolFormItem = {
  id: 'form-201',
  profile_id: 'child-prof-1',
  title: 'Annual Camp & Sports Physical Form',
  institution_name: 'Oakridge Elementary School',
  form_type: 'physical',
  issued_date: '2026-09-01',
  expires_at: '2026-10-30',
  days_until_expiry: 17,
  renewal_reminder_id: 'rem-901',
  guardian_only: true,
  under_13_safeguard: true,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
  prefill_draft: {
    student_name: 'Maya Patel',
    date_of_birth: '2016-05-14',
    immunisations: [
      {
        name: 'DTaP Dose 5',
        date: '2021-06-10',
        status: 'completed',
        source: 'AAP 2026',
      },
      {
        name: 'MMR Dose 2',
        date: '2021-06-10',
        status: 'completed',
        source: 'AAP 2026',
      },
    ],
    allergies: [
      {
        substance: 'Peanuts',
        reaction: 'Urticaria and wheezing',
        severity: 'Severe',
      },
    ],
    active_medications: [
      {
        name: 'Epinephrine Auto-Injector 0.15 mg',
        dosage: '0.15 mg IM',
        frequency: 'PRN Anaphylaxis',
      },
    ],
    latest_vitals: {
      height: '138 cm',
      weight: '32.5 kg',
      blood_pressure: '102/64 mmHg',
      recorded_at: '2026-09-01',
    },
    disclaimer:
      'Draft prefill generated from your saved records for parent and clinician review. Never auto-submitted.',
    compiled_at: '2026-10-13T12:00:00Z',
  },
};

describe('Pediatric School Forms and Sanitised Web Search Components Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('1. SchoolFormPrefillSheet Component', () => {
    it('renders compiled student fields, non-clinical disclaimer banner, and print/copy actions', () => {
      const onRegenerate = vi.fn();
      render(
        <SchoolFormPrefillSheet
          form={SAMPLE_SCHOOL_FORM}
          onRegeneratePrefill={onRegenerate}
        />
      );

      expect(
        screen.getByTestId('school-form-disclaimer-banner')
      ).toBeInTheDocument();
      expect(screen.getByTestId('school-form-disclaimer-text')).toHaveTextContent(
        'Draft prefill generated from your saved records for parent and clinician review. Never auto-submitted.'
      );

      expect(
        screen.getByTestId('prefill-section-immunisations')
      ).toHaveTextContent('DTaP Dose 5');
      expect(screen.getByTestId('prefill-section-allergies')).toHaveTextContent(
        'Peanuts'
      );
      expect(
        screen.getByTestId('prefill-section-medications')
      ).toHaveTextContent('Epinephrine Auto-Injector 0.15 mg');
      expect(screen.getByTestId('prefill-section-vitals')).toHaveTextContent(
        '138 cm'
      );
      expect(screen.getByTestId('prefill-section-vitals')).toHaveTextContent(
        '32.5 kg'
      );
      expect(screen.getByTestId('prefill-section-vitals')).toHaveTextContent(
        '102/64 mmHg'
      );

      fireEvent.click(screen.getByTestId('regenerate-prefill-btn'));
      expect(onRegenerate).toHaveBeenCalledWith('form-201');
    });
  });

  describe('2. SchoolFormsPanel Component', () => {
    it('lists school forms with expiration countdown, renewal reminder badge, and under-13 guardian safeguard badge', () => {
      const onDelete = vi.fn();
      render(
        <SchoolFormsPanel
          forms={[SAMPLE_SCHOOL_FORM]}
          guardianOnlyEnforced={true}
          onDeleteForm={onDelete}
        />
      );

      expect(
        screen.getByTestId('under-13-guardian-safeguard-badge')
      ).toHaveTextContent('Under-13 Guardian-Only Safeguard Active');
      expect(screen.getByTestId('school-form-expiry-form-201')).toHaveTextContent(
        'Expires in 17 days'
      );
      expect(
        screen.getByTestId('school-form-reminder-badge-form-201')
      ).toHaveTextContent('Renewal Reminder Set');
      expect(
        screen.getByTestId('school-form-guardian-badge-form-201')
      ).toHaveTextContent('Guardian Only');

      // Prefill sheet is open by default for the first form; toggle hide/show
      expect(
        screen.getByTestId('school-form-prefill-sheet')
      ).toBeInTheDocument();
      fireEvent.click(screen.getByTestId('view-prefill-btn-form-201'));
      expect(
        screen.queryByTestId('school-form-prefill-sheet')
      ).not.toBeInTheDocument();

      fireEvent.click(screen.getByTestId('delete-school-form-form-201'));
      expect(onDelete).toHaveBeenCalledWith('form-201');
    });
  });

  describe('3. WebSearchPreviewCard Component', () => {
    it('displays sanitised query, redacted PII count badge, allowlisted host badge, and taint indicator', () => {
      render(
        <WebSearchPreviewCard
          search={{
            sanitized_query: 'pediatric peanut allergy school action plan guidelines',
            redacted_items: ['NAME:Maya Patel', 'DOB:2016-05-14', 'MRN:99281'],
            provider: 'SearXNG',
            taint_active: true,
            results: [
              {
                title: 'AAP Allergy and Anaphylaxis Emergency Plan',
                url: 'https://www.healthychildren.org/anaphylaxis-plan',
                snippet:
                  'Standardized pediatric guidance for school epinephrine administration.',
              },
            ],
          }}
        />
      );

      expect(screen.getByTestId('web-search-preview-card')).toBeInTheDocument();
      expect(
        screen.getByTestId('web-search-sanitized-query')
      ).toHaveTextContent(
        'pediatric peanut allergy school action plan guidelines'
      );
      expect(screen.getByTestId('web-search-redacted-badge')).toHaveTextContent(
        '3 PII/PHI Redacted'
      );
      expect(screen.getByTestId('web-search-host-badge')).toHaveTextContent(
        'Allowlisted Host: SearXNG'
      );
      expect(screen.getByTestId('web-search-taint-badge')).toHaveTextContent(
        'Untrusted External Source (Taint Active)'
      );
      expect(screen.getByTestId('web-search-results-list')).toHaveTextContent(
        'AAP Allergy and Anaphylaxis Emergency Plan'
      );
    });
  });

  describe('4. School Forms API Client Helpers', () => {
    it('calls the expected /api/v1/profiles/:profileId/school-forms endpoints', async () => {
      const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
        ok: true,
        json: async () => ({}),
      } as Response);

      await listSchoolForms('child-prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/child-prof-1/school-forms',
        expect.objectContaining({ credentials: 'include' })
      );

      await createSchoolForm('child-prof-1', {
        title: 'Sports Clearance',
        institution_name: 'Oakridge',
        form_type: 'sports_clearance',
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/child-prof-1/school-forms',
        expect.objectContaining({ method: 'POST' })
      );

      await regenerateSchoolFormPrefill('child-prof-1', 'form-201');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/child-prof-1/school-forms/form-201/prefill',
        expect.objectContaining({ method: 'POST' })
      );

      await deleteSchoolForm('child-prof-1', 'form-201');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/child-prof-1/school-forms/form-201',
        expect.objectContaining({ method: 'DELETE' })
      );
    });
  });
});
