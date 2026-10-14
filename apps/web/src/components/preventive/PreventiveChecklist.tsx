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

import React, { useState, useMemo } from 'react';
import {
  CheckCircle2,
  Syringe,
  Stethoscope,
  Activity,
  ExternalLink,
  ClipboardPlus,
  BellPlus,
  Ban,
  MinusCircle,
  Clock,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import type {
  PreventiveActionType,
  PreventiveCategory,
  PreventiveItem,
  PreventiveStatus,
} from '@/types/preventive';

export type CategoryFilter = 'all' | PreventiveCategory;
export type StatusFilter = 'all' | 'due' | 'completed' | 'declined_na';

export interface PreventiveChecklistProps {
  items: PreventiveItem[];
  onUpdateStatus: (
    ruleId: string,
    status: PreventiveStatus,
    notes?: string
  ) => void | Promise<void>;
  onTriggerAction?: (
    ruleId: string,
    actionType: PreventiveActionType
  ) => void | Promise<void>;
  isLoading?: boolean;
  className?: string;
}

const CATEGORY_TABS: Array<{ id: CategoryFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'screening', label: 'Screenings' },
  { id: 'immunisation', label: 'Immunisations' },
  { id: 'well_visit', label: 'Well Visits' },
];

const STATUS_TABS: Array<{ id: StatusFilter; label: string }> = [
  { id: 'all', label: 'All Statuses' },
  { id: 'due', label: 'Due' },
  { id: 'completed', label: 'Completed' },
  { id: 'declined_na', label: 'Declined / N/A' },
];

