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

import React, { useState } from 'react';
import {
  Plug,
  RefreshCw,
  AlertTriangle,
  KeyRound,
  Activity,
  Trash2,
  ShieldCheck,
  Network,
  Globe,
  CheckCircle2,
  Cpu,
  Mail,
  Smartphone,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import { ConnectorConsentModal } from './ConnectorConsentModal';
import { SyncHealthTable } from './SyncHealthTable';
import { DataFlowsPanel } from './DataFlowsPanel';
import { McpPinsAndRoutinesPanel } from './McpPinsAndRoutinesPanel';
import { EmailDraftsAndSchoolFeedsPanel } from './EmailDraftsAndSchoolFeedsPanel';
import { CompanionAndHandoverPanel } from './CompanionAndHandoverPanel';
import { CoordinatedV2Panel } from './CoordinatedV2Panel';
import type {
  ConnectionItem,
  ConnectorManifestSummary,
  CreateConnectionPayload,
  DataFlowsInventory,
  SyncRunItem,
} from '@/types/connections';
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
} from '@/types/autonomyBatch6';
import type {
  AuditChainVerificationResponse,
  OsServiceDescriptorItem,
  SmartHealthCardVerificationResult,
  SmartSchedulingSlotItem,
  V2ConnectorSummary,
  ZocdocBookingPreview,
} from '@/types/autonomyBatch7';
import type {
  DiscoverSmartSchedulingSlotsPayload,
  PreviewZocdocBookingPayload,
  VerifySmartHealthCardPayload,
} from '@/lib/autonomyBatch7Client';

export type ConnectionsHubTab =
  | 'connections'
  | 'data_flows'
  | 'mcp_routines'
  | 'email_school'
  | 'companion_handover'
  | 'coordinated_v2';

export interface ConnectionsHubProps {
  connectors: ConnectorManifestSummary[];
  connections: ConnectionItem[];
  syncRunsByConnection?: Record<string, SyncRunItem[]>;
  dataFlows?: DataFlowsInventory | null;
  mcpPins?: McpToolPinItem[];
  routines?: StandingRoutineItem[];
  gmailCandidates?: GmailStagedCandidate[];
  emailDrafts?: EmailDraftItem[];
  schoolFeeds?: SchoolIcsFeedItem[];
  companionDevices?: CompanionDeviceItem[];
  pairingQr?: CompanionPairingQrPayload | null;
  handoverResult?: TeenHandoverResponse | null;
  shcResult?: SmartHealthCardVerificationResult | null;
  smartSlots?: SmartSchedulingSlotItem[];
  zocdocPreview?: ZocdocBookingPreview | null;
  v2Connectors?: V2ConnectorSummary[];
  auditVerification?: AuditChainVerificationResponse | null;
  serviceDescriptors?: OsServiceDescriptorItem[];
  isLoading?: boolean;
  onCreateConnection?: (payload: CreateConnectionPayload) => void | Promise<void>;
  onSyncNow?: (connectionId: string) => void | Promise<void>;
  onReauthenticate?: (connection: ConnectionItem) => void | Promise<void>;
  onRevokeConnection?: (
    connectionId: string,
    deleteImportedData: boolean
  ) => void | Promise<void>;
  onLoadSyncRuns?: (connectionId: string) => void | Promise<void>;
  onReapprovePin?: (pinId: string, schemaHash: string) => void | Promise<void>;
  onCreateRoutine?: (
    payload: CreateStandingRoutinePayload
  ) => void | Promise<void>;
  onPauseRoutine?: (routineId: string) => void | Promise<void>;
  onRevokeRoutine?: (routineId: string) => void | Promise<void>;
  onConfirmGmailCandidate?: (candidateIndex: number) => void | Promise<void>;
  onCreateEmailDraft?: (
    payload: CreateEmailDraftPayload
  ) => void | Promise<void>;
  onDownloadEmailEml?: (draftId: string) => void | Promise<void>;
  onCreateSchoolFeed?: (
    payload: CreateSchoolIcsFeedPayload
  ) => void | Promise<void>;
  onSyncSchoolFeed?: (feedId: string) => void | Promise<void>;
  onGeneratePairingQr?: (
    deviceName: string,
    allowedCategories: string[]
  ) => void | Promise<void>;
  onRevokeCompanionDevice?: (deviceId: string) => void | Promise<void>;
  onSaveViewerSections?: (
    viewerUserId: string,
    allowedSections: ViewerSectionKey[]
  ) => void | Promise<void>;
  onExecuteTeenHandover?: (
    payload: TeenHandoverPayload
  ) => void | Promise<void>;
  onVerifySmartHealthCard?: (
    payload: VerifySmartHealthCardPayload
  ) => void | Promise<void>;
  onDiscoverSmartSlots?: (
    payload: DiscoverSmartSchedulingSlotsPayload
  ) => void | Promise<void>;
  onRequestZocdocApproval?: (
    payload: PreviewZocdocBookingPayload
  ) => void | Promise<void>;
  onVerifyAuditChain?: () => void | Promise<void>;
  className?: string;
}

