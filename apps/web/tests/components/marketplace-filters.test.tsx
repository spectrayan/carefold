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

import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import React from 'react';
import { MarketplaceClient } from '@/app/MarketplaceClient';
import type { AgentSummary } from '@/lib/types';

const testAgents: AgentSummary[] = [
  {
    id: 'visit-steward',
    title: 'Visit Steward',
    version: '0.1.0',
    description: 'Prepare for appointments and organize medical questions.',
    risk_class: 'clinical_assist',
    domain: 'clinical',
    category: 'clinical.general',
    care_stages: ['pre_visit', 'during_visit'],
    target_audience: ['patient_adult', 'caregiver'],
    tags: ['appointments', 'visit-prep'],
    icon: 'Stethoscope',
    skills: ['visit-prep'],
    effectiveTools: ['attach-read'],
    starters: ['Questions list'],
    startersCount: 1,
    isBundled: true,
    is_bundled: true,
    verified: true,
  },
  {
    id: 'benefits-guide',
    title: 'Benefits Guide',
    version: '0.1.0',
    description: 'Understand insurance coverage, copays, and claims.',
    risk_class: 'admin',
    domain: 'navigation',
    category: 'navigation.insurance',
    care_stages: ['pre_visit', 'post_visit', 'daily_living'],
    target_audience: ['patient_adult', 'caregiver'],
    tags: ['insurance', 'benefits'],
    icon: 'FileText',
    skills: ['benefits-explainer'],
    effectiveTools: ['attach-read'],
    starters: ['Coverage details'],
    startersCount: 1,
    isBundled: true,
    is_bundled: true,
    verified: true,
  },
  {
    id: 'habit-companion',
    title: 'Habit Companion',
    version: '0.1.0',
    description: 'Track daily wellness habits and routines.',
    risk_class: 'wellness',
    domain: 'wellness',
    category: 'wellness.habits',
    care_stages: ['daily_living'],
    target_audience: ['patient_adult'], // Intentionally no caregiver to test toggle exclusion
    tags: ['habits', 'health'],
    icon: 'HeartPulse',
    skills: ['habit-checkin'],
    effectiveTools: ['workspace-note'],
    starters: ['Log habit'],
    startersCount: 1,
    isBundled: true,
    is_bundled: true,
    verified: true,
  },
  {
    id: 'oncology-navigator',
    title: 'Oncology Navigator',
    version: '0.1.0',
    description: 'Specialized cancer care navigation.',
    risk_class: 'clinical_assist',
    domain: 'clinical',
    category: 'clinical.oncology',
    care_stages: ['pre_visit', 'during_visit', 'post_visit', 'follow_up'],
    target_audience: ['cancer_patient', 'caregiver'],
    tags: ['oncology', 'cancer'],
    icon: 'Shield',
    skills: ['oncology-prep'],
    effectiveTools: ['attach-read'],
    starters: ['Treatment options'],
    startersCount: 1,
    isBundled: true,
    is_bundled: true,
    verified: true,
  },
];

const mockCategoryResponse = {
  total: 4,
  domains: {
    clinical: { count: 2, categories: {} },
    navigation: { count: 1, categories: {} },
    wellness: { count: 1, categories: {} },
    therapy: { count: 0, categories: {} },
    education: { count: 0, categories: {} },
  },
};

