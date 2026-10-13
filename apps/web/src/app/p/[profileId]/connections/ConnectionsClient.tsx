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

'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Plug, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ConnectionsHub } from '@/components/connections';
import {
  fetchConnectorCatalog,
  fetchProfileConnections,
  createProfileConnection,
  triggerConnectionSync,
  fetchConnectionSyncRuns,
  revokeProfileConnection,
  fetchProfileDataFlows,
} from '@/lib/connectionsClient';
import type {
  ConnectionItem,
  ConnectorManifestSummary,
  CreateConnectionPayload,
  DataFlowsInventory,
  SyncRunItem,
} from '@/types/connections';

export interface ConnectionsClientProps {
  profileId: string;
}

export function ConnectionsClient({ profileId }: ConnectionsClientProps) {
  const [connectors, setConnectors] = useState<ConnectorManifestSummary[]>([]);
  const [connections, setConnections] = useState<ConnectionItem[]>([]);
  const [syncRunsByConnection, setSyncRunsByConnection] = useState<
    Record<string, SyncRunItem[]>
  >({});
  const [dataFlows, setDataFlows] = useState<DataFlowsInventory | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setError(null);
    setIsLoading(true);
    try {
      const [catalogRes, connsRes, flowsRes] = await Promise.all([
        fetchConnectorCatalog(),
        fetchProfileConnections(profileId),
        fetchProfileDataFlows(profileId).catch(() => null),
      ]);
      setConnectors(catalogRes.connectors || []);
      setConnections(connsRes.connections || []);
      setDataFlows(flowsRes);
    } catch (err: any) {
      setError(err.message || 'Failed to load connections hub.');
    } finally {
      setIsLoading(false);
    }
  }, [profileId]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleCreateConnection = async (payload: CreateConnectionPayload) => {
    setError(null);
    setActionMessage(null);
    try {
      const res = await createProfileConnection(profileId, payload);
      setConnections((prev) => [res.connection, ...prev]);
      setActionMessage(
        `Consent recorded and connection "${res.connection.label}" initialized.`
      );
      const flowsRes = await fetchProfileDataFlows(profileId).catch(() => null);
      if (flowsRes) setDataFlows(flowsRes);
    } catch (err: any) {
      setError(err.message || 'Failed to create connection.');
    }
  };

  const handleSyncNow = async (connectionId: string) => {
    setError(null);
    setActionMessage(null);
    try {
      const res = await triggerConnectionSync(profileId, connectionId);
      setConnections((prev) =>
        prev.map((c) => (c.id === connectionId ? res.connection : c))
      );
      if (res.sync_run) {
        setSyncRunsByConnection((prev) => ({
          ...prev,
          [connectionId]: [res.sync_run, ...(prev[connectionId] || [])],
        }));
      }
      setActionMessage('Sync completed.');
    } catch (err: any) {
      setError(err.message || 'Failed to trigger sync.');
    }
  };

  const handleLoadSyncRuns = async (connectionId: string) => {
    try {
      const res = await fetchConnectionSyncRuns(profileId, connectionId);
      setSyncRunsByConnection((prev) => ({
        ...prev,
        [connectionId]: res.sync_runs || [],
      }));
    } catch (err: any) {
      setError(err.message || 'Failed to load sync telemetry.');
    }
  };

  const handleRevokeConnection = async (
    connectionId: string,
    deleteImportedData: boolean
  ) => {
    setError(null);
    setActionMessage(null);
    try {
      await revokeProfileConnection(
        profileId,
        connectionId,
        deleteImportedData
      );
      await loadAll();
      setActionMessage(
        deleteImportedData
          ? 'Connection revoked, Vault tokens purged, and imported records deleted.'
          : 'Connection revoked and Vault tokens purged.'
      );
    } catch (err: any) {
      setError(err.message || 'Failed to revoke connection.');
    }
  };

  return (
    <div
      data-testid="connections-client-page"
      className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-600 text-white flex items-center justify-center shadow-sm">
            <Plug className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--cf-fg)]">
              External Data Connections, Consent &amp; Data Flows
            </h1>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Granular OAuth2 + PKCE connectors, local AES-256-GCM Vault credentials, sync quarantine ledger, and outbound egress audit
            </p>
          </div>
        </div>

        <Button
          variant="secondary"
          size="sm"
          onClick={loadAll}
          leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
        >
          Refresh
        </Button>
      </div>

      {error && (
        <div
          data-testid="connections-client-error"
          className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-xs text-rose-700 dark:text-rose-300"
        >
          {error}
        </div>
      )}

      {actionMessage && (
        <div
          data-testid="connections-action-toast"
          className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/50 text-xs text-emerald-800 dark:text-emerald-200"
        >
          {actionMessage}
        </div>
      )}

      <ConnectionsHub
        connectors={connectors}
        connections={connections}
        syncRunsByConnection={syncRunsByConnection}
        dataFlows={dataFlows}
        isLoading={isLoading}
        onCreateConnection={handleCreateConnection}
        onSyncNow={handleSyncNow}
        onRevokeConnection={handleRevokeConnection}
        onLoadSyncRuns={handleLoadSyncRuns}
      />
    </div>
  );
}
