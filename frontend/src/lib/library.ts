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
} from '../types/api';

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
export async function fetchAttachments(profileId?: string): Promise<AttachmentItem[]> {
  const url = profileId && profileId !== 'me'
    ? `/api/v1/attachments?profile_id=${encodeURIComponent(profileId)}`
    : '/api/v1/attachments';
  const res = await fetch(url, {
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
export async function fetchNotes(profileId?: string): Promise<WorkspaceNoteSummary[]> {
  const url = profileId && profileId !== 'me'
    ? `/api/v1/notes?profile_id=${encodeURIComponent(profileId)}`
    : '/api/v1/notes';
  const res = await fetch(url, {
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
export async function fetchNoteDetail(slug: string, profileId?: string): Promise<WorkspaceNoteDetail> {
  const url = profileId && profileId !== 'me'
    ? `/api/v1/profiles/${encodeURIComponent(profileId)}/notes/${encodeURIComponent(slug)}`
    : `/api/v1/notes/${encodeURIComponent(slug)}`;
  const res = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store'
  });
  if (!res.ok) {
    if (profileId && profileId !== 'me') {
      const fallbackRes = await fetch(`/api/v1/notes/${encodeURIComponent(slug)}`, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        cache: 'no-store'
      });
      if (fallbackRes.ok) {
        return fallbackRes.json();
      }
    }
    throw new Error(`Failed to fetch note "${slug}" (HTTP ${res.status})`);
  }
  return res.json();
}

/**
 * Client-side uploader for attachments.
 */
export async function uploadAttachment(file: File, profileId?: string): Promise<AttachmentUploadResponse> {
  const formData = new FormData();
  formData.append('file', file, file.name);

  const url = profileId && profileId !== 'me'
    ? `/api/v1/attachments?profile_id=${encodeURIComponent(profileId)}`
    : '/api/v1/attachments';

  const res = await fetch(url, {
    method: 'POST',
    body: formData
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Upload failed with HTTP ${res.status}`);
  }

  return res.json();
}

export interface CreateNoteRequest {
  title: string;
  content: string;
  type?: string;
  tags?: string[];
  linked_appointment_id?: string;
}

export interface UpdateNoteRequest {
  title?: string;
  content?: string;
  type?: string;
  tags?: string[];
  linked_appointment_id?: string;
}

/**
 * Client-side creator for notes.
 */
export async function createNote(profileId: string, data: CreateNoteRequest): Promise<any> {
  const url = profileId && profileId !== 'me'
    ? `/api/v1/profiles/${encodeURIComponent(profileId)}/notes`
    : '/api/v1/notes';
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || err.message || `Failed to create note (HTTP ${res.status})`);
  }
  return res.json();
}

/**
 * Client-side updater for notes.
 */
export async function updateNote(profileId: string, noteId: string, data: UpdateNoteRequest): Promise<any> {
  const url = profileId && profileId !== 'me'
    ? `/api/v1/profiles/${encodeURIComponent(profileId)}/notes/${encodeURIComponent(noteId)}`
    : `/api/v1/notes/${encodeURIComponent(noteId)}`;
  const res = await fetch(url, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    if (!profileId || profileId === 'me') {
      const putRes = await fetch(url, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify(data),
      });
      if (putRes.ok) return putRes.json();
    }
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || err.message || `Failed to update note (HTTP ${res.status})`);
  }
  return res.json();
}

/**
 * Client-side deleter for notes.
 */
export async function deleteNote(profileId: string, noteId: string): Promise<void> {
  const url = profileId && profileId !== 'me'
    ? `/api/v1/profiles/${encodeURIComponent(profileId)}/notes/${encodeURIComponent(noteId)}`
    : `/api/v1/notes/${encodeURIComponent(noteId)}`;
  const res = await fetch(url, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || err.message || `Failed to delete note (HTTP ${res.status})`);
  }
}

/**
 * Client-side deleter for attachments.
 */
export async function deleteAttachment(attachmentId: string): Promise<void> {
  const res = await fetch(`/api/v1/attachments/${encodeURIComponent(attachmentId)}`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || err.message || `Failed to delete attachment (HTTP ${res.status})`);
  }
}
