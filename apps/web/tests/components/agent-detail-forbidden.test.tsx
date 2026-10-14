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
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { AgentDetailClient } from '@/app/agents/[id]/AgentDetailClient';
import type { AgentDetail } from '@/lib/types';

const mockAgent: AgentDetail = {
  id: 'cardiology-guide',
  title: 'Cardiology Guide',
  version: '0.1.0',
  model: 'llama3.2:3b',
  license: 'Apache-2.0',
  risk_class: 'clinical_assist',
  description: 'Helps users prepare for cardiology visits and understand cardiovascular terms.',
  persona: 'Role & Empathy: Cardiology guide.',
  skills: [
    {
      id: 'cardiology-prep',
      name: 'Cardiology Prep',
      version: '0.1.0',
      description: 'Cardiology visit agenda and symptom tracking.',
      risk_class: 'clinical_assist',
      tools: ['attach-read', 'skill-docs']
    },
    {
      id: 'emergency-red-flags',
      name: 'Emergency Red Flags',
      version: '0.1.0',
      description: 'Acute emergency escalation protocol.',
      risk_class: 'clinical_assist',
      tools: ['skill-docs']
    }
  ],
  effectiveTools: ['attach-read', 'skill-docs'],
  forbidden: ['diagnose', 'prescribe', 'dose', 'replace_emergency_care', 'custom_lab_alteration'],
  starters: ['What should I ask my cardiologist?']
};

describe('AgentDetailClient - Skills Links & Boundaries Panel', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders declared skills as interactive links to /skills/[id]', () => {
    render(<AgentDetailClient agent={mockAgent} />);

    const cardiologyLink = screen.getByTestId('agent-skill-link-cardiology-prep');
    expect(cardiologyLink).toHaveAttribute('href', '/skills/cardiology-prep');
    expect(cardiologyLink).toHaveTextContent('Cardiology Prep');

    const emergencyLink = screen.getByTestId('agent-skill-link-emergency-red-flags');
    expect(emergencyLink).toHaveAttribute('href', '/skills/emergency-red-flags');
    expect(emergencyLink).toHaveTextContent('Emergency Red Flags');
  });

  it('renders the "What this agent will and won\'t do" panel with positive capabilities', () => {
    render(<AgentDetailClient agent={mockAgent} />);

    const boundariesPanel = screen.getByTestId('agent-boundaries-panel');
    expect(boundariesPanel).toBeInTheDocument();

    expect(screen.getByText(/What this agent will and won't do/i)).toBeInTheDocument();
    expect(screen.getByText(/What this agent will help with/i)).toBeInTheDocument();

    // Positive capabilities include declared skills
    expect(within(boundariesPanel).getByText(/Cardiology Prep:/i)).toBeInTheDocument();
    expect(within(boundariesPanel).getByText(/Cardiology visit agenda and symptom tracking/i)).toBeInTheDocument();
  });

  it('renders plain-language translations for standard forbidden tokens', () => {
    render(<AgentDetailClient agent={mockAgent} />);

    const forbiddenList = screen.getByTestId('agent-forbidden-list');
    expect(forbiddenList).toBeInTheDocument();

    expect(screen.getByText('Diagnose a condition or tell you what illness you have.')).toBeInTheDocument();
    expect(screen.getByText('Prescribe, recommend, or switch medications or treatments.')).toBeInTheDocument();
    expect(screen.getByText('Tell you how much of a medication to take or how to change a dose.')).toBeInTheDocument();
    expect(
      screen.getByText('Replace emergency services or your care team in an urgent situation.')
    ).toBeInTheDocument();
  });

  it('gracefully humanizes unknown forbidden tokens with title-cased sentence', () => {
    render(<AgentDetailClient agent={mockAgent} />);

    // 'custom_lab_alteration' should be formatted as 'Custom lab alteration.'
    expect(screen.getByText('Custom lab alteration.')).toBeInTheDocument();
  });
});
