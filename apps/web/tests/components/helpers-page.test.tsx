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

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { HelpersClient } from '@/app/helpers/HelpersClient';
import type { AgentSummary } from '@/lib/types';
import type { SkillSummary } from '@/app/helpers/HelpersClient';

const mockAgents: AgentSummary[] = [
  {
    id: 'visit-steward',
    title: 'Visit Steward',
    version: '0.4.0',
    risk_class: 'clinical_assist',
    skills: ['visit-prep'],
    effectiveTools: ['attach-read', 'workspace-note'],
    starters: ['Help me prepare for my visit'],
    description: 'Prepares questions and checklists for upcoming clinical visits.'
  },
  {
    id: 'benefits-guide',
    title: 'Benefits Guide',
    version: '0.4.0',
    risk_class: 'admin',
    skills: ['benefits-explainer'],
    effectiveTools: ['attach-read'],
    starters: ['Explain my benefits'],
    description: 'Explains health insurance coverage, copays, and deductibles.'
  },
  {
    id: 'habit-companion',
    title: 'Habit Companion',
    version: '0.4.0',
    risk_class: 'wellness',
    skills: ['habit-checkin'],
    effectiveTools: ['workspace-note'],
    starters: ['Log my daily habit'],
    description: 'Gentle check-ins for health routines and daily living.'
  }
];

const mockSkills: SkillSummary[] = [
  {
    id: 'visit-prep',
    name: 'Clinical Visit Preparation',
    domain: 'clinical',
    risk_class: 'clinical_assist',
    description: 'Clinical guidelines and prompt templates for outpatient visit prep.',
    version: '1.0.0',
    tools: ['attach-read', 'workspace-note']
  },
  {
    id: 'benefits-explainer',
    name: 'Insurance Benefits Explainer',
    domain: 'navigation',
    risk_class: 'admin',
    description: 'Reference handbook on EOBs, copays, deductibles, and OOP maximums.',
    version: '1.0.0',
    tools: ['attach-read']
  }
];

describe('Helpers & Skills Catalog (/helpers)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders page header and search input with keyboard shortcut hint', () => {
    render(
      <HelpersClient initialAgents={mockAgents} initialSkills={mockSkills} />
    );

    expect(screen.getByRole('heading', { level: 1, name: /care helpers & skills/i })).toBeInTheDocument();
    const searchInput = screen.getByPlaceholderText(/search helpers or skills/i);
    expect(searchInput).toBeInTheDocument();
  });

  it('focuses search input when pressing "/" shortcut anywhere on the page', () => {
    render(
      <HelpersClient initialAgents={mockAgents} initialSkills={mockSkills} />
    );

    const searchInput = screen.getByPlaceholderText(/search helpers or skills/i);
    expect(document.activeElement).not.toBe(searchInput);

    fireEvent.keyDown(window, { key: '/' });
    expect(document.activeElement).toBe(searchInput);
  });

  it('toggles between Assistants and Skill Packs views via Segmented control', () => {
    render(
      <HelpersClient initialAgents={mockAgents} initialSkills={mockSkills} />
    );

    // Initial view: Assistants
    expect(screen.getByText('Visit Steward')).toBeInTheDocument();
    expect(screen.getByText('Benefits Guide')).toBeInTheDocument();

    // Click Skill Packs tab
    const skillsTab = screen.getByRole('radio', { name: /skill packs/i });
    fireEvent.click(skillsTab);

    // View switched to Skill Packs
    expect(screen.getByText('Clinical Visit Preparation')).toBeInTheDocument();
    expect(screen.getByText('Insurance Benefits Explainer')).toBeInTheDocument();
  });

  it('filters assistants by search query matching title or description', () => {
    render(
      <HelpersClient initialAgents={mockAgents} initialSkills={mockSkills} />
    );

    const searchInput = screen.getByPlaceholderText(/search helpers or skills/i);
    fireEvent.change(searchInput, { target: { value: 'insurance' } });

    expect(screen.getByText('Benefits Guide')).toBeInTheDocument();
    expect(screen.queryByText('Visit Steward')).not.toBeInTheDocument();
  });

  it('filters assistants by safety level dropdown', () => {
    render(
      <HelpersClient initialAgents={mockAgents} initialSkills={mockSkills} />
    );

    const riskSelect = screen.getByLabelText(/safety level/i);
    fireEvent.change(riskSelect, { target: { value: 'clinical_assist' } });

    expect(screen.getByText('Visit Steward')).toBeInTheDocument();
    expect(screen.queryByText('Habit Companion')).not.toBeInTheDocument();
    expect(screen.queryByText('Benefits Guide')).not.toBeInTheDocument();
  });

  it('renders 3-column clinical safety boundary card', () => {
    render(
      <HelpersClient initialAgents={mockAgents} initialSkills={mockSkills} />
    );

    expect(screen.getByRole('heading', { name: /how carefold helpers work safely/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /everyday wellness/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /paperwork & navigation/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /clinical visit preparation/i })).toBeInTheDocument();
  });

  it('renders empty state when search finds no matches', () => {
    render(
      <HelpersClient initialAgents={mockAgents} initialSkills={mockSkills} />
    );

    const searchInput = screen.getByPlaceholderText(/search helpers or skills/i);
    fireEvent.change(searchInput, { target: { value: 'nonexistent-helper-query-xyz' } });

    expect(screen.getByText(/no helpers found/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reset filters/i })).toBeInTheDocument();
  });
});
