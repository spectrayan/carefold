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

import React, { useState, useEffect } from 'react';
import {
  CalendarCheck,
  Clock,
  Plus,
  Copy,
  Check,
  Download,
  Info,
  CheckSquare,
  Square,
  ListChecks,
} from 'lucide-react';
import type { ClinicalVisitDossierData, ChecklistItemState } from '@/lib/types';
import {
  loadChecklist,
  toggleChecklistItem,
  addChecklistItem,
} from '@/lib/checklistStorage';
import { downloadBlob } from '@/lib/dossierExport';

export const DOSSIER_PATIENT_DISCLAIMER =
  'Extracted from your document. Check details with your care team or insurer.';

export interface VisitPrepCardProps {
  data: ClinicalVisitDossierData;
  threadId?: string;
  messageId?: string;
  agentTitle?: string;
  isGrounded?: boolean;
}

export function VisitPrepCard({
  data,
  threadId,
  messageId,
  agentTitle,
  isGrounded,
}: VisitPrepCardProps) {
  const [items, setItems] = useState<ChecklistItemState[]>(() =>
    loadChecklist(threadId, messageId, data.questions_to_ask || [])
  );
  const [newQuestion, setNewQuestion] = useState('');
  const [copied, setCopied] = useState(false);

  // Sync state if initial questions or ids change
  useEffect(() => {
    setItems(loadChecklist(threadId, messageId, data.questions_to_ask || []));
  }, [threadId, messageId, data.questions_to_ask]);

  const handleToggle = (itemId: string) => {
    const updated = toggleChecklistItem(threadId, messageId, itemId, items);
    setItems(updated);
  };

  const handleAddQuestion = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!newQuestion.trim()) return;
    const updated = addChecklistItem(threadId, messageId, newQuestion, items);
    setItems(updated);
    setNewQuestion('');
  };

  const formatMarkdown = (): string => {
    const lines: string[] = [];
    lines.push('# Clinical Visit Preparation Dossier');
    lines.push(`*${DOSSIER_PATIENT_DISCLAIMER}*`);
    lines.push('');
    if (data.reason_for_visit) {
      lines.push('## Reason for Visit');
      lines.push(data.reason_for_visit);
      lines.push('');
    }
    if (data.follow_up_timeline) {
      lines.push('## Follow-up Timeline');
      lines.push(data.follow_up_timeline);
      lines.push('');
    }
    if (data.physician_instructions && data.physician_instructions.length > 0) {
      lines.push('## Physician Instructions');
      for (const inst of data.physician_instructions) {
        lines.push(`- ${inst}`);
      }
      lines.push('');
    }
    lines.push('## Questions for Your Care Team');
    if (items.length > 0) {
      for (const item of items) {
        lines.push(`- [${item.completed ? 'x' : ' '}] ${item.text}`);
      }
    } else {
      lines.push('_None specified_');
    }
    return lines.join('\n');
  };

  const handleCopy = async () => {
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(formatMarkdown());
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch {
      // Gracefully handle clipboard errors
    }
  };

  const handleExport = () => {
    const md = formatMarkdown();
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const now = new Date();
    const dateStr = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}-${String(now.getUTCDate()).padStart(2, '0')}`;
    downloadBlob(blob, `carefold-visit-prep-${dateStr}.md`);
  };

  return (
    <div
      data-testid="visit-prep-card"
      className="rounded-xl border border-slate-200/80 dark:border-zinc-800 bg-slate-50/60 dark:bg-zinc-800/40 p-3.5 space-y-3 my-2 text-zinc-900 dark:text-zinc-100"
    >
      {/* Top Header Row with Icon, Title, Follow-up Timeline Badge, & Action Buttons */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-100 dark:border-zinc-800">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400">
            <CalendarCheck className="w-4 h-4" aria-hidden="true" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-zinc-200">
                Visit Preparation Dossier
              </h3>
              {isGrounded !== undefined && (
                <span
                  data-testid="dossier-grounded-badge"
                  className={`inline-flex items-center text-xs font-medium px-1.5 py-0.5 rounded-md border ${
                    isGrounded
                      ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900/50'
                      : 'bg-amber-50 dark:bg-amber-950/50 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-900/50'
                  }`}
                >
                  {isGrounded ? 'Grounded' : 'Partially Grounded'}
                </span>
              )}
            </div>
            {agentTitle && (
              <p className="text-xs text-slate-500 dark:text-zinc-400">
                Prepared with {agentTitle}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          {data.follow_up_timeline && (
            <span
              data-testid="visit-followup-badge"
              className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 dark:bg-zinc-800 dark:text-zinc-300 border border-slate-200 dark:border-zinc-700"
            >
              <Clock className="w-3 h-3" aria-hidden="true" />
              <span>Follow-up: {data.follow_up_timeline}</span>
            </span>
          )}

          <button
            type="button"
            data-testid="dossier-copy-btn"
            onClick={handleCopy}
            aria-label="Copy visit preparation dossier"
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 hover:bg-slate-100 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-200 transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-400" />
                <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400">Copied!</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span className="text-xs">Copy</span>
              </>
            )}
          </button>

          <button
            type="button"
            data-testid="dossier-export-btn"
            onClick={handleExport}
            aria-label="Export visit preparation dossier"
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 hover:bg-slate-100 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-200 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span className="text-xs">Export</span>
          </button>
        </div>
      </div>

      {/* Mandatory Patient-Friendly Safety Disclaimer Banner */}
      <div
        data-testid="dossier-disclaimer-banner"
        className="flex items-center gap-2 p-2.5 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-100/70 dark:bg-zinc-800/50 text-slate-800 dark:text-zinc-200 text-xs"
      >
        <Info className="w-4 h-4 text-slate-600 dark:text-zinc-400 shrink-0" aria-hidden="true" />
        <p className="leading-snug">{DOSSIER_PATIENT_DISCLAIMER}</p>
      </div>

      {/* Reason for Visit */}
      {data.reason_for_visit && (
        <div data-testid="visit-reason" className="space-y-1">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
            Reason for Visit
          </span>
          <p className="text-sm font-medium text-slate-900 dark:text-zinc-100 bg-slate-50 dark:bg-zinc-800/50 p-2.5 rounded-xl border border-slate-200/70 dark:border-zinc-700/50">
            {data.reason_for_visit}
          </p>
        </div>
      )}

      {/* Physician Instructions */}
      {data.physician_instructions && data.physician_instructions.length > 0 && (
        <div data-testid="visit-instructions" className="space-y-1.5">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
            Physician Instructions
          </span>
          <ul className="space-y-1 bg-slate-50 dark:bg-zinc-800/50 p-2.5 rounded-xl border border-slate-200/70 dark:border-zinc-700/50">
            {data.physician_instructions.map((instruction, idx) => (
              <li
                key={idx}
                className="flex items-start gap-2 text-xs text-slate-700 dark:text-zinc-300 leading-relaxed"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400 mt-1.5 shrink-0" />
                <span>{instruction}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Interactive Questions to Ask Checklist */}
      <div data-testid="visit-questions-checklist" className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <ListChecks className="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-400" aria-hidden="true" />
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
              Questions for Your Care Team
            </span>
          </div>
          <span className="text-xs text-slate-500 dark:text-zinc-400 tabular-nums">
            {items.filter((i) => i.completed).length} / {items.length} completed
          </span>
        </div>

        {items.length === 0 ? (
          <p className="text-xs text-slate-500 dark:text-zinc-400 italic py-1">
            No pre-set questions extracted. You can add questions below:
          </p>
        ) : (
          <ul className="space-y-1.5 bg-slate-50 dark:bg-zinc-800/50 p-2.5 rounded-xl border border-slate-200/70 dark:border-zinc-700/50">
            {items.map((item, idx) => (
              <li
                key={item.id}
                data-testid={`checklist-item-${idx}`}
                className="flex items-start gap-2.5 text-xs group"
              >
                <button
                  type="button"
                  data-testid={`checklist-checkbox-${item.id}`}
                  onClick={() => handleToggle(item.id)}
                  aria-label={`Mark "${item.text}" as ${item.completed ? 'incomplete' : 'completed'}`}
                  className="mt-0.5 text-slate-400 hover:text-emerald-700 dark:text-zinc-500 dark:hover:text-emerald-400 transition-colors shrink-0"
                >
                  {item.completed ? (
                    <CheckSquare className="w-4 h-4 text-emerald-700 dark:text-emerald-400" />
                  ) : (
                    <Square className="w-4 h-4" />
                  )}
                </button>
                <span
                  onClick={() => handleToggle(item.id)}
                  className={`cursor-pointer leading-relaxed transition-all ${
                    item.completed
                      ? 'line-through text-slate-400 dark:text-zinc-500'
                      : 'text-slate-800 dark:text-zinc-200'
                  }`}
                >
                  {item.text}
                </span>
              </li>
            ))}
          </ul>
        )}

        {/* Add Custom Question Form */}
        <form onSubmit={handleAddQuestion} className="flex items-center gap-2 pt-1">
          <input
            type="text"
            data-testid="add-question-input"
            value={newQuestion}
            onChange={(e) => setNewQuestion(e.target.value)}
            placeholder="Add custom question to discuss..."
            className="flex-1 text-xs px-3 py-1.5 rounded-xl border border-[#7f8ea3] dark:border-[#657895] bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder-slate-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
          <button
            type="submit"
            data-testid="add-question-btn"
            disabled={!newQuestion.trim()}
            className="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 disabled:opacity-40 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] font-medium transition-colors shrink-0"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add</span>
          </button>
        </form>
      </div>
    </div>
  );
}
