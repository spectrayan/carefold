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

export interface StartersChipsProps {
  starters: string[];
  onSelectStarter: (prompt: string, autoSend?: boolean) => void;
  disabled?: boolean;
  autoSend?: boolean;
}

export function StartersChips({
  starters,
  onSelectStarter,
  disabled = false,
  autoSend = true
}: StartersChipsProps) {
  if (!starters || starters.length === 0) {
    return null;
  }

  return (
    <div
      data-testid="starters-container"
      aria-label="Suggested starter prompts"
      className="w-full flex flex-wrap gap-2 pt-2 pb-1"
    >
      <div className="w-full flex items-center gap-1.5 text-xs text-zinc-700 dark:text-zinc-300 font-semibold mb-1">
        <svg
          className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        <span>Suggested starters:</span>
      </div>

      {starters.map((prompt, index) => (
        <button
          key={`${index}-${prompt.slice(0, 20)}`}
          type="button"
          data-testid="starter-chip"
          disabled={disabled}
          onClick={() => onSelectStarter(prompt, autoSend)}
          className="inline-flex items-center text-left text-xs min-h-[44px] max-w-full px-3.5 py-2 rounded-2xl border border-[#7f8ea3] dark:border-[#657895] bg-slate-50 dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 hover:bg-emerald-50 dark:hover:bg-zinc-700 hover:border-emerald-700 dark:hover:border-emerald-400 hover:text-emerald-950 dark:hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-150 shadow-sm hover:shadow group cursor-pointer"
        >
          <span className="break-words whitespace-normal max-w-full leading-snug">{prompt}</span>
          <svg
            className="w-3 h-3 ml-1.5 opacity-0 group-hover:opacity-100 transition-opacity text-emerald-700 dark:text-emerald-400 shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
          </svg>
        </button>
      ))}
    </div>
  );
}
