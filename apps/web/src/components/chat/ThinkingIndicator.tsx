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

export interface ThinkingIndicatorProps {
  /** Optional custom status text (defaults to 'Planning clinical navigation...') */
  text?: string;
  /** Optional additional class names */
  className?: string;
}

export function ThinkingIndicator({
  text = 'Planning clinical navigation...',
  className = ''
}: ThinkingIndicatorProps) {
  return (
    <div
      data-testid="thinking-indicator"
      role="status"
      aria-live="polite"
      className={`flex items-center gap-2.5 py-1 text-xs font-medium text-slate-500 dark:text-zinc-400 select-none ${className}`}
    >
      {/* Animated 3-dot pulse indicator */}
      <div data-testid="thinking-dots" className="flex items-center gap-1 shrink-0" aria-hidden="true">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400 animate-pulse" />
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400 animate-pulse [animation-delay:200ms]" />
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400 animate-pulse [animation-delay:400ms]" />
      </div>

      {/* Dynamic status text */}
      <span data-testid="thinking-text" className="animate-pulse">
        {text}
      </span>
    </div>
  );
}
