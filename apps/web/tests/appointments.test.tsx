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
import { AppointmentCard } from '@/components/appointments/AppointmentCard';
import { HowToBookSheet } from '@/components/appointments/HowToBookSheet';
import { RemindersChecklist } from '@/components/appointments/RemindersChecklist';
import type { AppointmentItem, ReminderItem } from '@/types/schedule';
import { humanizeRrule } from '@/lib/scheduleApi';

describe('Appointments & Reminders UI (Schedule Suite)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('AppointmentCard Component', () => {
    const mockAppointment: AppointmentItem = {
      id: 'apt-1',
      profile_id: 'prof-1',
      title: 'Cardiology Follow-Up',
      provider_name: 'Dr. Helen Vance',
      specialty: 'Cardiology',
      clinic_phone: '555-019-2834',
      location: 'Mercy Heart Center, Suite 402',
      preparation_notes: null,
      start_time: '2026-10-25T14:00:00Z',
      end_time: '2026-10-25T14:45:00Z',
      timezone: 'America/New_York',
      status: 'scheduled',
      reason: 'Evaluate elevated morning blood pressure trends',
      created_at: '2026-10-10T10:00:00Z',
      updated_at: '2026-10-10T10:00:00Z',
    };

    it('renders provider, specialty, clinic phone, and location details', () => {
      render(<AppointmentCard appointment={mockAppointment} profileId="prof-1" />);

      expect(screen.getByTestId('appointment-card-apt-1')).toBeInTheDocument();
      expect(screen.getByTestId('appointment-title')).toHaveTextContent('Cardiology Follow-Up');
      expect(screen.getByText(/Dr. Helen Vance/i)).toBeInTheDocument();
      expect(screen.getAllByText(/Cardiology/i).length).toBeGreaterThanOrEqual(1);

      const phoneLink = screen.getByTestId('appointment-phone-link');
      expect(phoneLink).toHaveAttribute('href', 'tel:555-019-2834');

      const locLink = screen.getByTestId('appointment-location-link');
      expect(locLink).toHaveAttribute('href', expect.stringContaining('Mercy%20Heart%20Center'));

      expect(screen.getByTestId('appointment-status-badge')).toHaveTextContent('Scheduled');
    });

    it('renders post-visit sweep banner when appointment status is completed', () => {
      const completedAppointment: AppointmentItem = {
        ...mockAppointment,
        id: 'apt-completed',
        status: 'completed',
      };

      render(<AppointmentCard appointment={completedAppointment} profileId="prof-1" />);
      expect(screen.getByTestId('post-visit-sweep-banner')).toBeInTheDocument();
      expect(screen.getByText(/Visit concluded/i)).toBeInTheDocument();
    });

    it('triggers export .ics download handler when calendar button is clicked', () => {
      render(<AppointmentCard appointment={mockAppointment} profileId="prof-1" />);
      const exportBtn = screen.getByTestId('export-single-ics-btn');
      expect(exportBtn).toBeInTheDocument();
      // Should not throw when clicked
      fireEvent.click(exportBtn);
    });

    it('displays "How to Book" button for requested appointments and calls callback', () => {
      const requestedAppointment: AppointmentItem = {
        ...mockAppointment,
        id: 'apt-req',
        status: 'requested',
      };
      const onOpenHowToBook = vi.fn();

      render(
        <AppointmentCard
          appointment={requestedAppointment}
          profileId="prof-1"
          onOpenHowToBook={onOpenHowToBook}
        />
      );

      const bookBtn = screen.getByTestId('how-to-book-trigger-btn');
      fireEvent.click(bookBtn);
      expect(onOpenHowToBook).toHaveBeenCalledWith(requestedAppointment);
    });
  });

  describe('HowToBookSheet Component', () => {
    const mockRequested: AppointmentItem = {
      id: 'apt-booking-req',
      profile_id: 'prof-1',
      title: 'Dermatology Full-Body Check',
      provider_name: 'Dr. Sarah Connor',
      specialty: 'Dermatology',
      clinic_phone: '555-012-3456',
      location: null,
      preparation_notes: null,
      start_time: '2026-10-28T10:00:00Z',
      end_time: '2026-10-28T10:30:00Z',
      timezone: 'America/New_York',
      status: 'requested',
      reason: 'Irregular border skin lesion on left forearm',
      created_at: '2026-10-10T10:00:00Z',
      updated_at: '2026-10-10T10:00:00Z',
    };

    it('renders 5-step phone script and allows toggling 5-point insurance checklist', () => {
      const onOpenChange = vi.fn();

      render(
        <HowToBookSheet
          isOpen={true}
          onOpenChange={onOpenChange}
          appointment={mockRequested}
        />
      );

      expect(screen.getByTestId('how-to-book-sheet')).toBeInTheDocument();
      expect(screen.getByTestId('phone-script-content')).toBeInTheDocument();
      expect(screen.getByText(/Hello, I would like to schedule an appointment with Dr. Sarah Connor/i)).toBeInTheDocument();

      // Check 5 checklist items
      expect(screen.getByTestId('checklist-item-0')).toHaveTextContent(/Verify in-network coverage/i);
      expect(screen.getByTestId('checklist-item-1')).toHaveTextContent(/Obtain PCP referral/i);
      expect(screen.getByTestId('checklist-item-2')).toHaveTextContent(/Prepare current medication list/i);
      expect(screen.getByTestId('checklist-item-3')).toHaveTextContent(/Bring photo ID/i);
      expect(screen.getByTestId('checklist-item-4')).toHaveTextContent(/Confirm clinic arrival time/i);

      // Toggle checklist item
      const item0Checkbox = screen.getByTestId('checklist-item-0').querySelector('input');
      expect(item0Checkbox).not.toBeChecked();
      fireEvent.click(screen.getByTestId('checklist-item-0'));
      expect(item0Checkbox).toBeChecked();
    });

    it('switches to portal draft view and displays copy-ready patient message', () => {
      const onOpenChange = vi.fn();

      render(
        <HowToBookSheet
          isOpen={true}
          onOpenChange={onOpenChange}
          appointment={mockRequested}
        />
      );

      const portalTab = screen.getByTestId('tab-portal-draft');
      fireEvent.click(portalTab);

      expect(screen.getByTestId('portal-draft-content')).toBeInTheDocument();
      const textarea = screen.getByTestId('portal-draft-textarea') as HTMLTextAreaElement;
      expect(textarea.value).toContain('Subject: Appointment Request');
      expect(textarea.value).toContain('Dr. Sarah Connor Care Team');
    });
  });

  describe('RemindersChecklist Component', () => {
    const mockReminders: ReminderItem[] = [
      {
        id: 'rem-1',
        profile_id: 'prof-1',
        title: 'Take Amlodipine 5mg',
        description: 'Take with morning glass of water',
        category: 'medication',
        rrule: 'RRULE:FREQ=DAILY;BYHOUR=8;BYMINUTE=0',
        timezone: 'UTC',
        next_due_at: '2026-10-13T12:00:00Z',
        status: 'pending',
        last_triggered_at: null,
        snooze_until: null,
        created_at: '2026-10-01T08:00:00Z',
        updated_at: '2026-10-01T08:00:00Z',
      },
      {
        id: 'rem-2',
        profile_id: 'prof-1',
        title: 'Log Morning Blood Pressure',
        description: null,
        category: 'vitals',
        rrule: 'RRULE:FREQ=DAILY;BYHOUR=8;BYMINUTE=30',
        timezone: 'UTC',
        next_due_at: '2026-10-11T12:30:00Z', // >24h in past => overdue
        status: 'missed',
        last_triggered_at: null,
        snooze_until: null,
        created_at: '2026-10-01T08:00:00Z',
        updated_at: '2026-10-01T08:00:00Z',
      },
      {
        id: 'rem-3',
        profile_id: 'prof-1',
        title: 'Annual Dental Cleaning',
        description: null,
        category: 'appointment',
        rrule: null,
        timezone: 'UTC',
        next_due_at: '2026-10-10T14:00:00Z',
        status: 'completed',
        last_triggered_at: null,
        snooze_until: null,
        created_at: '2026-10-01T08:00:00Z',
        updated_at: '2026-10-10T15:00:00Z',
      },
    ];

    it('renders active reminders, overdue badges, and humanized recurrence', () => {
      const onComplete = vi.fn();
      const onSnooze = vi.fn();

      render(
        <RemindersChecklist
          reminders={mockReminders}
          onCompleteReminder={onComplete}
          onSnoozeReminder={onSnooze}
        />
      );

      expect(screen.getByTestId('reminders-checklist-container')).toBeInTheDocument();
      expect(screen.getByTestId('reminder-item-rem-1')).toBeInTheDocument();
      expect(screen.getByTestId('reminder-item-rem-2')).toBeInTheDocument();

      // Check overdue badge for rem-2
      const rem2 = screen.getByTestId('reminder-item-rem-2');
      expect(rem2).toHaveTextContent(/Overdue/i);

      // Check humanized RRULE for rem-1
      expect(screen.getByTestId('reminder-item-rem-1')).toHaveTextContent(/Every day at/i);
    });

    it('calls onCompleteReminder when completion button is clicked', () => {
      const onComplete = vi.fn();
      const onSnooze = vi.fn();

      render(
        <RemindersChecklist
          reminders={mockReminders}
          onCompleteReminder={onComplete}
          onSnoozeReminder={onSnooze}
        />
      );

      const completeBtn = screen.getByTestId('complete-reminder-btn-rem-1');
      fireEvent.click(completeBtn);
      expect(onComplete).toHaveBeenCalledWith('rem-1');
    });

    it('opens snooze menu and triggers onSnoozeReminder with interval', () => {
      const onComplete = vi.fn();
      const onSnooze = vi.fn();

      render(
        <RemindersChecklist
          reminders={mockReminders}
          onCompleteReminder={onComplete}
          onSnoozeReminder={onSnooze}
        />
      );

      const snoozeToggle = screen.getByTestId('snooze-toggle-btn-rem-1');
      fireEvent.click(snoozeToggle);

      expect(screen.getByTestId('snooze-popover-menu')).toBeInTheDocument();
      const snooze15m = screen.getByTestId('snooze-15m-btn');
      fireEvent.click(snooze15m);

      expect(onSnooze).toHaveBeenCalledWith('rem-1', '+15m');
    });
  });

  describe('humanizeRrule Recurrence Formatter Utility', () => {
    it('humanizes standard RRULE frequencies', () => {
      expect(humanizeRrule('RRULE:FREQ=DAILY', '2026-10-13T08:00:00Z')).toContain('Every day at');
      expect(humanizeRrule('RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR', '2026-10-13T08:00:00Z')).toContain('Every Mon, Wed, Fri at');
      expect(humanizeRrule('RRULE:FREQ=MONTHLY', '2026-10-13T08:00:00Z')).toContain('Monthly at');
      expect(humanizeRrule(null, '2026-10-13T08:00:00Z')).toContain('One-time · Due');
    });
  });
});
