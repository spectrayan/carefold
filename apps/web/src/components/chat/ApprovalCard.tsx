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

'use client';

import React, { useState, useEffect, useId } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Globe,
  Lock,
  Edit3,
  Loader2
} from 'lucide-react';
import type { ApprovalRecord, RiskTier, ApprovalStatus } from '@/lib/types';
import { cn } from '@/lib/utils';

export interface ApprovalCardProps {
  approval: ApprovalRecord;
  profileId?: string;
  onDecided?: (updatedApproval: ApprovalRecord) => void;
  onResume?: (approvalId: string, threadId?: string) => void;
  disabled?: boolean;
  className?: string;
}

const RISK_TIER_CONFIG: Record<
  RiskTier,
  { label: string; badge: string; description: string; icon: typeof ShieldCheck }
> = {
  read: {
    label: 'Read Only',
    badge: 'bg-sky-50 text-sky-800 border-sky-200 dark:bg-sky-950/60 dark:text-sky-300 dark:border-sky-800',
    description: 'Harmless query; reads sandboxed profile state without side effects.',
    icon: ShieldCheck
  },
  write_local: {
    label: 'Local Write',
    badge: 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800',
    description: 'Modifies local profile notes or vitals; no external network traffic.',
    icon: ShieldCheck
  },
  write_workspace: {
    label: 'Workspace Write',
    badge: 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800',
    description: 'Modifies workspace files or local notes.',
    icon: ShieldCheck
  },
  write_external: {
    label: 'External Write',
    badge: 'bg-amber-50 text-amber-900 border-amber-300 dark:bg-amber-950/60 dark:text-amber-200 dark:border-amber-800',
    description: 'Outbound mutation transmitting data to an external API or health portal.',
    icon: AlertTriangle
  },
  admin: {
    label: 'Admin Operation',
    badge: 'bg-stone-100 text-emerald-950 border-stone-300 dark:bg-zinc-800 dark:text-emerald-200 dark:border-zinc-700',
    description: 'Privileged configuration or administrative change.',
    icon: ShieldAlert
  },
  irreversible: {
    label: 'Irreversible Action',
    badge: 'bg-rose-50 text-rose-900 border-rose-300 dark:bg-rose-950/60 dark:text-rose-200 dark:border-rose-800',
    description: 'Permanent clinical or administrative action that cannot be undone.',
    icon: ShieldAlert
  }
};

export function parseApprovalArgs(argsInput: Record<string, any> | string): Record<string, any> {
  if (typeof argsInput === 'object' && argsInput !== null) {
    return argsInput;
  }
  if (typeof argsInput === 'string') {
    try {
      const parsed = JSON.parse(argsInput);
      if (typeof parsed === 'object' && parsed !== null) return parsed;
    } catch {
      return { raw: argsInput };
    }
  }
  return {};
}

export function parseDestinationHosts(destInput?: string[] | string): string[] {
  if (Array.isArray(destInput)) return destInput;
  if (typeof destInput === 'string') {
    try {
      const parsed = JSON.parse(destInput);
      if (Array.isArray(parsed)) return parsed;
    } catch {
      if (destInput.trim()) return [destInput.trim()];
    }
  }
  return [];
}

