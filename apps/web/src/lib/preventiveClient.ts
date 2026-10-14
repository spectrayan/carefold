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
  PreventiveActionResponse,
  PreventiveActionType,
  PreventiveCategory,
  PreventiveItem,
  PreventiveListResponse,
  PreventiveStatus,
  ScheduleSource,
} from '@/types/preventive';

export async function fetchPreventiveItems(
  profileId: string,
  params?: {
    category?: PreventiveCategory;
    status?: PreventiveStatus;
    schedule_source?: ScheduleSource;
  }
): Promise<PreventiveListResponse> {
  const query = new URLSearchParams();
  if (params?.category) query.set('category', params.category);
  if (params?.status) query.set('status', params.status);
  if (params?.schedule_source) query.set('schedule_source', params.schedule_source);

  const qs = query.toString();
  const url = `/api/v1/profiles/${encodeURIComponent(profileId)}/preventive${qs ? `?${qs}` : ''}`;

  const res = await fetch(url, {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch preventive items (${res.status})`);
  }
  return res.json();
}

export async function updatePreventiveStatus(
  profileId: string,
  ruleId: string,
  payload: {
    status: PreventiveStatus;
    completed_at?: string | null;
    notes?: string | null;
  }
): Promise<PreventiveItem> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/preventive/${encodeURIComponent(ruleId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to update preventive status (${res.status})`);
  }
  return res.json();
}

export async function updateScheduleSource(
  profileId: string,
  scheduleSource: ScheduleSource
): Promise<{ profile_id: string; schedule_source: ScheduleSource }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/preventive/schedule-source`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ schedule_source: scheduleSource }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to update schedule source (${res.status})`);
  }
  return res.json();
}

export async function triggerPreventiveAction(
  profileId: string,
  ruleId: string,
  actionType: PreventiveActionType,
  options?: {
    note_id?: string;
    due_at?: string;
    notes?: string;
  }
): Promise<PreventiveActionResponse> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/preventive/${encodeURIComponent(ruleId)}/actions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        action_type: actionType,
        ...options,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to trigger preventive action (${res.status})`);
  }
  return res.json();
}
