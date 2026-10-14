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
import {
  Globe,
  ShieldAlert,
  ShieldCheck,
  Lock,
  ExternalLink,
} from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';

export interface WebSearchResultSnippet {
  title: string;
  url: string;
  snippet: string;
}

export interface WebSearchPreviewData {
  sanitized_query: string;
  redacted_items: string[] | number;
  provider?: 'SearXNG' | 'Brave' | string;
  taint_active?: boolean;
  results?: WebSearchResultSnippet[];
}

export interface WebSearchPreviewCardProps {
  search: WebSearchPreviewData;
  className?: string;
}

export function WebSearchPreviewCard({
  search,
  className,
}: WebSearchPreviewCardProps) {
  const redactedCount = Array.isArray(search.redacted_items)
    ? search.redacted_items.length
    : Number(search.redacted_items || 0);

  const redactedLabels = Array.isArray(search.redacted_items)
    ? search.redacted_items
    : [];

  const providerLabel = search.provider || 'SearXNG';
  const taintActive = search.taint_active !== false;

  return (
    <div
      data-testid="web-search-preview-card"
      className={cn(
        'p-4 rounded-2xl border border-blue-200 dark:border-blue-900/60 bg-blue-50/40 dark:bg-blue-950/20 shadow-sm space-y-3 text-xs',
        className
      )}
    >
      {/* Header Row */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-blue-200/80 dark:border-blue-900/40">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-emerald-700 text-white flex items-center justify-center shrink-0">
            <Globe className="w-3.5 h-3.5" />
          </div>
          <div>
            <h4 className="font-bold text-sm text-[var(--cf-fg)]">
              Sanitised Clinical Web Search
            </h4>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <Badge
            data-testid="web-search-host-badge"
            variant="info"
            size="sm"
            icon={<Lock className="w-3 h-3" />}
          >
            {`Allowlisted Host: ${providerLabel}`}
          </Badge>

          <Badge
            data-testid="web-search-redacted-badge"
            variant="success"
            size="sm"
            icon={<ShieldCheck className="w-3 h-3" />}
          >
            {`${redactedCount} PII/PHI Redacted`}
          </Badge>

          {taintActive && (
            <Badge
              data-testid="web-search-taint-badge"
              variant="warning"
              size="sm"
              icon={<ShieldAlert className="w-3 h-3" />}
            >
              Untrusted External Source (Taint Active)
            </Badge>
          )}
        </div>
      </div>

      {/* Sanitised Query Box */}
      <div className="p-2.5 rounded-xl bg-[var(--cf-surface)] border border-[var(--cf-border)] space-y-1">
        <div className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-muted)]">
          Outbound Sanitised Query (Zero Raw PHI)
        </div>
        <div
          data-testid="web-search-sanitized-query"
          className="font-mono font-semibold text-xs text-[var(--cf-fg)]"
        >
          {search.sanitized_query}
        </div>
        {redactedLabels.length > 0 && (
          <div
            data-testid="web-search-redacted-items-list"
            className="text-xs text-[var(--cf-fg-muted)] pt-1"
          >
            Stripped tokens: {redactedLabels.join(', ')}
          </div>
        )}
      </div>

      {/* Results Preview if present */}
      {search.results && search.results.length > 0 && (
        <div className="space-y-1.5" data-testid="web-search-results-list">
          {search.results.map((r, idx) => (
            <div
              key={idx}
              className="p-2.5 rounded-lg bg-[var(--cf-surface)] border border-[var(--cf-border)] space-y-0.5"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-[var(--cf-fg)]">
                  {r.title}
                </span>
                {r.url && (
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 hover:underline text-xs"
                  >
                    Source
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
              <p className="text-xs text-[var(--cf-fg-muted)]">
                {r.snippet}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
