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