function getStatusBadgeClasses(status: string): string {
  switch (status) {
    case 'active':
      return 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60';
    case 'degraded':
      return 'bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800/60';
    case 'needs_reauth':
      return 'bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/60';
    case 'revoked':
    case 'deleted':
      return 'bg-slate-100 dark:bg-slate-900 text-slate-600 dark:text-slate-400 border-slate-300 dark:border-slate-700';
    default:
      return 'bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800/60';
  }
}

export function ConnectionsHub({
  connectors,
  connections,
  syncRunsByConnection = {},
  dataFlows = null,
  mcpPins = [],
  routines = [],
  gmailCandidates = [],
  emailDrafts = [],
  schoolFeeds = [],
  companionDevices = [],
  pairingQr = null,
  handoverResult = null,
  shcResult = null,
  smartSlots = [],
  zocdocPreview = null,
  v2Connectors = [],
  auditVerification = null,
  serviceDescriptors = [],
  isLoading = false,
  onCreateConnection,
  onSyncNow,
  onReauthenticate,
  onRevokeConnection,
  onLoadSyncRuns,
  onReapprovePin,
  onCreateRoutine,
  onPauseRoutine,
  onRevokeRoutine,
  onConfirmGmailCandidate,
  onCreateEmailDraft,
  onDownloadEmailEml,
  onCreateSchoolFeed,
  onSyncSchoolFeed,
  onGeneratePairingQr,
  onRevokeCompanionDevice,
  onSaveViewerSections,
  onExecuteTeenHandover,
  onVerifySmartHealthCard,
  onDiscoverSmartSlots,
  onRequestZocdocApproval,
  onVerifyAuditChain,
  className,
}: ConnectionsHubProps) {
  const [activeTab, setActiveTab] = useState<ConnectionsHubTab>('connections');
  const [selectedConnector, setSelectedConnector] =
    useState<ConnectorManifestSummary | null>(null);
  const [expandedSyncHealthIds, setExpandedSyncHealthIds] = useState<
    Record<string, boolean>
  >({});
  const [revokeTarget, setRevokeTarget] = useState<ConnectionItem | null>(null);
  const [deleteImportedData, setDeleteImportedData] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  const degradedOrReauthConnections = connections.filter(
    (c) => c.status === 'degraded' || c.status === 'needs_reauth'
  );

  const handleToggleSyncHealth = async (connId: string) => {
    const nextExpanded = !expandedSyncHealthIds[connId];
    setExpandedSyncHealthIds((prev) => ({
      ...prev,
      [connId]: nextExpanded,
    }));
    if (nextExpanded && onLoadSyncRuns) {
      await onLoadSyncRuns(connId);
    }
  };

  const handleConfirmConsent = async (payload: CreateConnectionPayload) => {
    setIsSubmitting(true);
    try {
      await onCreateConnection?.(payload);
      setSelectedConnector(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmRevoke = async () => {
    if (!revokeTarget) return;
    setIsSubmitting(true);
    try {
      await onRevokeConnection?.(revokeTarget.id, deleteImportedData);
      setRevokeTarget(null);
      setDeleteImportedData(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      data-testid="connections-hub"
      className={cn('space-y-6', className)}
    >
      {/* Top View Switcher */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--cf-border)] pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={activeTab === 'connections' ? 'primary' : 'ghost'}
            data-testid="hub-tab-connections"
            leftIcon={<Plug className="w-3.5 h-3.5" />}
            onClick={() => setActiveTab('connections')}
          >
            Connections &amp; Sync Hub
          </Button>
          <Button
            size="sm"
            variant={activeTab === 'mcp_routines' ? 'primary' : 'ghost'}
            data-testid="hub-tab-mcp-routines"
            leftIcon={<Cpu className="w-3.5 h-3.5" />}
            onClick={() => setActiveTab('mcp_routines')}
          >
            MCP Pins &amp; A2 Routines
          </Button>
          <Button
            size="sm"
            variant={activeTab === 'email_school' ? 'primary' : 'ghost'}
            data-testid="hub-tab-email-school"
            leftIcon={<Mail className="w-3.5 h-3.5" />}
            onClick={() => setActiveTab('email_school')}
          >
            Gmail, Drafts &amp; School Feeds
          </Button>
          <Button
            size="sm"
            variant={activeTab === 'companion_handover' ? 'primary' : 'ghost'}
            data-testid="hub-tab-companion-handover"
            leftIcon={<Smartphone className="w-3.5 h-3.5" />}
            onClick={() => setActiveTab('companion_handover')}
          >
            iOS Companion &amp; Teen Handover
          </Button>
          <Button
            size="sm"
            variant={activeTab === 'coordinated_v2' ? 'primary' : 'ghost'}
            data-testid="hub-tab-coordinated-v2"
            leftIcon={<ShieldCheck className="w-3.5 h-3.5" />}
            onClick={() => setActiveTab('coordinated_v2')}
          >
            Coordinated v2 (SHC, Scheduling &amp; Audit)
          </Button>
          <Button
            size="sm"
            variant={activeTab === 'data_flows' ? 'primary' : 'ghost'}
            data-testid="hub-tab-data-flows"
            leftIcon={<Network className="w-3.5 h-3.5" />}
            onClick={() => setActiveTab('data_flows')}
          >
            Settings › Data Flows
          </Button>
        </div>

        <span className="text-xs text-[var(--cf-fg-muted)]">
          Capped v1 Starter Connectors ({connectors.length})
        </span>
      </div>

      {activeTab === 'data_flows' ? (
        <DataFlowsPanel
          inventory={dataFlows}
          isLoading={isLoading}
          onQuickRevoke={(connectionId) => {
            const found = connections.find((c) => c.id === connectionId);
            if (found) {
              setRevokeTarget(found);
              setDeleteImportedData(false);
            } else {
              onRevokeConnection?.(connectionId, false);
            }
          }}
        />
      ) : activeTab === 'mcp_routines' ? (
        <McpPinsAndRoutinesPanel
          mcpPins={mcpPins}
          routines={routines}
          onReapprovePin={onReapprovePin}
          onCreateRoutine={onCreateRoutine}
          onPauseRoutine={onPauseRoutine}
          onRevokeRoutine={onRevokeRoutine}
        />
      ) : activeTab === 'email_school' ? (
        <EmailDraftsAndSchoolFeedsPanel
          gmailCandidates={gmailCandidates}
          emailDrafts={emailDrafts}
          schoolFeeds={schoolFeeds}
          onConfirmGmailCandidate={onConfirmGmailCandidate}
          onCreateEmailDraft={onCreateEmailDraft}
          onDownloadEmailEml={onDownloadEmailEml}
          onCreateSchoolFeed={onCreateSchoolFeed}
          onSyncSchoolFeed={onSyncSchoolFeed}
        />
      ) : activeTab === 'companion_handover' ? (
        <CompanionAndHandoverPanel
          companionDevices={companionDevices}
          pairingQr={pairingQr}
          connections={connections}
          handoverResult={handoverResult}
          onGeneratePairingQr={onGeneratePairingQr}
          onRevokeCompanionDevice={onRevokeCompanionDevice}
          onSaveViewerSections={onSaveViewerSections}
          onExecuteTeenHandover={onExecuteTeenHandover}
        />
      ) : activeTab === 'coordinated_v2' ? (
        <CoordinatedV2Panel
          shcResult={shcResult}
          smartSlots={smartSlots}
          zocdocPreview={zocdocPreview}
          v2Connectors={v2Connectors}
          auditVerification={auditVerification}
          serviceDescriptors={serviceDescriptors}
          onVerifySmartHealthCard={onVerifySmartHealthCard}
          onDiscoverSmartSlots={onDiscoverSmartSlots}
          onRequestZocdocApproval={onRequestZocdocApproval}
          onVerifyAuditChain={onVerifyAuditChain}
        />
      ) : (
        <div className="space-y-6">
          {/* Degradation & Re-auth Alert Banner (E8.6) */}
          {degradedOrReauthConnections.length > 0 && (
            <div
              data-testid="connections-degradation-banner"
              className="flex items-start gap-3 p-4 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/60 text-xs text-amber-900 dark:text-amber-200"
            >
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-bold">
                  Connection Sync Attention Required (
                  {degradedOrReauthConnections.length})
                </p>
                <p className="text-amber-800 dark:text-amber-300 leading-relaxed">
                  One or more external data connections experienced consecutive sync failures or token expiration. Review the status cards below to re-authenticate or trigger a manual sync.
                </p>
              </div>
            </div>
          )}

          {/* Starter Connectors Catalog (3 Capped v1 Connectors) */}
          <div className="space-y-3">
            <div>
              <h3 className="text-sm font-bold text-[var(--cf-fg)]">
                Available v1 Starter Connectors
              </h3>
              <p className="text-xs text-[var(--cf-fg-muted)]">
                Each connector operates in a dedicated outbound host sandbox with granular category consent and local AES-256-GCM Vault credential storage
              </p>
            </div>

            <div
              data-testid="starter-connectors-grid"
              className="grid grid-cols-1 md:grid-cols-3 gap-4"
            >
              {connectors.map((connector) => {
                const isTrustedDevice =
                  connector.trust_level === 'trusted_device';
                return (
                  <Card
                    key={connector.id}
                    data-testid={`starter-connector-card-${connector.id}`}
                    className="p-4 flex flex-col justify-between gap-4 border border-[var(--cf-border)] shadow-sm"
                  >
                    <div className="space-y-2.5">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h4 className="text-sm font-bold text-[var(--cf-fg)]">
                            {connector.name}
                          </h4>
                          <span className="text-[11px] font-mono text-[var(--cf-fg-muted)]">
                            {connector.id} • v{connector.version}
                          </span>
                        </div>
                        <span
                          className={cn(
                            'px-2 py-0.5 rounded text-[10px] font-semibold border',
                            isTrustedDevice
                              ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                              : 'bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800/60'
                          )}
                        >
                          {isTrustedDevice ? 'Trusted Device' : 'External FHIR'}
                        </span>
                      </div>

                      <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed">
                        {connector.description}
                      </p>

                      <div className="flex flex-wrap gap-1 pt-1">
                        {connector.categories.map((cat) => (
                          <span
                            key={cat}
                            className="px-2 py-0.5 rounded bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-[11px] font-medium text-[var(--cf-fg)]"
                          >
                            {cat}
                          </span>
                        ))}
                      </div>

                      <div className="flex flex-wrap gap-1">
                        {connector.allowed_hosts.map((host) => (
                          <span
                            key={host}
                            className="inline-flex items-center gap-1 text-[10px] font-mono text-[var(--cf-fg-muted)]"
                          >
                            <Globe className="w-2.5 h-2.5 text-emerald-600" />
                            {host}
                          </span>
                        ))}
                      </div>
                    </div>

                    <Button
                      variant="primary"
                      size="sm"
                      data-testid={`connect-starter-btn-${connector.id}`}
                      leftIcon={<ShieldCheck className="w-3.5 h-3.5" />}
                      onClick={() => setSelectedConnector(connector)}
                    >
                      Review Consent &amp; Connect
                    </Button>
                  </Card>
                );
              })}
            </div>
          </div>

          {/* Configured Profile Connections */}
          <div className="space-y-3">
            <div>
              <h3 className="text-sm font-bold text-[var(--cf-fg)]">
                Profile Connections &amp; Sync Status
              </h3>
              <p className="text-xs text-[var(--cf-fg-muted)]">
                Manage active connections, inspect sync quarantine telemetry, or execute a full revoke cascade
              </p>
            </div>

            {connections.length === 0 ? (
              <Card
                data-testid="connections-empty-state"
                className="p-6 text-center text-xs text-[var(--cf-fg-muted)] border border-[var(--cf-border)]"
              >
                No external connections configured yet. Select one of the starter connectors above to grant consent.
              </Card>
            ) : (
              <div
                data-testid="active-connections-list"
                className="space-y-3"
              >
                {connections.map((conn) => {
                  const isSyncExpanded = Boolean(
                    expandedSyncHealthIds[conn.id]
                  );
                  const runs =
                    syncRunsByConnection[conn.id] ||
                    (conn.latest_sync_run ? [conn.latest_sync_run] : []);

                  return (
                    <Card
                      key={conn.id}
                      data-testid={`connection-card-${conn.id}`}
                      className="p-4 space-y-3 border border-[var(--cf-border)] shadow-sm"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2.5">
                            <h4 className="text-sm font-bold text-[var(--cf-fg)]">
                              {conn.label}
                            </h4>
                            <span
                              data-testid={`connection-status-badge-${conn.id}`}
                              className={cn(
                                'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border',
                                getStatusBadgeClasses(conn.status)
                              )}
                            >
                              {conn.status === 'active' && (
                                <CheckCircle2 className="w-3 h-3 shrink-0" />
                              )}
                              {(conn.status === 'degraded' ||
                                conn.status === 'needs_reauth') && (
                                <AlertTriangle className="w-3 h-3 shrink-0" />
                              )}
                              <span>{conn.status}</span>
                            </span>
                          </div>

                          <div className="flex flex-wrap items-center gap-3 text-[11px] text-[var(--cf-fg-muted)]">
                            <span className="font-mono">
                              Connector: {conn.connector_id} (v
                              {conn.consented_version})
                            </span>
                            {conn.last_sync_at && (
                              <span>Last synced: {conn.last_sync_at}</span>
                            )}
                            {conn.consecutive_failures > 0 && (
                              <span
                                data-testid={`connection-failures-${conn.id}`}
                                className="text-amber-700 dark:text-amber-400 font-semibold"
                              >
                                Consecutive failures: {conn.consecutive_failures}
                              </span>
                            )}
                          </div>

                          {conn.status_message && (
                            <p
                              data-testid={`connection-status-msg-${conn.id}`}
                              className="text-xs text-[var(--cf-fg-muted)]"
                            >
                              {conn.status_message}
                            </p>
                          )}
                        </div>

                        {/* Connection Action Buttons */}
                        <div className="flex flex-wrap items-center gap-2">
                          {conn.status === 'needs_reauth' && (
                            <Button
                              variant="primary"
                              size="sm"
                              data-testid={`reauth-btn-${conn.id}`}
                              leftIcon={<KeyRound className="w-3.5 h-3.5" />}
                              onClick={() => {
                                if (onReauthenticate) {
                                  onReauthenticate(conn);
                                } else {
                                  const matched = connectors.find(
                                    (c) => c.id === conn.connector_id
                                  );
                                  if (matched) setSelectedConnector(matched);
                                }
                              }}
                            >
                              Re-authenticate
                            </Button>
                          )}

                          {conn.status !== 'revoked' &&
                            conn.status !== 'deleted' && (
                              <Button
                                variant="secondary"
                                size="sm"
                                data-testid={`sync-now-btn-${conn.id}`}
                                leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
                                onClick={() => onSyncNow?.(conn.id)}
                              >
                                Sync Now
                              </Button>
                            )}

                          <Button
                            variant="outline"
                            size="sm"
                            data-testid={`toggle-sync-health-btn-${conn.id}`}
                            leftIcon={<Activity className="w-3.5 h-3.5" />}
                            onClick={() => handleToggleSyncHealth(conn.id)}
                          >
                            {isSyncExpanded
                              ? 'Hide Sync Health'
                              : 'View Sync Health'}
                          </Button>

                          {conn.status !== 'revoked' &&
                            conn.status !== 'deleted' && (
                              <Button
                                variant="danger"
                                size="sm"
                                data-testid={`open-revoke-modal-btn-${conn.id}`}
                                leftIcon={<Trash2 className="w-3.5 h-3.5" />}
                                onClick={() => {
                                  setRevokeTarget(conn);
                                  setDeleteImportedData(false);
                                }}
                              >
                                Disconnect / Revoke
                              </Button>
                            )}
                        </div>
                      </div>

                      {isSyncExpanded && (
                        <div className="pt-2">
                          <SyncHealthTable
                            runs={runs}
                            connectionLabel={conn.label}
                          />
                        </div>
                      )}
                    </Card>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Granular Consent Modal */}
      {selectedConnector && (
        <ConnectorConsentModal
          connector={selectedConnector}
          isOpen={true}
          isSubmitting={isSubmitting}
          onConfirm={handleConfirmConsent}
          onCancel={() => setSelectedConnector(null)}
        />
      )}

      {/* Disconnect / Revoke Cascade Modal (Titan S2) */}
      {revokeTarget && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="revoke-modal-title"
          data-testid="revoke-connection-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
        >
          <Card className="w-full max-w-md p-6 space-y-4 shadow-xl border border-[var(--cf-border)] bg-[var(--cf-surface)]">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-rose-600/10 text-rose-600 flex items-center justify-center shrink-0">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h3
                  id="revoke-modal-title"
                  className="text-sm font-bold text-[var(--cf-fg)]"
                >
                  Revoke Connection — {revokeTarget.label}
                </h3>
                <p className="text-xs text-[var(--cf-fg-muted)]">
                  Purges encrypted OAuth tokens from your local Vault and revokes the active consent grant.
                </p>
              </div>
            </div>

            <label
              data-testid="revoke-delete-imported-label"
              className="flex items-start gap-2.5 p-3 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface-2)] text-xs cursor-pointer"
            >
              <input
                type="checkbox"
                checked={deleteImportedData}
                data-testid="revoke-delete-imported-checkbox"
                onChange={(e) => setDeleteImportedData(e.target.checked)}
                className="mt-0.5 rounded border-[var(--cf-border)] text-rose-600"
              />
              <span className="text-[var(--cf-fg)] font-medium leading-relaxed">
                Also delete all records imported from this connection
              </span>
            </label>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[var(--cf-border)]">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                data-testid="cancel-revoke-btn"
                onClick={() => {
                  setRevokeTarget(null);
                  setDeleteImportedData(false);
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="danger"
                size="sm"
                loading={isSubmitting}
                data-testid="confirm-revoke-btn"
                onClick={handleConfirmRevoke}
              >
                Confirm Revoke
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
