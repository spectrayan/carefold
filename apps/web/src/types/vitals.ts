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

export interface VitalMeasurements {
  systolic?: number | null;
  diastolic?: number | null;
  heart_rate?: number | null;
  blood_glucose?: number | null;
  unit?: string; // "mg/dL", "mmol/L", "kg", "lbs", "cm", "in"
  spo2?: number | null;
  oxygen_saturation?: number | null;
  weight?: number | null;
  height?: number | null;
}

export interface EmergencyRedFlag {
  triggered: boolean;
  category?: string | null;
  severity: 'emergency' | 'urgent' | 'normal';
  directive?: string | null;
  prompt_recheck: boolean;
  details: Record<string, any>;
}

export interface BmiCalculation {
  bmi?: number | null;
  classification?: string | null;
  percentile?: number | null;
  z_score?: number | null;
  suppressed: boolean;
  weight_hidden: boolean;
  reason?: string | null;
}

export interface VitalsObservationItem {
  id: string;
  profile_id: string;
  resource_type: string;
  source_type: 'manual' | 'device' | 'note_extracted' | string;
  source_ref?: string | null;
  source_id?: string | null;
  status: string;
  data: Record<string, any>; // FHIR R4 JSON representation
  effective_at: string; // ISO UTC
  recorded_at: string; // ISO UTC
}

export interface TrendWindowMetrics {
  count: number;
  systolic?: number | null;
  diastolic?: number | null;
  pulse?: number | null;
  classification: string;
}

export interface DiurnalTrendWindow {
  am: TrendWindowMetrics;
  pm: TrendWindowMetrics;
}

export interface VitalsTrendsResponse {
  profile_id: string;
  metric: string;
  timezone: string;
  computed_at: string;
  trends: {
    '7_day': DiurnalTrendWindow;
    '30_day': DiurnalTrendWindow;
    '90_day': DiurnalTrendWindow;
  };
  latest_reading?: {
    id: string;
    effective_at: string;
    data: Record<string, any>;
  } | null;
}

export interface LatestVitalsState {
  bloodPressure?: {
    systolic: number;
    diastolic: number;
    effectiveAt: string;
    stage: string;
    isAM: boolean;
    deltaSys?: number;
    deltaDia?: number;
  };
  heartRate?: {
    value: number;
    effectiveAt: string;
    classification?: string;
    delta?: number;
  };
  bloodGlucose?: {
    value: number;
    unit: string;
    effectiveAt: string;
    classification?: string;
    delta?: number;
  };
  spo2?: {
    value: number;
    effectiveAt: string;
    classification?: string;
    delta?: number;
  };
  weight?: {
    valueKg?: number;
    valueLbs?: number;
    bmi?: number;
    classification?: string;
    percentile?: number;
    effectiveAt: string;
    weightHidden: boolean;
    delta?: number;
  };
}

export interface ClientSafetyEvaluation {
  triggered: boolean;
  category:
    | 'bp_crisis_symptomatic'
    | 'bp_crisis_asymptomatic'
    | 'severe_hypoxemia'
    | 'severe_hypoglycemia'
    | 'symptomatic_hypotension'
    | null;
  severity: 'emergency' | 'urgent' | 'normal';
  title: string;
  directive: string;
  call911: boolean;
  promptRecheck: boolean;
}
