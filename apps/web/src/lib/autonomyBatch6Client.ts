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
  CompanionDeviceItem,
  CompanionPairingQrPayload,
  CreateEmailDraftPayload,
  CreateSchoolIcsFeedPayload,
  CreateStandingRoutinePayload,
  EmailDraftItem,
  GmailStagedCandidate,
  McpToolPinItem,
  SchoolIcsFeedItem,
  StandingRoutineItem,
  TeenHandoverPayload,
  TeenHandoverResponse,
  ViewerSectionKey,
  ViewerSectionPermissions,
} from '@/types/autonomyBatch6';

export async function fetchMcpToolPins(
  profileId: string
): Promise<{ pins: McpToolPinItem[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/mcp-pins`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch MCP tool pins (${res.status})`
    );
  }
  return res.json();
}

export async function reapproveMcpToolPin(
  profileId: string,
  pinId: string,
  schemaHash: string
): Promise<{ pin: McpToolPinItem }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/mcp-pins/${encodeURIComponent(pinId)}/reapprove`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ schema_hash: schemaHash }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to re-approve MCP tool pin (${res.status})`
    );
  }
  return res.json();
}

export async function fetchStandingRoutines(
  profileId: string
): Promise<{ routines: StandingRoutineItem[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/routines`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch standing routines (${res.status})`
    );
  }
  return res.json();
}

export async function createStandingRoutine(
  profileId: string,
  payload: CreateStandingRoutinePayload
): Promise<{ routine: StandingRoutineItem }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/routines`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to create standing routine (${res.status})`
    );
  }
  return res.json();
}

export async function pauseStandingRoutine(
  profileId: string,
  routineId: string
): Promise<{ routine: StandingRoutineItem }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/routines/${encodeURIComponent(routineId)}/pause`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to pause standing routine (${res.status})`
    );
  }
  return res.json();
}

export async function revokeStandingRoutine(
  profileId: string,
  routineId: string
): Promise<{ routine: StandingRoutineItem }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/routines/${encodeURIComponent(routineId)}/revoke`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to revoke standing routine (${res.status})`
    );
  }
  return res.json();
}

export async function fetchGmailStagedCandidates(
  profileId: string,
  connectionId: string
): Promise<{ candidates: GmailStagedCandidate[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/connections/${encodeURIComponent(connectionId)}/gmail-staged`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch Gmail staged candidates (${res.status})`
    );
  }
  return res.json();
}

export async function confirmGmailStagedCandidate(
  profileId: string,
  connectionId: string,
  candidateIndex: number
): Promise<{ confirmed: boolean; record_id: string }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/connections/${encodeURIComponent(connectionId)}/gmail-confirm`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ candidate_index: candidateIndex }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to confirm Gmail staged candidate (${res.status})`
    );
  }
  return res.json();
}

export async function fetchEmailDrafts(
  profileId: string
): Promise<{ drafts: EmailDraftItem[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/email-drafts`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch email drafts (${res.status})`
    );
  }
  return res.json();
}

export async function createEmailDraft(
  profileId: string,
  payload: CreateEmailDraftPayload
): Promise<{ draft: EmailDraftItem }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/email-drafts`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to create email draft (${res.status})`
    );
  }
  return res.json();
}

export async function downloadEmailDraftEml(
  profileId: string,
  draftId: string
): Promise<{ eml_content: string }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/email-drafts/${encodeURIComponent(draftId)}/eml`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to download email draft .eml (${res.status})`
    );
  }
  return res.json();
}

export async function fetchSchoolIcsFeeds(
  profileId: string
): Promise<{ feeds: SchoolIcsFeedItem[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/school-feeds`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch school ICS feeds (${res.status})`
    );
  }
  return res.json();
}

export async function createSchoolIcsFeed(
  profileId: string,
  payload: CreateSchoolIcsFeedPayload
): Promise<{ feed: SchoolIcsFeedItem }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/school-feeds`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to subscribe to school ICS feed (${res.status})`
    );
  }
  return res.json();
}

export async function syncSchoolIcsFeed(
  profileId: string,
  feedId: string
): Promise<{ feed: SchoolIcsFeedItem; events_synced: number }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/school-feeds/${encodeURIComponent(feedId)}/sync`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to sync school ICS feed (${res.status})`
    );
  }
  return res.json();
}

export async function fetchCompanionDevices(
  profileId: string
): Promise<{ devices: CompanionDeviceItem[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/companion/devices`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch companion devices (${res.status})`
    );
  }
  return res.json();
}

export async function generateCompanionPairingQr(
  profileId: string,
  deviceName: string,
  allowedCategories: string[]
): Promise<CompanionPairingQrPayload> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/companion/pair`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        device_name: deviceName,
        allowed_categories: allowedCategories,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to generate companion pairing QR (${res.status})`
    );
  }
  return res.json();
}

export async function revokeCompanionDevice(
  profileId: string,
  deviceId: string
): Promise<{ device_id: string; status: string }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/companion/devices/${encodeURIComponent(deviceId)}/revoke`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to revoke companion device (${res.status})`
    );
  }
  return res.json();
}

export async function fetchViewerSectionPermissions(
  profileId: string,
  viewerUserId: string
): Promise<ViewerSectionPermissions> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/viewers/${encodeURIComponent(viewerUserId)}/sections`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch viewer section permissions (${res.status})`
    );
  }
  return res.json();
}

export async function updateViewerSectionPermissions(
  profileId: string,
  viewerUserId: string,
  allowedSections: ViewerSectionKey[]
): Promise<ViewerSectionPermissions> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/viewers/${encodeURIComponent(viewerUserId)}/sections`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ allowed_sections: allowedSections }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail ||
        `Failed to update viewer section permissions (${res.status})`
    );
  }
  return res.json();
}

export async function executeTeenHandover(
  profileId: string,
  payload: TeenHandoverPayload
): Promise<TeenHandoverResponse> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/handover/teen`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to execute teen handover (${res.status})`
    );
  }
  return res.json();
}
