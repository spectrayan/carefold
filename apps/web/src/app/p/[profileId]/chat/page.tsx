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
