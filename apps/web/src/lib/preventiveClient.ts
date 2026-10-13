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
