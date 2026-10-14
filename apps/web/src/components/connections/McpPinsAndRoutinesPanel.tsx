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
  ShieldAlert,
  ShieldCheck,
  Clock,
  PauseCircle,
  Trash2,
  Plus,
  Hash,
  RefreshCw,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import type {
  CreateStandingRoutinePayload,
  McpToolPinItem,
  StandingRoutineItem,
} from '@/types/autonomyBatch6';

export interface McpPinsAndRoutinesPanelProps {
  mcpPins: McpToolPinItem[];
  routines: StandingRoutineItem[];
  onReapprovePin?: (pinId: string, schemaHash: string) => void | Promise<void>;
  onCreateRoutine?: (
    payload: CreateStandingRoutinePayload
  ) => void | Promise<void>;
  onPauseRoutine?: (routineId: string) => void | Promise<void>;
  onRevokeRoutine?: (routineId: string) => void | Promise<void>;
  className?: string;
}

function computeDaysRemaining(expiresAt: string): number {
  const target = new Date(expiresAt).getTime();
  const now = Date.now();
  if (Number.isNaN(target)) return 90;
  const diffDays = Math.ceil((target - now) / (1000 * 60 * 60 * 24));
  return Math.max(0, Math.min(90, diffDays));
}

export function McpPinsAndRoutinesPanel({
  mcpPins,
  routines,
  onReapprovePin,
  onCreateRoutine,
  onPauseRoutine,
  onRevokeRoutine,
  className,
}: McpPinsAndRoutinesPanelProps) {
  const [routineName, setRoutineName] = useState('Morning BP & Vitals Digest');
  const [connectionId, setConnectionId] = useState('conn-withings-1');
  const [toolName, setToolName] = useState('withings.fetch_daily_vitals');
  const [rrule, setRrule] = useState('FREQ=DAILY;BYHOUR=7;BYMINUTE=30');
  const [timezone, setTimezone] = useState('America/Chicago');
  const [expiresInDays, setExpiresInDays] = useState<number>(30);
  const [expiryError, setExpiryError] = useState<string | null>(null);

  const handleSubmitRoutine = async (e: React.FormEvent) => {
    e.preventDefault();
    if (expiresInDays < 1 || expiresInDays > 90) {
      setExpiryError('A2 standing routines must expire within 1 to 90 days.');
      return;
    }
    setExpiryError(null);
    await onCreateRoutine?.({
      connection_id: connectionId.trim(),
      name: routineName.trim(),
      tool_name: toolName.trim(),
      rrule: rrule.trim(),
      timezone: timezone.trim(),
      expires_in_days: expiresInDays,
    });
  };

  return (
    <div
      data-testid="mcp-pins-and-routines-panel"
      className={cn('space-y-8', className)}
    >
      {/* Section 1: Curated Remote MCP Schema Pins (AU-57) */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Curated Remote MCP Schema Pins (SHA-256)
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Tool descriptors are cryptographically pinned at registration; schema drift halts execution until explicitly re-approved.
            </p>
          </div>
          <span
            data-testid="mcp-taint-policy-banner"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60"
          >
            <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
            All Remote MCP Outputs Tagged Untrusted (Taint Active)
          </span>
        </div>

        {mcpPins.length === 0 ? (
          <Card
            data-testid="mcp-pins-empty"
            className="p-4 text-xs text-[var(--cf-fg-muted)] border border-[var(--cf-border)] shadow-sm"
          >
            No remote MCP tool pins registered for this profile.
          </Card>
        ) : (
          <div data-testid="mcp-pins-list" className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {mcpPins.map((pin) => {
              const isDriftBlocked = pin.status === 'drift_blocked';
              return (
                <Card
                  key={pin.id}
                  data-testid={`mcp-pin-card-${pin.id}`}
                  className="p-4 space-y-3 border border-[var(--cf-border)] shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <h4 className="text-sm font-bold font-mono text-[var(--cf-fg)]">
                          {pin.tool_name}
                        </h4>
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-[var(--cf-fg)]">
                          Tier {pin.risk_tier}
                        </span>
                      </div>
                      {pin.description && (
                        <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
                          {pin.description}
                        </p>
                      )}
                    </div>

                    <span
                      data-testid={`mcp-pin-status-${pin.id}`}
                      className={cn(
                        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border',
                        isDriftBlocked
                          ? 'bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/60'
                          : 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                      )}
                    >
                      {isDriftBlocked ? (
                        <ShieldAlert className="w-3 h-3 shrink-0" />
                      ) : (
                        <ShieldCheck className="w-3 h-3 shrink-0" />
                      )}
                      <span>{pin.status}</span>
                    </span>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 text-[11px]">
                    <span
                      data-testid={`mcp-pin-hash-${pin.id}`}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[var(--cf-surface-2)] border border-[var(--cf-border)] font-mono text-[var(--cf-fg-muted)]"
                    >
                      <Hash className="w-3 h-3 text-emerald-600 shrink-0" />
                      SHA-256: {pin.schema_hash}
                    </span>
                    <span
                      data-testid={`mcp-pin-taint-badge-${pin.id}`}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60 font-medium"
                    >
                      Untrusted Output (Taint)
                    </span>
                  </div>

                  {isDriftBlocked && (
                    <div className="pt-2 border-t border-[var(--cf-border)] flex items-center justify-between gap-2">
                      <span className="text-[11px] text-rose-700 dark:text-rose-300 font-medium">
                        Upstream descriptor hash changed — execution blocked.
                      </span>
                      <Button
                        size="sm"
                        variant="primary"
                        data-testid={`mcp-pin-reapprove-btn-${pin.id}`}
                        leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
                        onClick={() =>
                          onReapprovePin?.(pin.id, pin.schema_hash)
                        }
                      >
                        Re-approve Schema
                      </Button>
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </section>

      {/* Section 2: A2 Standing Routines (AU-58) */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              A2 Standing Routines (&le; 90 Days Expiry)
            </h3>
            <p
              data-testid="routine-fire-recheck-notice"
              className="text-xs text-[var(--cf-fg-muted)]"
            >
              Re-verifies creator access, active consent, and untainted state at fire time
            </p>
          </div>
        </div>

        {/* Active / Paused Routines List */}
        {routines.length === 0 ? (
          <Card
            data-testid="routines-empty"
            className="p-4 text-xs text-[var(--cf-fg-muted)] border border-[var(--cf-border)] shadow-sm"
          >
            No A2 standing routines configured.
          </Card>
        ) : (
          <div data-testid="standing-routines-list" className="space-y-3">
            {routines.map((routine) => {
              const daysLeft = computeDaysRemaining(routine.expires_at);
              return (
                <Card
                  key={routine.id}
                  data-testid={`routine-card-${routine.id}`}
                  className="p-4 flex flex-wrap items-center justify-between gap-4 border border-[var(--cf-border)] shadow-sm"
                >
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="text-sm font-bold text-[var(--cf-fg)]">
                        {routine.name}
                      </h4>
                      <span
                        data-testid={`routine-status-badge-${routine.id}`}
                        className={cn(
                          'px-2 py-0.5 rounded-full text-[11px] font-semibold border',
                          routine.status === 'active'
                            ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                            : 'bg-slate-100 dark:bg-slate-900 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700'
                        )}
                      >
                        {routine.status}
                      </span>
                      <span
                        data-testid={`routine-expiry-badge-${routine.id}`}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/60"
                      >
                        <Clock className="w-3 h-3 shrink-0" />
                        Expires in {daysLeft}d (&le; 90 days max)
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-[11px] text-[var(--cf-fg-muted)] font-mono">
                      <span>Tool: {routine.tool_name}</span>
                      <span>RRULE: {routine.rrule}</span>
                      <span>TZ: {routine.timezone}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {routine.status === 'active' && (
                      <Button
                        size="sm"
                        variant="secondary"
                        data-testid={`routine-pause-btn-${routine.id}`}
                        leftIcon={<PauseCircle className="w-3.5 h-3.5" />}
                        onClick={() => onPauseRoutine?.(routine.id)}
                      >
                        Pause
                      </Button>
                    )}
                    {routine.status !== 'revoked' && (
                      <Button
                        size="sm"
                        variant="danger"
                        data-testid={`routine-revoke-btn-${routine.id}`}
                        leftIcon={<Trash2 className="w-3.5 h-3.5" />}
                        onClick={() => onRevokeRoutine?.(routine.id)}
                      >
                        Revoke
                      </Button>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        )}

        {/* New A2 Standing Routine Form */}
        <Card className="p-4 border border-[var(--cf-border)] shadow-sm">
          <form
            data-testid="create-routine-form"
            onSubmit={handleSubmitRoutine}
            className="space-y-3"
          >
            <h4 className="text-xs font-bold uppercase tracking-wider text-[var(--cf-fg-muted)]">
              Create New A2 Standing Routine
            </h4>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label
                  htmlFor="routine-name-input"
                  className="block text-[11px] font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  Routine Name
                </label>
                <input
                  id="routine-name-input"
                  type="text"
                  data-testid="routine-name-input"
                  value={routineName}
                  onChange={(e) => setRoutineName(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              <div>
                <label
                  htmlFor="routine-tool-input"
                  className="block text-[11px] font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  Pinned Tool Name (A2 Eligible)
                </label>
                <input
                  id="routine-tool-input"
                  type="text"
                  data-testid="routine-tool-input"
                  value={toolName}
                  onChange={(e) => setToolName(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              <div>
                <label
                  htmlFor="routine-expiry-days-input"
                  className="block text-[11px] font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  Expiry Days (Max 90)
                </label>
                <input
                  id="routine-expiry-days-input"
                  type="number"
                  min={1}
                  max={90}
                  data-testid="routine-expiry-days-input"
                  value={expiresInDays}
                  onChange={(e) =>
                    setExpiresInDays(parseInt(e.target.value || '0', 10))
                  }
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label
                  htmlFor="routine-conn-input"
                  className="block text-[11px] font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  Connection ID
                </label>
                <input
                  id="routine-conn-input"
                  type="text"
                  data-testid="routine-conn-input"
                  value={connectionId}
                  onChange={(e) => setConnectionId(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              <div>
                <label
                  htmlFor="routine-rrule-input"
                  className="block text-[11px] font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  Schedule RRULE
                </label>
                <input
                  id="routine-rrule-input"
                  type="text"
                  data-testid="routine-rrule-input"
                  value={rrule}
                  onChange={(e) => setRrule(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              <div>
                <label
                  htmlFor="routine-tz-input"
                  className="block text-[11px] font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  IANA Timezone
                </label>
                <input
                  id="routine-tz-input"
                  type="text"
                  data-testid="routine-tz-input"
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
            </div>

            {expiryError && (
              <p
                data-testid="routine-expiry-error"
                className="text-xs text-rose-600 dark:text-rose-400 font-medium"
              >
                {expiryError}
              </p>
            )}

            <div className="flex justify-end">
              <Button
                type="submit"
                size="sm"
                variant="primary"
                data-testid="create-routine-submit-btn"
                leftIcon={<Plus className="w-3.5 h-3.5" />}
              >
                Create A2 Routine
              </Button>
            </div>
          </form>
        </Card>
      </section>
    </div>
  );
}
