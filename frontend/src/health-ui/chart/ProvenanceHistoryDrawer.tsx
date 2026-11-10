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

import React, { useEffect } from 'react';
import {
  X,
  History,
  ShieldCheck,
  Code2,
  GitMerge,
  Clock,
  FileCheck2,
} from 'lucide-react';
import { Badge, type BadgeVariant } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { cn } from '../../lib/utils';
import { formatProvenanceBadge } from '../../lib/ehrChartClient';
import type { EhrClinicalItemBase, EhrResourceRevision } from '../../types/ehrChart';

export interface ProvenanceHistoryDrawerProps {
  item: EhrClinicalItemBase | null;
  revisions?: EhrResourceRevision[];
  onClose: () => void;
  className?: string;
}

function revisionBadgeVariant(operation: EhrResourceRevision['operation']): BadgeVariant {
  if (operation === 'CREATE') return 'success';
  if (operation === 'MERGE') return 'warning';
  return 'info';
}

export function ProvenanceHistoryDrawer({
  item,
  revisions,
  onClose,
  className,
}: ProvenanceHistoryDrawerProps) {
  useEffect(() => {
    if (!item) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [item, onClose]);

  if (!item) return null;

  const historyList = revisions && revisions.length > 0 ? revisions : item.history;

  return (
    <aside
      aria-labelledby="provenance-drawer-title"
      data-testid="provenance-history-drawer"
      className={cn(
        'fixed inset-block-0 inset-inline-end-0 z-40 w-full max-w-lg bg-[var(--cf-surface)] border-s border-[var(--cf-border)] shadow-xl flex flex-col text-start overscroll-contain',
        className
      )}
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-[var(--cf-border)] bg-[var(--cf-surface-2)] flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="info" size="sm" data-testid="drawer-resource-reference">
              {item.resourceType}/{item.id}
            </Badge>
            <Badge variant="neutral" size="sm" data-testid="drawer-current-version">
              ETag W/&quot;{item.provenance.versionId}&quot;
            </Badge>
          </div>
          <h2 id="provenance-drawer-title" className="text-base font-bold text-[var(--cf-fg)]">
            {item.title}
          </h2>
          <p className="text-xs text-[var(--cf-fg-muted)]">
            Source Provenance, Canonical Terminology &amp; Immutable <code className="font-mono">_history</code>
          </p>
        </div>

        <Button
          variant="ghost"
          size="sm"
          aria-label="Close provenance and history drawer"
          data-testid="close-provenance-drawer-btn"
          onClick={onClose}
        >
          <X className="w-4 h-4" aria-hidden="true" />
        </Button>
      </div>

      {/* Scrollable Inspector Body */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* 1. Source Lineage & Trust Boundary */}
        <section
          aria-labelledby="drawer-provenance-heading"
          data-testid="drawer-provenance-section"
          className="p-4 rounded-[var(--cf-radius-md)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-2.5"
        >
          <div className="flex items-center justify-between gap-2">
            <h3
              id="drawer-provenance-heading"
              className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-muted)] flex items-center gap-1.5"
            >
              <FileCheck2 className="w-3.5 h-3.5 text-[var(--cf-primary)]" aria-hidden="true" />
              Source Lineage (Provenance)
            </h3>
            <Badge
              variant={item.provenance.trustBoundary === 'verified_user' ? 'success' : 'warning'}
              size="sm"
              data-testid="drawer-trust-badge"
            >
              <ShieldCheck className="w-3 h-3 me-1 inline" aria-hidden="true" />
              {item.provenance.trustBoundary === 'verified_user'
                ? 'Verified User Entry'
                : 'External Import (Taint Guarded)'}
            </Badge>
          </div>

          <p
            data-testid="drawer-provenance-citation"
            className="text-sm font-semibold text-[var(--cf-fg)]"
          >
            {formatProvenanceBadge(item.provenance.sourceName, item.provenance.recordedDate)}
          </p>

          <div className="text-xs text-[var(--cf-fg-muted)] space-y-1">
            <p>
              Ingest Format: <span className="font-medium text-[var(--cf-fg)]">{item.provenance.sourceFormat}</span>
            </p>
            <p>
              Last Updated:{' '}
              <span className="font-mono text-[var(--cf-fg)]">{item.provenance.lastUpdated}</span>
            </p>
            {item.provenance.mergedPortals && item.provenance.mergedPortals.length > 1 && (
              <p
                data-testid="drawer-merged-portals"
                className="flex items-center gap-1.5 text-[var(--cf-warn-fg)] font-medium pt-1"
              >
                <GitMerge className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                Deduplicated across: {item.provenance.mergedPortals.join(' + ')}
              </p>
            )}
          </div>
        </section>

        {/* 2. Terminology Coding Badges */}
        <section
          aria-labelledby="drawer-terminology-heading"
          data-testid="drawer-terminology-section"
          className="space-y-2.5"
        >
          <h3
            id="drawer-terminology-heading"
            className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-muted)] flex items-center gap-1.5"
          >
            <Code2 className="w-3.5 h-3.5 text-[var(--cf-primary)]" aria-hidden="true" />
            Canonical Terminology Codings
          </h3>

          <div className="space-y-2">
            {item.codings.map((coding) => (
              <div
                key={`${coding.systemLabel}-${coding.code}`}
                data-testid={`drawer-coding-item-${coding.systemLabel}-${coding.code}`}
                className="p-3 rounded-[var(--cf-radius-md)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-1"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Badge variant="info" size="sm">
                    {coding.systemLabel} · {coding.code}
                  </Badge>
                  {coding.wasNormalized && (
                    <Badge variant="success" size="sm">
                      Normalized from {coding.originalSystem}
                    </Badge>
                  )}
                </div>
                <p className="text-xs font-medium text-[var(--cf-fg)]">{coding.display}</p>
                <p className="text-xs font-mono text-[var(--cf-fg-subtle)]">{coding.systemUri}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 3. Immutable Resource Version History (_history) */}
        <section
          aria-labelledby="drawer-history-heading"
          data-testid="drawer-history-section"
          className="space-y-3"
        >
          <h3
            id="drawer-history-heading"
            className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-muted)] flex items-center gap-1.5"
          >
            <History className="w-3.5 h-3.5 text-[var(--cf-primary)]" aria-hidden="true" />
            Immutable Version History (<code className="font-mono">_history</code>)
          </h3>

          <ol className="space-y-2.5" data-testid="drawer-history-list">
            {historyList.map((rev) => (
              <li
                key={`rev-${rev.versionId}`}
                data-testid={`drawer-history-version-${rev.versionId}`}
                className="p-3.5 rounded-[var(--cf-radius-md)] bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-1.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge variant={revisionBadgeVariant(rev.operation)} size="sm">
                      v{rev.versionId} · {rev.operation}
                    </Badge>
                    <span className="text-xs font-mono text-[var(--cf-fg-subtle)]">
                      {rev.etag}
                    </span>
                  </div>
                  <span className="text-xs text-[var(--cf-fg-subtle)] inline-flex items-center gap-1">
                    <Clock className="w-3 h-3" aria-hidden="true" />
                    {rev.recordedAt.slice(0, 10)}
                  </span>
                </div>
                <p className="text-xs text-[var(--cf-fg)]">{rev.summary}</p>
                <p className="text-xs text-[var(--cf-fg-subtle)]">
                  Actor: {rev.actorDisplay} · Source: {rev.sourceName}
                </p>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </aside>
  );
}
