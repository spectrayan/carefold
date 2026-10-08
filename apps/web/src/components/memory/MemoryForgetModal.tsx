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

import React, { useEffect, useRef } from 'react';
import { AlertTriangle, Trash2, X } from 'lucide-react';

export interface MemoryForgetModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  isBulk?: boolean;
  memoryKey?: string;
  isDeleting?: boolean;
}

export function MemoryForgetModal({
  isOpen,
  onClose,
  onConfirm,
  isBulk = false,
  memoryKey,
  isDeleting = false,
}: MemoryForgetModalProps) {
  const cancelBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isOpen) {
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Escape' && !isDeleting) {
          onClose();
        }
      };
      window.addEventListener('keydown', handleKeyDown);
      // Autofocus Cancel button to prevent accidental destructive confirmation
      setTimeout(() => cancelBtnRef.current?.focus(), 50);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, isDeleting, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="forget-modal-title"
      aria-describedby="forget-modal-desc"
    >
      <div
        className="w-full max-w-md bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl shadow-2xl p-6 overflow-hidden animate-in zoom-in-95"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/50 border border-rose-200 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 shrink-0">
            <AlertTriangle className="w-6 h-6" />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <h3
                id="forget-modal-title"
                className="text-base font-bold text-slate-900 dark:text-zinc-100"
              >
                {isBulk ? 'Forget All Memories?' : 'Forget This Memory?'}
              </h3>
              <button
                type="button"
                onClick={onClose}
                disabled={isDeleting}
                aria-label="Close modal"
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-zinc-200 transition cursor-pointer disabled:opacity-50"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <p
              id="forget-modal-desc"
              className="mt-2 text-xs text-slate-600 dark:text-zinc-400 leading-relaxed"
            >
              {isBulk
                ? 'This will permanently delete all stored clinical facts and episodic interactions from your local database. Carefold specialist agents will no longer recall any prior context. This action cannot be undone.'
                : `Carefold agents will permanently delete "${memoryKey || 'this item'}" from your local memory database and will no longer recall this fact in future conversations.`}
            </p>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3 pt-4 border-t border-slate-100 dark:border-zinc-800">
          <button
            ref={cancelBtnRef}
            type="button"
            data-testid="cancel-forget-btn"
            disabled={isDeleting}
            onClick={onClose}
            className="px-4 py-2 rounded-xl border border-slate-300 dark:border-zinc-700 text-xs font-semibold text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition cursor-pointer disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid={isBulk ? 'confirm-forget-all-btn' : 'confirm-forget-btn'}
            disabled={isDeleting}
            onClick={onConfirm}
            className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold shadow-sm shadow-rose-900/20 transition flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>{isDeleting ? 'Deleting...' : isBulk ? 'Confirm Forget All' : 'Forget Memory'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