describe('MarketplaceClient Data-Driven Filters', () => {
  it('hides domain filter pills with 0 matching agents on bundled workspace', () => {
    render(
      <MarketplaceClient
        initialAgents={testAgents}
        initialCategories={mockCategoryResponse}
      />
    );

    const domainContainer = screen.getByTestId('domain-filters');

    // Domains with count > 0 should be rendered
    expect(within(domainContainer).getByRole('button', { name: 'All Domains' })).toBeInTheDocument();
    expect(within(domainContainer).getByRole('button', { name: 'Clinical' })).toBeInTheDocument();
    expect(within(domainContainer).getByRole('button', { name: 'Navigation' })).toBeInTheDocument();
    expect(within(domainContainer).getByRole('button', { name: 'Wellness' })).toBeInTheDocument();

    // 0-count domains (Therapy, Education) must NOT be rendered
    expect(within(domainContainer).queryByRole('button', { name: 'Therapy' })).not.toBeInTheDocument();
    expect(within(domainContainer).queryByRole('button', { name: 'Education' })).not.toBeInTheDocument();
  });

  it('renders "When" care-stage filter pills and filters agents correctly', () => {
    render(<MarketplaceClient initialAgents={testAgents} />);

    const careStageContainer = screen.getByTestId('care-stage-filters');
    expect(careStageContainer).toBeInTheDocument();

    // Required stage pills
    expect(within(careStageContainer).getByRole('button', { name: 'All Stages' })).toBeInTheDocument();
    expect(within(careStageContainer).getByRole('button', { name: 'Before visit' })).toBeInTheDocument();
    expect(within(careStageContainer).getByRole('button', { name: 'During visit' })).toBeInTheDocument();
    expect(within(careStageContainer).getByRole('button', { name: 'After visit' })).toBeInTheDocument();
    expect(within(careStageContainer).getByRole('button', { name: 'Follow-up' })).toBeInTheDocument();
    expect(within(careStageContainer).getByRole('button', { name: 'Daily living' })).toBeInTheDocument();

    // Filter by "Follow-up" (only oncology-navigator has follow_up in testAgents)
    fireEvent.click(within(careStageContainer).getByRole('button', { name: 'Follow-up' }));
    expect(screen.getByText('Oncology Navigator')).toBeInTheDocument();
    expect(screen.queryByText('Visit Steward')).not.toBeInTheDocument();
    expect(screen.queryByText('Benefits Guide')).not.toBeInTheDocument();
    expect(screen.queryByText('Habit Companion')).not.toBeInTheDocument();

    // Reset to All Stages
    fireEvent.click(within(careStageContainer).getByRole('button', { name: 'All Stages' }));
    expect(screen.getByText('Visit Steward')).toBeInTheDocument();
    expect(screen.getByText('Habit Companion')).toBeInTheDocument();
  });

  it('renders "For caregivers" toggle switch and filters agents by target_audience', () => {
    render(<MarketplaceClient initialAgents={testAgents} />);

    const caregiverToggle = screen.getByTestId('caregiver-filter');
    expect(caregiverToggle).toBeInTheDocument();
    expect(caregiverToggle).toHaveAttribute('role', 'switch');
    expect(caregiverToggle).toHaveAttribute('aria-checked', 'false');

    // All 4 agents visible initially
    expect(screen.getByText('Habit Companion')).toBeInTheDocument();

    // Toggle on
    fireEvent.click(caregiverToggle);
    expect(caregiverToggle).toHaveAttribute('aria-checked', 'true');

    // Habit Companion has no caregiver audience, should be excluded
    expect(screen.queryByText('Habit Companion')).not.toBeInTheDocument();
    expect(screen.getByText('Visit Steward')).toBeInTheDocument();
    expect(screen.getByText('Benefits Guide')).toBeInTheDocument();
    expect(screen.getByText('Oncology Navigator')).toBeInTheDocument();

    // Toggle off
    fireEvent.click(caregiverToggle);
    expect(caregiverToggle).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByText('Habit Companion')).toBeInTheDocument();
  });

  it('combines multi-facet filters conjunctively (search + domain + risk + care stage + caregiver)', () => {
    render(<MarketplaceClient initialAgents={testAgents} />);

    // Filter by clinical domain
    const domainContainer = screen.getByTestId('domain-filters');
    fireEvent.click(within(domainContainer).getByRole('button', { name: 'Clinical' }));

    // Filter by "During visit"
    const careStageContainer = screen.getByTestId('care-stage-filters');
    fireEvent.click(within(careStageContainer).getByRole('button', { name: 'During visit' }));

    // Both Visit Steward and Oncology Navigator match
    expect(screen.getByText('Visit Steward')).toBeInTheDocument();
    expect(screen.getByText('Oncology Navigator')).toBeInTheDocument();
    expect(screen.queryByText('Benefits Guide')).not.toBeInTheDocument();

    // Add search term 'cancer'
    const searchInput = screen.getByPlaceholderText(/search agents/i);
    fireEvent.change(searchInput, { target: { value: 'cancer' } });

    // Only Oncology Navigator matches all criteria
    expect(screen.getByText('Oncology Navigator')).toBeInTheDocument();
    expect(screen.queryByText('Visit Steward')).not.toBeInTheDocument();
  });

  it('displays empty state with "Clear all filters" button and resets all active filters', () => {
    render(<MarketplaceClient initialAgents={testAgents} />);

    // Select domain Navigation
    const domainContainer = screen.getByTestId('domain-filters');
    fireEvent.click(within(domainContainer).getByRole('button', { name: 'Navigation' }));

    // Select Care stage "Follow-up" (Navigation agent Benefits Guide does not have follow_up)
    const careStageContainer = screen.getByTestId('care-stage-filters');
    fireEvent.click(within(careStageContainer).getByRole('button', { name: 'Follow-up' }));

    expect(screen.getByText('No agents found')).toBeInTheDocument();
    const clearBtn = screen.getByTestId('clear-all-filters-btn');
    expect(clearBtn).toBeInTheDocument();

    // Click clear all filters
    fireEvent.click(clearBtn);

    // All agents restored
    expect(screen.getByText('Visit Steward')).toBeInTheDocument();
    expect(screen.getByText('Benefits Guide')).toBeInTheDocument();
    expect(screen.getByText('Habit Companion')).toBeInTheDocument();
    expect(screen.getByText('Oncology Navigator')).toBeInTheDocument();
  });

  it('renders care stage labels and safety badges on agent cards', () => {
    render(<MarketplaceClient initialAgents={testAgents} />);

    // Care stage badges on cards
    const careStageBadges = screen.getAllByTestId('care-stage-badge');
    expect(careStageBadges.length).toBeGreaterThan(0);
    expect(careStageBadges.some((b) => b.textContent === 'Before visit')).toBe(true);

    const safetyBadges = screen.getAllByTestId('card-safety-badge');
    expect(safetyBadges.length).toBe(4);
  });

  it('gracefully falls back to deriving active domains from initialAgents when categories is null', () => {
    render(
      <MarketplaceClient
        initialAgents={testAgents}
        initialCategories={null}
      />
    );

    const domainContainer = screen.getByTestId('domain-filters');
    // Derived from testAgents: clinical, navigation, wellness
    expect(within(domainContainer).getByRole('button', { name: 'Clinical' })).toBeInTheDocument();
    expect(within(domainContainer).getByRole('button', { name: 'Navigation' })).toBeInTheDocument();
    expect(within(domainContainer).getByRole('button', { name: 'Wellness' })).toBeInTheDocument();
    expect(within(domainContainer).queryByRole('button', { name: 'Therapy' })).not.toBeInTheDocument();
    expect(within(domainContainer).queryByRole('button', { name: 'Education' })).not.toBeInTheDocument();
  });
});
