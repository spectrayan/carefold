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
