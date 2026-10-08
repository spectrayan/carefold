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
import {
  Brain,
  Search,
  X,
  Trash2,
  RefreshCw,
  ShieldCheck,
  PauseCircle,
  PlayCircle,
  AlertCircle,
  Clock,
  BookOpen,
  Activity,
  Layers,
  Database,
  Check,
} from 'lucide-react';
import type { MemoryRecord, MemoryTier, MemoryStatus } from '@/types/api';
import {
  fetchMemories,
  fetchMemoryStatus,
  updateMemory,
  deleteMemory,
  clearAllMemories,
  isSessionMemoryPaused,
  setSessionMemoryPaused,
  MEMORY_PAUSE_EVENT,
} from '@/lib/memory';
import { MemoryItemCard, formatFactText } from './MemoryItemCard';
import { MemoryEditModal } from './MemoryEditModal';
import { MemoryForgetModal } from './MemoryForgetModal';
import { cn } from '@/lib/utils';

export function MemoryManagementPanel() {
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  // Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTier, setSelectedTier] = useState<MemoryTier | 'all'>('all');

  // Session pause state
  const [isPaused, setIsPaused] = useState<boolean>(() => isSessionMemoryPaused());

  // Modal states
  const [editingRecord, setEditingRecord] = useState<MemoryRecord | null>(null);
  const [forgettingRecord, setForgettingRecord] = useState<MemoryRecord | null>(null);
  const [isBulkForgetting, setIsBulkForgetting] = useState(false);
  const [isActionPending, setIsActionPending] = useState(false);

  // Listen to session pause events
  useEffect(() => {
    const handlePauseChange = (e: Event) => {
      const custom = e as CustomEvent<{ paused: boolean }>;
      if (custom.detail !== undefined) {
        setIsPaused(custom.detail.paused);
      }
    };
    window.addEventListener(MEMORY_PAUSE_EVENT, handlePauseChange);
    return () => window.removeEventListener(MEMORY_PAUSE_EVENT, handlePauseChange);
  }, []);

  const handleTogglePause = () => {
    const next = !isPaused;
    setIsPaused(next);
    setSessionMemoryPaused(next);
    setFeedback(
      next
        ? 'Memory collection paused for this session.'
        : 'Memory collection resumed.'
    );
    setTimeout(() => setFeedback(null), 3000);
  };

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [fetchedMemories, fetchedStatus] = await Promise.all([
        fetchMemories({ limit: 100 }),
        fetchMemoryStatus().catch(() => null),
      ]);
      setMemories(fetchedMemories);
      if (fetchedStatus) {
        setStatus(fetchedStatus);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load memories from Carefold backend.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Client-side filtering
  const filteredMemories = useMemo(() => {
    return memories.filter((item) => {
      // Tier match
      if (selectedTier !== 'all') {
        const itemTier = String(item.tier || '').toLowerCase();
        if (itemTier !== selectedTier) return false;
      }
      // Query match
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const keyMatch = item.key.toLowerCase().includes(q);
        const textMatch = formatFactText(item.value).toLowerCase().includes(q);
        const agentMatch = String(
          item.metadata?.agent_id || item.metadata?.source_agent || ''
        )
          .toLowerCase()
          .includes(q);
        const nsMatch = (item.namespace || '').toLowerCase().includes(q);
        if (!keyMatch && !textMatch && !agentMatch && !nsMatch) {
          return false;
        }
      }
      return true;
    });
  }, [memories, selectedTier, searchQuery]);

  // Handlers
  const handleSaveEdit = async (updated: {
    key: string;
    value: any;
    tier: MemoryTier;
    metadata?: any;
  }) => {
    setIsActionPending(true);
    try {
      const saved = await updateMemory(updated.key, {
        value: updated.value,
        tier: updated.tier,
        metadata: updated.metadata,
      });
      setMemories((prev) =>
        prev.map((item) => (item.key === saved.key ? saved : item))
      );
      setEditingRecord(null);
      setFeedback(`Memory "${updated.key}" updated successfully.`);
      setTimeout(() => setFeedback(null), 3000);
    } catch (err: any) {
      throw err;
    } finally {
      setIsActionPending(false);
    }
  };

  const handleConfirmForgetSingle = async () => {
    if (!forgettingRecord) return;
    setIsActionPending(true);
    try {
      await deleteMemory(forgettingRecord.key, forgettingRecord.namespace || 'default');
      setMemories((prev) => prev.filter((item) => item.key !== forgettingRecord.key));
      setFeedback(`Forgot memory "${forgettingRecord.key}".`);
      setForgettingRecord(null);
      setTimeout(() => setFeedback(null), 3000);
    } catch (err: any) {
      setError(err?.message || 'Failed to delete memory.');
    } finally {
      setIsActionPending(false);
    }
  };

  const handleConfirmForgetAll = async () => {
    setIsActionPending(true);
    try {
      await clearAllMemories('default');
      setMemories([]);
      setIsBulkForgetting(false);
      setFeedback('All memories have been permanently cleared.');
      setTimeout(() => setFeedback(null), 3000);
    } catch (err: any) {
      setError(err?.message || 'Failed to clear all memories.');
    } finally {
      setIsActionPending(false);
    }
  };

  const tierCounts = useMemo(() => {
    const counts = { all: memories.length, episodic: 0, semantic: 0, working: 0, procedural: 0 };
    for (const m of memories) {
      const t = String(m.tier || '').toLowerCase() as MemoryTier;
      if (t in counts) {
        counts[t]++;
      }
    }
    return counts;
  }, [memories]);

  return (
    <div className="flex flex-col gap-5 text-slate-800 dark:text-zinc-200">
      {/* Top Banner: Status & Global Actions */}
      <div className="flex items-center justify-between gap-3 p-3.5 rounded-2xl bg-slate-50 dark:bg-zinc-800/60 border border-slate-200 dark:border-zinc-700/60 flex-wrap">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-900/60 text-emerald-600 dark:text-emerald-400">
            <Database className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-slate-900 dark:text-zinc-100">
                Cognitive Memory Storage
              </span>
              <span
                data-testid="memory-status-badge"
                className={cn(
                  'px-2 py-0.5 rounded-full text-[10px] font-bold border',
                  status?.healthy !== false
                    ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800'
                    : 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800'
                )}
              >
                {status?.backend === 'spector'
                  ? 'Spector Synapse'
                  : 'SQLite Local FTS5'}{' '}
                • {status?.healthy !== false ? 'Healthy' : 'Degraded'}
              </span>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-zinc-400">
              {memories.length} item{memories.length === 1 ? '' : 's'} remembered across clinical consultations
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="refresh-memories-btn"
            onClick={loadData}
            disabled={isLoading}
            aria-label="Refresh memories"
            className="p-1.5 rounded-xl border border-slate-200 dark:border-zinc-700 text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800 transition cursor-pointer disabled:opacity-50"
          >
            <RefreshCw className={cn('w-3.5 h-3.5', isLoading && 'animate-spin')} />
          </button>

          <button
            type="button"
            data-testid="forget-all-memories-btn"
            disabled={memories.length === 0 || isActionPending}
            onClick={() => setIsBulkForgetting(true)}
            className="px-3 py-1.5 rounded-xl border border-rose-200 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-xs font-semibold transition flex items-center gap-1.5 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Forget All Memories</span>
          </button>
        </div>
      </div>

      {/* Session Pause Control Card */}
      <div className="p-3.5 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 flex items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              'p-2 rounded-xl border mt-0.5',
              isPaused
                ? 'bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-800'
                : 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800'
            )}
          >
            {isPaused ? <PauseCircle className="w-4 h-4" /> : <PlayCircle className="w-4 h-4" />}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-slate-900 dark:text-zinc-100">
                Pause memory for this session
              </span>
              {isPaused && (
                <span className="px-1.5 py-0.2 rounded-md bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 text-[10px] font-bold">
                  ACTIVE
                </span>
              )}
            </div>
            <p className="text-[11px] text-slate-500 dark:text-zinc-400">
              When enabled, new turns and clinical facts will not be committed to long-term memory for active consultations.
            </p>
          </div>
        </div>

        <button
          type="button"
          data-testid="toggle-pause-memory"
          role="switch"
          aria-checked={isPaused}
          onClick={handleTogglePause}
          className={cn(
            'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none',
            isPaused ? 'bg-amber-500' : 'bg-slate-200 dark:bg-zinc-700'
          )}
        >
          <span
            className={cn(
              'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out',
              isPaused ? 'translate-x-5' : 'translate-x-0'
            )}
          />
        </button>
      </div>

      {/* Feedback Banner */}
      {feedback && (
        <div
          role="status"
          data-testid="memory-feedback-banner"
          className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-xs text-emerald-800 dark:text-emerald-200 flex items-center gap-2 animate-in fade-in"
        >
          <Check className="w-4 h-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
          <span>{feedback}</span>
        </div>
      )}

      {/* Error Alert */}
      {error && (
        <div
          role="alert"
          className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs text-rose-800 dark:text-rose-200 flex items-center justify-between gap-2"
        >
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-zinc-200"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Search Bar & Tier Tabs */}
      <div className="space-y-3">
        {/* Search Input */}
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-zinc-500" />
          <input
            type="text"
            data-testid="memory-search-input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search remembered facts, keys, or agents..."
            className="w-full pl-10 pr-10 py-2.5 rounded-xl bg-white dark:bg-zinc-800/80 border border-slate-200 dark:border-zinc-700 text-xs text-slate-900 dark:text-zinc-100 placeholder-slate-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
          />
          {searchQuery && (
            <button
              type="button"
              data-testid="clear-memory-search-btn"
              onClick={() => setSearchQuery('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600 dark:hover:text-zinc-200"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Cognitive Tier Selector Pills */}
        <div
          className="flex items-center gap-1.5 overflow-x-auto pb-1"
          role="tablist"
          aria-label="Filter memories by cognitive tier"
        >
          <button
            type="button"
            data-testid="filter-tier-all"
            role="tab"
            aria-selected={selectedTier === 'all'}
            onClick={() => setSelectedTier('all')}
            className={cn(
              'px-3 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-1.5 whitespace-nowrap cursor-pointer',
              selectedTier === 'all'
                ? 'bg-slate-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shadow-sm'
                : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700'
            )}
          >
            <span>All Tiers</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/20 dark:bg-black/10">
              {tierCounts.all}
            </span>
          </button>

          <button
            type="button"
            data-testid="filter-tier-episodic"
            role="tab"
            aria-selected={selectedTier === 'episodic'}
            onClick={() => setSelectedTier('episodic')}
            className={cn(
              'px-3 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-1.5 whitespace-nowrap cursor-pointer',
              selectedTier === 'episodic'
                ? 'bg-sky-600 text-white shadow-sm'
                : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700'
            )}
          >
            <Clock className="w-3.5 h-3.5" />
            <span>[EPISODIC]</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/20 dark:bg-black/10">
              {tierCounts.episodic}
            </span>
          </button>

          <button
            type="button"
            data-testid="filter-tier-semantic"
            role="tab"
            aria-selected={selectedTier === 'semantic'}
            onClick={() => setSelectedTier('semantic')}
            className={cn(
              'px-3 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-1.5 whitespace-nowrap cursor-pointer',
              selectedTier === 'semantic'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700'
            )}
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>[SEMANTIC]</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/20 dark:bg-black/10">
              {tierCounts.semantic}
            </span>
          </button>

          <button
            type="button"
            data-testid="filter-tier-working"
            role="tab"
            aria-selected={selectedTier === 'working'}
            onClick={() => setSelectedTier('working')}
            className={cn(
              'px-3 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-1.5 whitespace-nowrap cursor-pointer',
              selectedTier === 'working'
                ? 'bg-amber-600 text-white shadow-sm'
                : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700'
            )}
          >
            <Activity className="w-3.5 h-3.5" />
            <span>[WORKING]</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/20 dark:bg-black/10">
              {tierCounts.working}
            </span>
          </button>

          <button
            type="button"
            data-testid="filter-tier-procedural"
            role="tab"
            aria-selected={selectedTier === 'procedural'}
            onClick={() => setSelectedTier('procedural')}
            className={cn(
              'px-3 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-1.5 whitespace-nowrap cursor-pointer',
              selectedTier === 'procedural'
                ? 'bg-purple-600 text-white shadow-sm'
                : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700'
            )}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>[PROCEDURAL]</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/20 dark:bg-black/10">
              {tierCounts.procedural}
            </span>
          </button>
        </div>
      </div>

      {/* Memory Cards List */}
      <div className="space-y-3 min-h-[160px]">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400 dark:text-zinc-500">
            <RefreshCw className="w-6 h-6 animate-spin mb-2 text-emerald-500" />
            <p className="text-xs">Loading cognitive memories...</p>
          </div>
        ) : filteredMemories.length === 0 ? (
          <div className="text-center py-12 px-4 rounded-2xl border border-dashed border-slate-200 dark:border-zinc-800 bg-slate-50/50 dark:bg-zinc-900/40">
            <Brain className="w-8 h-8 mx-auto text-slate-300 dark:text-zinc-600 mb-2" />
            <p className="text-xs font-semibold text-slate-700 dark:text-zinc-300">
              {searchQuery.trim()
                ? `No memories matched "${searchQuery}". Try clearing your filter.`
                : "Carefold hasn't saved any long-term memories yet. Important facts from your specialist consultations will appear here."}
            </p>
            {searchQuery.trim() && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="mt-3 px-3 py-1 rounded-lg bg-slate-200 dark:bg-zinc-700 text-slate-700 dark:text-zinc-200 text-xs font-semibold hover:bg-slate-300 transition"
              >
                Clear Search
              </button>
            )}
          </div>
        ) : (
          filteredMemories.map((record) => (
            <MemoryItemCard
              key={`${record.namespace}:${record.key}`}
              record={record}
              onEdit={setEditingRecord}
              onDelete={setForgettingRecord}
            />
          ))
        )}
      </div>

      {/* Local-First Privacy Notice Banner */}
      <div className="p-3.5 rounded-2xl bg-slate-50 dark:bg-zinc-800/40 border border-slate-200 dark:border-zinc-800 flex items-start gap-3 text-slate-600 dark:text-zinc-400 text-xs leading-relaxed">
        <ShieldCheck className="w-5 h-5 shrink-0 text-emerald-600 dark:text-emerald-400 mt-0.5" />
        <div>
          <span className="font-bold text-slate-800 dark:text-zinc-200 block mb-0.5">
            Local-First Privacy Guarantee
          </span>
          All episodic and semantic memories reside strictly within your local database (127.0.0.1) in your Carefold workspace. Zero telemetry or memory content is synced to cloud servers.
        </div>
      </div>

      {/* Modals */}
      <MemoryEditModal
        isOpen={Boolean(editingRecord)}
        record={editingRecord}
        onClose={() => setEditingRecord(null)}
        onSave={handleSaveEdit}
        isSaving={isActionPending}
      />

      <MemoryForgetModal
        isOpen={Boolean(forgettingRecord) || isBulkForgetting}
        isBulk={isBulkForgetting}
        memoryKey={forgettingRecord?.key}
        onClose={() => {
          setForgettingRecord(null);
          setIsBulkForgetting(false);
        }}
        onConfirm={isBulkForgetting ? handleConfirmForgetAll : handleConfirmForgetSingle}
        isDeleting={isActionPending}
      />
    </div>
  );
}
