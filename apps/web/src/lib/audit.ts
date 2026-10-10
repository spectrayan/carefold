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

import { AuditEvent, AuditListResponse, AuditFilterParams } from '@/types/api';

export class AuditApiError extends Error {
  status: number;
  detail?: string;

  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.name = 'AuditApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Fetches recent audit events from the Next.js /api/audit proxy route.
 */
export async function fetchAuditEvents(
  params: AuditFilterParams = {}
): Promise<AuditListResponse> {
  const searchParams = new URLSearchParams();

  if (params.limit !== undefined && params.limit !== null) {
    searchParams.set('limit', String(params.limit));
  }
  if (params.agent_id && params.agent_id.trim()) {
    searchParams.set('agent_id', params.agent_id.trim());
  }
  if (params.event && params.event.trim()) {
    searchParams.set('event', params.event.trim());
  }

  const queryString = searchParams.toString();
  const url = queryString ? `/api/v1/audit?${queryString}` : '/api/v1/audit';

  const res = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store'
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    const message =
      errorData?.detail || errorData?.error || `Failed to fetch audit events (HTTP ${res.status})`;
    const err = new AuditApiError(message, res.status, errorData?.detail);
    throw err;
  }

  const data: AuditListResponse = await res.json();
  return {
    total: typeof data.total === 'number' ? data.total : 0,
    limit: typeof data.limit === 'number' ? data.limit : 50,
    events: Array.isArray(data.events) ? data.events : []
  };
}

/**
 * Copies sanitized audit events to the user's clipboard formatted as JSON.
 */
export async function copyAuditEventsToClipboard(
  events: AuditEvent[]
): Promise<boolean> {
  try {
    const sanitized = events.map((ev) => {
      // Ensure zero prompt/completion bodies in exported output
      const { prompt, completion, ...rest } = ev as any;
      return rest;
    });

    const json = JSON.stringify(sanitized, null, 2);
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      await navigator.clipboard.writeText(json);
      return true;
    }
    return false;
  } catch (err) {
    console.error('Failed to copy audit events to clipboard:', err);
    return false;
  }
}

/**
 * Triggers a client-side JSON file download containing the given audit events.
 */
export function exportAuditEventsAsJson(
  events: AuditEvent[],
  filenamePrefix: string = 'carefold-activity-log'
): void {
  if (typeof window === 'undefined') return;

  const sanitized = events.map((ev) => {
    const { prompt, completion, ...rest } = ev as any;
    return rest;
  });

  const json = JSON.stringify(sanitized, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const now = new Date().toISOString().replace(/[:.]/g, '-');
  const filename = `${filenamePrefix}-${now}.json`;

  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Formats an ISO-8601 UTC timestamp into localized readable date & time.
 */
export function formatAuditTimestamp(isoDate: string): string {
  try {
    const date = new Date(isoDate);
    if (isNaN(date.getTime())) return isoDate;

    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    }).format(date);
  } catch {
    return isoDate;
  }
}

/**
 * Formats duration in milliseconds into a concise badge string.
 */
export function formatAuditDuration(ms?: number | null): string {
  if (ms === undefined || ms === null) return '';
  if (ms < 1) return '< 1 ms';
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}
