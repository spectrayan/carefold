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

import React, { Suspense } from 'react';
import { ChatStudioShell } from '@/components/chat/ChatStudioShell';
import type { AgentSummary } from '@/lib/types';

export const dynamic = 'force-dynamic';

async function getInstalledAgents(): Promise<AgentSummary[]> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  try {
    const res = await fetch(`${backendUrl}/api/v1/agents`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.error('Failed to fetch agents from backend:', err);
  }
  return [];
}

interface ProfileChatPageProps {
  params: Promise<{
    profileId: string;
  }>;
}

export default async function ProfileChatPage({ params }: ProfileChatPageProps) {
  const resolvedParams = await params;
  const profileId = resolvedParams?.profileId || 'me';
  const agents = await getInstalledAgents();

  return (
    <Suspense fallback={<div className="p-8 text-center text-slate-500">Loading consultation studio...</div>}>
      <ChatStudioShell profileId={profileId} initialAgents={agents} />
    </Suspense>
  );
}
