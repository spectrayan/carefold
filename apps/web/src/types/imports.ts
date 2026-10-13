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
