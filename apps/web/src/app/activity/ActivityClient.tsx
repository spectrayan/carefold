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

import React, { useState, useMemo, useCallback } from 'react';
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

interface ActivityClientProps {
  initialEvents: AuditEvent[];
}

export function ActivityClient({ initialEvents }: ActivityClientProps) {
  const [events, setEvents] = useState<AuditEvent[]>(initialEvents);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [agentFilter, setAgentFilter] = useState<string>('all');
  const [eventFilter, setEventFilter] = useState<string>('all');
  const [onlyBlocked, setOnlyBlocked] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // UI state
  const [copied, setCopied] = useState(false);
  const [expandedIndices, setExpandedIndices] = useState<Set<number>>(new Set());

  // Reload events from API
  const handleRefresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAuditEvents({ limit: 100 });
      setEvents(response.events || []);
    } catch (err: any) {
      setError(err?.message || 'Failed to refresh activity events');
    } finally {
      setLoading(false);
    }
  }, []);

  // Discovered agent list
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
      if (agentFilter !== 'all' && ev.agent_id !== agentFilter) {
        return false;
      }
      if (eventFilter !== 'all' && ev.event !== eventFilter) {
        return false;
      }
      if (onlyBlocked) {
        const isBlocked = ev.allowed === false || ev.event === 'refuse';
        if (!isBlocked) return false;
      }
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

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-zinc-100 tracking-tight">
              Activity & Safety Log
            </h1>
            <span
              data-testid="audit-count-badge"
              className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-200 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300"
            >
              {filteredEvents.length} {filteredEvents.length === 1 ? 'event' : 'events'}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-zinc-400">
            Inspect runtime agent operations, tool calls, and clinical guardrail decisions in your local workspace.
          </p>
        </div>

        {/* Badges and Actions */}
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <div
            data-testid="redacted-mode-badge"
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300 text-xs font-medium shadow-sm"
            title="Prompts and completion bodies are never recorded or displayed"
          >
            <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
            <span>Redacted Mode (Zero Prompt Retention)</span>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              data-testid="refresh-audit-btn"
              onClick={handleRefresh}
              disabled={loading}
              className="p-2 rounded-xl border border-slate-200 dark:border-zinc-700 hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-600 dark:text-zinc-400 transition cursor-pointer disabled:opacity-50 shadow-sm"
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
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-200 dark:border-zinc-700 hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-700 dark:text-zinc-300 text-xs font-medium transition cursor-pointer disabled:opacity-50 shadow-sm"
              title={copied ? 'Copied to clipboard!' : 'Copy events as JSON'}
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span>Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy JSON</span>
                </>
              )}
            </button>

            <button
              type="button"
              data-testid="export-audit-btn"
              onClick={handleExport}
              disabled={filteredEvents.length === 0}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium transition cursor-pointer disabled:opacity-50 shadow-sm"
              title="Download events as JSON"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Export JSON</span>
            </button>
          </div>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="p-4 rounded-2xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 shadow-sm space-y-3">
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Search input */}
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 dark:text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              data-testid="audit-search-input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search tools, reasons, agents, event types..."
              className="w-full pl-9 pr-4 py-2 text-xs sm:text-sm rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder-slate-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Agent filter dropdown */}
            <select
              data-testid="audit-agent-filter"
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              className="px-3 py-2 rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
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
              className="px-3 py-2 rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
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
              className="flex items-center gap-2 cursor-pointer px-3 py-2 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800/80 select-none text-xs sm:text-sm font-medium"
              title="Filter exclusively to blocked tool executions and safety refusals"
            >
              <input
                type="checkbox"
                data-testid="audit-blocked-toggle"
                checked={onlyBlocked}
                onChange={(e) => setOnlyBlocked(e.target.checked)}
                className="w-4 h-4 rounded text-rose-600 focus:ring-rose-500 border-slate-300 dark:border-zinc-600 cursor-pointer"
              />
              <span className="text-slate-800 dark:text-zinc-200">
                Only Blocked & Refused
              </span>
            </label>
          </div>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-4 rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 text-sm">
          <div className="font-semibold mb-1 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400" />
            Failed to load activity logs
          </div>
          <p>{error}</p>
        </div>
      )}

      {/* Empty state */}
      {filteredEvents.length === 0 && !loading && (
        <div
          data-testid="audit-empty-state"
          className="text-center py-16 px-4 space-y-3 border border-dashed border-slate-200 dark:border-zinc-800 rounded-2xl bg-white dark:bg-zinc-900/40"
        >
          <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-zinc-800 flex items-center justify-center mx-auto text-slate-400 dark:text-zinc-500">
            <Activity className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-slate-800 dark:text-zinc-200">
            No activity events found
          </h3>
          <p className="text-sm text-slate-500 dark:text-zinc-400 max-w-md mx-auto">
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
              className="mt-3 text-sm font-medium text-emerald-600 dark:text-emerald-400 hover:underline cursor-pointer"
            >
              Reset all filters
            </button>
          )}
        </div>
      )}

      {/* Events Grid */}
      <div className="space-y-3" data-testid="audit-event-list">
        {filteredEvents.map((ev, index) => {
          const isExpanded = expandedIndices.has(index);

          // NON-COLOR DISTINCTION INVARIANT
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
                'rounded-2xl border p-4 bg-white dark:bg-zinc-900 shadow-sm transition hover:shadow-md',
                cardBorder
              )}
            >
              {/* Card Header */}
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    data-testid="audit-status-badge"
                    className={cn(
                      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold border',
                      badgeStyle
                    )}
                  >
                    <BadgeIcon className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                    <span>{badgeText}</span>
                  </span>

                  <span
                    data-testid="audit-agent-badge"
                    className="px-2.5 py-1 rounded-md text-xs font-mono font-medium bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300"
                  >
                    {ev.agent_id}
                  </span>
                </div>

                <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-zinc-500 font-mono">
                  {ev.duration_ms !== undefined && ev.duration_ms !== null && (
                    <span
                      data-testid="audit-duration-badge"
                      className="px-2 py-0.5 rounded bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-300 font-medium"
                    >
                      {formatAuditDuration(ev.duration_ms)}
                    </span>
                  )}
                  <span className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5 text-slate-400" />
                    {formatAuditTimestamp(ev.ts)}
                  </span>
                </div>
              </div>

              {/* Event Summary Details */}
              <div className="text-sm space-y-1.5 text-slate-700 dark:text-zinc-300">
                {ev.tool && (
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-500 dark:text-zinc-400 text-xs">
                      Tool:
                    </span>
                    <code className="font-mono text-emerald-700 dark:text-emerald-400 font-semibold bg-emerald-50 dark:bg-emerald-950/30 px-2 py-0.5 rounded text-xs">
                      {ev.tool}
                    </code>
                  </div>
                )}

                {ev.reason && (
                  <div className="text-xs">
                    <span className="font-semibold text-slate-500 dark:text-zinc-400">
                      Reason:{' '}
                    </span>
                    <span className="font-mono text-slate-700 dark:text-zinc-300">
                      {ev.reason}
                    </span>
                  </div>
                )}
              </div>

              {/* Collapsible raw metadata toggle */}
              <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-zinc-800 flex items-center justify-between text-xs">
                <button
                  type="button"
                  onClick={() => toggleExpand(index)}
                  className="flex items-center gap-1.5 text-slate-500 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 transition cursor-pointer font-medium"
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
                    className="text-slate-500 dark:text-zinc-400 hover:text-emerald-600 dark:hover:text-emerald-400 flex items-center gap-1.5 transition cursor-pointer"
                  >
                    <Copy className="w-3.5 h-3.5" />
                    Copy Event JSON
                  </button>
                )}
              </div>

              {isExpanded && (
                <pre
                  data-testid="audit-raw-json"
                  className="mt-3 p-3 rounded-xl bg-slate-900 dark:bg-black text-slate-100 text-xs font-mono overflow-x-auto"
                >
                  {JSON.stringify(ev, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
