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
