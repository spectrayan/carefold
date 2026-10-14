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

export type ImportFormat = 'fhir_r4' | 'ccda' | 'apple_health';

export type ImportBatchStatus = 'staged' | 'committed' | 'discarded';

export interface StagedRecordPreview {
  index: number;
  resource_type: string;
  category:
    | 'conditions'
    | 'medications'
    | 'allergies'
    | 'immunizations'
    | 'vitals'
    | 'apple_health_summaries'
    | string;
  display_title: string;
  effective_date?: string | null;
  source_name: string;
  source_id?: string | null;
  details?: Record<string, any>;
  selected?: boolean;
}

export interface ImportBatchSummary {
  conditions: number;
  medications: number;
  allergies: number;
  immunizations: number;
  vitals: number;
  apple_health_summaries: number;
  total: number;
}

export interface ImportBatchResponse {
  batch_id: string;
  profile_id: string;
  format: ImportFormat;
  source_name: string;
  status: ImportBatchStatus;
  summary: ImportBatchSummary;
  records: StagedRecordPreview[];
  created_at: string;
  committed_at?: string | null;
  warnings?: string[];
}
