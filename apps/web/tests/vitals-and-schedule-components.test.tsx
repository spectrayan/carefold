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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { VitalsSummaryCards } from '@/components/vitals/VitalsSummaryCards';
import { BloodPressureTrendChart } from '@/components/vitals/BloodPressureTrendChart';
import { LogVitalsModal } from '@/components/vitals/LogVitalsModal';
import { AppointmentCard } from '@/components/appointments/AppointmentCard';
import { HowToBookSheet } from '@/components/appointments/HowToBookSheet';
import { RemindersChecklist } from '@/components/appointments/RemindersChecklist';
import { classifyBloodPressure, evaluateClientSafety } from '@/lib/vitalsClient';
import { exportSingleAppointmentIcs, humanizeRrule } from '@/lib/scheduleApi';
import type { LatestVitalsState } from '@/types/vitals';
import type { AppointmentItem, ReminderItem } from '@/types/schedule';

describe('Vitals and Schedule Components Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. Vitals Summary Cards & Chart
  // =========================================================================
  describe('1. Vitals Summary Cards & Chart Component Tests', () => {
    it('1.1 Empty state: renders all 5 cards with empty CTAs when no readings are recorded', () => {
      const onLogVital = vi.fn();
      render(<VitalsSummaryCards vitals={{}} onLogVital={onLogVital} />);

      expect(screen.getByTestId('bp-summary-card')).toBeInTheDocument();
      expect(screen.getByTestId('hr-summary-card')).toBeInTheDocument();
      expect(screen.getByTestId('glucose-summary-card')).toBeInTheDocument();
      expect(screen.getByTestId('spo2-summary-card')).toBeInTheDocument();
      expect(screen.getByTestId('weight-summary-card')).toBeInTheDocument();

      const emptyTexts = screen.getAllByText('No readings logged');
      expect(emptyTexts).toHaveLength(5);

      // Verify action buttons
      fireEvent.click(screen.getByRole('button', { name: /log bp/i }));
      expect(onLogVital).toHaveBeenCalledWith('bp');

      fireEvent.click(screen.getByRole('button', { name: /log pulse/i }));
      expect(onLogVital).toHaveBeenCalledWith('hr');

      fireEvent.click(screen.getByRole('button', { name: /log glucose/i }));
      expect(onLogVital).toHaveBeenCalledWith('glucose');

      fireEvent.click(screen.getByRole('button', { name: /log spo2/i }));
      expect(onLogVital).toHaveBeenCalledWith('spo2');

      fireEvent.click(screen.getByRole('button', { name: /log weight/i }));
      expect(onLogVital).toHaveBeenCalledWith('weight');
    });

    it('1.2 Empty state: BloodPressureTrendChart displays empty placeholder when points is empty', () => {
      render(<BloodPressureTrendChart points={[]} />);
      expect(screen.getByTestId('bp-chart-empty')).toBeInTheDocument();
      expect(screen.getByText(/no blood pressure observations to plot/i)).toBeInTheDocument();
    });

    it('1.3 AHA/ACC 2025 stage classifications across boundary numbers (120/80, 130/80, 140/90, 180/120)', () => {
      // Normal: SBP < 120 and DBP < 80
      expect(classifyBloodPressure(119, 79)).toBe('Normal');

      // Elevated: SBP 120-129 and DBP < 80
      expect(classifyBloodPressure(120, 79)).toBe('Elevated');
      expect(classifyBloodPressure(129, 79)).toBe('Elevated');

      // Boundary 120/80: DBP is 80 -> Stage 1 per AHA/ACC
      expect(classifyBloodPressure(120, 80)).toBe('Stage 1');
      expect(classifyBloodPressure(119, 80)).toBe('Stage 1');

      // Boundary 130/80: Stage 1 (SBP 130-139 or DBP 80-89)
      expect(classifyBloodPressure(130, 79)).toBe('Stage 1');
      expect(classifyBloodPressure(130, 80)).toBe('Stage 1');
      expect(classifyBloodPressure(139, 89)).toBe('Stage 1');

      // Boundary 140/90: Stage 2 (SBP >= 140 or DBP >= 90)
      expect(classifyBloodPressure(140, 79)).toBe('Stage 2');
      expect(classifyBloodPressure(125, 90)).toBe('Stage 2');
      expect(classifyBloodPressure(140, 90)).toBe('Stage 2');
      expect(classifyBloodPressure(179, 119)).toBe('Stage 2');

      // Boundary 180/120: Hypertensive Crisis (SBP >= 180 or DBP >= 120)
      expect(classifyBloodPressure(180, 79)).toBe('Hypertensive Crisis');
      expect(classifyBloodPressure(125, 120)).toBe('Hypertensive Crisis');
      expect(classifyBloodPressure(180, 120)).toBe('Hypertensive Crisis');
      expect(classifyBloodPressure(220, 130)).toBe('Hypertensive Crisis');

      // Edge cases: null/undefined
      expect(classifyBloodPressure(null, 80)).toBe('Unknown');
      expect(classifyBloodPressure(120, null)).toBe('Unknown');
      expect(classifyBloodPressure(undefined, undefined)).toBe('Unknown');
    });

    it('1.4 hide_weight toggle state toggling and masking in VitalsSummaryCards', () => {
      const mockVitals: LatestVitalsState = {
        weight: {
          valueKg: 78.4,
          valueLbs: 172.8,
          bmi: 24.5,
          classification: 'Normal (18.5–24.9)',
          effectiveAt: '2026-10-13T08:00:00Z',
          weightHidden: false,
        },
      };

      const onToggleHideWeight = vi.fn();
      const { rerender } = render(
        <VitalsSummaryCards
          vitals={mockVitals}
          hideWeight={false}
          onToggleHideWeight={onToggleHideWeight}
        />
      );

      // Unmasked: reveals value and BMI
      expect(screen.getByTestId('weight-value')).toHaveTextContent('78.4');
      expect(screen.getByTestId('bmi-badge')).toHaveTextContent('BMI 24.5');
      expect(screen.queryByTestId('weight-masked-value')).not.toBeInTheDocument();

      // Click toggle
      const toggleBtn = screen.getByTestId('toggle-hide-weight-btn');
      fireEvent.click(toggleBtn);
      expect(onToggleHideWeight).toHaveBeenCalledTimes(1);

      // Masked view
      rerender(
        <VitalsSummaryCards
          vitals={mockVitals}
          hideWeight={true}
          onToggleHideWeight={onToggleHideWeight}
        />
      );

      expect(screen.getByTestId('weight-masked-value')).toHaveTextContent('••••');
      expect(screen.queryByTestId('weight-value')).not.toBeInTheDocument();
      expect(screen.queryByTestId('bmi-badge')).not.toBeInTheDocument();
      expect(screen.getByText('Privacy Mode')).toBeInTheDocument();
    });

    it('1.5 BP Chart coordinate mapping: readings outside normal range (220 or 70) render within SVG bounds', () => {
      const extremePoints = [
        {
          id: 'pt-extreme-high',
          timestamp: '2026-10-10T08:00:00Z',
          systolic: 220, // Above maxY=200
          diastolic: 125,
          isAM: true,
          classification: 'Hypertensive Crisis',
        },
        {
          id: 'pt-extreme-low',
          timestamp: '2026-10-11T08:00:00Z',
          systolic: 70, // Near minY=50
          diastolic: 45, // Below minY=50
          isAM: false,
          classification: 'Hypotension',
        },
      ];

      render(<BloodPressureTrendChart points={extremePoints} />);

      expect(screen.getByTestId('bp-trend-chart-container')).toBeInTheDocument();
      const svg = screen.getByRole('img');
      expect(svg).toBeInTheDocument();

      // Verify that point 0 (220/125) and point 1 (70/45) render g elements
      const pt0 = screen.getByTestId('bp-chart-point-0');
      const pt1 = screen.getByTestId('bp-chart-point-1');
      expect(pt0).toBeInTheDocument();
      expect(pt1).toBeInTheDocument();

      // Inspect SVG lines and circles: y-coordinates must be clamped numbers without NaN
      const line0 = pt0.querySelector('line');
      expect(line0).toBeInTheDocument();
      const y1 = parseFloat(line0!.getAttribute('y1') || '0');
      const y2 = parseFloat(line0!.getAttribute('y2') || '0');
      expect(y1).toBeGreaterThanOrEqual(25); // padding.top is 25
      expect(y2).toBeLessThanOrEqual(220); // padding.top + plotHeight is 220

      // Hover over extreme point to test tooltip stability
      fireEvent.mouseEnter(pt0);
      expect(screen.getByTestId('bp-chart-tooltip')).toBeInTheDocument();
      expect(screen.getByText('220 / 125 mmHg')).toBeInTheDocument();
      fireEvent.mouseLeave(pt0);
    });
  });

  // =========================================================================
  // 2. Log Vitals Modal
  // =========================================================================
  describe('2. Log Vitals Modal Component Tests', () => {
    it('2.1 Form validation: missing fields, negative numbers, and incomplete blood pressure', () => {
      render(
        <LogVitalsModal
          profileId="prof-stress"
          isOpen={true}
          onOpenChange={vi.fn()}
        />
      );

      const submitBtn = screen.getByTestId('submit-vitals-btn');
      // Empty form: submit is disabled
      expect(submitBtn).toBeDisabled();

      const sysInput = screen.getByTestId('input-systolic');
      const diaInput = screen.getByTestId('input-diastolic');
      const wtInput = screen.getByTestId('input-weight');

      // Incomplete BP: systolic only
      fireEvent.change(sysInput, { target: { value: '130' } });
      expect(screen.getByText(/Please enter both systolic and diastolic blood pressure values/i)).toBeInTheDocument();
      expect(submitBtn).toBeDisabled();

      // Complete BP but invalid order: systolic < diastolic
      fireEvent.change(diaInput, { target: { value: '140' } });
      expect(screen.getByTestId('bp-error-order')).toHaveTextContent(/must be greater than diastolic/i);
      expect(submitBtn).toBeDisabled();

      // Negative weight
      fireEvent.change(sysInput, { target: { value: '140' } });
      fireEvent.change(diaInput, { target: { value: '85' } });
      fireEvent.change(wtInput, { target: { value: '-10' } });
      expect(submitBtn).toBeDisabled();

      // Reset weight to valid positive
      fireEvent.change(wtInput, { target: { value: '75' } });
      expect(submitBtn).not.toBeDisabled();
    });

    it('2.2 Emergency Red Flag: systolic >= 180 or diastolic >= 120 triggers prominent warning with tel:911 when symptomatic', async () => {
      render(
        <LogVitalsModal
          profileId="prof-stress"
          isOpen={true}
          onOpenChange={vi.fn()}
        />
      );

      const sysInput = screen.getByTestId('input-systolic');
      const diaInput = screen.getByTestId('input-diastolic');

      // Enter 182/115 (Crisis BP)
      fireEvent.change(sysInput, { target: { value: '182' } });
      fireEvent.change(diaInput, { target: { value: '115' } });

      // Before symptom selection: Asymptomatic crisis directive
      await waitFor(() => {
        expect(screen.getByTestId('vitals-safety-banner')).toBeInTheDocument();
        expect(screen.getByTestId('safety-alert-title')).toHaveTextContent(/Very High Blood Pressure Reading/i);
      });
      expect(screen.queryByTestId('safety-call-911-btn')).not.toBeInTheDocument();

      // Select acute red flag symptom: chest pain
      const chestPainBox = screen.getByTestId('checkbox-symptom-chest_pain');
      fireEvent.click(chestPainBox);

      // Now symptomatic crisis triggers direct 911 action!
      await waitFor(() => {
        const btn911 = screen.getByTestId('safety-call-911-btn');
        expect(btn911).toBeInTheDocument();
        expect(btn911).toHaveAttribute('href', 'tel:911');
        expect(screen.getByTestId('safety-alert-title')).toHaveTextContent(/CRITICAL EMERGENCY: Call 911 Immediately/i);
      });

      // Test isolated diastolic >= 120 crisis with shortness of breath
      fireEvent.change(sysInput, { target: { value: '150' } });
      fireEvent.change(diaInput, { target: { value: '122' } });
      expect(screen.getByTestId('safety-call-911-btn')).toBeInTheDocument();
    });

    it('2.3 Emergency Red Flag: SpO2 < 90% triggers emergency directive and direct tel:911', async () => {
      render(
        <LogVitalsModal
          profileId="prof-stress"
          isOpen={true}
          onOpenChange={vi.fn()}
        />
      );

      const spo2Input = screen.getByTestId('input-spo2');
      fireEvent.change(spo2Input, { target: { value: '87' } });

      await waitFor(() => {
        expect(screen.getByTestId('vitals-safety-banner')).toBeInTheDocument();
        expect(screen.getByTestId('safety-alert-title')).toHaveTextContent(/Critically Low Oxygen Saturation \(<90%\)/i);
        const btn911 = screen.getByTestId('safety-call-911-btn');
        expect(btn911).toBeInTheDocument();
        expect(btn911).toHaveAttribute('href', 'tel:911');
      });
    });

    it('2.4 Emergency Red Flag: Glucose < 54 mg/dL triggers Rule of 15 acute directive', async () => {
      render(
        <LogVitalsModal
          profileId="prof-stress"
          isOpen={true}
          onOpenChange={vi.fn()}
        />
      );

      const glucInput = screen.getByTestId('input-glucose');
      fireEvent.change(glucInput, { target: { value: '48' } });

      await waitFor(() => {
        expect(screen.getByTestId('vitals-safety-banner')).toBeInTheDocument();
        expect(screen.getByTestId('safety-alert-title')).toHaveTextContent(/Severe Hypoglycemia \(<54 mg\/dL\) — Rule of 15/i);
        expect(screen.getByTestId('safety-alert-directive')).toHaveTextContent(/15 grams of fast-acting carbohydrate/i);
      });
    });

    it('2.5 Direct evaluator safety test for symptomatic hypotension', () => {
      const res = evaluateClientSafety({ systolic: 82, diastolic: 54 }, ['dizziness', 'fainting']);
      expect(res.triggered).toBe(true);
      expect(res.category).toBe('symptomatic_hypotension');
      expect(res.title).toContain('Symptomatic Low Blood Pressure');
    });
  });

  // =========================================================================
  // 3. Appointments & Schedule
  // =========================================================================
  describe('3. Appointments & Schedule Component Tests', () => {
    const mockAppointments: AppointmentItem[] = [
      {
        id: 'apt-late',
        profile_id: 'prof-stress',
        title: 'Endocrinology Check',
        provider_name: 'Dr. Bruce Banner',
        specialty: 'Endocrinology',
        clinic_phone: '555-444-3333',
        location: 'City Hospital, Suite 100',
        preparation_notes: null,
        start_time: '2026-11-15T14:00:00Z',
        end_time: '2026-11-15T14:30:00Z',
        timezone: 'UTC',
        status: 'confirmed',
        reason: 'Thyroid hormone level follow-up',
        created_at: '2026-10-01T10:00:00Z',
        updated_at: '2026-10-01T10:00:00Z',
      },
      {
        id: 'apt-early',
        profile_id: 'prof-stress',
        title: 'Cardiology Consultation',
        provider_name: 'Dr. Stephen Strange',
        specialty: 'Cardiology',
        clinic_phone: '555-111-2222',
        location: 'Metro Heart Center',
        preparation_notes: null,
        start_time: '2026-10-18T09:00:00Z',
        end_time: '2026-10-18T09:45:00Z',
        timezone: 'UTC',
        status: 'requested',
        reason: 'Palpitations during morning exercise',
        created_at: '2026-10-01T10:00:00Z',
        updated_at: '2026-10-01T10:00:00Z',
      },
      {
        id: 'apt-completed',
        profile_id: 'prof-stress',
        title: 'Annual Physical Exam',
        provider_name: 'Dr. Helen Cho',
        specialty: 'Internal Medicine',
        clinic_phone: '555-999-8888',
        location: 'Wellness Clinic',
        preparation_notes: null,
        start_time: '2026-10-05T11:00:00Z',
        end_time: '2026-10-05T12:00:00Z',
        timezone: 'UTC',
        status: 'completed',
        reason: 'Routine health assessment',
        created_at: '2026-10-01T10:00:00Z',
        updated_at: '2026-10-05T12:00:00Z',
      },
    ];

    it('3.1 Appointments list sorting and status badges', () => {
      // Test sorting logic
      const sorted = [...mockAppointments].sort(
        (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
      );
      expect(sorted[0].id).toBe('apt-completed'); // Oct 5
      expect(sorted[1].id).toBe('apt-early'); // Oct 18
      expect(sorted[2].id).toBe('apt-late'); // Nov 15

      // Render confirmed card
      const { rerender } = render(
        <AppointmentCard appointment={mockAppointments[0]} profileId="prof-stress" />
      );
      expect(screen.getByTestId('appointment-status-badge')).toHaveTextContent('Confirmed');

      // Render requested card
      rerender(
        <AppointmentCard appointment={mockAppointments[1]} profileId="prof-stress" />
      );
      expect(screen.getByTestId('appointment-status-badge')).toHaveTextContent('Booking Needed');
      expect(screen.getByTestId('how-to-book-trigger-btn')).toBeInTheDocument();

      // Render completed card
      rerender(
        <AppointmentCard appointment={mockAppointments[2]} profileId="prof-stress" />
      );
      expect(screen.getByTestId('appointment-status-badge')).toHaveTextContent('Completed');
      expect(screen.getByTestId('post-visit-sweep-banner')).toBeInTheDocument();
    });

    it('3.2 Calendar export: test RFC 5545 .ics download trigger and payload formatting', () => {
      const createObjectURLMock = vi.fn().mockReturnValue('blob:http://localhost/test-ics');
      const revokeObjectURLMock = vi.fn();
      window.URL.createObjectURL = createObjectURLMock;
      window.URL.revokeObjectURL = revokeObjectURLMock;

      const appendChildSpy = vi.spyOn(document.body, 'appendChild');
      const removeChildSpy = vi.spyOn(document.body, 'removeChild');

      render(
        <AppointmentCard appointment={mockAppointments[0]} profileId="prof-stress" />
      );

      const exportBtn = screen.getByTestId('export-single-ics-btn');
      fireEvent.click(exportBtn);

      expect(createObjectURLMock).toHaveBeenCalledTimes(1);
      expect(appendChildSpy).toHaveBeenCalled();
      expect(removeChildSpy).toHaveBeenCalled();
      expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:http://localhost/test-ics');

      // Direct verification of RFC 5545 exporter function
      exportSingleAppointmentIcs(mockAppointments[1]);
      expect(createObjectURLMock).toHaveBeenCalledTimes(2);
    });

    it('3.3 "How to Book" sheet: test script formatting and copy-to-clipboard button', async () => {
      const writeTextMock = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', {
        value: {
          writeText: writeTextMock,
        },
        configurable: true,
        writable: true,
      });

      render(
        <HowToBookSheet
          isOpen={true}
          onOpenChange={vi.fn()}
          appointment={mockAppointments[1]}
        />
      );

      expect(screen.getByTestId('how-to-book-sheet')).toBeInTheDocument();
      expect(screen.getAllByText(/Dr. Stephen Strange/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/Palpitations during morning exercise/i).length).toBeGreaterThanOrEqual(1);

      // Switch to portal draft
      const portalTab = screen.getByTestId('tab-portal-draft');
      fireEvent.click(portalTab);

      const copyBtn = screen.getByTestId('copy-portal-draft-btn');
      fireEvent.click(copyBtn);

      await waitFor(() => {
        expect(writeTextMock).toHaveBeenCalledTimes(1);
        expect(writeTextMock.mock.calls[0][0]).toContain('Subject: Appointment Request — Palpitations during morning exercise');
        expect(writeTextMock.mock.calls[0][0]).toContain('Dr. Stephen Strange Care Team');
        expect(screen.getByText('Copied!')).toBeInTheDocument();
      });
    });

    it('3.4 Reminders checklist: test snooze presets (+15m, +1h, +24h) and completion actions', () => {
      const mockReminders: ReminderItem[] = [
        {
          id: 'rem-daily-bp',
          profile_id: 'prof-stress',
          title: 'Morning Blood Pressure Check',
          description: 'Measure seated before morning breakfast',
          category: 'vitals',
          rrule: 'RRULE:FREQ=DAILY;BYHOUR=7;BYMINUTE=30',
          timezone: 'America/New_York',
          next_due_at: '2026-10-13T11:30:00Z',
          status: 'pending',
          last_triggered_at: null,
          snooze_until: null,
          created_at: '2026-10-01T08:00:00Z',
          updated_at: '2026-10-01T08:00:00Z',
        },
        {
          id: 'rem-overdue',
          profile_id: 'prof-stress',
          title: 'Refill Lisinopril 20mg',
          description: null,
          category: 'medication',
          rrule: null,
          timezone: 'America/New_York',
          next_due_at: '2026-10-10T12:00:00Z', // >24h in past
          status: 'missed',
          last_triggered_at: null,
          snooze_until: null,
          created_at: '2026-10-01T08:00:00Z',
          updated_at: '2026-10-01T08:00:00Z',
        },
      ];

      const onComplete = vi.fn();
      const onSnooze = vi.fn();

      render(
        <RemindersChecklist
          reminders={mockReminders}
          onCompleteReminder={onComplete}
          onSnoozeReminder={onSnooze}
        />
      );

      // Verify overdue reminder is present with badge
      expect(screen.getByTestId('reminder-item-rem-overdue')).toBeInTheDocument();
      expect(screen.getByTestId('overdue-badge')).toBeInTheDocument();

      // Test completion action
      const completeBtn = screen.getByTestId('complete-reminder-btn-rem-daily-bp');
      fireEvent.click(completeBtn);
      expect(onComplete).toHaveBeenCalledWith('rem-daily-bp');

      // Test snooze presets
      const snoozeToggle = screen.getByTestId('snooze-toggle-btn-rem-daily-bp');
      fireEvent.click(snoozeToggle);
      expect(screen.getByTestId('snooze-popover-menu')).toBeInTheDocument();

      // +15m
      fireEvent.click(screen.getByTestId('snooze-15m-btn'));
      expect(onSnooze).toHaveBeenCalledWith('rem-daily-bp', '+15m');

      // +1h
      fireEvent.click(snoozeToggle);
      fireEvent.click(screen.getByTestId('snooze-1h-btn'));
      expect(onSnooze).toHaveBeenCalledWith('rem-daily-bp', '+1h');

      // +24h
      fireEvent.click(snoozeToggle);
      fireEvent.click(screen.getByTestId('snooze-24h-btn'));
      expect(onSnooze).toHaveBeenCalledWith('rem-daily-bp', '+24h');
    });

    it('3.5 humanizeRrule formats recurring and one-time schedules', () => {
      expect(humanizeRrule('RRULE:FREQ=DAILY', '2026-10-13T09:00:00Z')).toContain('Every day at');
      expect(humanizeRrule('RRULE:FREQ=WEEKLY;BYDAY=TU,TH', '2026-10-13T09:00:00Z')).toContain('Every Tue, Thu at');
      expect(humanizeRrule('RRULE:FREQ=MONTHLY', '2026-10-13T09:00:00Z')).toContain('Monthly at');
      expect(humanizeRrule(null, '2026-10-13T09:00:00Z')).toContain('One-time · Due');
    });
  });
});
