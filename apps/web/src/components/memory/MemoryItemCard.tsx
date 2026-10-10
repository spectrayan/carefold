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
  Calendar,
  Clock,
  Edit2,
  Trash2,
  Bot,
  Hash,
  Sparkles,
  BookOpen,
  Layers,
  Activity,
} from 'lucide-react';
import type { MemoryRecord, MemoryTier } from '@/types/api';
import { cn } from '@/lib/utils';

export interface MemoryItemCardProps {
  record: MemoryRecord;
  onEdit: (record: MemoryRecord) => void;
  onDelete: (record: MemoryRecord) => void;
}

export function formatFactText(value: any): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'object') {
    if (value.fact && typeof value.fact === 'string') return value.fact;
    if (value.text && typeof value.text === 'string') return value.text;
    if (value.content && typeof value.content === 'string') return value.content;
    if (value.summary && typeof value.summary === 'string') return value.summary;
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

export function getTierBadgeConfig(tier: string | MemoryTier) {
  const cleanTier = String(tier || 'episodic').toLowerCase();
  switch (cleanTier) {
    case 'semantic':
      return {
        label: 'Semantic',
        code: '[SEMANTIC]',
        icon: BookOpen,
        classes:
          'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800',
      };
    case 'working':
      return {
        label: 'Working',
        code: '[WORKING]',
        icon: Activity,
        classes:
          'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800',
      };
    case 'procedural':
      return {
        label: 'Procedural',
        code: '[PROCEDURAL]',
        icon: Layers,
        classes:
          'bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-400 border-purple-200 dark:border-purple-800',
      };
    case 'episodic':
    default:
      return {
        label: 'Episodic',
        code: '[EPISODIC]',
        icon: Clock,
        classes:
          'bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-800',
      };
  }
}

export function MemoryItemCard({ record, onEdit, onDelete }: MemoryItemCardProps) {
  const tierConfig = getTierBadgeConfig(record.tier);
  const TierIcon = tierConfig.icon;
  const factText = formatFactText(record.value);

  const formattedDate = record.created_at
    ? new Date(record.created_at).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : null;

  const agentId = record.metadata?.agent_id || record.metadata?.source_agent;
  const sessionId = record.metadata?.session_id || record.metadata?.thread_id;
  const source = record.metadata?.source;

  return (
    <div
      data-testid={`memory-card-${record.key}`}
      className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800/80 shadow-sm hover:border-slate-300 dark:hover:border-zinc-700 transition flex flex-col gap-3"
    >
      {/* Header: Tier Badge, Key, Salience */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'px-2 py-0.5 rounded-md text-xs font-bold border flex items-center gap-1',
              tierConfig.classes
            )}
            title={`Cognitive tier: ${tierConfig.label}`}
          >
            <TierIcon className="w-3 h-3" />
            <span>{tierConfig.code}</span>
          </span>

          <span
            className="text-xs font-mono font-medium text-slate-500 dark:text-zinc-400 truncate max-w-xs"
            title={record.key}
          >
            {record.key}
          </span>
        </div>

        {/* Salience or namespace */}
        <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-zinc-500">
          {record.salience !== undefined && record.salience !== null && (
            <span
              className="px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-300 font-mono text-xs flex items-center gap-0.5"
              title="Salience retrieval weight"
            >
              <Sparkles className="w-2.5 h-2.5 text-amber-500" />
              salience: {record.salience.toFixed(1)}
            </span>
          )}
          {record.namespace && record.namespace !== 'default' && (
            <span
              className="px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 text-xs"
              title={`Namespace: ${record.namespace}`}
            >
              ns: {record.namespace}
            </span>
          )}
        </div>
      </div>

      {/* Main Fact Text */}
      <div className="text-xs text-slate-800 dark:text-zinc-200 leading-relaxed font-normal whitespace-pre-wrap break-words">
        {factText || <span className="italic text-slate-400">(Empty payload)</span>}
      </div>

      {/* Footer: Provenance metadata & Actions */}
      <div className="pt-2 border-t border-slate-100 dark:border-zinc-800/60 flex items-center justify-between gap-2 flex-wrap text-xs">
        {/* Provenance Tags */}
        <div className="flex items-center gap-3 text-slate-500 dark:text-zinc-400 flex-wrap">
          {agentId && (
            <span className="flex items-center gap-1">
              <Bot className="w-3 h-3 text-slate-400 dark:text-zinc-500" />
              <span className="font-medium text-slate-700 dark:text-zinc-300">{agentId}</span>
            </span>
          )}

          {sessionId && (
            <span
              className="flex items-center gap-1 font-mono text-xs text-slate-400 dark:text-zinc-500"
              title={`Session Thread: ${sessionId}`}
            >
              <Hash className="w-2.5 h-2.5" />
              {String(sessionId).slice(0, 8)}…
            </span>
          )}

          {source && !agentId && (
            <span className="text-slate-400 dark:text-zinc-500">Source: {source}</span>
          )}

          {formattedDate && (
            <span className="flex items-center gap-1 text-xs text-slate-400 dark:text-zinc-500">
              <Calendar className="w-2.5 h-2.5" />
              {formattedDate}
            </span>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            data-testid={`edit-memory-btn-${record.key}`}
            onClick={() => onEdit(record)}
            aria-label={`Edit memory ${record.key}`}
            className="px-2.5 py-1 rounded-lg border border-slate-200 dark:border-zinc-700 text-slate-600 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 text-xs font-semibold transition flex items-center gap-1 cursor-pointer"
          >
            <Edit2 className="w-3 h-3 text-slate-500 dark:text-zinc-400" />
            <span>Edit</span>
          </button>

          <button
            type="button"
            data-testid={`delete-memory-btn-${record.key}`}
            onClick={() => onDelete(record)}
            aria-label={`Forget memory ${record.key}`}
            className="px-2.5 py-1 rounded-lg border border-rose-200 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-xs font-semibold transition flex items-center gap-1 cursor-pointer"
          >
            <Trash2 className="w-3 h-3 text-rose-500" />
            <span>Forget</span>
          </button>
        </div>
      </div>
    </div>
  );
}
