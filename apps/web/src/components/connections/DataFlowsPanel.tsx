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

import React from 'react';
import {
  Cpu,
  Search,
  Globe,
  ShieldCheck,
  ShieldAlert,
  Trash2,
  Network,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import type { DataFlowsInventory } from '@/types/connections';

export interface DataFlowsPanelProps {
  inventory: DataFlowsInventory | null;
  isLoading?: boolean;
  onQuickRevoke?: (connectionId: string) => void | Promise<void>;
  className?: string;
}

export function DataFlowsPanel({
  inventory,
  isLoading = false,
  onQuickRevoke,
  className,
}: DataFlowsPanelProps) {
  if (isLoading) {
    return (
      <Card
        data-testid="data-flows-loading"
        className={cn('p-6 text-center text-xs text-[var(--cf-fg-muted)]', className)}
      >
        Loading outbound data flows transparency matrix...
      </Card>
    );
  }

  if (!inventory) {
    return (
      <Card
        data-testid="data-flows-empty"
        className={cn('p-6 text-center text-xs text-[var(--cf-fg-muted)]', className)}
      >
        No data flows inventory available.
      </Card>
    );
  }

  const { model_provider, search_provider, connections } = inventory;

  return (
    <div
      data-testid="data-flows-panel"
      className={cn('space-y-5', className)}
    >
      {/* Top Cards: AI Model Provider & Outbound Web Search */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Active AI Model Provider Card */}
        <Card
          data-testid="data-flows-model-provider-card"
          className="p-4 space-y-3 shadow-sm border border-[var(--cf-border)]"
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-emerald-600/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
                <Cpu className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-xs font-bold text-[var(--cf-fg)]">
                  Active AI Model Provider
                </h3>
                <p
                  data-testid="data-flows-model-name"
                  className="text-xs font-semibold text-emerald-700 dark:text-emerald-400"
                >
                  {model_provider.provider}
                </p>
              </div>
            </div>
            <span
              data-testid="data-flows-model-locality-badge"
              className={cn(
                'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border',
                model_provider.is_local
                  ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                  : 'bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800/60'
              )}
            >
              <ShieldCheck className="w-3 h-3 shrink-0" />
              <span>
                {model_provider.is_local
                  ? 'Local-Default Active'
                  : 'Cloud Endpoint'}
              </span>
            </span>
          </div>

          <div className="space-y-1.5 text-xs">
            <div className="flex items-center justify-between text-[var(--cf-fg-muted)]">
              <span>Inference Host:</span>
              <code
                data-testid="data-flows-model-host"
                className="px-2 py-0.5 rounded bg-[var(--cf-surface-2)] font-mono text-[11px] text-[var(--cf-fg)]"
              >
                {model_provider.host}
              </code>
            </div>
            <p
              data-testid="data-flows-model-policy"
              className="text-[11px] text-[var(--cf-fg-muted)] leading-relaxed pt-1 border-t border-[var(--cf-border)]"
            >
              {model_provider.connector_context_policy ||
                'Local-default inference enforced whenever external connector data is present in conversation context.'}
            </p>
          </div>
        </Card>

        {/* Outbound Web Search Card */}
        <Card
          data-testid="data-flows-search-provider-card"
          className="p-4 space-y-3 shadow-sm border border-[var(--cf-border)]"
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-blue-600/10 text-blue-600 dark:text-blue-400 flex items-center justify-center shrink-0">
                <Search className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-xs font-bold text-[var(--cf-fg)]">
                  Outbound Web Search Egress
                </h3>
                <p
                  data-testid="data-flows-search-name"
                  className="text-xs font-semibold text-blue-700 dark:text-blue-400"
                >
                  {search_provider.provider}
                </p>
              </div>
            </div>
            <span
              data-testid="data-flows-phi-sanitiser-badge"
              className={cn(
                'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border',
                search_provider.phi_sanitiser_enabled
                  ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                  : 'bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/60'
              )}
            >
              {search_provider.phi_sanitiser_enabled ? (
                <>
                  <ShieldCheck className="w-3 h-3 shrink-0" />
                  <span>PHI Query Sanitiser Active</span>
                </>
              ) : (
                <>
                  <ShieldAlert className="w-3 h-3 shrink-0" />
                  <span>Sanitiser Disabled</span>
                </>
              )}
            </span>
          </div>

          <div className="space-y-1.5 text-xs">
            <span className="block text-[11px] text-[var(--cf-fg-muted)]">
              Allowlisted Search Hosts:
            </span>
            <div
              data-testid="data-flows-search-hosts"
              className="flex flex-wrap gap-1.5"
            >
              {search_provider.allowed_hosts.map((host) => (
                <span
                  key={host}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[var(--cf-surface-2)] border border-[var(--cf-border)] font-mono text-[11px] text-[var(--cf-fg)]"
                >
                  <Globe className="w-3 h-3 text-blue-600 shrink-0" />
                  {host}
                </span>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* Per-Connection Egress & Consent Table */}
      <Card className="p-5 space-y-4 shadow-sm border border-[var(--cf-border)]">
        <div className="flex items-center justify-between gap-2 pb-3 border-b border-[var(--cf-border)]">
          <div className="flex items-center gap-2.5">
            <Network className="w-4 h-4 text-emerald-600" />
            <div>
              <h3 className="text-sm font-bold text-[var(--cf-fg)]">
                Settings › Data Flows &amp; Per-Connection Egress Ledger
              </h3>
              <p className="text-xs text-[var(--cf-fg-muted)]">
                Complete audit of external destination hosts, consented data categories, and active terms versions
              </p>
            </div>
          </div>
          <span className="text-xs font-medium text-[var(--cf-fg-muted)]">
            {connections.length}{' '}
            {connections.length === 1 ? 'connection' : 'connections'}
          </span>
        </div>

        {connections.length === 0 ? (
          <div
            data-testid="data-flows-no-connections"
            className="py-6 text-center text-xs text-[var(--cf-fg-muted)]"
          >
            No active or historical external data connections configured for this profile.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table
              data-testid="data-flows-connections-table"
              className="w-full text-left border-collapse text-xs"
            >
              <thead>
                <tr className="border-b border-[var(--cf-border)] text-[11px] text-[var(--cf-fg-muted)]">
                  <th className="py-2 pr-3 font-semibold">Connector</th>
                  <th className="py-2 px-3 font-semibold">Status</th>
                  <th className="py-2 px-3 font-semibold">
                    Allowed Outbound Hosts
                  </th>
                  <th className="py-2 px-3 font-semibold">
                    Consented Data Categories
                  </th>
                  <th className="py-2 px-3 font-semibold">Terms Version</th>
                  <th className="py-2 pl-3 font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--cf-border)]">
                {connections.map((conn) => (
                  <tr
                    key={conn.connection_id}
                    data-testid={`data-flow-row-${conn.connection_id}`}
                    className="hover:bg-[var(--cf-surface-2)]/50"
                  >
                    <td className="py-3 pr-3 font-semibold text-[var(--cf-fg)]">
                      <div>
                        {conn.label || conn.connector_name || conn.connector_id}
                      </div>
                      <div className="text-[11px] font-mono text-[var(--cf-fg-muted)]">
                        {conn.connector_id}
                      </div>
                    </td>
                    <td className="py-3 px-3">
                      <span
                        data-testid={`data-flow-status-${conn.connection_id}`}
                        className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-[var(--cf-fg)]"
                      >
                        {conn.status}
                      </span>
                    </td>
                    <td
                      data-testid={`data-flow-hosts-${conn.connection_id}`}
                      className="py-3 px-3"
                    >
                      <div className="flex flex-wrap gap-1">
                        {conn.allowed_hosts.map((host) => (
                          <span
                            key={host}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[var(--cf-surface-2)] border border-[var(--cf-border)] font-mono text-[11px] text-[var(--cf-fg)]"
                          >
                            <Globe className="w-3 h-3 text-emerald-600 shrink-0" />
                            {host}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td
                      data-testid={`data-flow-categories-${conn.connection_id}`}
                      className="py-3 px-3"
                    >
                      <div className="flex flex-wrap gap-1">
                        {conn.categories.map((cat) => (
                          <span
                            key={cat}
                            className="px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/30 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60 text-[11px] font-medium"
                          >
                            {cat}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td
                      data-testid={`data-flow-terms-${conn.connection_id}`}
                      className="py-3 px-3 font-mono text-[11px] text-[var(--cf-fg-muted)]"
                    >
                      v{conn.terms_version}
                    </td>
                    <td className="py-3 pl-3 text-right">
                      {onQuickRevoke && conn.status !== 'revoked' && (
                        <Button
                          variant="danger"
                          size="sm"
                          data-testid={`data-flow-revoke-btn-${conn.connection_id}`}
                          leftIcon={<Trash2 className="w-3.5 h-3.5" />}
                          onClick={() => onQuickRevoke(conn.connection_id)}
                        >
                          Revoke
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
