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
