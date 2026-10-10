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

export type ToolTraceStatus = 'running' | 'completed' | 'denied' | 'failed';

export interface ToolTraceItem {
  id?: string;
  tool: string;
  status: ToolTraceStatus;
  input?: Record<string, any>;
  params?: Record<string, any>;
  output?: any;
  result?: any;
  error?: string;
  duration_ms?: number;
  allowed?: boolean;
  reason?: string;
  startTime?: number;
}

export interface ToolTraceCardProps {
  trace: ToolTraceItem;
  defaultExpanded?: boolean;
}

export function sanitizeToolParams(_tool: string, input?: Record<string, any>): Record<string, any> {
  if (!input || typeof input !== 'object') return {};
  const sanitized: Record<string, any> = {};

  for (const [key, value] of Object.entries(input)) {
    if (['path', 'file_path', 'doc', 'skill_id', 'title', 'format'].includes(key)) {
      sanitized[key] = value;
    } else if (key === 'content' && typeof value === 'string') {
      sanitized[key] = value.length > 50 ? `${value.slice(0, 47)}... [${value.length} chars]` : value;
    } else if (typeof value === 'string' && value.length > 80) {
      sanitized[key] = `${value.slice(0, 77)}...`;
    } else {
      sanitized[key] = value;
    }
  }
  return sanitized;
}

export function ToolTraceCard({ trace, defaultExpanded = false }: ToolTraceCardProps) {
  const [expanded, setExpanded] = useState<boolean>(defaultExpanded || trace.status === 'running');

  const statusConfig: Record<string, { badge: string; label: string; dot: string }> = {
    running: {
      badge: 'bg-sky-100 text-sky-800 border-sky-300 dark:bg-sky-950/60 dark:text-sky-300 dark:border-sky-800',
      label: 'Running',
      dot: 'bg-sky-500 animate-pulse'
    },
    completed: {
      badge: 'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800',
      label: 'Completed',
      dot: 'bg-emerald-500'
    },
    denied: {
      badge: 'bg-rose-100 text-rose-800 border-rose-300 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800',
      label: 'Denied',
      dot: 'bg-rose-500'
    },
    failed: {
      badge: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800',
      label: 'Failed',
      dot: 'bg-amber-500'
    }
  };

  const currentConfig = statusConfig[trace.status] || {
    badge: 'bg-slate-100 text-slate-800 border-slate-300 dark:bg-zinc-800 dark:text-zinc-300 dark:border-zinc-700',
    label: trace.status,
    dot: 'bg-slate-400'
  };

  const inputParams = trace.input || trace.params;
  const sanitizedInput = sanitizeToolParams(trace.tool, inputParams);
  const outputData = trace.output !== undefined ? trace.output : trace.result;

  return (
    <div
      data-testid="tool-trace-card"
      data-tool={trace.tool}
      data-status={trace.status}
      className="my-2 rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800/80 shadow-sm text-xs overflow-hidden transition-all duration-200 ease-in-out"
    >
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-slate-100 dark:hover:bg-zinc-700/50 transition-colors cursor-pointer select-none"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className={`inline-block w-2 h-2 rounded-full ${currentConfig.dot}`} />
          <span className="font-mono font-medium text-slate-800 dark:text-zinc-200 truncate">
            {trace.tool}
          </span>
          <span
            data-testid="tool-trace-status-badge"
            className={`px-1.5 py-0.5 rounded text-xs font-semibold border ${currentConfig.badge}`}
          >
            {currentConfig.label}
          </span>
          {typeof trace.duration_ms === 'number' && (
            <span data-testid="tool-trace-duration" className="text-slate-600 dark:text-zinc-400 font-mono text-xs">
              {trace.duration_ms} ms
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 text-slate-600 dark:text-zinc-400">
          <span className="text-xs select-none">{expanded ? 'Hide' : 'Details'}</span>
          <svg
            className={`w-3.5 h-3.5 transform transition-transform duration-150 ${expanded ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {expanded && (
        <div data-testid="tool-trace-details" className="p-3 border-t border-slate-200 dark:border-zinc-700 bg-white/80 dark:bg-zinc-900/80 space-y-2 transition-all duration-200 ease-in-out">
          {trace.reason && (
            <div data-testid="tool-trace-reason" className="p-2 rounded bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900 text-rose-700 dark:text-rose-300">
              <span className="font-semibold">Reason: </span>
              {trace.reason}
            </div>
          )}

          {trace.error && !trace.reason && (
            <div data-testid="tool-trace-error" className="p-2 rounded bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900 text-amber-700 dark:text-amber-300">
              <span className="font-semibold">Error: </span>
              {trace.error}
            </div>
          )}

          {inputParams && Object.keys(inputParams).length > 0 && (
            <div>
              <div className="font-semibold text-slate-600 dark:text-zinc-400 text-xs mb-1">Parameters:</div>
              <pre data-testid="tool-trace-params" className="p-2 rounded bg-slate-100 dark:bg-zinc-900 border border-slate-200 dark:border-zinc-700 font-mono text-xs max-h-40 overflow-auto text-slate-800 dark:text-zinc-200">
                {JSON.stringify(sanitizedInput, null, 2)}
              </pre>
            </div>
          )}

          {outputData !== undefined && outputData !== null && (
            <div>
              <div className="font-semibold text-slate-600 dark:text-zinc-400 text-xs mb-1">Output Preview:</div>
              <pre data-testid="tool-trace-output" className="p-2 rounded bg-slate-100 dark:bg-zinc-900 border border-slate-200 dark:border-zinc-700 font-mono text-xs max-h-40 overflow-auto text-slate-800 dark:text-zinc-200">
                {typeof outputData === 'object' ? JSON.stringify(outputData, null, 2) : String(outputData)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
