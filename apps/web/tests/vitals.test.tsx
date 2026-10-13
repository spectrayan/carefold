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
import { DiurnalTrendTable } from '@/components/vitals/DiurnalTrendTable';
import { BloodPressureTrendChart } from '@/components/vitals/BloodPressureTrendChart';
import { LogVitalsModal } from '@/components/vitals/LogVitalsModal';
import { classifyBloodPressure, evaluateClientSafety } from '@/lib/vitalsClient';
import type { LatestVitalsState, VitalsTrendsResponse } from '@/types/vitals';

describe('Vitals UI Components & Safety Classifiers', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('AHA/ACC 2025 Blood Pressure Classification & Safety', () => {
    it('accurately classifies blood pressure stages', () => {
      expect(classifyBloodPressure(115, 75)).toBe('Normal');
      expect(classifyBloodPressure(125, 75)).toBe('Elevated');
      expect(classifyBloodPressure(135, 82)).toBe('Stage 1');
      expect(classifyBloodPressure(145, 92)).toBe('Stage 2');
      expect(classifyBloodPressure(185, 122)).toBe('Hypertensive Crisis');
    });

    it('evaluates client safety red flags for hypertensive crisis with symptoms', () => {
      const evalResult = evaluateClientSafety(
        { systolic: 185, diastolic: 122 },
        ['chest_pain', 'shortness_of_breath']
      );
      expect(evalResult.triggered).toBe(true);
      expect(evalResult.category).toBe('bp_crisis_symptomatic');
      expect(evalResult.severity).toBe('emergency');
      expect(evalResult.call911).toBe(true);
    });

    it('evaluates client safety for severe hypoxemia (<90% SpO2)', () => {
      const evalResult = evaluateClientSafety({ spo2: 88 });
      expect(evalResult.triggered).toBe(true);
      expect(evalResult.category).toBe('severe_hypoxemia');
      expect(evalResult.severity).toBe('emergency');
    });

    it('evaluates client safety for severe hypoglycemia (<54 mg/dL)', () => {
      const evalResult = evaluateClientSafety({ glucose: 48 });
      expect(evalResult.triggered).toBe(true);
      expect(evalResult.category).toBe('severe_hypoglycemia');
      expect(evalResult.directive).toContain('15 grams');
    });
  });

  describe('VitalsSummaryCards Component', () => {
    const mockVitals: LatestVitalsState = {
      bloodPressure: {
        systolic: 128,
        diastolic: 82,
        effectiveAt: '2026-10-13T08:30:00Z',
        stage: 'Stage 1',
        isAM: true,
        deltaSys: -2,
        deltaDia: 1,
      },
      heartRate: {
        value: 72,
        effectiveAt: '2026-10-13T08:30:00Z',
        classification: 'Normal (60–100)',
      },
      bloodGlucose: {
        value: 95,
        unit: 'mg/dL',
        effectiveAt: '2026-10-13T08:30:00Z',
        classification: 'Normal (70–99)',
      },
      spo2: {
        value: 98,
        effectiveAt: '2026-10-13T08:30:00Z',
        classification: 'Normal (95–100%)',
      },
      weight: {
        valueKg: 70.5,
        valueLbs: 155.4,
        bmi: 23.2,
        classification: 'Normal (18.5–24.9)',
        effectiveAt: '2026-10-13T08:30:00Z',
        weightHidden: false,
      },
    };

    it('renders all biometric cards and metrics accurately', () => {
      render(<VitalsSummaryCards vitals={mockVitals} />);

      expect(screen.getByTestId('bp-summary-card')).toBeInTheDocument();
      expect(screen.getByText('128/82')).toBeInTheDocument();
      expect(screen.getByText('Stage 1')).toBeInTheDocument();

      expect(screen.getByTestId('hr-summary-card')).toBeInTheDocument();
      expect(screen.getByText('72')).toBeInTheDocument();

      expect(screen.getByTestId('glucose-summary-card')).toBeInTheDocument();
      expect(screen.getByText('95')).toBeInTheDocument();

      expect(screen.getByTestId('spo2-summary-card')).toBeInTheDocument();
      expect(screen.getByText('98')).toBeInTheDocument();

      expect(screen.getByTestId('weight-summary-card')).toBeInTheDocument();
      expect(screen.getByText('70.5')).toBeInTheDocument();
      expect(screen.getByText(/BMI 23.2/i)).toBeInTheDocument();
    });

    it('masks weight and BMI when hideWeight=true', () => {
      render(<VitalsSummaryCards vitals={mockVitals} hideWeight={true} />);

      const weightCard = screen.getByTestId('weight-summary-card');
      expect(weightCard).toBeInTheDocument();
      expect(screen.queryByText('70.5')).not.toBeInTheDocument();
      expect(screen.getByTestId('weight-masked-value')).toBeInTheDocument();
    });

    it('triggers onToggleHideWeight callback when privacy toggle is clicked', () => {
      const toggleFn = vi.fn();
      render(<VitalsSummaryCards vitals={mockVitals} hideWeight={false} onToggleHideWeight={toggleFn} />);

      const toggleBtn = screen.getByTestId('toggle-hide-weight-btn');
      fireEvent.click(toggleBtn);
      expect(toggleFn).toHaveBeenCalledTimes(1);
    });

    it('triggers onLogVital callback when log vitals action button is clicked on empty card', () => {
      const logFn = vi.fn();
      render(<VitalsSummaryCards vitals={{}} onLogVital={logFn} />);

      const logBpBtn = screen.getByRole('button', { name: /log bp/i });
      fireEvent.click(logBpBtn);
      expect(logFn).toHaveBeenCalledWith('bp');
    });
  });

  describe('BloodPressureTrendChart Component', () => {
    const mockPoints = [
      {
        id: 'pt-1',
        timestamp: '2026-10-10T08:00:00Z',
        systolic: 120,
        diastolic: 78,
        isAM: true,
        classification: 'Normal',
      },
      {
        id: 'pt-2',
        timestamp: '2026-10-11T19:00:00Z',
        systolic: 130,
        diastolic: 85,
        isAM: false,
        classification: 'Stage 1',
      },
    ];

    it('renders native SVG chart elements, normal target zone, and markers', () => {
      render(<BloodPressureTrendChart points={mockPoints} />);

      expect(screen.getByTestId('bp-trend-chart-container')).toBeInTheDocument();
      expect(screen.getByRole('img')).toBeInTheDocument();
      expect(screen.getByTestId('bp-chart-point-0')).toBeInTheDocument();
      expect(screen.getByTestId('bp-chart-point-1')).toBeInTheDocument();
    });

    it('renders empty state when no BP observations are available', () => {
      render(<BloodPressureTrendChart points={[]} />);
      expect(screen.getByTestId('bp-chart-empty')).toBeInTheDocument();
    });
  });

  describe('DiurnalTrendTable Component', () => {
    const mockTrends: VitalsTrendsResponse = {
      profile_id: 'prof-1',
      metric: 'blood_pressure',
      timezone: 'America/New_York',
      computed_at: '2026-10-13T08:00:00Z',
      trends: {
        '7_day': {
          am: { count: 7, systolic: 122, diastolic: 78, pulse: 70, classification: 'Normal' },
          pm: { count: 6, systolic: 128, diastolic: 82, pulse: 74, classification: 'Stage 1' },
        },
        '30_day': {
          am: { count: 30, systolic: 124, diastolic: 79, pulse: 71, classification: 'Normal' },
          pm: { count: 28, systolic: 130, diastolic: 83, pulse: 75, classification: 'Stage 1' },
        },
        '90_day': {
          am: { count: 85, systolic: 125, diastolic: 80, pulse: 72, classification: 'Stage 1' },
          pm: { count: 82, systolic: 131, diastolic: 84, pulse: 76, classification: 'Stage 1' },
        },
      },
    };

    it('renders AM and PM averages and allows switching trend windows', () => {
      render(<DiurnalTrendTable trends={mockTrends} />);

      expect(screen.getByTestId('diurnal-trend-table-container')).toBeInTheDocument();
      // Default window is 30 Days
      expect(screen.getByTestId('am-mean-bp')).toHaveTextContent('124 / 79 mmHg');
      expect(screen.getByTestId('pm-mean-bp')).toHaveTextContent('130 / 83 mmHg');

      // Switch to 7-day
      const btn7 = screen.getByRole('radio', { name: /7 Days/i });
      fireEvent.click(btn7);
      expect(screen.getByTestId('am-mean-bp')).toHaveTextContent('122 / 78 mmHg');
      expect(screen.getByTestId('pm-mean-bp')).toHaveTextContent('128 / 82 mmHg');
    });
  });

  describe('LogVitalsModal Component', () => {
    it('validates systolic > diastolic and displays real-time red flag emergency warning', async () => {
      const onSuccess = vi.fn();
      const onOpenChange = vi.fn();

      render(
        <LogVitalsModal
          profileId="prof-1"
          isOpen={true}
          onOpenChange={onOpenChange}
          onSuccess={onSuccess}
        />
      );

      const sysInput = screen.getByTestId('input-systolic');
      const diaInput = screen.getByTestId('input-diastolic');

      // Enter invalid: SBP < DBP
      fireEvent.change(sysInput, { target: { value: '80' } });
      fireEvent.change(diaInput, { target: { value: '120' } });

      expect(screen.getByTestId('bp-error-order')).toHaveTextContent(
        /Systolic pressure must be greater than diastolic pressure/i
      );

      // Enter hypertensive crisis reading with symptoms: 185/122 + chest pain
      fireEvent.change(sysInput, { target: { value: '185' } });
      fireEvent.change(diaInput, { target: { value: '122' } });

      const symptomCheckbox = screen.getByTestId('checkbox-symptom-chest_pain');
      fireEvent.click(symptomCheckbox);

      // Check for red flag emergency banner
      await waitFor(() => {
        expect(screen.getByTestId('vitals-safety-banner')).toBeInTheDocument();
        expect(screen.getByTestId('safety-call-911-btn')).toBeInTheDocument();
      });
    });
  });
});
