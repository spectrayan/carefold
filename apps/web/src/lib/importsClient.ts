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

import type {
  ImportBatchResponse,
  ImportBatchStatus,
  ImportFormat,
} from '@/types/imports';

export async function stageClinicalImport(
  profileId: string,
  payload: {
    format: ImportFormat;
    source_name: string;
    content: string;
  }
): Promise<ImportBatchResponse> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/imports/stage`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to stage clinical import (${res.status})`);
  }
  return res.json();
}

export async function listImportBatches(
  profileId: string
): Promise<{ batches: ImportBatchResponse[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/imports`,
    {
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to list import batches (${res.status})`);
  }
  return res.json();
}

export async function getImportBatch(
  profileId: string,
  batchId: string
): Promise<ImportBatchResponse> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/imports/${encodeURIComponent(batchId)}`,
    {
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to get import batch (${res.status})`);
  }
  return res.json();
}

export async function commitImportBatch(
  profileId: string,
  batchId: string,
  selectedIndices?: number[]
): Promise<ImportBatchResponse & { committed_count?: number }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/imports/${encodeURIComponent(batchId)}/commit`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(
        selectedIndices !== undefined ? { selected_indices: selectedIndices } : {}
      ),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to commit import batch (${res.status})`);
  }
  return res.json();
}

export async function discardImportBatch(
  profileId: string,
  batchId: string
): Promise<{ batch_id: string; status: ImportBatchStatus }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/imports/${encodeURIComponent(batchId)}/discard`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to discard import batch (${res.status})`);
  }
  return res.json();
}
