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
  Search,
  Filter,
  History,
  RotateCcw,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ActivityItemResponse } from '@/types/activity';
import { ActivityTimelineItem } from './ActivityTimelineItem';

export interface ActivityTimelineFeedProps {
  items: ActivityItemResponse[];
  onUndo?: (eventId: string) => Promise<void> | void;
  className?: string;
}

export function ActivityTimelineFeed({
  items = [],
  onUndo,
  className,
}: ActivityTimelineFeedProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTool, setSelectedTool] = useState<string>('all');
  const [undoableOnly, setUndoableOnly] = useState(false);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      // 1. Undoable only filter
      if (undoableOnly && !item.undoable) {
        return false;
      }

      // 2. Tool filter
      if (selectedTool !== 'all') {
        const itemTool = item.tool || item.action || item.event;
        if (itemTool !== selectedTool) {
          return false;
        }
      }

      // 3. Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesSummary = item.summary.toLowerCase().includes(q);
        const matchesDesc = item.description?.toLowerCase().includes(q);
        const matchesTool = item.tool?.toLowerCase().includes(q);
        const matchesActor = item.actor?.toLowerCase().includes(q) || item.principal?.toLowerCase().includes(q);
        return matchesSummary || matchesDesc || matchesTool || matchesActor;
      }

      return true;
    });
  }, [items, searchQuery, selectedTool, undoableOnly]);

  return (
    <div data-testid="activity-timeline-feed" className={cn('space-y-4', className)}>
      {/* Search and Filters Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-2xl border border-[var(--cf-border)] bg-[var(--cf-surface)] shadow-sm">
        {/* Search Input */}
        <div className="relative flex-1 min-w-[200px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--cf-fg-subtle)]" />
          <input
            type="text"
            data-testid="activity-search-input"
            placeholder="Search activities by summary, actor, or tool..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] placeholder:text-[var(--cf-fg-subtle)]"
          />
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          {/* Tool Filter Dropdown */}
          <div className="flex items-center gap-1.5 text-xs text-[var(--cf-fg-muted)]">
            <Filter className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)]" />
            <select
              data-testid="activity-tool-filter"
              value={selectedTool}
              onChange={(e) => setSelectedTool(e.target.value)}
              className="px-2.5 py-1.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] text-xs text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)]"
            >
              <option value="all">All Tools</option>
              <option value="record_vitals">Vitals Recorded</option>
              <option value="create_appointment">Appointments</option>
              <option value="create_reminder">Reminders</option>
              <option value="generate_prep_pack">Prep Packs</option>
              <option value="create_typed_note">Clinical Notes</option>
              <option value="undo">Reversals</option>
            </select>
          </div>

          {/* Undoable Only Switch */}
          <label className="flex items-center gap-2 text-xs text-[var(--cf-fg-muted)] cursor-pointer select-none pl-1">
            <input
              type="checkbox"
              data-testid="undoable-only-toggle"
              checked={undoableOnly}
              onChange={(e) => setUndoableOnly(e.target.checked)}
              className="rounded text-[var(--cf-primary)] focus:ring-[var(--cf-focus)]"
            />
            <span className="flex items-center gap-1">
              <RotateCcw className="w-3 h-3 text-amber-600" />
              Undoable only
            </span>
          </label>
        </div>
      </div>

      {/* Events Stream */}
      {filteredItems.length === 0 ? (
        <div
          data-testid="activity-empty-state"
          className="py-16 text-center text-sm text-[var(--cf-fg-subtle)] border-dashed border-2 border-[var(--cf-border)] rounded-2xl p-6"
        >
          <History className="w-8 h-8 mx-auto text-[var(--cf-fg-subtle)] mb-2 opacity-50" />
          <p className="font-medium text-[var(--cf-fg-muted)]">No activity events found</p>
          <p className="text-xs mt-0.5">
            {searchQuery || selectedTool !== 'all' || undoableOnly
              ? 'Try adjusting your filters or search terms.'
              : 'Actions taken by you or Carefold assistants will appear in this timeline.'}
          </p>
        </div>
      ) : (
        <div data-testid="activity-items-list" className="space-y-3">
          {filteredItems.map((item) => (
            <ActivityTimelineItem key={item.id} item={item} onUndo={onUndo} />
          ))}
        </div>
      )}
    </div>
  );
}
