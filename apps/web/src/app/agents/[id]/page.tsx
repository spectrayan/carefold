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
import type { AgentDetail } from '@/lib/types';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentDetailPage({ params }: PageProps) {
  const { id } = await params;
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

  try {
    const res = await fetch(`${backendUrl}/api/agents/${id}?allow_clinical=true`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });

    if (!res.ok) {
      return notFound();
    }

    const data = await res.json();
    const personaStr =
      typeof data.persona === 'string'
        ? data.persona
        : data.persona?.instructions || `${data.persona?.role}: ${data.persona?.instructions}`;

    const agentDetail: AgentDetail = {
      id: data.id,
      title: data.title,
      version: data.version,
      license: data.license || 'Apache-2.0',
      risk_class: data.risk_class,
      model: typeof data.model === 'string' ? data.model : data.model?.name || 'llama3.2',
      skills: (data.resolvedSkills || []).map((s: any) => ({
        id: s.id,
        name: s.name,
        description: s.description,
        version: s.version || '0.1.0',
        risk_class: s.risk_class,
        tools: s.tools || []
      })),
      effectiveTools: data.effectiveTools || [],
      forbidden: data.forbidden || [
        'diagnose',
        'prescribe',
        'dose',
        'replace_emergency_care',
        'instruct_stop_medication'
      ],
      persona: personaStr,
      starters: data.starters || [],
      readmeText: data.readmeText || ''
    };

    return <AgentDetailClient agent={agentDetail} />;
  } catch {
    return notFound();
  }
}
