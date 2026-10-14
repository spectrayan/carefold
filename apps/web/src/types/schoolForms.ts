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

export type SchoolFormType =
  | 'physical'
  | 'immunization'
  | 'medication_authorization'
  | 'sports_clearance'
  | 'general';

export interface SchoolFormPrefillDraft {
  student_name: string;
  date_of_birth?: string | null;
  immunisations: Array<{
    name: string;
    date?: string | null;
    status: string;
    source?: string | null;
  }>;
  allergies: Array<{
    substance: string;
    reaction?: string | null;
    severity?: string | null;
  }>;
  active_medications: Array<{
    name: string;
    dosage?: string | null;
    frequency?: string | null;
  }>;
  latest_vitals: {
    height?: string | null;
    weight?: string | null;
    blood_pressure?: string | null;
    recorded_at?: string | null;
  };
  disclaimer: string;
  compiled_at: string;
}

export interface SchoolFormItem {
  id: string;
  profile_id: string;
  title: string;
  institution_name: string;
  form_type: SchoolFormType;
  issued_date?: string | null;
  expires_at?: string | null;
  days_until_expiry?: number | null;
  renewal_reminder_id?: string | null;
  guardian_only: boolean;
  under_13_safeguard?: boolean;
  prefill_draft: SchoolFormPrefillDraft;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}
