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

import React, { useState } from 'react';
import {
  User,
  Bot,
  Cpu,
  HeartPulse,
  Calendar,
  Bell,
  FileText,
  FileEdit,
  RotateCcw,
  Clock,
  Sparkles,
  Undo2,
} from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';
import type { ActivityItemResponse } from '@/types/activity';
import { formatRelativeTime } from '@/lib/activity';
import { UndoConfirmPopover } from './UndoConfirmPopover';

export interface ActivityTimelineItemProps {
  item: ActivityItemResponse;
  onUndo?: (eventId: string) => Promise<void> | void;
  className?: string;
}

export function ActivityTimelineItem({
  item,
  onUndo,
  className,
}: ActivityTimelineItemProps) {
  const [showUndoPopover, setShowUndoPopover] = useState(false);
  const [isUndoing, setIsUndoing] = useState(false);

  const actorLabel = () => {
    if (item.principal === 'user' || item.actor === 'user') return 'You';
    if (item.principal === 'system' || item.actor === 'system') return 'System';
    return 'Carefold Agent';
  };

  const actorIcon = () => {
    if (item.principal === 'user' || item.actor === 'user') {
      return <User className="w-3.5 h-3.5 text-blue-600" />;
    }
    if (item.principal === 'system' || item.actor === 'system') {
      return <Cpu className="w-3.5 h-3.5 text-slate-500" />;
    }
    return <Bot className="w-3.5 h-3.5 text-emerald-600" />;
  };

  const actorColorClass = () => {
    if (item.principal === 'user' || item.actor === 'user') {
      return 'bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-900/60';
    }
    if (item.principal === 'system' || item.actor === 'system') {
      return 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700';
    }
    return 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900/60';
  };

  const toolBadge = () => {
    const t = item.tool || item.action || item.event;
    switch (t) {
      case 'record_vitals':
        return {
          label: 'Vitals Recorded',
          icon: <HeartPulse className="w-3.5 h-3.5 text-rose-500" />,
          colorClass: 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-900/60',
        };
      case 'create_appointment':
        return {
          label: 'Appointment',
          icon: <Calendar className="w-3.5 h-3.5 text-violet-500" />,
          colorClass: 'bg-violet-50 dark:bg-violet-950/40 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-900/60',
        };
      case 'create_reminder':
        return {
          label: 'Reminder',
          icon: <Bell className="w-3.5 h-3.5 text-amber-500" />,
          colorClass: 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-900/60',
        };
      case 'generate_prep_pack':
        return {
          label: 'Prep Pack',
          icon: <FileText className="w-3.5 h-3.5 text-teal-500" />,
          colorClass: 'bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 border-teal-200 dark:border-teal-900/60',
        };
      case 'create_typed_note':
        return {
          label: 'Clinical Note',
          icon: <FileEdit className="w-3.5 h-3.5 text-sky-500" />,
          colorClass: 'bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 border-sky-200 dark:border-sky-900/60',
        };
      case 'undo':
        return {
          label: 'Reversal',
          icon: <RotateCcw className="w-3.5 h-3.5 text-slate-500" />,
          colorClass: 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700',
        };
      default:
        return {
          label: t,
          icon: <Sparkles className="w-3.5 h-3.5 text-[var(--cf-primary)]" />,
          colorClass: 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border-[var(--cf-border)]',
        };
    }
  };

  const badgeInfo = toolBadge();
  const relativeTime = formatRelativeTime(item.ts);
  const fullTime = new Date(item.ts).toLocaleString();

  const handleConfirmUndo = async () => {
    if (!onUndo) return;
    setIsUndoing(true);
    try {
      await onUndo(item.id);
      setShowUndoPopover(false);
    } finally {
      setIsUndoing(false);
    }
  };

  const isExpiredWriteLocal = !item.undoable && !item.undone && item.risk === 'write_local';

  return (
    <div
      data-testid={`activity-item-${item.id}`}
      className={cn(
        'relative p-4 rounded-2xl border transition-all shadow-sm',
        item.undone
          ? 'bg-[var(--cf-surface-2)]/30 border-slate-200 dark:border-slate-800 opacity-70'
          : 'bg-[var(--cf-surface)] border-[var(--cf-border)]',
        className
      )}
    >
      <div className="flex items-start justify-between gap-3">
        {/* Left: Content Details */}
        <div className="space-y-1.5 flex-1 min-w-0">
          {/* Metadata Badges Row */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Actor Badge */}
            <span
              data-testid="actor-badge"
              className={cn(
                'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border',
                actorColorClass()
              )}
            >
              {actorIcon()}
              <span>{actorLabel()}</span>
            </span>

            {/* Tool Badge */}
            <span
              data-testid="tool-badge"
              className={cn(
                'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border',
                badgeInfo.colorClass
              )}
            >
              {badgeInfo.icon}
              <span>{badgeInfo.label}</span>
            </span>

            {/* Undone Pill */}
            {item.undone && (
              <Badge data-testid="undone-badge" variant="neutral" size="sm">
                [UNDONE]
              </Badge>
            )}

            {/* Timestamp */}
            <span
              data-testid="activity-timestamp"
              title={fullTime}
              className="text-[11px] text-[var(--cf-fg-subtle)] flex items-center gap-1 font-mono ml-auto"
            >
              <Clock className="w-3 h-3" />
              {relativeTime}
            </span>
          </div>

          {/* Headline Summary */}
          <h4
            data-testid="activity-summary"
            className={cn(
              'font-semibold text-sm text-[var(--cf-fg)] leading-snug',
              item.undone && 'line-through text-[var(--cf-fg-muted)]'
            )}
          >
            {item.summary}
          </h4>

          {/* Description */}
          {item.description && (
            <p
              data-testid="activity-description"
              className="text-xs text-[var(--cf-fg-muted)] leading-relaxed"
            >
              {item.description}
            </p>
          )}
        </div>

        {/* Right: Single-Click Undo Action */}
        <div className="relative shrink-0 pt-0.5">
          {item.undoable ? (
            <button
              type="button"
              data-testid="undo-action-btn"
              onClick={() => setShowUndoPopover(true)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-[var(--cf-border)] hover:border-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/30 text-xs font-semibold text-[var(--cf-fg-muted)] hover:text-amber-700 dark:hover:text-amber-300 transition-colors"
              title="Undo this action"
            >
              <Undo2 className="w-3.5 h-3.5 text-amber-600" />
              <span>Undo</span>
            </button>
          ) : isExpiredWriteLocal ? (
            <button
              type="button"
              disabled
              data-testid="undo-action-disabled-btn"
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-[var(--cf-border)] opacity-40 cursor-not-allowed text-xs font-medium text-[var(--cf-fg-subtle)]"
              title="Actions older than 7 days cannot be undone"
            >
              <Undo2 className="w-3.5 h-3.5" />
              <span>Undo</span>
            </button>
          ) : null}

          {/* Undo Confirmation Popover */}
          <UndoConfirmPopover
            isOpen={showUndoPopover}
            onClose={() => setShowUndoPopover(false)}
            onConfirm={handleConfirmUndo}
            item={item}
            isLoading={isUndoing}
          />
        </div>
      </div>
    </div>
  );
}
