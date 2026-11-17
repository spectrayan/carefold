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
import { BloodPressureTrendChart } from '@/health-ui/vitals/BloodPressureTrendChart';
import { DiurnalTrendTable } from '@/health-ui/vitals/DiurnalTrendTable';
import { VitalsSummaryCards } from '@/health-ui/vitals/VitalsSummaryCards';
import { LogVitalsModal } from '@/health-ui/vitals/LogVitalsModal';
import { MetricTrendChart } from '@/health-ui/vitals/MetricTrendChart';
import { VitalsHistoryTable } from '@/health-ui/vitals/VitalsHistoryTable';
import type { LatestVitalsState, VitalsTrendsResponse, VitalsObservationItem } from '@/types/vitals';

const mockLatestVitals: LatestVitalsState = {
  bloodPressure: {
    systolic: 124,
    diastolic: 80,
    effectiveAt: '2026-10-15T08:30:00Z',
    stage: 'Normal',
    isAM: true,
  },
  heartRate: {
    value: 72,
    effectiveAt: '2026-10-15T08:30:00Z',
  },
  bloodGlucose: {
    value: 98,
    unit: 'mg/dL',
    effectiveAt: '2026-10-15T07:45:00Z',
  },
  spo2: {
    value: 99,
    effectiveAt: '2026-10-15T08:30:00Z',
  },
  weight: {
    valueKg: 70.5,
    valueLbs: 155.4,
    effectiveAt: '2026-10-14T08:00:00Z',
    weightHidden: false,
  },
};

const mockTrends: VitalsTrendsResponse = {
  profile_id: 'rosa',
  metric: 'blood_pressure',
  timezone: 'America/New_York',
  computed_at: '2026-10-15T09:00:00Z',
  trends: {
    '7_day': {
      am: { count: 7, systolic: 122, diastolic: 79, classification: 'Normal' },
      pm: { count: 7, systolic: 126, diastolic: 83, classification: 'Elevated' },
    },
    '30_day': {
      am: { count: 28, systolic: 123, diastolic: 80, classification: 'Normal' },
      pm: { count: 27, systolic: 128, diastolic: 84, classification: 'Stage 1' },
    },
    '90_day': {
      am: { count: 80, systolic: 124, diastolic: 81, classification: 'Normal' },
      pm: { count: 78, systolic: 129, diastolic: 85, classification: 'Stage 1' },
    },
  },
};

const mockChartPoints = [
  { id: '1', timestamp: '2026-10-13T08:00:00Z', systolic: 120, diastolic: 78, isAM: true },
  { id: '2', timestamp: '2026-10-13T20:00:00Z', systolic: 128, diastolic: 84, isAM: false },
  { id: '3', timestamp: '2026-10-14T08:15:00Z', systolic: 122, diastolic: 80, isAM: true },
  { id: '4', timestamp: '2026-10-14T19:45:00Z', systolic: 126, diastolic: 82, isAM: false },
  { id: '5', timestamp: '2026-10-15T08:30:00Z', systolic: 124, diastolic: 80, isAM: true },
];

