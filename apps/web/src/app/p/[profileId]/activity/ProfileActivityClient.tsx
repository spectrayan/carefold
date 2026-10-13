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

import React, { useState, useEffect, useCallback } from 'react';
import {
  History,
  RefreshCw,
  Loader2,
  CheckCircle2,
} from 'lucide-react';
import { ActivityTimelineFeed } from '@/components/activity';
import { fetchProfileActivity, undoActivityEvent } from '@/lib/activity';
import type { ActivityItemResponse } from '@/types/activity';

export interface ProfileActivityClientProps {
  profileId: string;
  initialItems?: ActivityItemResponse[];
  initialTotal?: number;
  initialHasMore?: boolean;
}

export function ProfileActivityClient({
  profileId,
  initialItems = [],
  initialTotal: _initialTotal = 0,
  initialHasMore: _initialHasMore = false,
}: ProfileActivityClientProps) {
  const [items, setItems] = useState<ActivityItemResponse[]>(initialItems);
  const [isLoading, setIsLoading] = useState(initialItems.length === 0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setError(null);
    try {
      const res = await fetchProfileActivity(profileId, { limit: 100 });
      setItems(res.items || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load activity timeline.');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [profileId]);

  useEffect(() => {
    if (initialItems.length === 0) {
      loadData();
    }
  }, [initialItems.length, loadData]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    loadData();
  };

  const handleUndo = async (eventId: string) => {
    try {
      const res = await undoActivityEvent(profileId, eventId);

      // Optimistically mark item as undone
      setItems((prev) =>
        prev.map((item) =>
          item.id === eventId
            ? { ...item, undoable: false, undone: true }
            : item
        )
      );

      // Prepend undo event if returned
      if (res.undo_event_id) {
        const undoItem: ActivityItemResponse = {
          id: res.undo_event_id,
          ts: new Date().toISOString(),
          profile_id: profileId,
          principal: 'user',
          actor: 'user',
          event: 'undo',
          tool: 'undo',
          summary: `Reverted: ${res.reverted_summary || 'action'}`,
          description: res.message || 'Action was reverted by user single-click undo.',
          undoable: false,
          undone: false,
          details: { reverted_event_id: eventId },
        };
        setItems((prev) => [undoItem, ...prev]);
      }

      setToastMessage('Action reverted successfully.');
      setTimeout(() => setToastMessage(null), 4000);
    } catch (err: any) {
      setError(err.message || 'Failed to revert action.');
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto py-2">
      {/* Header Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[var(--cf-border)]">
        <div>
          <h1
            data-testid="activity-page-heading"
            className="text-2xl font-bold tracking-tight text-[var(--cf-fg)] flex items-center gap-2.5"
          >
            <History className="w-6 h-6 text-emerald-600" />
            Activity & History
          </h1>
          <p className="text-xs sm:text-sm text-[var(--cf-fg-muted)] mt-1">
            Chronological audit timeline of actions performed for this profile with single-click undo.
          </p>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          <span
            data-testid="activity-count-badge"
            className="text-xs px-2.5 py-1 rounded-full bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] font-semibold border border-[var(--cf-border)]"
          >
            {items.length} {items.length === 1 ? 'activity' : 'activities'}
          </span>

          <button
            type="button"
            data-testid="activity-refresh-btn"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="p-2 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition-colors min-h-[40px] min-w-[40px] flex items-center justify-center"
            title="Refresh activity timeline"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {toastMessage && (
        <div
          data-testid="activity-toast-success"
          role="status"
          className="p-3.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-900 text-emerald-800 dark:text-emerald-200 text-xs flex items-center gap-2 shadow-sm animate-fade-in"
        >
          <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          <span className="font-medium">{toastMessage}</span>
        </div>
      )}

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-300 dark:border-rose-900 text-rose-800 dark:text-rose-200 text-xs">
          {error}
        </div>
      )}

      {isLoading ? (
        <div className="py-20 flex flex-col items-center justify-center gap-3 text-[var(--cf-fg-subtle)]">
          <Loader2 className="w-8 h-8 animate-spin text-[var(--cf-primary)]" />
          <p className="text-sm">Loading activity stream...</p>
        </div>
      ) : (
        <ActivityTimelineFeed items={items} onUndo={handleUndo} />
      )}
    </div>
  );
}
