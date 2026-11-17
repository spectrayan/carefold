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
import { render, screen, fireEvent } from '@testing-library/react';
import { AppRail } from '@/components/layout/AppRail';
import { AppointmentCard } from '@/health-ui/appointments/AppointmentCard';
import { SchoolFormsPanel } from '@/health-ui/school-forms/SchoolFormsPanel';
import { SchoolFormPrefillSheet } from '@/health-ui/school-forms/SchoolFormPrefillSheet';
import type { AppointmentItem } from '@/types/schedule';
import type { SchoolFormItem } from '@/types/schoolForms';

const mockAppointment: AppointmentItem = {
  id: 'appt-ped-101',
  profile_id: 'leo',
  title: 'Annual Pediatric Well-Child Exam',
  provider_name: 'Dr. Sarah Lin, MD',
  specialty: 'Pediatrics',
  location: '2525 N Lincoln Ave, Chicago, IL 60614',
  clinic_phone: '(312) 555-0199',
  start_time: '2026-11-20T10:00:00Z',
  end_time: '2026-11-20T10:45:00Z',
  timezone: 'America/Chicago',
  status: 'requested',
  reason: 'Annual school clearance, growth check, and booster vaccinations',
  preparation_notes: null,
  created_at: '2026-11-15T00:00:00Z',
  updated_at: '2026-11-15T00:00:00Z',
};

const mockCompletedAppointment: AppointmentItem = {
  ...mockAppointment,
  id: 'appt-ped-102',
  status: 'completed',
};

const mockSchoolForm: SchoolFormItem = {
  id: 'form-sports-201',
  profile_id: 'leo',
  title: 'State Universal Child Health Form',
  institution_name: 'Lincoln Park Elementary',
  form_type: 'sports_clearance',
  issued_date: '2026-08-15',
  expires_at: '2026-11-25',
  days_until_expiry: 10,
  renewal_reminder_id: 'rem-301',
  guardian_only: true,
  created_at: '2026-08-15T00:00:00Z',
  updated_at: '2026-08-15T00:00:00Z',
  prefill_draft: {
    student_name: 'Leo Joshi',
    date_of_birth: '2019-06-12',
    immunisations: [
      { name: 'DTaP', date: '2024-05-10', status: 'Up-to-date', source: 'EHR Sync' },
      { name: 'MMR', date: '2024-05-10', status: 'Up-to-date', source: 'EHR Sync' },
    ],
    allergies: [
      { substance: 'Peanuts', reaction: 'Anaphylaxis', severity: 'Severe' },
    ],
    active_medications: [
      { name: 'Albuterol HFA Inhaler', dosage: '90 mcg', frequency: 'PRN wheezing' },
    ],
    latest_vitals: {
      height: '122 cm',
      weight: '24.5 kg',
      blood_pressure: '102/65 mmHg',
      recorded_at: '2026-10-15',
    },
    disclaimer:
      'Draft prefill generated from your saved records for parent and clinician review. Never auto-submitted.',
    compiled_at: '2026-11-15T12:00:00Z',
  },
};

