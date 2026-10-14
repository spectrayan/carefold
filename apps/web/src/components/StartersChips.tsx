/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan (https://spectrayan.com)
 *
 * Licensed under the PolyForm Noncommercial License 1.0.0 and the
 * Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
 * Personal and household local use only. Commercial use, hosted service
 * offering, rebranding, white-labeling, and redistribution of modified
 * forks are prohibited without a written commercial license from Spectrayan.
 *
 * Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
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
          className="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-400"
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
          className="inline-flex items-center text-left whitespace-normal break-words text-xs min-h-[44px] max-w-full px-3.5 py-2 rounded-2xl border border-[#7f8ea3] dark:border-[#657895] bg-slate-50 dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 hover:bg-emerald-50 dark:hover:bg-zinc-700 hover:border-emerald-700 dark:hover:border-emerald-400 hover:text-emerald-950 dark:hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-150 shadow-sm hover:shadow group cursor-pointer"
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