export function ApprovalCard({
  approval,
  profileId,
  onDecided,
  onResume,
  disabled = false,
  className
}: ApprovalCardProps) {
  const cardId = useId();
  const initialArgs = parseApprovalArgs(approval.args_redacted);
  const destinationHosts = parseDestinationHosts(approval.destination_hosts);

  const [currentStatus, setCurrentStatus] = useState<ApprovalStatus>(approval.status || 'pending');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Argument editing state
  const [isEditing, setIsEditing] = useState(false);
  const [editedArgsText, setEditedArgsText] = useState(() => JSON.stringify(initialArgs, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [hasModifiedArgs, setHasModifiedArgs] = useState(false);
  const [appliedArgs, setAppliedArgs] = useState<Record<string, any>>(initialArgs);

  // Time-to-live countdown
  const [remainingTimeText, setRemainingTimeText] = useState<string | null>(null);

  useEffect(() => {
    if (currentStatus !== 'pending' || !approval.expires_at) return;

    const updateTimer = () => {
      const expiry = new Date(approval.expires_at!).getTime();
      const now = Date.now();
      const diffSecs = Math.max(0, Math.floor((expiry - now) / 1000));

      if (diffSecs <= 0) {
        setCurrentStatus('expired');
        setRemainingTimeText('Expired');
        return;
      }

      const mins = Math.floor(diffSecs / 60);
      const secs = diffSecs % 60;
      setRemainingTimeText(`${mins}:${secs.toString().padStart(2, '0')}`);
    };

    updateTimer();
    const interval = setInterval(updateTimer, 1000);
    return () => clearInterval(interval);
  }, [approval.expires_at, currentStatus]);

  const tierMeta = RISK_TIER_CONFIG[approval.risk_tier] || RISK_TIER_CONFIG.write_external;
  const TierIcon = tierMeta.icon;

  const handleJsonChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value;
    setEditedArgsText(text);
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setJsonError('Tool arguments must be a JSON object.');
      } else {
        setJsonError(null);
      }
    } catch (err: any) {
      setJsonError(err.message || 'Invalid JSON syntax');
    }
  };

  const handleApplyEdits = () => {
    try {
      const parsed = JSON.parse(editedArgsText);
      setAppliedArgs(parsed);
      setHasModifiedArgs(true);
      setIsEditing(false);
      setJsonError(null);
    } catch (err: any) {
      setJsonError(err.message || 'Cannot apply invalid JSON');
    }
  };

  const handleResetEdits = () => {
    setEditedArgsText(JSON.stringify(initialArgs, null, 2));
    setAppliedArgs(initialArgs);
    setHasModifiedArgs(false);
    setIsEditing(false);
    setJsonError(null);
  };

  const submitDecision = async (decision: 'approved' | 'rejected') => {
    if (disabled || isSubmitting || currentStatus !== 'pending') return;

    setIsSubmitting(true);
    setErrorMessage(null);

    const targetUrl = profileId
      ? `/api/profiles/${encodeURIComponent(profileId)}/approvals/${encodeURIComponent(approval.id)}/decide`
      : `/api/approvals/${encodeURIComponent(approval.id)}/decide`;

    const payload: { decision: string; edited_args?: Record<string, any> } = {
      decision
    };

    if (decision === 'approved' && hasModifiedArgs) {
      payload.edited_args = appliedArgs;
    }

    try {
      const res = await fetch(targetUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || errorData.error || `HTTP ${res.status}`);
      }

      const result = await res.json();
      const updatedStatus: ApprovalStatus = decision === 'approved' ? 'approved' : 'rejected';
      setCurrentStatus(updatedStatus);

      const updatedRecord: ApprovalRecord = {
        ...approval,
        status: updatedStatus,
        args_redacted: hasModifiedArgs ? appliedArgs : approval.args_redacted,
        payload_hash: result.payload_hash || approval.payload_hash,
        decided_at: result.decided_at || new Date().toISOString(),
        decided_by: result.decided_by
      };

      onDecided?.(updatedRecord);

      if (decision === 'approved') {
        onResume?.(approval.id, approval.thread_id);
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to submit decision.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      role="region"
      aria-labelledby={`${cardId}-tool-name`}
      data-testid="approval-card"
      data-status={currentStatus}
      data-risk-tier={approval.risk_tier}
      className={cn(
        'rounded-2xl border p-4 shadow-sm transition-all',
        currentStatus === 'pending' &&
          'border-amber-300 dark:border-amber-800/80 bg-amber-50/40 dark:bg-amber-950/20 text-slate-900 dark:text-zinc-100',
        currentStatus === 'approved' &&
          'border-emerald-300 dark:border-emerald-800/80 bg-emerald-50/40 dark:bg-emerald-950/20 text-slate-900 dark:text-zinc-100',
        currentStatus === 'rejected' &&
          'border-slate-300 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/40 text-slate-700 dark:text-zinc-300 opacity-90',
        currentStatus === 'consumed' &&
          'border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/60 text-zinc-600 dark:text-zinc-400',
        currentStatus === 'expired' &&
          'border-rose-300 dark:border-rose-800/80 bg-rose-50/40 dark:bg-rose-950/20 text-rose-950 dark:text-rose-200',
        className
      )}
    >
      {/* Header Banner */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-200/80 dark:border-zinc-700/80">
        <div className="flex items-center gap-2">
          <div
            className={cn(
              'w-7 h-7 rounded-lg flex items-center justify-center shrink-0 font-bold',
              currentStatus === 'pending' && 'bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-300',
              currentStatus === 'approved' && 'bg-emerald-100 dark:bg-emerald-900/60 text-emerald-800 dark:text-emerald-300',
              currentStatus === 'rejected' && 'bg-slate-200 dark:bg-zinc-700 text-slate-700 dark:text-zinc-300',
              currentStatus === 'consumed' && 'bg-zinc-200 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-400',
              currentStatus === 'expired' && 'bg-rose-100 dark:bg-rose-900/60 text-rose-800 dark:text-rose-300'
            )}
          >
            <TierIcon className="w-4 h-4" aria-hidden="true" />
          </div>

          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
                Action Authorization Required
              </span>
              {remainingTimeText && currentStatus === 'pending' && (
                <span
                  data-testid="approval-ttl-timer"
                  className="inline-flex items-center gap-1 text-xs font-mono font-medium px-1.5 py-0.5 rounded bg-amber-100/80 dark:bg-amber-900/60 text-amber-900 dark:text-amber-200"
                >
                  <Clock className="w-3 h-3" />
                  <span>{remainingTimeText}</span>
                </span>
              )}
            </div>
            <h3 id={`${cardId}-tool-name`} className="text-sm font-bold text-slate-900 dark:text-zinc-100 font-mono">
              {approval.tool_name}
            </h3>
          </div>
        </div>

        {/* Badges: Risk Tier & Status */}
        <div className="flex items-center gap-1.5">
          <span
            data-testid="approval-risk-badge"
            className={cn('text-xs font-semibold px-2 py-0.5 rounded-full border', tierMeta.badge)}
            title={tierMeta.description}
          >
            {tierMeta.label}
          </span>

          <span
            data-testid="approval-status-badge"
            className={cn(
              'text-xs font-semibold px-2 py-0.5 rounded-full border uppercase tracking-wider',
              currentStatus === 'pending' && 'bg-amber-100 text-amber-900 border-amber-300 dark:bg-amber-900/60 dark:text-amber-200 dark:border-amber-700',
              currentStatus === 'approved' && 'bg-emerald-100 text-emerald-900 border-emerald-300 dark:bg-emerald-900/60 dark:text-emerald-200 dark:border-emerald-700',
              currentStatus === 'rejected' && 'bg-slate-200 text-slate-800 border-slate-300 dark:bg-zinc-800 dark:text-zinc-300 dark:border-zinc-700',
              currentStatus === 'consumed' && 'bg-zinc-200 text-zinc-700 border-zinc-300 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700',
              currentStatus === 'expired' && 'bg-rose-100 text-rose-900 border-rose-300 dark:bg-rose-900/60 dark:text-rose-200 dark:border-rose-700'
            )}
          >
            {currentStatus}
          </span>
        </div>
      </div>

      {/* Destination Hosts Indicator */}
      <div className="mt-3 flex items-start gap-2 text-xs">
        {destinationHosts.length > 0 ? (
          <div className="flex items-center flex-wrap gap-1.5 text-slate-600 dark:text-zinc-300">
            <span className="flex items-center gap-1 font-semibold text-slate-700 dark:text-zinc-200">
              <Globe className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
              <span>Outbound Egress:</span>
            </span>
            {destinationHosts.map((host) => (
              <span
                key={host}
                data-testid="destination-host-pill"
                className="font-mono text-xs px-1.5 py-0.5 rounded bg-slate-200 dark:bg-zinc-700 text-slate-800 dark:text-zinc-200 border border-slate-300 dark:border-zinc-600"
              >
                {host}
              </span>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-1 text-slate-500 dark:text-zinc-400">
            <Lock className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
            <span>Local profile sandbox (zero external egress)</span>
          </div>
        )}
      </div>

      {/* Argument Preview Table / Editor */}
      <div className="mt-3">
        <div className="flex items-center justify-between mb-1.5 text-xs text-slate-600 dark:text-zinc-400">
          <span className="font-semibold">Invocation Arguments</span>
          {currentStatus === 'pending' && !isEditing && (
            <button
              type="button"
              data-testid="edit-arguments-button"
              onClick={() => setIsEditing(true)}
              disabled={disabled || isSubmitting}
              className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 dark:text-emerald-400 hover:underline cursor-pointer disabled:opacity-50"
            >
              <Edit3 className="w-3 h-3" />
              <span>Edit Arguments</span>
            </button>
          )}
          {hasModifiedArgs && !isEditing && (
            <span className="text-xs font-semibold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-900/60 px-1.5 py-0.5 rounded">
              Modified Arguments
            </span>
          )}
        </div>

        {isEditing ? (
          <div className="space-y-2">
            <label htmlFor={`${cardId}-args-editor`} className="sr-only">
              Edit Tool JSON Arguments
            </label>
            <textarea
              id={`${cardId}-args-editor`}
              data-testid="arguments-json-editor"
              value={editedArgsText}
              onChange={handleJsonChange}
              rows={5}
              className="w-full font-mono text-xs p-2.5 rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-600 shadow-inner"
            />
            {jsonError && (
              <div data-testid="arguments-json-error" className="text-xs text-rose-600 dark:text-rose-400 font-medium">
                {jsonError}
              </div>
            )}
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="save-edits-button"
                onClick={handleApplyEdits}
                disabled={Boolean(jsonError)}
                className="px-3 py-1 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-semibold text-xs shadow-sm transition disabled:opacity-50 cursor-pointer"
              >
                Apply Edits
              </button>
              <button
                type="button"
                data-testid="reset-edits-button"
                onClick={handleResetEdits}
                className="px-3 py-1 rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-300 font-semibold text-xs shadow-sm transition cursor-pointer"
              >
                Reset to Original
              </button>
              <button
                type="button"
                onClick={() => setIsEditing(false)}
                className="px-2.5 py-1 text-xs text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200 cursor-pointer"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-zinc-700/80 bg-white dark:bg-zinc-900/90 shadow-inner">
            <table data-testid="arguments-table" className="w-full text-left text-xs">
              <thead className="bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 font-semibold border-b border-slate-200 dark:border-zinc-700">
                <tr>
                  <th scope="col" className="px-3 py-2 w-1/3">
                    Parameter
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Value
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-zinc-800">
                {Object.keys(appliedArgs).length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-3 py-2 italic text-slate-400 dark:text-zinc-500">
                      No arguments provided.
                    </td>
                  </tr>
                ) : (
                  Object.entries(appliedArgs).map(([key, val]) => (
                    <tr key={key} className="hover:bg-slate-50/50 dark:hover:bg-zinc-800/40">
                      <td className="px-3 py-1.5 font-mono font-medium text-slate-700 dark:text-zinc-300">
                        {key}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-slate-900 dark:text-zinc-100 break-all">
                        {typeof val === 'object' && val !== null ? (
                          <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(val, null, 2)}</pre>
                        ) : String(val) === '[REDACTED]' ? (
                          <span className="font-semibold px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-950/80 text-amber-800 dark:text-amber-300 text-xs">
                            [REDACTED]
                          </span>
                        ) : (
                          String(val)
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Error Message Notice */}
      {errorMessage && (
        <div data-testid="approval-error-banner" className="mt-3 p-2 rounded-xl bg-rose-100 dark:bg-rose-950/60 border border-rose-300 dark:border-rose-800 text-rose-900 dark:text-rose-200 text-xs font-semibold">
          {errorMessage}
        </div>
      )}

      {/* Bottom Action Controls */}
      <div className="mt-4 pt-3 border-t border-slate-200/80 dark:border-zinc-700/80 flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-mono text-slate-400 dark:text-zinc-500">
          Hash: {approval.payload_hash ? approval.payload_hash.slice(0, 12) + '...' : 'pending'}
        </div>

        {currentStatus === 'pending' && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="reject-button"
              onClick={() => submitDecision('rejected')}
              disabled={disabled || isSubmitting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-rose-300 dark:border-rose-800 bg-white dark:bg-zinc-900 hover:bg-rose-50 dark:hover:bg-rose-950/50 text-rose-700 dark:text-rose-300 font-semibold text-xs shadow-sm transition cursor-pointer disabled:opacity-50"
            >
              {isSubmitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
              <span>Reject</span>
            </button>

            <button
              type="button"
              data-testid="approve-button"
              onClick={() => submitDecision('approved')}
              disabled={disabled || isSubmitting}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 active:bg-emerald-900 text-white font-bold text-xs shadow-sm transition cursor-pointer disabled:opacity-50"
            >
              {isSubmitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              <span>Approve Action</span>
            </button>
          </div>
        )}

        {currentStatus === 'approved' && (
          <div data-testid="approval-approved-notice" className="flex items-center gap-1.5 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>Authorized by human steward — Execution resumed</span>
          </div>
        )}

        {currentStatus === 'rejected' && (
          <div data-testid="approval-rejected-notice" className="flex items-center gap-1.5 text-xs font-semibold text-slate-600 dark:text-zinc-400">
            <XCircle className="w-4 h-4 shrink-0 text-rose-600 dark:text-rose-400" />
            <span>Action rejected — Execution safely cancelled</span>
          </div>
        )}

        {currentStatus === 'consumed' && (
          <div data-testid="approval-consumed-notice" className="flex items-center gap-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            <Lock className="w-4 h-4 shrink-0" />
            <span>Single-use token consumed — Cannot be replayed</span>
          </div>
        )}

        {currentStatus === 'expired' && (
          <div data-testid="approval-expired-notice" className="flex items-center gap-1.5 text-xs font-semibold text-rose-700 dark:text-rose-400">
            <Clock className="w-4 h-4 shrink-0" />
            <span>Token expired (TTL exceeded) — Fail-closed</span>
          </div>
        )}
      </div>
    </div>
  );
}
