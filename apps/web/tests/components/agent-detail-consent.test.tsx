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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { AgentDetailClient } from '@/app/agents/[id]/AgentDetailClient';
import { toAgentPreview } from '@/lib/agentDetail';
import { grantClinicalConsent, hasClinicalConsent } from '@/lib/clinicalConsent';
import type { AgentSummary } from '@/lib/types';

const summary: AgentSummary = {
  id: 'cardiology-guide',
  title: 'Cardiology Guide',
  version: '0.1.0',
  risk_class: 'clinical_assist',
  skills: ['cardiology-prep'],
  effectiveTools: ['skill-docs'],
  starters: ['Help me prepare for my cardiology visit'],
  description: 'Helps you prepare for heart health appointments.',
  forbidden: ['diagnose']
};

const fullDetailPayload = {
  id: 'cardiology-guide',
  title: 'Cardiology Guide',
  version: '0.1.0',
  risk_class: 'clinical_assist',
  persona: { role: 'Guide', instructions: 'FULL PERSONA INSTRUCTIONS' },
  resolvedSkills: [{ id: 'cardiology-prep', name: 'Cardiology Prep', description: 'Prep skill', version: '1.0.0' }],
  effectiveTools: ['skill-docs'],
  starters: [],
  forbidden: ['diagnose']
};

describe('AgentDetailClient clinical consent (#87)', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('shows a read-only summary with a consent card and withholds the persona', async () => {
    const mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);

    render(<AgentDetailClient agent={toAgentPreview(summary)} consentRequired />);

    expect(await screen.findByTestId('agent-consent-required')).toHaveTextContent('read-only summary');
    expect(screen.getByTestId('agent-persona-withheld')).toBeInTheDocument();
    expect(screen.getByTestId('agent-try-chat-gated')).toBeInTheDocument();
    expect(screen.queryByTestId('clinical-consent-chip')).not.toBeInTheDocument();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('decline keeps the user on the page with an explanation', async () => {
    vi.stubGlobal('fetch', vi.fn());
    render(<AgentDetailClient agent={toAgentPreview(summary)} consentRequired />);

    fireEvent.click(screen.getByTestId('agent-try-chat-gated'));
    fireEvent.click(await screen.findByTestId('clinical-consent-decline'));

    await waitFor(() => expect(screen.queryByTestId('clinical-consent-dialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('agent-consent-required')).toHaveTextContent('You chose not to give consent.');
    expect(hasClinicalConsent('cardiology-guide')).toBe(false);
  });

  it('grant loads the full detail through the proxy with allow_clinical=true', async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fullDetailPayload), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );
    vi.stubGlobal('fetch', mockFetch);

    render(<AgentDetailClient agent={toAgentPreview(summary)} consentRequired />);
    fireEvent.click(await screen.findByTestId('agent-consent-review'));
    fireEvent.click(await screen.findByTestId('clinical-consent-ack'));
    fireEvent.click(screen.getByTestId('clinical-consent-accept'));

    expect(await screen.findByText('FULL PERSONA INSTRUCTIONS')).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledWith('/api/v1/agents/cardiology-guide?allow_clinical=true');
    expect(screen.getByTestId('clinical-consent-chip')).toBeInTheDocument();
    expect(screen.queryByTestId('agent-consent-required')).not.toBeInTheDocument();
  });

  it('with previously stored consent, upgrades to full detail automatically', async () => {
    grantClinicalConsent('cardiology-guide');
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fullDetailPayload), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );
    vi.stubGlobal('fetch', mockFetch);

    render(<AgentDetailClient agent={toAgentPreview(summary)} consentRequired />);

    expect(await screen.findByText('FULL PERSONA INSTRUCTIONS')).toBeInTheDocument();
    expect(screen.getByText('Cardiology Prep')).toBeInTheDocument();
  });

  it('non-gated agents render normally without any consent UI', () => {
    vi.stubGlobal('fetch', vi.fn());
    render(
      <AgentDetailClient
        agent={{ ...toAgentPreview({ ...summary, risk_class: 'wellness' }), persona: 'Wellness persona' }}
      />
    );
    expect(screen.getByText('Wellness persona')).toBeInTheDocument();
    expect(screen.queryByTestId('agent-consent-required')).not.toBeInTheDocument();
    expect(screen.queryByTestId('agent-try-chat-gated')).not.toBeInTheDocument();
  });
});
