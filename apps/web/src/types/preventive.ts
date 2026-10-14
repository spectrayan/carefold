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
