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

import type { AgentDetail, AgentSummary } from '@/lib/types';
import { DEFAULT_FORBIDDEN_INTENTS } from '@/lib/clinicalConsent';

/** Maps a backend `GET /api/agents/{id}` payload into the agent detail view model. */
export function toAgentDetail(data: any): AgentDetail {
  const personaStr =
    typeof data.persona === 'string'
      ? data.persona
      : data.persona?.instructions || `${data.persona?.role}: ${data.persona?.instructions}`;

  return {
    id: data.id,
    title: data.title,
    version: data.version,
    license: data.license || 'Apache-2.0',
    risk_class: data.risk_class,
    model: typeof data.model === 'string' ? data.model : data.model?.name || 'llama3.2',
    skills: (data.resolvedSkills || []).map((s: any) => ({
      id: s.id,
      name: s.name,
      title: s.title || s.name,
      description: s.description,
      version: s.version || '0.1.0',
      risk_class: s.risk_class,
      tools: s.tools || []
    })),
    effectiveTools: data.effectiveTools || [],
    forbidden: data.forbidden || [...DEFAULT_FORBIDDEN_INTENTS],
    persona: personaStr,
    starters: data.starters || [],
    readmeText: data.readmeText || '',
    description: data.personaSummary || data.description || ''
  };
}

/**
 * Builds a read-only preview from a public agent summary, used when the detail
 * endpoint is consent-gated (clinical_assist without consent). The persona is
 * intentionally omitted because the backend withholds it until consent.
 */
export function toAgentPreview(summary: AgentSummary): AgentDetail {
  return {
    id: summary.id,
    title: summary.title,
    version: summary.version,
    license: 'Apache-2.0',
    risk_class: summary.risk_class,
    model: '',
    skills: (summary.skills || []).map((skillId) => ({
      id: skillId,
      name: skillId,
      title: skillId.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      description: '',
      version: '',
      risk_class: summary.risk_class,
      tools: []
    })),
    effectiveTools: summary.effectiveTools || [],
    forbidden: summary.forbidden && summary.forbidden.length > 0 ? summary.forbidden : [...DEFAULT_FORBIDDEN_INTENTS],
    persona: '',
    starters: summary.starters || [],
    description: summary.description || ''
  };
}
