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
