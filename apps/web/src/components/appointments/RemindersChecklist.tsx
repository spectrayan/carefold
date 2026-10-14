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

import React, { useState } from 'react';
import {
  Pill,
  HeartPulse,
  Calendar,
  ClipboardCheck,
  Bell,
  Clock,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Trash2,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { cn } from '@/lib/utils';
import type {
  ReminderItem,
  ReminderCategory,
  SnoozeInterval,
} from '@/types/schedule';
import { humanizeRrule } from '@/lib/scheduleApi';

export interface RemindersChecklistProps {
  reminders: ReminderItem[];
  profileId?: string;
  onCompleteReminder: (reminderId: string) => void;
  onSnoozeReminder: (reminderId: string, interval: SnoozeInterval) => void;
  onDeleteReminder?: (reminderId: string) => void;
  className?: string;
}

export function RemindersChecklist({
  reminders = [],
  profileId: _profileId,
  onCompleteReminder,
  onSnoozeReminder,
  onDeleteReminder,
  className,
}: RemindersChecklistProps) {
  const [showCompleted, setShowCompleted] = useState(false);
  const [openSnoozeMenuId, setOpenSnoozeMenuId] = useState<string | null>(null);

  const categoryIcon = (category: ReminderCategory) => {
    switch (category) {
      case 'medication':
        return <Pill className="w-3.5 h-3.5 text-violet-500" />;
      case 'vitals':
        return <HeartPulse className="w-3.5 h-3.5 text-rose-500" />;
      case 'appointment':
        return <Calendar className="w-3.5 h-3.5 text-blue-500" />;
      case 'prep':
        return <ClipboardCheck className="w-3.5 h-3.5 text-amber-500" />;
      default:
        return <Bell className="w-3.5 h-3.5 text-emerald-500" />;
    }
  };

  const categoryColorClass = (category: ReminderCategory) => {
    switch (category) {
      case 'medication':
        return 'bg-violet-50 dark:bg-violet-950/40 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-900/60';
      case 'vitals':
        return 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-900/60';
      case 'appointment':
        return 'bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-900/60';
      case 'prep':
        return 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-900/60';
      default:
        return 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900/60';
    }
  };

  const now = new Date();

  // Partition reminders into active vs completed
  const activeReminders = reminders.filter((r) => r.status !== 'completed' && r.status !== 'cancelled');
  const completedReminders = reminders.filter((r) => r.status === 'completed');

  // Check if reminder is overdue by >24h or status is missed
  const isOverdue = (rem: ReminderItem) => {
    if (rem.status === 'missed') return true;
    const dueDate = new Date(rem.snooze_until || rem.next_due_at);
    return now.getTime() - dueDate.getTime() > 24 * 60 * 60 * 1000;
  };

  // Sort active: overdue first, then snoozed, then pending
  const sortedActive = [...activeReminders].sort((a, b) => {
    const aOver = isOverdue(a);
    const bOver = isOverdue(b);
    if (aOver && !bOver) return -1;
    if (!aOver && bOver) return 1;
    return new Date(a.next_due_at).getTime() - new Date(b.next_due_at).getTime();
  });

  return (
    <Card
      data-testid="reminders-checklist-container"
      className={cn('p-5 shadow-sm space-y-4', className)}
    >
      <div className="flex items-center justify-between pb-3 border-b border-[var(--cf-border)]">
        <div>
          <h3 className="font-semibold text-base text-[var(--cf-fg)] flex items-center gap-2">
            <Bell className="w-4 h-4 text-emerald-600" />
            Reminders & Daily Tasks
          </h3>
          <p className="text-xs text-[var(--cf-fg-muted)] mt-0.5">
            {sortedActive.length} active routine task{sortedActive.length === 1 ? '' : 's'}
          </p>
        </div>
      </div>

      {/* Active Reminders List */}
      {sortedActive.length === 0 ? (
        <div
          data-testid="reminders-empty"
          className="py-10 text-center text-sm text-[var(--cf-fg-subtle)]"
        >
          <CheckCircle2 className="w-8 h-8 mx-auto text-emerald-500 mb-2 opacity-80" />
          <p className="font-medium text-[var(--cf-fg-muted)]">All caught up!</p>
          <p className="text-xs">No pending reminders or tasks due.</p>
        </div>
      ) : (
        <ul data-testid="active-reminders-list" className="space-y-2.5">
          {sortedActive.map((rem) => {
            const overdue = isOverdue(rem);
            const isSnoozed = rem.status === 'snoozed';
            const rruleLabel = humanizeRrule(rem.rrule, rem.next_due_at);

            return (
              <li
                key={rem.id}
                data-testid={`reminder-item-${rem.id}`}
                className={cn(
                  'p-3 rounded-xl border transition-all text-xs flex flex-col gap-2',
                  overdue
                    ? 'border-rose-300 dark:border-rose-900 bg-rose-50/50 dark:bg-rose-950/20'
                    : isSnoozed
                    ? 'border-amber-200 dark:border-amber-900/60 bg-amber-50/30 dark:bg-amber-950/15'
                    : 'border-[var(--cf-border)] bg-[var(--cf-surface)]'
                )}
              >
                <div className="flex items-start justify-between gap-2.5">
                  <div className="flex items-start gap-2.5 min-w-0 flex-1">
                    {/* Completion Checkbox */}
                    <button
                      type="button"
                      data-testid={`complete-reminder-btn-${rem.id}`}
                      onClick={() => onCompleteReminder(rem.id)}
                      className="mt-0.5 w-4 h-4 rounded border border-[var(--cf-border-strong)] hover:border-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950 flex items-center justify-center shrink-0 transition-colors"
                      title="Mark complete"
                      aria-label={`Mark complete: ${rem.title}`}
                    />

                    {/* Title & Description */}
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span
                          className={cn(
                            'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold uppercase tracking-wider border',
                            categoryColorClass(rem.category)
                          )}
                        >
                          {categoryIcon(rem.category)}
                          <span>{rem.category}</span>
                        </span>

                        {overdue && (
                          <span
                            data-testid="overdue-badge"
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-bold bg-rose-100 dark:bg-rose-900 text-rose-700 dark:text-rose-200"
                          >
                            <AlertTriangle className="w-3 h-3 text-rose-600" />
                            Overdue (&gt;24h)
                          </span>
                        )}

                        {isSnoozed && (
                          <span
                            data-testid="snoozed-badge"
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200"
                          >
                            <Clock className="w-3 h-3 text-amber-600" />
                            Snoozed
                          </span>
                        )}
                      </div>

                      <p
                        data-testid="reminder-title"
                        className="font-semibold text-sm text-[var(--cf-fg)] leading-snug"
                      >
                        {rem.title}
                      </p>

                      {rem.description && (
                        <p className="text-[var(--cf-fg-muted)] leading-relaxed text-xs">
                          {rem.description}
                        </p>
                      )}

                      <div className="flex items-center gap-2 text-xs text-[var(--cf-fg-subtle)] font-mono">
                        <Clock className="w-3 h-3" />
                        <span data-testid="reminder-rrule">{rruleLabel}</span>
                      </div>
                    </div>
                  </div>

                  {/* Actions: Snooze & Delete */}
                  <div className="relative flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      data-testid={`snooze-toggle-btn-${rem.id}`}
                      onClick={() =>
                        setOpenSnoozeMenuId((prev) => (prev === rem.id ? null : rem.id))
                      }
                      className="px-2 py-1 rounded text-xs font-medium border border-[var(--cf-border)] hover:bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] transition-colors flex items-center gap-1"
                      title="Snooze options"
                    >
                      <Clock className="w-3 h-3" />
                      <span>Snooze</span>
                    </button>

                    {onDeleteReminder && (
                      <button
                        type="button"
                        data-testid={`delete-reminder-btn-${rem.id}`}
                        onClick={() => onDeleteReminder(rem.id)}
                        className="p-1 rounded text-[var(--cf-fg-subtle)] hover:text-rose-600 transition-colors"
                        title="Delete reminder"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}

                    {/* Snooze Presets Popover */}
                    {openSnoozeMenuId === rem.id && (
                      <div
                        data-testid="snooze-popover-menu"
                        className="absolute right-0 top-full mt-1 w-32 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] shadow-lg z-20 py-1"
                      >
                        <button
                          type="button"
                          data-testid="snooze-15m-btn"
                          onClick={() => {
                            onSnoozeReminder(rem.id, '+15m');
                            setOpenSnoozeMenuId(null);
                          }}
                          className="w-full text-left px-3 py-1.5 hover:bg-[var(--cf-surface-2)] text-xs text-[var(--cf-fg)]"
                        >
                          +15 minutes
                        </button>
                        <button
                          type="button"
                          data-testid="snooze-1h-btn"
                          onClick={() => {
                            onSnoozeReminder(rem.id, '+1h');
                            setOpenSnoozeMenuId(null);
                          }}
                          className="w-full text-left px-3 py-1.5 hover:bg-[var(--cf-surface-2)] text-xs text-[var(--cf-fg)]"
                        >
                          +1 hour
                        </button>
                        <button
                          type="button"
                          data-testid="snooze-24h-btn"
                          onClick={() => {
                            onSnoozeReminder(rem.id, '+24h');
                            setOpenSnoozeMenuId(null);
                          }}
                          className="w-full text-left px-3 py-1.5 hover:bg-[var(--cf-surface-2)] text-xs text-[var(--cf-fg)]"
                        >
                          +24 hours
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Collapsible Completed Section */}
      {completedReminders.length > 0 && (
        <div className="pt-2 border-t border-[var(--cf-border)]">
          <button
            type="button"
            data-testid="toggle-completed-reminders-btn"
            onClick={() => setShowCompleted((prev) => !prev)}
            className="flex items-center gap-1.5 text-xs font-semibold text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] transition-colors w-full text-left py-1"
          >
            {showCompleted ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            <span>Completed Tasks ({completedReminders.length})</span>
          </button>

          {showCompleted && (
            <ul data-testid="completed-reminders-list" className="space-y-1.5 pt-2">
              {completedReminders.map((rem) => (
                <li
                  key={rem.id}
                  className="p-2 rounded-lg bg-[var(--cf-surface-2)]/50 text-xs flex items-center justify-between text-[var(--cf-fg-subtle)]"
                >
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                    <span className="line-through">{rem.title}</span>
                  </div>
                  <span className="text-xs font-mono">
                    {rem.category}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
