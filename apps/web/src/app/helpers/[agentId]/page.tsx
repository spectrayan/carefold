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
import AgentDetailPage from '@/app/agents/[id]/page';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ agentId: string }>;
}

export default async function HelperDetailPage({ params }: PageProps) {
  const { agentId } = await params;
  return <AgentDetailPage params={Promise.resolve({ id: agentId })} />;
}
