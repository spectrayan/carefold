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

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import Link from 'next/link';
import {
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  Bot,
  AlertCircle,
  XCircle,
  RotateCcw,
  Copy,
  Download,
  X,
  Search,
  Activity,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  Check,
  Clock
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { AuditEvent } from '@/types/api';
import {
  fetchAuditEvents,
  copyAuditEventsToClipboard,
  exportAuditEventsAsJson,
  formatAuditTimestamp,
  formatAuditDuration
} from '@/lib/audit';

export interface ActivityLogDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  activeAgentId?: string;
}

export function ActivityLogDrawer({
  isOpen,
  onClose,
  activeAgentId
}: ActivityLogDrawerProps) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unauthenticated, setUnauthenticated] = useState<boolean>(false);

  // Filters
  const [agentFilter, setAgentFilter] = useState<string>(activeAgentId || 'all');
  const [eventFilter, setEventFilter] = useState<string>('all');
  const [onlyBlocked, setOnlyBlocked] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Update agent filter if activeAgentId prop changes
  useEffect(() => {
    if (activeAgentId) {
      setAgentFilter(activeAgentId);
    }
  }, [activeAgentId]);

  // UI state
  const [copied, setCopied] = useState(false);
  const [expandedIndices, setExpandedIndices] = useState<Set<number>>(new Set());

  // Load audit events
  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAuditEvents({ limit: 100 });
      setEvents(response.events || []);
      setUnauthenticated(false);
    } catch (err: any) {
      if (err?.status === 401 || err?.message?.includes('401') || err?.message?.toLowerCase().includes('unauthorized')) {
        setUnauthenticated(true);
      }
      setError(err?.message || 'Failed to load activity events');
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch when opened
  useEffect(() => {
    if (isOpen) {
      loadEvents();
    }
  }, [isOpen, loadEvents]);

  // Handle escape key
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Unique agents discovered in events
  const uniqueAgents = useMemo(() => {
    const set = new Set<string>();
    events.forEach((ev) => {
      if (ev.agent_id) set.add(ev.agent_id);
    });
    return Array.from(set).sort();
  }, [events]);

  // Filtered events
  const filteredEvents = useMemo(() => {
    return events.filter((ev) => {
      // 1. Agent filter
      if (agentFilter !== 'all' && ev.agent_id !== agentFilter) {
        return false;
      }

      // 2. Event type filter
      if (eventFilter !== 'all' && ev.event !== eventFilter) {
        return false;
      }

      // 3. Only Blocked & Refused filter
      if (onlyBlocked) {
        const isBlocked = ev.allowed === false || ev.event === 'refuse';
        if (!isBlocked) return false;
      }

      // 4. Text search (case-insensitive across tool names, reasons, agent, errors)
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const toolMatch = ev.tool?.toLowerCase().includes(q) ?? false;
        const reasonMatch = ev.reason?.toLowerCase().includes(q) ?? false;
        const agentMatch = ev.agent_id?.toLowerCase().includes(q) ?? false;
        const eventMatch = ev.event?.toLowerCase().includes(q) ?? false;
        if (!toolMatch && !reasonMatch && !agentMatch && !eventMatch) {
          return false;
        }
      }

      return true;
    });
  }, [events, agentFilter, eventFilter, onlyBlocked, searchQuery]);

  const handleCopy = async () => {
    const success = await copyAuditEventsToClipboard(filteredEvents);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleExport = () => {
    exportAuditEventsAsJson(
      filteredEvents,
      agentFilter !== 'all' ? `carefold-audit-${agentFilter}` : 'carefold-audit'
    );
  };

  const toggleExpand = (idx: number) => {
    setExpandedIndices((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-900/40 dark:bg-black/60 backdrop-blur-sm z-40 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
        data-testid="activity-drawer-backdrop"
      />

      {/* Slide-over panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Activity & Safety Log"
        className="fixed inset-y-0 right-0 z-50 w-full sm:max-w-md md:max-w-lg lg:max-w-xl bg-white dark:bg-zinc-900 border-l border-slate-200 dark:border-zinc-800 shadow-2xl flex flex-col transition-transform duration-300 ease-in-out"
        data-testid="activity-log-drawer"
      >
        {/* Header */}
        <div className="px-4 py-3.5 border-b border-slate-200 dark:border-zinc-800 flex items-center justify-between gap-3 bg-slate-50/70 dark:bg-zinc-900/80 shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 dark:bg-emerald-950/60 border border-emerald-300 dark:border-emerald-800 flex items-center justify-center text-emerald-700 dark:text-emerald-300 shrink-0">
              <Activity className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-slate-900 dark:text-zinc-100 truncate">
                  Activity & Safety Log
                </h2>
                <span
                  data-testid="audit-count-badge"
                  className="px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-200 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300"
                >
                  {filteredEvents.length} {filteredEvents.length === 1 ? 'event' : 'events'}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span
                  data-testid="redacted-mode-badge"
                  className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400"
                  title="Your messages and notes stay on this device and are never recorded."
                >
                  <ShieldCheck className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                  Private Mode · Not Stored
                </span>
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              data-testid="refresh-audit-btn"
              onClick={loadEvents}
              disabled={loading}
              className="p-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-600 dark:text-zinc-400 transition cursor-pointer disabled:opacity-50"
              title="Refresh logs"
              aria-label="Refresh logs"
            >
              <RotateCcw className={cn('w-4 h-4', loading && 'animate-spin')} />
            </button>

            <button
              type="button"
              data-testid="copy-audit-btn"
              onClick={handleCopy}
              disabled={filteredEvents.length === 0}
              className="p-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-600 dark:text-zinc-400 transition cursor-pointer disabled:opacity-50"
              title={copied ? 'Copied to clipboard!' : 'Copy events as JSON'}
              aria-label="Copy events as JSON"
            >
              {copied ? (
                <Check className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
            </button>

            <button
              type="button"
              data-testid="export-audit-btn"
              onClick={handleExport}
              disabled={filteredEvents.length === 0}
              className="p-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-600 dark:text-zinc-400 transition cursor-pointer disabled:opacity-50"
              title="Download events as JSON file"
              aria-label="Download events as JSON file"
            >
              <Download className="w-4 h-4" />
            </button>

            <button
              type="button"
              data-testid="close-drawer-btn"
              onClick={onClose}
              className="p-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-600 dark:text-zinc-400 transition cursor-pointer"
              title="Close drawer"
              aria-label="Close drawer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Sticky Filter Bar */}
        <div className="p-3 border-b border-slate-200 dark:border-zinc-800 bg-slate-50/50 dark:bg-zinc-900/50 space-y-2.5 shrink-0">
          {/* Row 1: Search input */}
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 dark:text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              data-testid="audit-search-input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search tools, reasons, agents..."
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder-slate-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          {/* Row 2: Selectors & Toggles */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {/* Agent filter dropdown */}
            <select
              data-testid="audit-agent-filter"
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              className="px-2 py-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500"
              aria-label="Filter by agent"
            >
              <option value="all">All Agents</option>
              {uniqueAgents.map((ag) => (
                <option key={ag} value={ag}>
                  {ag}
                </option>
              ))}
            </select>

            {/* Event type filter dropdown */}
            <select
              data-testid="audit-event-filter"
              value={eventFilter}
              onChange={(e) => setEventFilter(e.target.value)}
              className="px-2 py-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500"
              aria-label="Filter by event type"
            >
              <option value="all">All Events</option>
              <option value="tool">Tools (tool)</option>
              <option value="refuse">Refusals (refuse)</option>
              <option value="run">Runs (run)</option>
              <option value="error">Errors (error)</option>
              <option value="boundary_warning">Boundary Warnings (boundary_warning)</option>
            </select>

            {/* "Only Blocked & Refused" toggle */}
            <label
              className="flex items-center gap-1.5 cursor-pointer ml-auto select-none py-1"
              title="Filter exclusively to blocked tool executions and safety refusals"
            >
              <input
                type="checkbox"
                data-testid="audit-blocked-toggle"
                checked={onlyBlocked}
                onChange={(e) => setOnlyBlocked(e.target.checked)}
                className="w-3.5 h-3.5 rounded text-rose-600 focus:ring-rose-500 border-slate-300 dark:border-zinc-600 cursor-pointer"
              />
              <span className="font-medium text-slate-700 dark:text-zinc-300">
                Only Blocked & Refused
              </span>
            </label>
          </div>
        </div>

        {/* Event List */}
        <div
          className="flex-1 overflow-y-auto p-4 space-y-3"
          data-testid="audit-event-list"
        >
          {unauthenticated && (
            <div
              data-testid="audit-drawer-unauthenticated-banner"
              className="p-4 rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200 text-xs space-y-2"
            >
              <div className="font-semibold flex items-center gap-1.5 text-amber-900 dark:text-amber-100">
                <ShieldAlert className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                Authentication Required
              </div>
              <p className="text-amber-700 dark:text-amber-300">
                Activity logs require an active user session. Please sign in to view your activity history.
              </p>
              <div className="pt-1">
                <Link
                  href="/login"
                  onClick={onClose}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium shadow-sm transition"
                >
                  Sign In
                </Link>
              </div>
            </div>
          )}

          {error && !unauthenticated && (
            <div className="p-3 rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 text-xs">
              <div className="font-semibold mb-1 flex items-center gap-1.5">
                <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400" />
                Failed to load activity events
              </div>
              <p>{error}</p>
            </div>
          )}

          {filteredEvents.length === 0 && !loading && (
            <div
              data-testid="audit-empty-state"
              className="text-center py-12 px-4 space-y-2 border border-dashed border-slate-200 dark:border-zinc-800 rounded-2xl"
            >
              <div className="w-10 h-10 rounded-full bg-slate-100 dark:bg-zinc-800 flex items-center justify-center mx-auto text-slate-400 dark:text-zinc-500">
                <Activity className="w-5 h-5" />
              </div>
              <h3 className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                No activity events found
              </h3>
              <p className="text-xs text-slate-500 dark:text-zinc-400 max-w-sm mx-auto">
                {events.length === 0
                  ? 'No operational or safety logs have been recorded in this runtime session.'
                  : 'No events match your current filter criteria. Try adjusting the search or filters.'}
              </p>
              {(agentFilter !== 'all' || eventFilter !== 'all' || onlyBlocked || searchQuery) && (
                <button
                  type="button"
                  onClick={() => {
                    setAgentFilter('all');
                    setEventFilter('all');
                    setOnlyBlocked(false);
                    setSearchQuery('');
                  }}
                  className="mt-2 text-xs font-medium text-emerald-700 dark:text-emerald-400 hover:text-emerald-800 dark:hover:text-emerald-300 hover:underline cursor-pointer"
                >
                  Reset all filters
                </button>
              )}
            </div>
          )}

          {filteredEvents.map((ev, index) => {
            const isExpanded = expandedIndices.has(index);

            // NON-COLOR DISTINCTION INVARIANT
            // Explicit text labels + distinct icon badges + distinct borders
            let badgeText = '[COMPLETED]';
            let BadgeIcon = Bot;
            let badgeStyle =
              'border-sky-300 dark:border-sky-800 bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300';
            let cardBorder = 'border-slate-200 dark:border-zinc-800';

            if (ev.event === 'tool' && ev.allowed === false) {
              badgeText = '[TOOL DENIED]';
              BadgeIcon = ShieldAlert;
              badgeStyle =
                'border-rose-400 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/50 text-rose-700 dark:text-rose-300 font-bold border-dashed';
              cardBorder = 'border-rose-300 dark:border-rose-800/80';
            } else if (ev.event === 'refuse') {
              badgeText = '[SAFETY REFUSAL]';
              BadgeIcon = AlertTriangle;
              badgeStyle =
                'border-amber-400 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/50 text-amber-700 dark:text-amber-300 font-bold';
              cardBorder = 'border-amber-300 dark:border-amber-800/80';
            } else if (ev.event === 'tool' && ev.allowed !== false) {
              badgeText = '[ALLOWED]';
              BadgeIcon = CheckCircle2;
              badgeStyle =
                'border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300';
            } else if (ev.event === 'boundary_warning') {
              badgeText = '[BOUNDARY WARNING]';
              BadgeIcon = AlertCircle;
              badgeStyle =
                'border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300';
            } else if (ev.event === 'error') {
              badgeText = '[ERROR]';
              BadgeIcon = XCircle;
              badgeStyle =
                'border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300';
            } else if (ev.event === 'run') {
              badgeText = '[COMPLETED]';
              BadgeIcon = Bot;
              badgeStyle =
                'border-sky-300 dark:border-sky-800 bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300';
            }

            return (
              <div
                key={`${ev.ts}-${index}`}
                data-testid="audit-event-card"
                className={cn(
                  'rounded-xl border p-3 bg-white dark:bg-zinc-800/50 shadow-sm transition hover:shadow',
                  cardBorder
                )}
              >
                {/* Event Card Header */}
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {/* Non-color status distinction badge */}
                    <span
                      data-testid="audit-status-badge"
                      className={cn(
                        'inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold border',
                        badgeStyle
                      )}
                    >
                      <BadgeIcon className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                      <span>{badgeText}</span>
                    </span>

                    {/* Agent badge */}
                    <span
                      data-testid="audit-agent-badge"
                      className="px-2 py-0.5 rounded-md text-xs font-mono font-medium bg-slate-100 dark:bg-zinc-700 text-slate-700 dark:text-zinc-300"
                    >
                      {ev.agent_id}
                    </span>
                  </div>

                  {/* Timestamp & Duration */}
                  <div className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-zinc-500 font-mono shrink-0">
                    {ev.duration_ms !== undefined && ev.duration_ms !== null && (
                      <span
                        data-testid="audit-duration-badge"
                        className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-zinc-700 text-slate-600 dark:text-zinc-300 font-medium"
                      >
                        {formatAuditDuration(ev.duration_ms)}
                      </span>
                    )}
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3 text-slate-400" />
                      {formatAuditTimestamp(ev.ts)}
                    </span>
                  </div>
                </div>

                {/* Event Details */}
                <div className="text-xs space-y-1 text-slate-700 dark:text-zinc-300">
                  {ev.tool && (
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-slate-500 dark:text-zinc-400">Tool:</span>
                      <code className="font-mono text-emerald-700 dark:text-emerald-400 font-semibold bg-emerald-50 dark:bg-emerald-950/30 px-1.5 py-0.5 rounded">
                        {ev.tool}
                      </code>
                    </div>
                  )}

                  {ev.reason && (
                    <div className="text-xs">
                      <span className="font-semibold text-slate-500 dark:text-zinc-400">Reason: </span>
                      <span className="font-mono text-slate-700 dark:text-zinc-300">{ev.reason}</span>
                    </div>
                  )}
                </div>

                {/* Collapsible raw metadata toggle */}
                <div className="mt-2.5 pt-2 border-t border-slate-100 dark:border-zinc-700/60 flex items-center justify-between text-xs">
                  <button
                    type="button"
                    onClick={() => toggleExpand(index)}
                    className="flex items-center gap-1 text-slate-500 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 transition cursor-pointer font-medium"
                  >
                    {isExpanded ? (
                      <>
                        <ChevronUp className="w-3.5 h-3.5" />
                        Hide Raw Details
                      </>
                    ) : (
                      <>
                        <ChevronDown className="w-3.5 h-3.5" />
                        Inspect Raw Details
                      </>
                    )}
                  </button>

                  {isExpanded && (
                    <button
                      type="button"
                      onClick={() => copyAuditEventsToClipboard([ev])}
                      className="text-slate-500 dark:text-zinc-400 hover:text-emerald-700 dark:hover:text-emerald-400 flex items-center gap-1 transition cursor-pointer"
                    >
                      <Copy className="w-3 h-3" />
                      Copy Event JSON
                    </button>
                  )}
                </div>

                {isExpanded && (
                  <pre
                    data-testid="audit-raw-json"
                    className="mt-2 p-2.5 rounded-lg bg-slate-900 dark:bg-black text-slate-100 text-xs font-mono overflow-x-auto"
                  >
                    {JSON.stringify(ev, null, 2)}
                  </pre>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="px-4 py-2.5 border-t border-slate-200 dark:border-zinc-800 bg-slate-50 dark:bg-zinc-900/90 text-center shrink-0">
          <p className="text-xs text-slate-500 dark:text-zinc-400">
            Carefold runtime audit logs are stored locally in your workspace with zero prompt retention.
          </p>
        </div>
      </div>
    </>
  );
}