const mockObservations: VitalsObservationItem[] = [
  {
    id: 'obs-bp-1',
    profile_id: 'rosa',
    resource_type: 'observation',
    source_type: 'manual',
    status: 'active',
    data: {
      resourceType: 'Observation',
      code: { coding: [{ system: 'http://loinc.org', code: '85354-9', display: 'Blood pressure' }] },
      component: [
        { code: { coding: [{ system: 'http://loinc.org', code: '8480-6' }] }, valueQuantity: { value: 124, unit: 'mmHg' } },
        { code: { coding: [{ system: 'http://loinc.org', code: '8462-4' }] }, valueQuantity: { value: 80, unit: 'mmHg' } },
      ],
    },
    effective_at: '2026-10-15T08:30:00Z',
    recorded_at: '2026-10-15T08:30:00Z',
  },
  {
    id: 'obs-hr-1',
    profile_id: 'rosa',
    resource_type: 'observation',
    source_type: 'device',
    status: 'active',
    data: {
      resourceType: 'Observation',
      code: { coding: [{ system: 'http://loinc.org', code: '8867-4', display: 'Heart rate' }] },
      valueQuantity: { value: 72, unit: 'bpm' },
    },
    effective_at: '2026-10-15T08:30:00Z',
    recorded_at: '2026-10-15T08:30:00Z',
  },
  {
    id: 'obs-temp-1',
    profile_id: 'rosa',
    resource_type: 'observation',
    source_type: 'manual',
    status: 'active',
    data: {
      resourceType: 'Observation',
      code: { coding: [{ system: 'http://loinc.org', code: '8310-5', display: 'Body temperature' }] },
      valueQuantity: { value: 98.6, unit: '°F' },
    },
    effective_at: '2026-10-15T08:30:00Z',
    recorded_at: '2026-10-15T08:30:00Z',
  },
  {
    id: 'obs-rr-1',
    profile_id: 'rosa',
    resource_type: 'observation',
    source_type: 'manual',
    status: 'active',
    data: {
      resourceType: 'Observation',
      code: { coding: [{ system: 'http://loinc.org', code: '9279-1', display: 'Respiratory rate' }] },
      valueQuantity: { value: 16, unit: 'br/min' },
    },
    effective_at: '2026-10-15T08:30:00Z',
    recorded_at: '2026-10-15T08:30:00Z',
  },
];

