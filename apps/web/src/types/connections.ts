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

export type ConnectionState =
  | 'pending_auth'
  | 'active'
  | 'degraded'
  | 'needs_reauth'
  | 'revoked'
  | 'deleted';

export type SyncRunStatus = 'running' | 'succeeded' | 'partial' | 'failed';

export type ConnectorTrustLevel =
  | 'trusted_device'
  | 'untrusted_external'
  | string;

export interface ConnectorManifestSummary {
  id: string;
  name: string;
  version: string;
  description: string;
  categories: string[];
  allowed_hosts: string[];
  scopes: string[];
  auth_type: string;
  pkce: boolean;
  client_source: string;
  trust_level: ConnectorTrustLevel;
}

export interface SyncRunItem {
  id: string;
  connection_id: string;
  connector_id: string;
  stream: string;
  status: SyncRunStatus | string;
  records_fetched: number;
  records_upserted: number;
  records_quarantined: number;
  error_code?: string | null;
  error_message?: string | null;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
}

export interface ConnectionItem {
  id: string;
  profile_id: string;
  connector_id: string;
  label: string;
  status: ConnectionState;
  status_message?: string | null;
  consecutive_failures: number;
  consented_version: string;
  last_sync_at?: string | null;
  created_at: string;
  latest_sync_run?: SyncRunItem | null;
}

export interface ConsentGrantItem {
  id: string;
  profile_id: string;
  connection_id: string;
  connector_id: string;
  categories: string[];
  scopes: string[];
  allowed_hosts: string[];
  purpose: string;
  terms_version: string;
  connector_version: string;
  status: 'active' | 'revoked' | string;
  granted_at: string;
  revoked_at?: string | null;
}

export interface DataFlowModelProvider {
  provider: string;
  host: string;
  is_local: boolean;
  connector_context_policy?: string;
}

export interface DataFlowSearchProvider {
  provider: string;
  allowed_hosts: string[];
  phi_sanitiser_enabled: boolean;
  status?: string;
}

export interface DataFlowConnectionEntry {
  connection_id: string;
  connector_id: string;
  connector_name?: string;
  label?: string;
  status: ConnectionState | string;
  allowed_hosts: string[];
  categories: string[];
  scopes?: string[];
  terms_version: string;
  connector_version?: string;
  trust_level?: string;
  last_sync_at?: string | null;
}

export interface DataFlowsInventory {
  profile_id: string;
  model_provider: DataFlowModelProvider;
  search_provider: DataFlowSearchProvider;
  connections: DataFlowConnectionEntry[];
}

export interface CreateConnectionPayload {
  connector_id: string;
  label?: string;
  categories: string[];
  scopes?: string[];
  purpose?: string;
  terms_version?: string;
  client_id?: string;
  client_secret?: string;
  redirect_uri?: string;
}

export interface CreateConnectionResponse {
  connection: ConnectionItem;
  consent_grant?: ConsentGrantItem;
  authorization_url?: string | null;
  state?: string | null;
}

export interface CompleteOAuthCallbackPayload {
  code: string;
  state: string;
  code_verifier?: string;
}
