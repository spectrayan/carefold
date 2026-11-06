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
import type { OrchestrationNoticeItem, TaskState, TaskStatusItem } from '@/lib/types';

export interface OrchestrationStatusProps {
  tasks?: TaskStatusItem[];
  notices?: OrchestrationNoticeItem[];
}

const TASK_STATE_CONFIG: Record<TaskState, { label: string; badge: string; dot: string }> = {
  started: {
    label: 'Working',
    badge: 'bg-sky-100 text-sky-800 border-sky-300 dark:bg-sky-950/60 dark:text-sky-300 dark:border-sky-800',
    dot: 'bg-sky-500 animate-pulse'
  },
  completed: {
    label: 'Done',
    badge: 'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800',
    dot: 'bg-emerald-500'
  },
  failed: {
    label: 'Failed',
    badge: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800',
    dot: 'bg-amber-500'
  },
  timed_out: {
    label: 'Timed out',
    badge: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800',
    dot: 'bg-amber-500'
  },
  cancelled: {
    label: 'Cancelled',
    badge: 'bg-slate-100 text-slate-800 border-slate-300 dark:bg-zinc-800 dark:text-zinc-300 dark:border-zinc-700',
    dot: 'bg-slate-400'
  }
};

/** Helper-agent progress and degraded-turn notices for one assistant message. */
export function OrchestrationStatus({ tasks = [], notices = [] }: OrchestrationStatusProps) {
  if (tasks.length === 0 && notices.length === 0) return null;

  return (
    <div data-testid="orchestration-status" className="space-y-1">
      {notices.map((notice) => (
        <div
          key={`${notice.code}-${notice.message}`}
          data-testid="orchestration-notice"
          data-code={notice.code}
          role="status"
          className="my-1 p-2 rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/30 text-xs text-amber-800 dark:text-amber-300"
        >
          {notice.message}
        </div>
      ))}

      {tasks.length > 0 && (
        <ul
          data-testid="task-status-list"
          aria-label="Helper agents"
          className="my-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800/80 shadow-sm text-xs divide-y divide-slate-200 dark:divide-zinc-700"
        >
          {tasks.map((task) => {
            const config = TASK_STATE_CONFIG[task.state] || TASK_STATE_CONFIG.cancelled;
            return (
              <li
                key={task.taskId}
                data-testid="task-status-row"
                data-state={task.state}
                className="px-3 py-2 flex items-center gap-2 min-w-0"
              >
                <span className={`inline-block w-2 h-2 rounded-full ${config.dot}`} />
                <span className="font-mono font-medium text-slate-800 dark:text-zinc-200 truncate">
                  {task.agentId}
                </span>
                <span
                  data-testid="task-status-badge"
                  className={`px-1.5 py-0.5 rounded text-xs font-semibold border ${config.badge}`}
                >
                  {config.label}
                </span>
                {task.detail && (
                  <span data-testid="task-status-detail" className="text-slate-600 dark:text-zinc-400 truncate">
                    {task.detail}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
