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

export type ScheduleSource = 'aap_2026' | 'cdc';

export type PreventiveStatus = 'due' | 'completed' | 'not_applicable' | 'declined';

export type PreventiveCategory = 'screening' | 'immunisation' | 'well_visit';

export type PreventiveActionType = 'add_to_visit_prep' | 'set_reminder';

export interface PreventiveItem {
  rule_id: string;
  title: string;
  category: PreventiveCategory;
  status: PreventiveStatus;
  schedule_variant?: ScheduleSource | string | null;
  clinical_summary: string;
  source: string;
  citation_url: string;
  reviewed_by: string;
  reviewed_at: string;
  completed_at?: string | null;
  notes?: string | null;
  min_age_months?: number | null;
  max_age_months?: number | null;
  sex_filter?: string | null;
}

export interface PreventiveListResponse {
  profile_id: string;
  schedule_source: ScheduleSource;
  items: PreventiveItem[];
  counts?: {
    due: number;
    completed: number;
    not_applicable: number;
    declined: number;
  };
}

export interface PreventiveActionResponse {
  status: string;
  rule_id: string;
  action_type: PreventiveActionType;
  target_id?: string | null;
  message?: string;
}
