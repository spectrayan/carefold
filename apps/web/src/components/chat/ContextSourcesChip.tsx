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

import React, { useState, useRef, useEffect } from 'react';
import {
  Layers,
  FileText,
  Key,
  Globe,
  Database,
  AlertTriangle,
  ChevronDown,
  Lock
} from 'lucide-react';
import type { ContextSourceItem } from '@/lib/types';
import { cn } from '@/lib/utils';

export interface ContextSourcesChipProps {
  sources: ContextSourceItem[];
  isTainted?: boolean;
  hasPhi?: boolean;
  className?: string;
}

const SOURCE_ICON_MAP: Record<string, typeof FileText> = {
  thread: Database,
  attachments: FileText,
  records: FileText,
  vault: Key,
  connector: Globe,
  web: Globe
};

export function ContextSourcesChip({
  sources = [],
  isTainted = false,
  hasPhi = false,
  className
}: ContextSourcesChipProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close dropdown on click outside or escape key
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };

    document.addEventListener('mousedown', handleClickOutside);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  const count = sources.length;

  return (
    <div ref={containerRef} className={cn('relative inline-block text-left', className)}>
      <button
        type="button"
        data-testid="context-sources-chip-button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        title={
          isTainted
            ? 'Untrusted context sources active (monotone taint escalated)'
            : hasPhi
            ? 'Protected Health Information (PHI) loaded in active context'
            : 'Active context sources for current reasoning thread'
        }
        className={cn(
          'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-semibold border transition shadow-sm cursor-pointer select-none',
          isTainted
            ? 'bg-amber-50 dark:bg-amber-950/60 border-amber-300 dark:border-amber-800 text-amber-900 dark:text-amber-200 hover:bg-amber-100'
            : hasPhi
            ? 'bg-purple-50 dark:bg-purple-950/60 border-purple-300 dark:border-purple-800 text-purple-900 dark:text-purple-200 hover:bg-purple-100'
            : 'bg-white dark:bg-zinc-800 border-slate-300 dark:border-zinc-700 text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-750'
        )}
      >
        {isTainted ? (
          <AlertTriangle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400 shrink-0" />
        ) : hasPhi ? (
          <Lock className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400 shrink-0" />
        ) : (
          <Layers className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400 shrink-0" />
        )}

        <span>
          {count === 0 ? 'Context: Thread' : count === 1 ? sources[0].label : `${count} Sources`}
        </span>

        {isTainted && (
          <span
            data-testid="context-taint-badge"
            className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.2 rounded-full bg-amber-200 dark:bg-amber-900 text-amber-900 dark:text-amber-100"
          >
            Tainted
          </span>
        )}

        {hasPhi && !isTainted && (
          <span
            data-testid="context-phi-badge"
            className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.2 rounded-full bg-purple-200 dark:bg-purple-900 text-purple-900 dark:text-purple-100"
          >
            PHI
          </span>
        )}

        <ChevronDown className="w-3 h-3 text-slate-400 dark:text-zinc-500" />
      </button>

      {/* Expanded Popover */}
      {isOpen && (
        <div
          role="dialog"
          aria-label="Active context sources"
          data-testid="context-sources-popover"
          className="absolute left-0 mt-2 w-80 max-w-[90vw] rounded-2xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-xl p-3 z-50 space-y-2.5 transition-all text-xs"
        >
          <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-zinc-800">
            <span className="font-bold text-slate-900 dark:text-zinc-100">Active Context Sources</span>
            <span className="text-[11px] font-medium text-slate-500 dark:text-zinc-400">
              {sources.length} active
            </span>
          </div>

          {/* Monotone Taint Callout */}
          {isTainted && (
            <div
              data-testid="taint-warning-banner"
              className="p-2.5 rounded-xl bg-amber-50 dark:bg-amber-950/50 border border-amber-300 dark:border-amber-800 text-amber-900 dark:text-amber-200 space-y-1"
            >
              <div className="flex items-center gap-1.5 font-bold text-xs">
                <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
                <span>Monotone Taint Active (AU-19)</span>
              </div>
              <p className="text-[11px] leading-relaxed">
                Untrusted external data (e.g. web search, imported EHR text) was injected into this turn. Outbound external mutations strictly require human sign-off.
              </p>
            </div>
          )}

          {/* Sources List */}
          <div className="space-y-1.5 max-h-56 overflow-y-auto">
            {sources.length === 0 ? (
              <div className="p-2 rounded-lg bg-slate-50 dark:bg-zinc-800/60 text-slate-500 dark:text-zinc-400 italic">
                Local thread memory only (zero external documents).
              </div>
            ) : (
              sources.map((src) => {
                const Icon = SOURCE_ICON_MAP[src.type] || FileText;
                return (
                  <div
                    key={src.id}
                    data-testid="context-source-item"
                    className="p-2 rounded-xl border border-slate-200/70 dark:border-zinc-800 bg-slate-50/50 dark:bg-zinc-800/40 flex items-start gap-2"
                  >
                    <Icon className="w-4 h-4 text-emerald-700 dark:text-emerald-400 shrink-0 mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-1">
                        <span className="font-semibold text-slate-800 dark:text-zinc-200 truncate">
                          {src.label}
                        </span>
                        {src.has_phi && (
                          <span className="text-[10px] font-bold px-1.5 py-0.2 rounded bg-purple-100 dark:bg-purple-900/60 text-purple-800 dark:text-purple-300 shrink-0">
                            PHI
                          </span>
                        )}
                        {src.is_tainted && (
                          <span className="text-[10px] font-bold px-1.5 py-0.2 rounded bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-300 shrink-0">
                            Tainted
                          </span>
                        )}
                      </div>
                      {src.description && (
                        <p className="text-[11px] text-slate-500 dark:text-zinc-400 truncate">
                          {src.description}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <div className="pt-2 border-t border-slate-100 dark:border-zinc-800 text-[11px] text-slate-400 dark:text-zinc-500">
            Carefold local-first security ensures data sources are governed by policy gates and sandboxed tools.
          </div>
        </div>
      )}
    </div>
  );
}
