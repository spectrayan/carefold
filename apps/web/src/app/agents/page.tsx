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
import { AgentsClient } from './AgentsClient';
import type { AgentSummary } from '@/lib/types';
import type { SkillSummary } from '@/types/api';

export const dynamic = 'force-dynamic';

async function getAgentsData(): Promise<{
  agents: AgentSummary[];
  categories: Record<string, any> | null;
  skills: SkillSummary[];
}> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  const [agentsRes, catsRes, skillsRes] = await Promise.allSettled([
    fetch(`${backendUrl}/api/v1/agents`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    }),
    fetch(`${backendUrl}/api/v1/agents/categories`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    }),
    fetch(`${backendUrl}/api/v1/skills`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    })
  ]);

  const agents: AgentSummary[] =
    agentsRes.status === 'fulfilled' && agentsRes.value.ok
      ? await agentsRes.value.json()
      : [];
  const categories =
    catsRes.status === 'fulfilled' && catsRes.value.ok
      ? await catsRes.value.json()
      : null;
  const skills: SkillSummary[] =
    skillsRes.status === 'fulfilled' && skillsRes.value.ok
      ? await skillsRes.value.json()
      : [];

  return { agents, categories, skills };
}

export default async function AgentsPage() {
  const { agents, categories, skills } = await getAgentsData();

  return (
    <AgentsClient
      initialAgents={agents}
      initialCategories={categories}
      initialSkills={skills}
    />
  );
}
