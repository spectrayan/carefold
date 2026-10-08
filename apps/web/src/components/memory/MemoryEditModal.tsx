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

import React, { useState, useEffect, useRef } from 'react';
import { Edit3, Save, X } from 'lucide-react';
import type { MemoryRecord, MemoryTier } from '@/types/api';

export interface MemoryEditModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (updatedRecord: { key: string; value: any; tier: MemoryTier; metadata?: any }) => Promise<void> | void;
  record: MemoryRecord | null;
  isSaving?: boolean;
}

export function MemoryEditModal({
  isOpen,
  onClose,
  onSave,
  record,
  isSaving = false,
}: MemoryEditModalProps) {
  const [valueText, setValueText] = useState('');
  const [selectedTier, setSelectedTier] = useState<MemoryTier>('episodic');
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (record) {
      const initialVal =
        typeof record.value === 'string'
          ? record.value
          : typeof record.value === 'object' && record.value !== null
            ? (record.value.fact || record.value.text || record.value.content || JSON.stringify(record.value, null, 2))
            : String(record.value || '');
      setValueText(initialVal);
      setSelectedTier((record.tier as MemoryTier) || 'episodic');
      setError(null);
    }
  }, [record, isOpen]);

  useEffect(() => {
    if (isOpen) {
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Escape' && !isSaving) {
          onClose();
        }
      };
      window.addEventListener('keydown', handleKeyDown);
      setTimeout(() => textareaRef.current?.focus(), 50);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, isSaving, onClose]);

  if (!isOpen || !record) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valueText.trim()) {
      setError('Memory content cannot be empty.');
      return;
    }

    try {
      setError(null);
      await onSave({
        key: record.key,
        value: valueText.trim(),
        tier: selectedTier,
        metadata: {
          ...(record.metadata || {}),
          edited_at: new Date().toISOString(),
          edited_by: 'patient',
        },
      });
    } catch (err: any) {
      setError(err?.message || 'Failed to save memory edits.');
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="edit-memory-title"
    >
      <div
        className="w-full max-w-lg bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl shadow-2xl p-6 overflow-hidden animate-in zoom-in-95"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between pb-4 border-b border-slate-100 dark:border-zinc-800">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-900/60 text-emerald-600 dark:text-emerald-400">
              <Edit3 className="w-5 h-5" />
            </div>
            <div>
              <h3 id="edit-memory-title" className="text-base font-bold text-slate-900 dark:text-zinc-100">
                Edit Clinical Memory
              </h3>
              <p className="text-[11px] text-slate-500 dark:text-zinc-400">
                Correct or refine clinical facts remembered by Carefold agents
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            aria-label="Close edit dialog"
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-zinc-200 transition cursor-pointer disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          {/* Key and Tier info */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-slate-600 dark:text-zinc-400 mb-1">
                Memory Identifier
              </label>
              <div className="px-3 py-2 rounded-xl bg-slate-100 dark:bg-zinc-800/80 border border-slate-200 dark:border-zinc-700/60 text-xs font-mono text-slate-700 dark:text-zinc-300 truncate">
                {record.key}
              </div>
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-slate-600 dark:text-zinc-400 mb-1">
                Cognitive Tier
              </label>
              <select
                value={selectedTier}
                onChange={(e) => setSelectedTier(e.target.value as MemoryTier)}
                className="w-full px-3 py-2 rounded-xl bg-white dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700 text-xs text-slate-800 dark:text-zinc-200 font-medium focus:outline-none focus:ring-2 focus:ring-emerald-500/30 cursor-pointer"
              >
                <option value="episodic">Episodic (Conversation turn / visit)</option>
                <option value="semantic">Semantic (Consolidated fact)</option>
                <option value="working">Working (Session context)</option>
                <option value="procedural">Procedural (Care guideline / rule)</option>
              </select>
            </div>
          </div>

          {/* Fact value textarea */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label
                htmlFor="edit-memory-value"
                className="text-xs font-semibold text-slate-700 dark:text-zinc-300"
              >
                Remembered Fact Text
              </label>
              <span className="text-[10px] text-slate-400 dark:text-zinc-500">
                {valueText.length} characters
              </span>
            </div>
            <textarea
              id="edit-memory-value"
              ref={textareaRef}
              data-testid="edit-memory-value-input"
              rows={4}
              value={valueText}
              onChange={(e) => {
                setValueText(e.target.value);
                if (error) setError(null);
              }}
              placeholder="Enter the corrected clinical or navigational fact..."
              className="w-full p-3 rounded-xl bg-slate-50 dark:bg-zinc-800/60 border border-slate-200 dark:border-zinc-700 text-xs text-slate-900 dark:text-zinc-100 placeholder-slate-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 resize-none font-sans"
            />
          </div>

          {error && (
            <div className="p-2.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs text-rose-700 dark:text-rose-400">
              {error}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-zinc-800">
            <button
              type="button"
              data-testid="cancel-edit-memory-btn"
              disabled={isSaving}
              onClick={onClose}
              className="px-4 py-2 rounded-xl border border-slate-300 dark:border-zinc-700 text-xs font-semibold text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition cursor-pointer disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              data-testid="save-memory-edit-btn"
              disabled={isSaving || !valueText.trim()}
              className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-sm shadow-emerald-900/20 transition flex items-center gap-1.5 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Save className="w-3.5 h-3.5" />
              <span>{isSaving ? 'Saving...' : 'Save Changes'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