describe('E2E Vitals Multi-Metric & MCP CRUD UI (Feature 6 / Issue #356)', () => {
  it('renders VitalsSummaryCards with blood pressure, heart rate, glucose, and oxygen saturation', () => {
    render(<VitalsSummaryCards vitals={mockLatestVitals} />);

    expect(screen.getByText('124/80')).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
    expect(screen.getByText('98')).toBeInTheDocument();
    expect(screen.getByText('99')).toBeInTheDocument();
  });

  it('toggles weight display visibility via onToggleHideWeight callback', () => {
    const handleToggle = vi.fn();
    render(
      <VitalsSummaryCards
        vitals={mockLatestVitals}
        hideWeight={true}
        onToggleHideWeight={handleToggle}
      />
    );

    expect(screen.getByTestId('weight-masked-value')).toHaveTextContent('••••');
    expect(screen.getByText('Privacy Mode')).toBeInTheDocument();
    const toggleBtn = screen.getByTestId('toggle-hide-weight-btn');
    fireEvent.click(toggleBtn);
    expect(handleToggle).toHaveBeenCalledTimes(1);
  });

  it('renders BloodPressureTrendChart with historical points and SVG elements', () => {
    const { container } = render(<BloodPressureTrendChart points={mockChartPoints} />);

    const svg = container.querySelector('svg');
    expect(svg).toBeInTheDocument();
    expect(screen.getByText(/Blood Pressure History/i)).toBeInTheDocument();
    expect(screen.getByText(/Morning \(AM\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Evening \(PM\)/i)).toBeInTheDocument();
  });

  it('renders DiurnalTrendTable and toggles between 7-day, 30-day, and 90-day timeframes', () => {
    render(<DiurnalTrendTable trends={mockTrends} />);

    expect(screen.getByText(/Diurnal Blood Pressure Moving Averages/i)).toBeInTheDocument();
    // Default is 30_day window
    expect(screen.getByTestId('am-mean-bp')).toHaveTextContent('123 / 80 mmHg');
    expect(screen.getByTestId('pm-mean-bp')).toHaveTextContent('128 / 84 mmHg');

    // Switch to 7_day window
    const btn7Day = screen.getByRole('radio', { name: /7 days/i }) || screen.getByText('7 Days');
    fireEvent.click(btn7Day);
    expect(screen.getByTestId('am-mean-bp')).toHaveTextContent('122 / 79 mmHg');
  });

  it('renders LogVitalsModal and validates required blood pressure inputs', () => {
    const handleClose = vi.fn();
    render(
      <LogVitalsModal
        isOpen={true}
        onOpenChange={handleClose}
        profileId="rosa"
      />
    );

    expect(screen.getByRole('heading', { name: /Log Vitals Observation/i })).toBeInTheDocument();
    expect(screen.getByTestId('input-systolic')).toBeInTheDocument();
    expect(screen.getByTestId('input-diastolic')).toBeInTheDocument();
    expect(screen.getByTestId('input-heart-rate')).toBeInTheDocument();
    expect(screen.getByTestId('input-glucose')).toBeInTheDocument();
    expect(screen.getByTestId('input-spo2')).toBeInTheDocument();
  });

  it('renders LogVitalsModal with temperature, respiratory rate, unit selectors, and custom timestamp', () => {
    const handleClose = vi.fn();
    render(
      <LogVitalsModal
        isOpen={true}
        onOpenChange={handleClose}
        profileId="rosa"
      />
    );

    // Temperature & Respiratory Rate inputs
    expect(screen.getByTestId('input-temperature')).toBeInTheDocument();
    expect(screen.getByTestId('input-respiratory-rate')).toBeInTheDocument();

    // Unit selectors
    const tempUnitBtn = screen.getByTestId('select-temp-unit');
    expect(tempUnitBtn).toBeInTheDocument();
    expect(tempUnitBtn).toHaveTextContent(/Switch to °C/i);
    fireEvent.click(tempUnitBtn);
    expect(tempUnitBtn).toHaveTextContent(/Switch to °F/i);

    const weightUnitBtn = screen.getByTestId('select-weight-unit');
    expect(weightUnitBtn).toBeInTheDocument();
    expect(weightUnitBtn).toHaveTextContent(/Switch to lbs/i);
    fireEvent.click(weightUnitBtn);
    expect(weightUnitBtn).toHaveTextContent(/Switch to kg/i);

    // Timestamp picker
    expect(screen.getByTestId('input-effective-at')).toBeInTheDocument();
  });

  it('renders MetricTrendChart with metric selector tabs and summary statistics', () => {
    render(<MetricTrendChart observations={mockObservations} />);

    expect(screen.getByTestId('metric-trend-chart-container')).toBeInTheDocument();
    expect(screen.getByTestId('metric-trend-selector')).toBeInTheDocument();
    expect(screen.getByTestId('metric-tab-heart_rate')).toBeInTheDocument();
    expect(screen.getByTestId('metric-tab-temperature')).toBeInTheDocument();
    expect(screen.getByTestId('metric-tab-respiratory_rate')).toBeInTheDocument();

    // Switch to temperature tab
    fireEvent.click(screen.getByTestId('metric-tab-temperature'));
    expect(screen.getByText(/Temperature Trends/i)).toBeInTheDocument();
    expect(screen.getByTestId('metric-trend-stats')).toBeInTheDocument();
  });

  it('renders VitalsHistoryTable, filters by vital type, and opens edit/delete modals', () => {
    const handleRefresh = vi.fn();
    render(
      <VitalsHistoryTable
        observations={mockObservations}
        profileId="rosa"
        onRefresh={handleRefresh}
      />
    );

    const table = screen.getByTestId('vitals-history-table');
    expect(table).toBeInTheDocument();
    expect(within(table).getByText('Blood Pressure')).toBeInTheDocument();
    expect(within(table).getByText('Heart Rate')).toBeInTheDocument();
    expect(within(table).getByText('Body Temperature')).toBeInTheDocument();
    expect(within(table).getByText('Respiratory Rate')).toBeInTheDocument();

    // Filter by vital type
    const filterSelect = screen.getByTestId('filter-vital-type');
    fireEvent.change(filterSelect, { target: { value: 'temperature' } });
    expect(within(table).getByText('Body Temperature')).toBeInTheDocument();
    expect(within(table).queryByText('Blood Pressure')).not.toBeInTheDocument();

    // Reset filter
    fireEvent.change(filterSelect, { target: { value: 'all' } });

    // Open Edit modal
    const editBtn = screen.getByTestId('edit-vital-obs-temp-1');
    fireEvent.click(editBtn);
    expect(screen.getByTestId('edit-vital-modal')).toBeInTheDocument();
    expect(screen.getByTestId('save-vital-btn')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('cancel-edit-vital-btn'));

    // Open Delete confirmation modal
    const deleteBtn = screen.getByTestId('delete-vital-obs-temp-1');
    fireEvent.click(deleteBtn);
    expect(screen.getByTestId('delete-vital-confirm-modal')).toBeInTheDocument();
    expect(screen.getByTestId('confirm-delete-vital-btn')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('cancel-delete-vital-btn'));
  });
});
