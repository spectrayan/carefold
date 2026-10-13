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
  CompleteOAuthCallbackPayload,
  ConnectionItem,
  ConnectorManifestSummary,
  ConsentGrantItem,
  CreateConnectionPayload,
  CreateConnectionResponse,
  DataFlowsInventory,
  SyncRunItem,
} from '@/types/connections';

export async function fetchConnectorCatalog(): Promise<{
  connectors: ConnectorManifestSummary[];
}> {
  const res = await fetch('/api/v1/connectors', {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch connector catalog (${res.status})`
    );
  }
  return res.json();
}

export async function fetchProfileConnections(
  profileId: string
): Promise<{ connections: ConnectionItem[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/connections`,
    {
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch profile connections (${res.status})`
    );
  }
  return res.json();
}

export async function createProfileConnection(
  profileId: string,
  payload: CreateConnectionPayload
): Promise<CreateConnectionResponse> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/connections`,
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
      err.detail || `Failed to create profile connection (${res.status})`
    );
  }
  return res.json();
}

export async function completeOAuthCallback(
  profileId: string,
  connectionId: string,
  payload: CompleteOAuthCallbackPayload
): Promise<{ connection: ConnectionItem }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/connections/${encodeURIComponent(connectionId)}/oauth/callback`,
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
      err.detail || `Failed to complete OAuth callback (${res.status})`
    );
  }
  return res.json();
}

export async function triggerConnectionSync(
  profileId: string,
  connectionId: string
): Promise<{
  connection: ConnectionItem;
  sync_run: SyncRunItem;
}> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/connections/${encodeURIComponent(connectionId)}/sync`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to trigger connection sync (${res.status})`
    );
  }
  return res.json();
}

export async function fetchConnectionSyncRuns(
  profileId: string,
  connectionId: string
): Promise<{ sync_runs: SyncRunItem[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/connections/${encodeURIComponent(connectionId)}/sync-runs`,
    {
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch connection sync runs (${res.status})`
    );
  }
  return res.json();
}

export async function revokeProfileConnection(
  profileId: string,
  connectionId: string,
  deleteImportedData: boolean = false
): Promise<{
  connection_id: string;
  status: string;
  deleted_records_count?: number;
}> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/connections/${encodeURIComponent(connectionId)}/revoke`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ delete_imported_data: Boolean(deleteImportedData) }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to revoke profile connection (${res.status})`
    );
  }
  return res.json();
}

export async function fetchProfileConsents(
  profileId: string
): Promise<{ consents: ConsentGrantItem[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/consents`,
    {
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch profile consents (${res.status})`
    );
  }
  return res.json();
}

export async function fetchProfileDataFlows(
  profileId: string
): Promise<DataFlowsInventory> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/data-flows`,
    {
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch profile data flows (${res.status})`
    );
  }
  return res.json();
}
