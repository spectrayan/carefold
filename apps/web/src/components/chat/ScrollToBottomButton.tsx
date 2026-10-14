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
import { ChevronDown } from 'lucide-react';

export interface ScrollToBottomButtonProps {
  /** Whether the user is scrolled away from the bottom */
  visible: boolean;
  /** Callback fired when clicking the button to scroll to bottom */
  onClick: () => void;
  /** Count of unread tokens or messages received while scrolled up */
  unreadCount?: number;
  /** Optional extra classes */
  className?: string;
}

export function ScrollToBottomButton({
  visible,
  onClick,
  unreadCount = 0,
  className = ''
}: ScrollToBottomButtonProps) {
  const hasUnread = unreadCount > 0;
  const badgeText = unreadCount > 99 ? '99+' : unreadCount;

  return (
    <div
      className={`absolute bottom-4 right-4 sm:right-6 z-20 transition-all duration-200 ease-in-out ${
        visible ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
      } ${className}`}
    >
      <button
        type="button"
        data-testid="scroll-to-bottom-btn"
        onClick={onClick}
        tabIndex={visible ? 0 : -1}
        aria-label={hasUnread ? `Scroll to bottom (${unreadCount} unread)` : 'Scroll to bottom'}
        title="Scroll to bottom"
        className="relative min-w-[44px] min-h-[44px] w-11 h-11 rounded-full shadow-md hover:shadow-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-750 hover:text-slate-900 dark:hover:text-white flex items-center justify-center cursor-pointer transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
      >
        <ChevronDown className="w-5 h-5 text-slate-600 dark:text-zinc-300" />

        {hasUnread && (
          <span
            data-testid="unread-counter-badge"
            className="absolute -top-1.5 -right-1.5 min-w-[20px] h-[20px] px-1 bg-emerald-700 dark:bg-emerald-500 text-white text-xs font-bold rounded-full flex items-center justify-center shadow-sm animate-pulse"
          >
            {badgeText}
          </span>
        )}
      </button>
    </div>
  );
}
