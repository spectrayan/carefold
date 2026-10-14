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
  ActivityTimelineResponse,
  ActivityUndoResponse,
} from '@/types/activity';

export interface ActivityQueryParams {
  limit?: number;
  offset?: number;
  undoable_only?: boolean;
  event?: string;
  tool?: string;
}

export async function fetchProfileActivity(
  profileId: string,
  params: ActivityQueryParams = {}
): Promise<ActivityTimelineResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  if (params.undoable_only) query.set('undoable_only', 'true');
  if (params.event) query.set('event', params.event);
  if (params.tool) query.set('tool', params.tool);

  const qs = query.toString();
  const url = `/api/profiles/${encodeURIComponent(profileId)}/activity${qs ? `?${qs}` : ''}`;
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
    credentials: 'include',
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Failed to fetch activity timeline (HTTP ${res.status})`);
  }
  return res.json();
}

export async function undoActivityEvent(
  profileId: string,
  eventId: string
): Promise<ActivityUndoResponse> {
  const url = `/api/profiles/${encodeURIComponent(profileId)}/activity/${encodeURIComponent(eventId)}/undo`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    credentials: 'include',
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Failed to undo action (HTTP ${res.status})`);
  }
  return res.json();
}

export function formatRelativeTime(isoString: string): string {
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (diffSec < 60) return 'Just now';
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;

    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return isoString;
  }
}
