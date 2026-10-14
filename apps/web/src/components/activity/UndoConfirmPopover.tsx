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
import { RotateCcw, AlertTriangle, X, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import type { ActivityItemResponse } from '@/types/activity';

export interface UndoConfirmPopoverProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  item: ActivityItemResponse;
  isLoading?: boolean;
}

export function UndoConfirmPopover({
  isOpen,
  onClose,
  onConfirm,
  item,
  isLoading = false,
}: UndoConfirmPopoverProps) {
  if (!isOpen) return null;

  const entityType = item.external_ref ? item.external_ref.split(':')[0] : 'record';

  const rollbackDescription = () => {
    switch (entityType) {
      case 'health_resource':
        return 'Tombstones vital signs observation and removes it from trends.';
      case 'appointment':
        return 'Marks the scheduled appointment as cancelled.';
      case 'reminder':
        return 'Cancels the reminder and halts scheduled alerts.';
      case 'note':
        return 'Removes note and purges document from search index.';
      default:
        return 'Reverts the local state changes created by this action.';
    }
  };

  return (
    <>
      {/* Click outside backdrop */}
      <div
        className="fixed inset-0 z-30"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        data-testid="undo-confirm-popover"
        role="dialog"
        aria-modal="true"
        aria-labelledby="undo-dialog-title"
        className="absolute right-0 top-full mt-2 w-80 rounded-2xl border border-[var(--cf-border)] bg-[var(--cf-surface)] p-4 shadow-xl z-40 text-left"
      >
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 flex items-center justify-center shrink-0">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <h4
              id="undo-dialog-title"
              className="text-sm font-semibold text-[var(--cf-fg)]"
            >
              Revert this action?
            </h4>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] p-1 rounded-md"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed mb-2">
          {rollbackDescription()}
        </p>

        <p className="text-xs text-[var(--cf-fg-subtle)] mb-3">
          An audited reversal event will be logged in this timeline.
        </p>

        <div className="flex items-center justify-end gap-2 pt-2 border-t border-[var(--cf-border)]">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={isLoading}
            className="text-xs"
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="danger"
            size="sm"
            data-testid="confirm-undo-btn"
            onClick={onConfirm}
            disabled={isLoading}
            className="text-xs"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                Reverting...
              </>
            ) : (
              <>
                <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
                Confirm Undo
              </>
            )}
          </Button>
        </div>
      </div>
    </>
  );
}
