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
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SkillsClient } from '@/app/skills/SkillsClient';
import type { SkillSummary } from '@/types/api';

const mockSkills: SkillSummary[] = [
  {
    id: 'visit-prep',
    name: 'Visit Prep',
    description: 'Helps users prepare an organized agenda for visits.',
    version: '0.1.0',
    risk_class: 'wellness',
    domain: 'clinical',
    category: 'clinical.general',
    tools: ['attach-read', 'skill-docs'],
    forbidden: ['diagnose', 'prescribe', 'dose'],
    has_evals: true,
    is_verified: true
  },
  {
    id: 'benefits-explainer',
    name: 'Benefits Explainer',
    description: 'Explains health insurance coverage and cost sharing.',
    version: '0.2.0',
    risk_class: 'admin',
    domain: 'navigation',
    category: 'navigation.insurance',
    tools: ['attach-read'],
    forbidden: ['prescribe'],
    has_evals: false,
    is_verified: true
  },
  {
    id: 'habit-checkin',
    name: 'Habit Checkin',
    description: 'Assists with daily healthy lifestyle habits.',
    version: '0.1.5',
    risk_class: 'wellness',
    domain: 'wellness',
    category: 'wellness.lifestyle',
    tools: [],
    forbidden: ['dose'],
    has_evals: true,
    is_verified: false
  },
  {
    id: '_template',
    name: 'Template Starter',
    description: 'Should never appear in the UI catalog.',
    version: '0.0.1',
    risk_class: 'wellness',
    domain: 'clinical',
    tools: []
  }
];

describe('SkillsClient Component (/skills catalog)', () => {
  it('renders skills catalog header, disclaimer banner, and production skills', () => {
    render(<SkillsClient initialSkills={mockSkills} />);

    expect(screen.getByRole('heading', { level: 1, name: /Skills Catalog/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /Clinical Safety Boundary/i })).toBeInTheDocument();

    // Production skills are visible
    expect(screen.getByText('Visit Prep')).toBeInTheDocument();
    expect(screen.getByText('Benefits Explainer')).toBeInTheDocument();
    expect(screen.getByText('Habit Checkin')).toBeInTheDocument();

    // Defensive check: _template is excluded
    expect(screen.queryByText('Template Starter')).not.toBeInTheDocument();
    expect(screen.queryByTestId('skill-card-_template')).not.toBeInTheDocument();
  });

  it('renders Verified and Has evals badges accurately', () => {
    render(<SkillsClient initialSkills={mockSkills} />);

    const verifiedBadges = screen.getAllByTestId('badge-verified');
    expect(verifiedBadges.length).toBe(2); // visit-prep, benefits-explainer

    const evalsBadges = screen.getAllByTestId('badge-has-evals');
    expect(evalsBadges.length).toBe(2); // visit-prep, habit-checkin
  });

  it('links each skill card to /skills/[id]', () => {
    render(<SkillsClient initialSkills={mockSkills} />);

    const visitPrepCard = screen.getByTestId('skill-card-visit-prep');
    expect(visitPrepCard).toHaveAttribute('href', '/skills/visit-prep');

    const benefitsCard = screen.getByTestId('skill-card-benefits-explainer');
    expect(benefitsCard).toHaveAttribute('href', '/skills/benefits-explainer');
  });

  it('filters skills by search keyword', () => {
    render(<SkillsClient initialSkills={mockSkills} />);

    const searchInput = screen.getByTestId('skills-search-input');
    fireEvent.change(searchInput, { target: { value: 'insurance' } });

    expect(screen.getByText('Benefits Explainer')).toBeInTheDocument();
    expect(screen.queryByText('Visit Prep')).not.toBeInTheDocument();
    expect(screen.queryByText('Habit Checkin')).not.toBeInTheDocument();

    // Clear search
    fireEvent.change(searchInput, { target: { value: '' } });
    expect(screen.getByText('Visit Prep')).toBeInTheDocument();
  });

  it('filters skills by domain tabs', () => {
    render(<SkillsClient initialSkills={mockSkills} />);

    const domainFilters = screen.getByTestId('skills-domain-filters');
    const clinicalBtn = Array.from(domainFilters.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Clinical'
    );
    expect(clinicalBtn).toBeDefined();

    fireEvent.click(clinicalBtn!);

    expect(screen.getByText('Visit Prep')).toBeInTheDocument();
    expect(screen.queryByText('Benefits Explainer')).not.toBeInTheDocument();
    expect(screen.queryByText('Habit Checkin')).not.toBeInTheDocument();
  });

  it('filters skills by risk class buttons', () => {
    render(<SkillsClient initialSkills={mockSkills} />);

    const riskFilters = screen.getByTestId('skills-risk-filters');
    const adminBtn = Array.from(riskFilters.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Admin'
    );
    expect(adminBtn).toBeDefined();

    fireEvent.click(adminBtn!);

    expect(screen.getByText('Benefits Explainer')).toBeInTheDocument();
    expect(screen.queryByText('Visit Prep')).not.toBeInTheDocument();
    expect(screen.queryByText('Habit Checkin')).not.toBeInTheDocument();
  });

  it('displays empty state with reset button when no skills match', () => {
    render(<SkillsClient initialSkills={mockSkills} />);

    const searchInput = screen.getByTestId('skills-search-input');
    fireEvent.change(searchInput, { target: { value: 'nonexistent-query-xyz' } });

    expect(screen.getByTestId('skills-empty-state')).toBeInTheDocument();
    expect(screen.getByText(/No matching skills found/i)).toBeInTheDocument();

    const resetBtn = screen.getByRole('button', { name: /Reset all filters/i });
    fireEvent.click(resetBtn);

    expect(screen.getByText('Visit Prep')).toBeInTheDocument();
    expect(screen.getByText('Benefits Explainer')).toBeInTheDocument();
  });
});
