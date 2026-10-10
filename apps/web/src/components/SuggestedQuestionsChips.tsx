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
import { Sparkles, ArrowRight } from 'lucide-react';

export interface SuggestedQuestionsChipsProps {
  /** Array of 2-3 contextual follow-up question strings emitted by the agent runner. */
  suggestions?: string[];
  /** Callback fired when a chip is clicked, passing the chosen question to submit. */
  onSelectSuggestion: (question: string) => void;
  /** Whether the chips are disabled (e.g. while an answer is currently streaming). */
  disabled?: boolean;
}

export function SuggestedQuestionsChips({
  suggestions,
  onSelectSuggestion,
  disabled = false
}: SuggestedQuestionsChipsProps) {
  if (!suggestions || suggestions.length === 0) {
    return null;
  }

  // Deduplicate and cap at 3 suggestions
  const cleanSuggestions = Array.from(
    new Set(suggestions.map((s) => (typeof s === 'string' ? s.trim() : '')).filter(Boolean))
  ).slice(0, 3);

  if (cleanSuggestions.length === 0) {
    return null;
  }

  return (
    <div
      data-testid="suggested-questions-container"
      aria-label="Suggested follow-up questions"
      className="w-full flex flex-col gap-1.5 pt-1 pb-2"
    >
      <div className="flex items-center gap-1.5 text-xs text-emerald-800 dark:text-emerald-300 font-semibold select-none">
        <Sparkles className="w-3.5 h-3.5 shrink-0" />
        <span>Suggested follow-ups:</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {cleanSuggestions.map((question, idx) => (
          <button
            key={`${idx}-${question.slice(0, 24)}`}
            type="button"
            data-testid="suggested-question-chip"
            disabled={disabled}
            onClick={() => onSelectSuggestion(question)}
            className="inline-flex items-center text-left text-xs min-h-[44px] max-w-full px-3.5 py-2 rounded-2xl border border-emerald-300 dark:border-emerald-800/80 bg-emerald-50/60 dark:bg-emerald-950/40 text-emerald-950 dark:text-emerald-100 hover:bg-emerald-100 dark:hover:bg-emerald-900/60 hover:border-emerald-700 dark:hover:border-emerald-400 hover:text-emerald-950 dark:hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-150 shadow-sm hover:shadow group cursor-pointer"
          >
            <span className="break-words whitespace-normal max-w-full leading-snug">{question}</span>
            <ArrowRight className="w-3 h-3 ml-1.5 opacity-0 group-hover:opacity-100 transition-opacity text-emerald-700 dark:text-emerald-400 shrink-0" />
          </button>
        ))}
      </div>
    </div>
  );
}
