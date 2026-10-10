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
  FileText,
  Hash,
  Layers,
  Copy,
  Check,
  Download,
  Info,
} from 'lucide-react';
import type { GenericDocumentDossierData } from '@/lib/types';
import { downloadBlob } from '@/lib/dossierExport';
import { DOSSIER_PATIENT_DISCLAIMER } from './VisitPrepCard';

export interface GenericDossierCardProps {
  data: GenericDocumentDossierData;
  agentTitle?: string;
  isGrounded?: boolean;
}

function formatKeyLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function GenericDossierCard({
  data,
  agentTitle,
  isGrounded,
}: GenericDossierCardProps) {
  const [copied, setCopied] = useState(false);

  const numericalEntries = Object.entries(data.key_numerical_values || {});

  const formatMarkdown = (): string => {
    const lines: string[] = [];
    lines.push('# Document Extraction Summary');
    lines.push(`*${DOSSIER_PATIENT_DISCLAIMER}*`);
    lines.push('');
    if (data.summary) {
      lines.push('## Executive Summary');
      lines.push(data.summary);
      lines.push('');
    }
    if (numericalEntries.length > 0) {
      lines.push('## Key Extracted Values');
      for (const [key, val] of numericalEntries) {
        lines.push(`- **${formatKeyLabel(key)}:** ${val}`);
      }
      lines.push('');
    }
    if (data.sections && data.sections.length > 0) {
      lines.push('## Document Sections');
      for (const section of data.sections) {
        lines.push(`- ${section}`);
      }
      lines.push('');
    }
    return lines.join('\n');
  };

  const handleCopy = async () => {
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(formatMarkdown());
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch {
      // Gracefully handle clipboard errors
    }
  };

  const handleExport = () => {
    const md = formatMarkdown();
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const now = new Date();
    const dateStr = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}-${String(now.getUTCDate()).padStart(2, '0')}`;
    downloadBlob(blob, `carefold-document-summary-${dateStr}.md`);
  };

  return (
    <div
      data-testid="generic-dossier-card"
      className="rounded-xl border border-slate-200/80 dark:border-zinc-800 bg-slate-50/60 dark:bg-zinc-800/40 p-3.5 space-y-3 my-2 text-zinc-900 dark:text-zinc-100"
    >
      {/* Top Header Row with Icon, Title, & Action Buttons */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-100 dark:border-zinc-800">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400">
            <FileText className="w-4 h-4" aria-hidden="true" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-zinc-200">
                Document Summary Dossier
              </h3>
              {isGrounded !== undefined && (
                <span
                  data-testid="dossier-grounded-badge"
                  className={`inline-flex items-center text-xs font-medium px-1.5 py-0.5 rounded-md border ${
                    isGrounded
                      ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900/50'
                      : 'bg-amber-50 dark:bg-amber-950/50 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-900/50'
                  }`}
                >
                  {isGrounded ? 'Grounded' : 'Partially Grounded'}
                </span>
              )}
            </div>
            {agentTitle && (
              <p className="text-xs text-slate-500 dark:text-zinc-400">
                Prepared with {agentTitle}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            data-testid="dossier-copy-btn"
            onClick={handleCopy}
            aria-label="Copy document extraction dossier"
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 hover:bg-slate-100 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-200 transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-400" />
                <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400">Copied!</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span className="text-xs">Copy</span>
              </>
            )}
          </button>

          <button
            type="button"
            data-testid="dossier-export-btn"
            onClick={handleExport}
            aria-label="Export document extraction dossier"
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 hover:bg-slate-100 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-200 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span className="text-xs">Export</span>
          </button>
        </div>
      </div>

      {/* Mandatory Patient-Friendly Safety Disclaimer Banner */}
      <div
        data-testid="dossier-disclaimer-banner"
        className="flex items-center gap-2 p-2.5 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-100/70 dark:bg-zinc-800/50 text-slate-800 dark:text-zinc-200 text-xs"
      >
        <Info className="w-4 h-4 text-slate-600 dark:text-zinc-400 shrink-0" aria-hidden="true" />
        <p className="leading-snug">{DOSSIER_PATIENT_DISCLAIMER}</p>
      </div>

      {/* Executive Summary */}
      {data.summary && (
        <div data-testid="generic-summary" className="space-y-1">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
            Document Summary
          </span>
          <p className="text-xs text-slate-700 dark:text-zinc-300 bg-slate-50 dark:bg-zinc-800/50 p-2.5 rounded-xl border border-slate-200/70 dark:border-zinc-700/50 leading-relaxed">
            {data.summary}
          </p>
        </div>
      )}

      {/* Key Extracted Numerical Values */}
      {numericalEntries.length > 0 && (
        <div data-testid="generic-key-values" className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Hash className="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-400" />
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
              Key Extracted Metrics
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {numericalEntries.map(([key, val]) => (
              <div
                key={key}
                className="p-2.5 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200/70 dark:border-zinc-700/50 flex items-center justify-between"
              >
                <span className="text-xs text-slate-600 dark:text-zinc-400 font-medium">
                  {formatKeyLabel(key)}
                </span>
                <span className="text-xs font-bold text-slate-900 dark:text-zinc-100">
                  {val}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sections List */}
      {data.sections && data.sections.length > 0 && (
        <div data-testid="generic-sections" className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-400" />
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
              Identified Sections
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {data.sections.map((section, idx) => (
              <span
                key={idx}
                className="px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-700 dark:bg-zinc-800 dark:text-zinc-300 border border-slate-200 dark:border-zinc-700"
              >
                {section}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
