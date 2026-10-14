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

import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import React from 'react';
import { MarketplaceClient } from '@/app/MarketplaceClient';
import type { AgentSummary } from '@/lib/types';

const mockAgents: AgentSummary[] = [
  {
    id: 'visit-steward',
    title: 'Visit Steward',
    version: '0.1.0',
    description: 'Prepare for appointments and organize medical questions.',
    risk_class: 'clinical_assist',
    domain: 'navigation',
    category: 'navigation.appointments',
    tags: ['appointments', 'visit-prep'],
    icon: 'Stethoscope',
    skills: ['visit-prep'],
    tools: ['attach-read', 'workspace-note'],
    effectiveTools: ['attach-read', 'workspace-note'],
    starters: ['Questions list'],
    startersCount: 1,
    isBundled: true,
    is_bundled: true,
    verified: true
  },
  {
    id: 'benefits-guide',
    title: 'Benefits Guide',
    version: '0.1.0',
    description: 'Understand insurance coverage, copays, and claims.',
    risk_class: 'admin',
    domain: 'navigation',
    category: 'navigation.insurance',
    tags: ['insurance', 'benefits'],
    icon: 'FileText',
    skills: ['benefits-explainer'],
    tools: ['attach-read'],
    effectiveTools: ['attach-read'],
    starters: ['Plan coverage'],
    startersCount: 1,
    isBundled: true,
    is_bundled: true,
    verified: true
  },
  {
    id: 'habit-companion',
    title: 'Habit Companion',
    version: '0.1.0',
    description: 'Track daily wellness habits and routines.',
    risk_class: 'wellness',
    domain: 'wellness',
    category: 'wellness.habits',
    tags: ['habits', 'health'],
    icon: 'HeartPulse',
    skills: ['habit-checkin'],
    tools: ['workspace-note'],
    effectiveTools: ['workspace-note'],
    starters: ['Log habit'],
    startersCount: 1,
    isBundled: false,
    is_bundled: false,
    verified: true
  }
];

describe('Marketplace Home Screen', () => {
  it('renders grid of installed agents with safety badges', () => {
    render(<MarketplaceClient initialAgents={mockAgents} />);

    expect(screen.getByText('Visit Steward')).toBeInTheDocument();
    expect(screen.getByText('Benefits Guide')).toBeInTheDocument();
    expect(screen.getByText('Habit Companion')).toBeInTheDocument();

    const safetyBadges = screen.getAllByTestId('card-safety-badge');
    expect(safetyBadges.length).toBeGreaterThanOrEqual(2);
  });

  it('renders "Try in chat" actions linking to /chat?agent=[id]', () => {
    render(<MarketplaceClient initialAgents={mockAgents} />);

    const tryLinks = screen.getAllByRole('link', { name: /try in chat/i });
    expect(tryLinks[0]).toHaveAttribute('href', expect.stringContaining('/chat?agent=visit-steward'));
  });

  it('filters agents by search keyword', () => {
    render(<MarketplaceClient initialAgents={mockAgents} />);

    const searchInput = screen.getByPlaceholderText(/search agents/i);
    fireEvent.change(searchInput, { target: { value: 'benefits' } });

    expect(screen.getByText('Benefits Guide')).toBeInTheDocument();
    expect(screen.queryByText('Visit Steward')).not.toBeInTheDocument();
  });

  it('displays streamlined badges on agent cards', () => {
    render(<MarketplaceClient initialAgents={mockAgents} />);

    const safetyBadges = screen.getAllByTestId('card-safety-badge');
    expect(safetyBadges.length).toBe(3);
    expect(safetyBadges.some((b) => b.textContent?.toLowerCase().includes('clinical assist'))).toBe(true);
    expect(safetyBadges.some((b) => b.textContent?.toLowerCase().includes('wellness'))).toBe(true);
  });

  it('renders domain filter tabs and filters agents by domain', () => {
    render(<MarketplaceClient initialAgents={mockAgents} />);

    const domainFiltersContainer = screen.getByTestId('domain-filters');

    // Filter by wellness
    const wellnessTab = within(domainFiltersContainer).getByRole('button', { name: 'Wellness' });
    fireEvent.click(wellnessTab);

    expect(screen.getByText('Habit Companion')).toBeInTheDocument();
    expect(screen.queryByText('Visit Steward')).not.toBeInTheDocument();
    expect(screen.queryByText('Benefits Guide')).not.toBeInTheDocument();

    // Filter by navigation
    const navTab = within(domainFiltersContainer).getByRole('button', { name: 'Navigation' });
    fireEvent.click(navTab);

    expect(screen.getByText('Visit Steward')).toBeInTheDocument();
    expect(screen.getByText('Benefits Guide')).toBeInTheDocument();
    expect(screen.queryByText('Habit Companion')).not.toBeInTheDocument();

    // Reset to all domains
    const allTab = within(domainFiltersContainer).getByRole('button', { name: 'All Domains' });
    fireEvent.click(allTab);

    expect(screen.getByText('Visit Steward')).toBeInTheDocument();
    expect(screen.getByText('Benefits Guide')).toBeInTheDocument();
    expect(screen.getByText('Habit Companion')).toBeInTheDocument();
  });

  it('renders dynamic Lucide icon specified by icon field', () => {
    const customAgent: AgentSummary = {
      id: 'custom-expert',
      title: 'Custom Expert',
      version: '0.1.0',
      description: 'Expert agent with custom icon',
      risk_class: 'wellness',
      domain: 'wellness',
      icon: 'Sparkles',
      skills: [],
      effectiveTools: [],
      starters: [],
    };

    const { container } = render(<MarketplaceClient initialAgents={[customAgent]} />);
    expect(container.querySelector('svg.lucide-sparkles')).toBeInTheDocument();
  });
});
