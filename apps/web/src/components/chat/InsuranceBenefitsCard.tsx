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
  ShieldCheck,
  DollarSign,
  Percent,
  FileCheck,
  AlertCircle,
  Copy,
  Check,
  Download,
  Info,
} from 'lucide-react';
import type { InsuranceBenefitsDossierData } from '@/lib/types';
import { downloadBlob } from '@/lib/dossierExport';
import { DOSSIER_PATIENT_DISCLAIMER } from './VisitPrepCard';

export interface InsuranceBenefitsCardProps {
  data: InsuranceBenefitsDossierData;
  agentTitle?: string;
  isGrounded?: boolean;
}

function formatServiceLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function InsuranceBenefitsCard({
  data,
  agentTitle,
  isGrounded,
}: InsuranceBenefitsCardProps) {
  const [copied, setCopied] = useState(false);

  const copayEntries = Object.entries(data.copays || {});

  const formatMarkdown = (): string => {
    const lines: string[] = [];
    lines.push('# Health Insurance Benefits Dossier');
    lines.push(`*${DOSSIER_PATIENT_DISCLAIMER}*`);
    lines.push('');
    lines.push('## Financial Cost-Sharing Metrics');
    lines.push(`- **Annual Deductible:** ${data.deductible || 'Not specified'}`);
    lines.push(`- **Out-of-Pocket Maximum:** ${data.out_of_pocket_maximum || 'Not specified'}`);
    lines.push(`- **Coinsurance:** ${data.coinsurance || 'Not specified'}`);
    lines.push('');
    if (copayEntries.length > 0) {
      lines.push('## Copayments');
      lines.push('| Service Category | Copay Amount |');
      lines.push('| :--- | :--- |');
      for (const [service, amount] of copayEntries) {
        lines.push(`| ${formatServiceLabel(service)} | ${amount} |`);
      }
      lines.push('');
    }
    if (data.in_out_network_rules) {
      lines.push('## In-Network & Out-of-Network Rules');
      lines.push(data.in_out_network_rules);
      lines.push('');
    }
    if (data.prior_authorization_flags && data.prior_authorization_flags.length > 0) {
      lines.push('## Prior Authorization Required');
      for (const flag of data.prior_authorization_flags) {
        lines.push(`- ${flag}`);
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
    downloadBlob(blob, `carefold-insurance-benefits-${dateStr}.md`);
  };

  return (
    <div
      data-testid="insurance-benefits-card"
      className="rounded-2xl border border-slate-200 dark:border-zinc-700/80 bg-white dark:bg-zinc-900/90 p-4 shadow-sm space-y-3.5 my-2 text-zinc-900 dark:text-zinc-100"
    >
      {/* Top Header Row with Icon, Title, & Action Buttons */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-100 dark:border-zinc-800">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400">
            <ShieldCheck className="w-4 h-4" aria-hidden="true" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-zinc-200">
                Insurance Benefits Summary
              </h3>
              {isGrounded !== undefined && (
                <span
                  data-testid="dossier-grounded-badge"
                  className={`inline-flex items-center text-[10px] font-medium px-1.5 py-0.5 rounded-md border ${
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
              <p className="text-[11px] text-slate-500 dark:text-zinc-400">
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
            aria-label="Copy insurance benefits dossier"
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 hover:bg-slate-100 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-200 transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                <span className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400">Copied!</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span className="text-[11px]">Copy</span>
              </>
            )}
          </button>

          <button
            type="button"
            data-testid="dossier-export-btn"
            onClick={handleExport}
            aria-label="Export insurance benefits dossier"
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-slate-50 hover:bg-slate-100 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-200 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span className="text-[11px]">Export</span>
          </button>
        </div>
      </div>

      {/* Mandatory Patient-Friendly Safety Disclaimer Banner */}
      <div
        data-testid="dossier-disclaimer-banner"
        className="flex items-center gap-2 p-2.5 rounded-xl border border-blue-200 dark:border-blue-900/60 bg-blue-50/70 dark:bg-blue-950/30 text-blue-900 dark:text-blue-200 text-xs"
      >
        <Info className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0" aria-hidden="true" />
        <p className="leading-snug">{DOSSIER_PATIENT_DISCLAIMER}</p>
      </div>

      {/* Top Financial Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <div
          data-testid="metric-deductible"
          className="p-3 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200/70 dark:border-zinc-700/50 space-y-1"
        >
          <div className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
            <DollarSign className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
            <span>Deductible</span>
          </div>
          <p className="text-base font-bold text-slate-900 dark:text-zinc-100">
            {data.deductible || 'Not specified'}
          </p>
        </div>

        <div
          data-testid="metric-oop-max"
          className="p-3 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200/70 dark:border-zinc-700/50 space-y-1"
        >
          <div className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
            <FileCheck className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />
            <span>Out-of-Pocket Max</span>
          </div>
          <p className="text-base font-bold text-slate-900 dark:text-zinc-100">
            {data.out_of_pocket_maximum || 'Not specified'}
          </p>
        </div>

        <div
          data-testid="metric-coinsurance"
          className="p-3 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200/70 dark:border-zinc-700/50 space-y-1"
        >
          <div className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
            <Percent className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
            <span>Coinsurance</span>
          </div>
          <p className="text-base font-bold text-slate-900 dark:text-zinc-100">
            {data.coinsurance || 'Not specified'}
          </p>
        </div>
      </div>

      {/* Copays Breakdown Table */}
      <div data-testid="insurance-copays-section" className="space-y-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
          Copayments Breakdown
        </span>
        {copayEntries.length === 0 ? (
          <p className="text-xs text-slate-500 dark:text-zinc-400 italic bg-slate-50 dark:bg-zinc-800/50 p-2.5 rounded-xl border border-slate-200/70 dark:border-zinc-700/50">
            No fixed copays specified in document.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200/70 dark:border-zinc-700/50">
            <table data-testid="copays-table" className="w-full text-xs text-left">
              <thead className="bg-slate-100/80 dark:bg-zinc-800/80 text-[11px] font-semibold text-slate-600 dark:text-zinc-300 uppercase tracking-wider">
                <tr>
                  <th scope="col" className="px-3 py-2">Service Category</th>
                  <th scope="col" className="px-3 py-2 text-right">Copay Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200/50 dark:divide-zinc-800">
                {copayEntries.map(([service, amount]) => (
                  <tr key={service} className="hover:bg-slate-50 dark:hover:bg-zinc-800/40">
                    <td className="px-3 py-2 font-medium text-slate-800 dark:text-zinc-200">
                      {formatServiceLabel(service)}
                    </td>
                    <td className="px-3 py-2 text-right font-semibold text-slate-900 dark:text-zinc-100">
                      {amount}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* In-Network vs Out-of-Network Rules */}
      {data.in_out_network_rules && (
        <div data-testid="network-rules" className="space-y-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
            Network Rules & Coverage
          </span>
          <p className="text-xs text-slate-700 dark:text-zinc-300 bg-slate-50 dark:bg-zinc-800/50 p-2.5 rounded-xl border border-slate-200/70 dark:border-zinc-700/50 leading-relaxed">
            {data.in_out_network_rules}
          </p>
        </div>
      )}

      {/* Prior Authorization Requirements */}
      {data.prior_authorization_flags && data.prior_authorization_flags.length > 0 && (
        <div data-testid="prior-auth-flags" className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <AlertCircle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
              Prior Authorization Required
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {data.prior_authorization_flags.map((flag, idx) => (
              <span
                key={idx}
                className="px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-900/60"
              >
                {flag}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
