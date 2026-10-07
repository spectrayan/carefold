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

import React, { useState, useRef, useEffect } from 'react';
import { Download, ChevronDown, FileText, FileCode } from 'lucide-react';
import { exportDossier } from '@/lib/dossierExport';
import type { ChatMessage } from '@/lib/types';
import type { AgentSummary, AgentDetailResponse } from '@/types/api';

export interface DossierExportMenuProps {
  messages: ChatMessage[];
  agent?: AgentSummary | AgentDetailResponse | null;
  agentId?: string;
  threadId?: string;
  isStreaming?: boolean;
}

export function DossierExportMenu({
  messages,
  agent,
  agentId,
  threadId,
  isStreaming = false,
}: DossierExportMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const isDisabled = messages.length === 0 || Boolean(isStreaming);

  const getTooltip = (): string => {
    if (isStreaming) {
      return 'Cannot export while response is generating';
    }
    if (messages.length === 0) {
      return 'No messages to export';
    }
    return 'Export consultation dossier';
  };

  // Close menu if session becomes disabled (e.g. streaming starts)
  useEffect(() => {
    if (isDisabled && isOpen) {
      setIsOpen(false);
    }
  }, [isDisabled, isOpen]);

  // Click outside listener
  useEffect(() => {
    if (!isOpen) return;

    const handleOutsideClick = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleOutsideClick);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
    };
  }, [isOpen]);

  // Keyboard navigation listener (Escape key dismiss)
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  const handleExport = (format: 'md' | 'json') => {
    exportDossier(format, {
      agent,
      agentId,
      messages,
      threadId,
    });
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  const toggleMenu = () => {
    if (!isDisabled) {
      setIsOpen((prev) => !prev);
    }
  };

  return (
    <div
      ref={containerRef}
      data-testid="export-dossier-menu-wrapper"
      className="relative inline-block text-left"
    >
      <button
        ref={triggerRef}
        type="button"
        data-testid="export-dossier-menu-btn"
        onClick={toggleMenu}
        disabled={isDisabled}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label="Export consultation dossier"
        title={getTooltip()}
        className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-xl transition cursor-pointer ${
          isDisabled
            ? 'text-slate-400 dark:text-zinc-600 cursor-not-allowed opacity-50'
            : 'text-slate-600 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-zinc-100 hover:bg-slate-200 dark:hover:bg-zinc-800'
        }`}
      >
        <Download className="w-3.5 h-3.5" />
        <span className="hidden md:inline">Export</span>
        <ChevronDown
          className={`w-3 h-3 text-slate-400 dark:text-zinc-500 transition-transform ${
            isOpen ? 'rotate-180' : ''
          }`}
        />
      </button>

      {isOpen && !isDisabled && (
        <div
          role="menu"
          aria-orientation="vertical"
          aria-label="Export dossier options"
          className="absolute right-0 mt-1.5 w-60 rounded-xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-lg shadow-slate-900/10 dark:shadow-black/40 py-1.5 z-50 focus:outline-none animate-in fade-in zoom-in-95 duration-100"
        >
          <div className="px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-zinc-500 border-b border-slate-100 dark:border-zinc-800 mb-1">
            Export Consultation
          </div>

          <button
            type="button"
            data-testid="export-markdown-option"
            role="menuitem"
            onClick={() => handleExport('md')}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-zinc-800 transition cursor-pointer"
          >
            <FileText className="w-4 h-4 text-emerald-500 dark:text-emerald-400 shrink-0" />
            <div className="text-left">
              <div className="text-xs font-medium text-slate-800 dark:text-zinc-200">
                Markdown (.md)
              </div>
              <div className="text-[10px] text-slate-500 dark:text-zinc-400">
                Clinical prep & visit notes
              </div>
            </div>
          </button>

          <button
            type="button"
            data-testid="export-json-option"
            role="menuitem"
            onClick={() => handleExport('json')}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-zinc-800 transition cursor-pointer"
          >
            <FileCode className="w-4 h-4 text-indigo-500 dark:text-indigo-400 shrink-0" />
            <div className="text-left">
              <div className="text-xs font-medium text-slate-800 dark:text-zinc-200">
                JSON (.json)
              </div>
              <div className="text-[10px] text-slate-500 dark:text-zinc-400">
                Structured session transcript
              </div>
            </div>
          </button>
        </div>
      )}
    </div>
  );
}
