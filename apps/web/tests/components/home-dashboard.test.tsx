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

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { HomeDashboardClient, type CareProfile } from '@/app/p/[profileId]/HomeDashboardClient';

const mockRosaProfile: CareProfile = {
  id: 'rosa',
  name: 'Rosa Rivera',
  relationship: 'Mom',
  colorSlot: 3,
  role: 'You manage'
};

const mockEmptyProfile: CareProfile = {
  id: 'new-profile',
  name: 'Alex Taylor',
  relationship: 'Self',
  colorSlot: 1,
  role: 'Personal care'
};

const mockRosaAppointment = {
  id: 'appt-cardio',
  title: 'Cardiology follow-up',
  monthShort: 'OCT',
  dayNumber: 13,
  timeStr: 'Tuesday 10:30 AM',
  clinician: 'Dr. Elena Whitfield · Cardiology',
  clinic: 'Lakeside Heart Clinic',
  linkedDocTitle: 'Discharge summary, Sep 2',
  specialistId: 'visit-steward',
  specialistTitle: 'Visit Steward',
  prepCompletedQuestions: 4,
  prepTotalQuestions: 6,
  checklist: [
    { id: 'c1', text: 'Questions for cardiologist ready', isDone: true },
    { id: 'c2', text: 'Bring current medication list and BP log', isDone: false },
    { id: 'c3', text: 'Bring prior auth approval letter', isDone: false },
    { id: 'c4', text: 'Note recent symptom dates', isDone: false }
  ],
  savedToNotesTimestamp: "Saved to Rosa's notes · Oct 6"
};

const mockRosaPaperwork = {
  id: 'eob-sep28',
  title: 'Explanation of benefits · Sep 28',
  facility: 'Lakeside Heart Clinic · echo + office visit',
  statusBadge: '1 to review',
  planName: 'Blue Shield Silver PPO',
  deductibleMet: '$450 / $1,500',
  copaySpecialist: '$35 Specialist',
  billedAmount: '$412.00',
  planPaidAmount: '$318.40',
  patientOwedAmount: '$93.60'
};

const mockRosaRoutines = [
  {
    id: 'r1',
    name: 'Metoprolol 25mg',
    daysCompleted: [true, true, true, true, true, false, true],
    summaryCount: '6/7'
  },
  {
    id: 'r2',
    name: 'Blood pressure log',
    daysCompleted: [true, true, false, true, true, true, false],
    summaryCount: '5/7'
  }
];

describe('Home Dashboard Client (/p/[profileId])', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders hero greeting with person name, role tag, and privacy indicator', () => {
    render(<HomeDashboardClient profile={mockRosaProfile} />);

    expect(screen.getByText(/good (morning|afternoon|evening), rosa rivera/i)).toBeInTheDocument();
    expect(screen.getByText(/you manage · mom/i)).toBeInTheDocument();
    expect(screen.getByText(/private on this computer/i)).toBeInTheDocument();
  });

  it('renders "Ask about [Person]" composer with quick starter prompt buttons', () => {
    render(<HomeDashboardClient profile={mockRosaProfile} />);

    const textarea = screen.getByPlaceholderText(/ask anything about rosa's health, paperwork, or visits/i);
    expect(textarea).toBeInTheDocument();

    expect(screen.getByRole('button', { name: /prepare for cardiologist visit/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /review recent bills/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /check medication schedule/i })).toBeInTheDocument();
  });

  it('clicking starter button populates the composer textarea', () => {
    render(<HomeDashboardClient profile={mockRosaProfile} />);

    const starterBtn = screen.getByRole('button', { name: /prepare for cardiologist visit/i });
    fireEvent.click(starterBtn);

    const textarea = screen.getByPlaceholderText(/ask anything about rosa's health, paperwork, or visits/i) as HTMLTextAreaElement;
    expect(textarea.value).toBe('Prepare questions for cardiologist visit on Tuesday');
  });

  it('renders next visit prep card with progress bar, date badge, and checklist', () => {
    render(
      <HomeDashboardClient
        profile={mockRosaProfile}
        initialAppointment={mockRosaAppointment}
      />
    );

    expect(screen.getByRole('heading', { name: /next visit prep/i })).toBeInTheDocument();
    expect(screen.getByText('Dr. Elena Whitfield · Cardiology')).toBeInTheDocument();
    expect(screen.getAllByText(/ready/i).length).toBeGreaterThanOrEqual(1);

    // Check checklist items
    const checklistItems = screen.getAllByRole('checkbox');
    expect(checklistItems.length).toBeGreaterThanOrEqual(4);
  });

  it('allows toggling checklist items in next visit prep card', () => {
    render(
      <HomeDashboardClient
        profile={mockRosaProfile}
        initialAppointment={mockRosaAppointment}
      />
    );

    const checklistItems = screen.getAllByRole('checkbox');
    const firstCheckbox = checklistItems[0];
    const initialChecked = firstCheckbox.getAttribute('aria-checked') === 'true';

    fireEvent.click(firstCheckbox);
    const updatedChecked = firstCheckbox.getAttribute('aria-checked') === 'true';
    expect(updatedChecked).toBe(!initialChecked);
  });

  it('renders paperwork summary card with financial key-value grid', () => {
    render(
      <HomeDashboardClient
        profile={mockRosaProfile}
        initialPaperwork={mockRosaPaperwork}
      />
    );

    expect(screen.getByRole('heading', { name: /paperwork & coverage/i })).toBeInTheDocument();
    expect(screen.getByText(/blue shield silver ppo/i)).toBeInTheDocument();
    expect(screen.getByText('$450 / $1,500')).toBeInTheDocument();
    expect(screen.getByText('$35 Specialist')).toBeInTheDocument();
  });

  it('renders daily routines card with 7-day dot completion indicators', () => {
    render(
      <HomeDashboardClient
        profile={mockRosaProfile}
        initialRoutines={mockRosaRoutines}
      />
    );

    expect(screen.getByRole('heading', { name: /daily routines/i })).toBeInTheDocument();
    expect(screen.getByText(/metoprolol 25mg/i)).toBeInTheDocument();
    expect(screen.getByText(/blood pressure log/i)).toBeInTheDocument();
  });

  it('renders empty state fallbacks for new profile without appointments or paperwork', () => {
    render(<HomeDashboardClient profile={mockEmptyProfile} />);

    expect(screen.getByText(/no upcoming visits scheduled/i)).toBeInTheDocument();
    expect(screen.getByText(/no insurance paperwork on file/i)).toBeInTheDocument();
    expect(screen.getByText(/no active daily routines/i)).toBeInTheDocument();
  });
});