describe('E2E Schedule, School Forms & AppRail Navigation (Feature 8 / Issue #358)', () => {
  it('renders AppRail navigation with active profile and caring section links', () => {
    render(
      <AppRail
        activeProfile={{
          id: 'leo',
          name: 'Leo',
          shortName: 'Leo',
          relationship: 'Child',
          age: 7,
          role: 'You manage',
          colorSlot: 2,
        }}
        counts={{
          chat: 1,
          schedule: 2,
          vitals: 4,
          library: 3,
        }}
      />
    );

    expect(screen.getByTestId('app-rail')).toBeInTheDocument();
    expect(screen.getByText('Leo')).toBeInTheDocument();
    expect(screen.getByText('Child')).toBeInTheDocument();
    expect(screen.getByText(/You manage/i)).toBeInTheDocument();

    // Navigation links for profile
    const scheduleLink = screen.getByRole('link', { name: /Schedule/i });
    expect(scheduleLink).toHaveAttribute('href', '/p/leo/appointments');

    const vitalsLink = screen.getByRole('link', { name: /Vitals/i });
    expect(vitalsLink).toHaveAttribute('href', '/p/leo/vitals');

    const libraryLink = screen.getByRole('link', { name: /Library/i });
    expect(libraryLink).toHaveAttribute('href', '/p/leo/library');
  });

  it('toggles AppRail collapse state on collapse button click', () => {
    const handleToggle = vi.fn();
    render(
      <AppRail
        isCollapsed={false}
        onToggleCollapse={handleToggle}
      />
    );

    const toggleBtn = screen.getByRole('button', { name: /Collapse sidebar/i });
    fireEvent.click(toggleBtn);
    expect(handleToggle).toHaveBeenCalledTimes(1);
  });

  it('renders AppointmentCard with date tile, location, phone, and triggers onOpenHowToBook', () => {
    const handleHowToBook = vi.fn();
    render(
      <AppointmentCard
        appointment={mockAppointment}
        profileId="leo"
        onOpenHowToBook={handleHowToBook}
      />
    );

    expect(screen.getByTestId('appointment-card-appt-ped-101')).toBeInTheDocument();
    expect(screen.getByText('Annual Pediatric Well-Child Exam')).toBeInTheDocument();
    expect(screen.getByText('Booking Needed')).toBeInTheDocument();
    expect(screen.getByTestId('appointment-date-tile')).toBeInTheDocument();

    // Location link
    const locLink = screen.getByTestId('appointment-location-link');
    expect(locLink).toHaveAttribute(
      'href',
      expect.stringContaining('2525%20N%20Lincoln%20Ave')
    );

    // How to book button
    const bookBtn = screen.getByTestId('how-to-book-trigger-btn');
    fireEvent.click(bookBtn);
    expect(handleHowToBook).toHaveBeenCalledWith(mockAppointment);
  });

  it('renders post-visit sweep banner when appointment status is completed', () => {
    render(
      <AppointmentCard
        appointment={mockCompletedAppointment}
        profileId="leo"
      />
    );

    expect(screen.getByTestId('post-visit-sweep-banner')).toBeInTheDocument();
    expect(screen.getByText(/Visit concluded:/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Add Notes →/i })).toHaveAttribute(
      'href',
      '/p/leo/library?type=after_visit'
    );
  });

  it('renders SchoolFormsPanel with guardian safeguard, expiry status, and toggles prefill sheet', () => {
    const handleDelete = vi.fn();
    render(
      <SchoolFormsPanel
        forms={[mockSchoolForm]}
        guardianOnlyEnforced={true}
        onDeleteForm={handleDelete}
      />
    );

    expect(screen.getByTestId('school-forms-panel')).toBeInTheDocument();
    expect(screen.getByTestId('under-13-guardian-safeguard-badge')).toBeInTheDocument();
    expect(screen.getByTestId('school-form-card-form-sports-201')).toBeInTheDocument();
    expect(screen.getByTestId('school-form-expiry-form-sports-201')).toHaveTextContent(
      /Expires in 10 days/i
    );

    // Prefill sheet rendered initially for selected form
    expect(screen.getByTestId('school-form-prefill-sheet')).toBeInTheDocument();
    expect(screen.getByText('Leo Joshi')).toBeInTheDocument();
    expect(screen.getByText(/DTaP/i)).toBeInTheDocument();
  });

  it('renders SchoolFormPrefillSheet with disclaimer, medical info, and copy action', async () => {
    render(
      <SchoolFormPrefillSheet
        form={mockSchoolForm}
        onClose={vi.fn()}
      />
    );

    // Disclaimer
    expect(screen.getByText(/Draft prefill generated from your saved records/i)).toBeInTheDocument();

    // Vitals and allergies
    expect(screen.getByText(/Peanuts/i)).toBeInTheDocument();
    expect(screen.getByText(/Albuterol HFA Inhaler/i)).toBeInTheDocument();
    expect(screen.getByText(/122 cm/i)).toBeInTheDocument();

    // Copy action
    const copyBtn = screen.getByTestId('copy-prefill-btn');
    expect(copyBtn).toBeInTheDocument();
    fireEvent.click(copyBtn);
  });
});
