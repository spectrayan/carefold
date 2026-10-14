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

import React from 'react';
import { notFound } from 'next/navigation';
import { AgentDetailClient } from './AgentDetailClient';
import type { AgentSummary } from '@/lib/types';
import { toAgentDetail, toAgentPreview } from '@/lib/agentDetail';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentDetailPage({ params }: PageProps) {
  const { id } = await params;
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  try {
    // The server never has the user's consent (it lives in browser storage), so it
    // always requests without allow_clinical (#87).
    const res = await fetch(`${backendUrl}/api/v1/agents/${id}`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });

    if (res.status === 403) {
      // clinical_assist agent without consent: render a read-only summary instead.
      const listRes = await fetch(`${backendUrl}/api/v1/agents`, {
        headers: { Accept: 'application/json' },
        cache: 'no-store'
      });
      if (!listRes.ok) {
        return notFound();
      }
      const summaries: AgentSummary[] = await listRes.json();
      const summary = Array.isArray(summaries) ? summaries.find((a) => a.id === id) : undefined;
      if (!summary) {
        return notFound();
      }
      return <AgentDetailClient agent={toAgentPreview(summary)} consentRequired />;
    }

    if (!res.ok) {
      return notFound();
    }

    const data = await res.json();
    return <AgentDetailClient agent={toAgentDetail(data)} />;
  } catch {
    return notFound();
  }
}