export function PreventiveChecklist({
  items = [],
  onUpdateStatus,
  onTriggerAction,
  isLoading = false,
  className,
}: PreventiveChecklistProps) {
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (categoryFilter !== 'all' && item.category !== categoryFilter) {
        return false;
      }
      if (statusFilter === 'due' && item.status !== 'due') {
        return false;
      }
      if (statusFilter === 'completed' && item.status !== 'completed') {
        return false;
      }
      if (
        statusFilter === 'declined_na' &&
        item.status !== 'declined' &&
        item.status !== 'not_applicable'
      ) {
        return false;
      }
      return true;
    });
  }, [items, categoryFilter, statusFilter]);

  const categoryIcon = (cat: PreventiveCategory) => {
    switch (cat) {
      case 'immunisation':
        return <Syringe className="w-4 h-4 text-violet-500" />;
      case 'well_visit':
        return <Stethoscope className="w-4 h-4 text-blue-500" />;
      case 'screening':
      default:
        return <Activity className="w-4 h-4 text-emerald-500" />;
    }
  };

  const statusBadge = (status: PreventiveStatus) => {
    switch (status) {
      case 'completed':
        return (
          <Badge variant="success" size="sm" dot>
            Completed
          </Badge>
        );
      case 'not_applicable':
        return (
          <Badge variant="neutral" size="sm">
            Not Applicable
          </Badge>
        );
      case 'declined':
        return (
          <Badge variant="neutral" size="sm">
            Declined
          </Badge>
        );
      case 'due':
      default:
        return (
          <Badge variant="warning" size="sm" dot>
            Possibly Due
          </Badge>
        );
    }
  };

  return (
    <Card
      data-testid="preventive-checklist"
      className={cn('p-5 space-y-4 shadow-sm', className)}
    >
      {/* Filter Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--cf-border)]">
        {/* Category Filter */}
        <div
          role="tablist"
          aria-label="Filter preventive items by category"
          className="flex items-center gap-1.5 flex-wrap"
        >
          {CATEGORY_TABS.map((tab) => {
            const active = categoryFilter === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={active}
                data-testid={`preventive-category-tab-${tab.id}`}
                onClick={() => setCategoryFilter(tab.id)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors',
                  active
                    ? 'bg-[var(--cf-primary)] text-[var(--cf-fg-on-primary)]'
                    : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)]'
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Status Filter */}
        <div
          role="group"
          aria-label="Filter preventive items by status"
          className="flex items-center gap-1.5 flex-wrap"
        >
          {STATUS_TABS.map((tab) => {
            const active = statusFilter === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                data-testid={`preventive-status-tab-${tab.id}`}
                onClick={() => setStatusFilter(tab.id)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs font-medium border transition-colors',
                  active
                    ? 'border-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300'
                    : 'border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg-subtle)] hover:bg-[var(--cf-surface-2)]'
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Checklist Items */}
      {isLoading ? (
        <div
          data-testid="preventive-checklist-loading"
          className="py-8 text-center text-sm text-[var(--cf-fg-muted)]"
        >
          Loading preventive care checklist...
        </div>
      ) : filteredItems.length === 0 ? (
        <div
          data-testid="preventive-checklist-empty"
          className="py-8 text-center space-y-1"
        >
          <p className="text-sm font-semibold text-[var(--cf-fg)]">
            No preventive care items match this filter
          </p>
          <p className="text-xs text-[var(--cf-fg-muted)]">
            Try switching category or status filters above.
          </p>
        </div>
      ) : (
        <div className="space-y-3" data-testid="preventive-items-list">
          {filteredItems.map((item) => (
            <div
              key={item.rule_id}
              data-testid={`preventive-item-${item.rule_id}`}
              className="p-4 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] hover:border-[var(--cf-border-strong)] transition-colors space-y-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex items-start gap-2.5">
                  <div className="mt-0.5 shrink-0">{categoryIcon(item.category)}</div>
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="text-sm font-bold text-[var(--cf-fg)]">
                        {item.title}
                      </h4>
                      {statusBadge(item.status)}
                    </div>
                    <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed">
                      {item.clinical_summary}
                    </p>
                  </div>
                </div>

                {/* Source & Reviewed Metadata */}
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span
                    data-testid={`preventive-source-badge-${item.rule_id}`}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md font-semibold bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-900/50"
                  >
                    {item.source}
                  </span>
                  <span
                    data-testid={`preventive-reviewed-at-${item.rule_id}`}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)]"
                  >
                    <Clock className="w-3 h-3" />
                    Reviewed {item.reviewed_at}
                  </span>
                  {item.citation_url && (
                    <a
                      href={item.citation_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 hover:underline font-medium"
                    >
                      Guideline
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
              </div>

              {/* Action Bar: Status Controls & 1-Click Actions */}
              <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[var(--cf-border)]">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Button
                    size="sm"
                    variant={item.status === 'completed' ? 'primary' : 'secondary'}
                    data-testid={`mark-completed-${item.rule_id}`}
                    leftIcon={<CheckCircle2 className="w-3.5 h-3.5" />}
                    onClick={() => onUpdateStatus(item.rule_id, 'completed')}
                  >
                    Mark Completed
                  </Button>
                  <Button
                    size="sm"
                    variant={
                      item.status === 'not_applicable' ? 'primary' : 'ghost'
                    }
                    data-testid={`mark-na-${item.rule_id}`}
                    leftIcon={<MinusCircle className="w-3.5 h-3.5" />}
                    onClick={() => onUpdateStatus(item.rule_id, 'not_applicable')}
                  >
                    Not Applicable
                  </Button>
                  <Button
                    size="sm"
                    variant={item.status === 'declined' ? 'primary' : 'ghost'}
                    data-testid={`mark-declined-${item.rule_id}`}
                    leftIcon={<Ban className="w-3.5 h-3.5" />}
                    onClick={() => onUpdateStatus(item.rule_id, 'declined')}
                  >
                    Decline
                  </Button>
                </div>

                {onTriggerAction && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      data-testid={`add-visit-prep-${item.rule_id}`}
                      leftIcon={<ClipboardPlus className="w-3.5 h-3.5" />}
                      onClick={() =>
                        onTriggerAction(item.rule_id, 'add_to_visit_prep')
                      }
                    >
                      Add to Visit Prep
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      data-testid={`set-reminder-${item.rule_id}`}
                      leftIcon={<BellPlus className="w-3.5 h-3.5" />}
                      onClick={() => onTriggerAction(item.rule_id, 'set_reminder')}
                    >
                      Set Reminder
                    </Button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
