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
  AttachmentItem,
  AttachmentUploadResponse,
  WorkspaceNoteDetail,
  WorkspaceNoteSummary
} from '@/types/api';

/**
 * Formats byte size into human-readable string (e.g. "14.2 KB", "2.1 MB").
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Formats an ISO-8601 timestamp string into localized date and time.
 */
export function formatDate(isoString: string): string {
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    }).format(date);
  } catch {
    return isoString;
  }
}

/**
 * Returns formatted file type badge from filename extension.
 */
export function getFileFormat(filename: string): 'PDF' | 'MD' | 'JSON' | 'CSV' | 'TXT' | 'FILE' {
  const ext = filename.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'pdf':
      return 'PDF';
    case 'md':
      return 'MD';
    case 'json':
      return 'JSON';
    case 'csv':
    case 'tsv':
      return 'CSV';
    case 'txt':
      return 'TXT';
    default:
      return 'FILE';
  }
}

/**
 * Client-side fetcher for workspace attachments.
 */
export async function fetchAttachments(): Promise<AttachmentItem[]> {
  const res = await fetch('/api/v1/attachments', {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store'
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch attachments (HTTP ${res.status})`);
  }
  return res.json();
}

/**
 * Client-side fetcher for workspace notes.
 */
export async function fetchNotes(): Promise<WorkspaceNoteSummary[]> {
  const res = await fetch('/api/v1/notes', {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store'
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch workspace notes (HTTP ${res.status})`);
  }
  return res.json();
}

/**
 * Client-side fetcher for a single workspace note detail.
 */
export async function fetchNoteDetail(slug: string): Promise<WorkspaceNoteDetail> {
  const res = await fetch(`/api/v1/notes/${encodeURIComponent(slug)}`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store'
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch note "${slug}" (HTTP ${res.status})`);
  }
  return res.json();
}

/**
 * Client-side uploader for attachments.
 */
export async function uploadAttachment(file: File): Promise<AttachmentUploadResponse> {
  const formData = new FormData();
  formData.append('file', file, file.name);

  const res = await fetch('/api/v1/attachments', {
    method: 'POST',
    body: formData
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Upload failed with HTTP ${res.status}`);
  }

  return res.json();
}
