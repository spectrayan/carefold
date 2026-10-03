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

describe('Adversarial Stress Suite: Marketplace UI & Icon Resolution', () => {
  const baseAgent: AgentSummary = {
    id: 'test-agent',
    title: 'Test Agent',
    version: '1.0.0',
    description: 'A test agent for adversarial validation.',
    risk_class: 'wellness',
    domain: 'wellness',
    category: 'wellness.habits',
    tags: ['test', 'habits'],
    icon: 'Shield',
    skills: ['habit-tracking'],
    tools: ['workspace-note'],
    effectiveTools: ['workspace-note'],
    starters: ['Start habit'],
    startersCount: 1,
    isBundled: true,
    is_bundled: true,
    verified: true,
  };

  describe('1. Dynamic Lucide Icon Resolution & Robustness', () => {
    it('handles non-existent icon gracefully (falls back to default without crashing)', () => {
      const agentWithBogusIcon: AgentSummary = {
        ...baseAgent,
        id: 'bogus-icon-agent',
        title: 'Bogus Icon Agent',
        icon: 'NonExistentIconXYZ123',
      };

      const { container } = render(<MarketplaceClient initialAgents={[agentWithBogusIcon]} />);
      expect(screen.getByText('Bogus Icon Agent')).toBeInTheDocument();
      // Should fall back to Shield icon
      const svg = container.querySelector('svg.lucide-shield');
      expect(svg).toBeInTheDocument();
    });

    it('handles empty string icon cleanly (falls back to default Shield)', () => {
      const agentWithEmptyIcon: AgentSummary = {
        ...baseAgent,
        id: 'empty-icon-agent',
        title: 'Empty Icon Agent',
        icon: '',
      };

      const { container } = render(<MarketplaceClient initialAgents={[agentWithEmptyIcon]} />);
      expect(screen.getByText('Empty Icon Agent')).toBeInTheDocument();
      const svg = container.querySelector('svg.lucide-shield');
      expect(svg).toBeInTheDocument();
    });

    it('handles undefined icon cleanly (falls back to default Shield)', () => {
      const agentWithUndefinedIcon: AgentSummary = {
        ...baseAgent,
        id: 'undefined-icon-agent',
        title: 'Undefined Icon Agent',
        icon: undefined,
      };

      const { container } = render(<MarketplaceClient initialAgents={[agentWithUndefinedIcon]} />);
      expect(screen.getByText('Undefined Icon Agent')).toBeInTheDocument();
      const svg = container.querySelector('svg.lucide-shield');
      expect(svg).toBeInTheDocument();
    });

    it('falls back to custom ID icons when icon is undefined or empty', () => {
      const visitStewardAgent: AgentSummary = {
        ...baseAgent,
        id: 'visit-steward',
        title: 'Visit Steward',
        icon: undefined,
      };
      const benefitsGuideAgent: AgentSummary = {
        ...baseAgent,
        id: 'benefits-guide',
        title: 'Benefits Guide',
        icon: '',
      };
      const habitCompanionAgent: AgentSummary = {
        ...baseAgent,
        id: 'habit-companion',
        title: 'Habit Companion',
        icon: undefined,
      };

      const { container } = render(
        <MarketplaceClient initialAgents={[visitStewardAgent, benefitsGuideAgent, habitCompanionAgent]} />
      );

      expect(container.querySelector('svg.lucide-stethoscope')).toBeInTheDocument();
      expect(container.querySelector('svg.lucide-file-text')).toBeInTheDocument();
      expect(container.querySelector('svg.lucide-heart-pulse')).toBeInTheDocument();
    });

    it('handles undefined or null domain and category without crashing and hides badges', () => {
      const agentWithMissingMetadata: AgentSummary = {
        ...baseAgent,
        id: 'missing-meta-agent',
        title: 'Missing Meta Agent',
        domain: undefined,
        category: undefined,
      };

      const { rerender } = render(<MarketplaceClient initialAgents={[agentWithMissingMetadata]} />);
      expect(screen.getByText('Missing Meta Agent')).toBeInTheDocument();
      expect(screen.queryByTestId('domain-badge')).not.toBeInTheDocument();
      expect(screen.queryByTestId('category-badge')).not.toBeInTheDocument();

      // Test with null values coerced as any
      const agentWithNullMetadata: AgentSummary = {
        ...baseAgent,
        id: 'null-meta-agent',
        title: 'Null Meta Agent',
        domain: null as any,
        category: null as any,
      };

      rerender(<MarketplaceClient initialAgents={[agentWithNullMetadata]} />);
      expect(screen.getByText('Null Meta Agent')).toBeInTheDocument();
      expect(screen.queryByTestId('domain-badge')).not.toBeInTheDocument();
      expect(screen.queryByTestId('category-badge')).not.toBeInTheDocument();
    });

    it('challenges built-in Object properties as icon names (e.g. constructor, toString)', () => {
      // In JS ES Modules, namespace objects (import * as LucideIcons) have a null prototype ([Module: null prototype]),
      // so 'constructor' in LucideIcons evaluates to false and safely falls back without throwing!
      const agentWithConstructorIcon: AgentSummary = {
        ...baseAgent,
        id: 'constructor-icon-agent',
        title: 'Constructor Icon Agent',
        icon: 'constructor',
      };

      const { container } = render(<MarketplaceClient initialAgents={[agentWithConstructorIcon]} />);
      expect(screen.getByText('Constructor Icon Agent')).toBeInTheDocument();
      expect(container.querySelector('svg.lucide-shield')).toBeInTheDocument();
    });

    it('challenges non-icon exports like createLucideIcon', () => {
      const agentWithCreateLucideIcon: AgentSummary = {
        ...baseAgent,
        id: 'helper-fn-icon-agent',
        title: 'Helper Fn Icon Agent',
        icon: 'createLucideIcon',
      };

      let errorCaught: any = null;
      try {
        render(<MarketplaceClient initialAgents={[agentWithCreateLucideIcon]} />);
      } catch (e) {
        errorCaught = e;
      }
      expect(errorCaught).not.toBeNull();
      // createLucideIcon is a factory function returning {$$typeof, render}; rendering it as a component produces this React error
      expect(String(errorCaught)).toContain('Objects are not valid as a React child');
    });
  });

  describe('2. Domain Filtering & Multi-Filter Combinations', () => {
    const agentsList: AgentSummary[] = [
      {
        id: 'visit-steward',
        title: 'Visit Steward',
        version: '0.1.0',
        description: 'Prepare for appointments and clinical questions.',
        risk_class: 'clinical_assist',
        domain: 'clinical',
        category: 'clinical.appointments',
        tags: ['appointments', 'clinical'],
        icon: 'Stethoscope',
        skills: ['appointment-prep'],
        effectiveTools: ['attach-read'],
        starters: ['What to ask?'],
      },
      {
        id: 'benefits-guide',
        title: 'Benefits Guide',
        version: '0.1.0',
        description: 'Understand insurance coverage, copays, and claims.',
        risk_class: 'admin',
        domain: 'navigation',
        category: 'navigation.insurance',
        tags: ['insurance', 'claims'],
        icon: 'FileText',
        skills: ['benefits-explainer'],
        effectiveTools: ['attach-read'],
        starters: ['Deductible?'],
      },
      {
        id: 'habit-companion',
        title: 'Habit Companion',
        version: '0.1.0',
        description: 'Track daily wellness habits and routines.',
        risk_class: 'wellness',
        domain: 'wellness',
        category: 'wellness.habits',
        tags: ['habits'],
        icon: 'HeartPulse',
        skills: ['habit-tracker'],
        effectiveTools: ['workspace-note'],
        starters: ['Log habit'],
      },
      {
        id: 'therapy-journal',
        title: 'Therapy Journal',
        version: '0.1.0',
        description: 'Guided journaling and reflection prompts for therapy.',
        risk_class: 'wellness',
        domain: 'therapy',
        category: 'therapy.journaling',
        tags: ['journaling'],
        icon: 'BookOpen',
        skills: ['journal-prompts'],
        effectiveTools: ['workspace-note'],
        starters: ['Reflect'],
      },
    ];

    it('renders empty state cleanly when selecting a domain with 0 matching agents', () => {
      render(<MarketplaceClient initialAgents={agentsList} />);

      const domainContainer = screen.getByTestId('domain-filters');
      const educationTab = within(domainContainer).getByRole('button', { name: 'Education' });

      // Click domain 'Education' (none in agentsList has domain education)
      fireEvent.click(educationTab);

      expect(screen.getByText('No agents found')).toBeInTheDocument();
      expect(screen.getByText('Try adjusting your search terms or filters.')).toBeInTheDocument();
      expect(screen.getByText('carefold agent add visit-steward')).toBeInTheDocument();
      expect(screen.queryByText('Visit Steward')).not.toBeInTheDocument();
      expect(screen.queryByText('Benefits Guide')).not.toBeInTheDocument();
      expect(screen.queryByText('Habit Companion')).not.toBeInTheDocument();
      expect(screen.queryByText('Therapy Journal')).not.toBeInTheDocument();
    });

    it('simultaneously combines domain filter + search keyword filter + risk_class filter', () => {
      render(<MarketplaceClient initialAgents={agentsList} />);

      const domainContainer = screen.getByTestId('domain-filters');
      const riskContainer = screen.getByTestId('risk-filters');
      const searchInput = screen.getByPlaceholderText(/search agents/i);

      // Step 1: Filter domain to Navigation
      const navTab = within(domainContainer).getByRole('button', { name: 'Navigation' });
      fireEvent.click(navTab);

      expect(screen.getByText('Benefits Guide')).toBeInTheDocument();
      expect(screen.queryByText('Visit Steward')).not.toBeInTheDocument();
      expect(screen.queryByText('Habit Companion')).not.toBeInTheDocument();

      // Step 2: Filter risk class to 'Admin'
      const adminRisk = within(riskContainer).getByRole('button', { name: 'Admin' });
      fireEvent.click(adminRisk);

      expect(screen.getByText('Benefits Guide')).toBeInTheDocument();

      // Step 3: Add search keyword matching 'claims'
      fireEvent.change(searchInput, { target: { value: 'claims' } });

      expect(screen.getByText('Benefits Guide')).toBeInTheDocument();

      // Step 4: Add search keyword that does NOT match ('dental')
      fireEvent.change(searchInput, { target: { value: 'dental' } });

      expect(screen.queryByText('Benefits Guide')).not.toBeInTheDocument();
      expect(screen.getByText('No agents found')).toBeInTheDocument();

      // Step 5: Switch risk filter to 'Wellness' while domain is 'Navigation' and search is 'insurance'
      fireEvent.change(searchInput, { target: { value: 'insurance' } });
      const wellnessRisk = within(riskContainer).getByRole('button', { name: 'Wellness' });
      fireEvent.click(wellnessRisk);

      // No agent has domain=Navigation AND risk_class=wellness AND search='insurance'
      expect(screen.queryByText('Benefits Guide')).not.toBeInTheDocument();
      expect(screen.getByText('No agents found')).toBeInTheDocument();

      // Step 6: Reset risk to 'All Agents' and clear search
      const allRisk = within(riskContainer).getByRole('button', { name: 'All Agents' });
      fireEvent.click(allRisk);
      fireEvent.change(searchInput, { target: { value: '' } });

      // Now Benefits Guide should reappear (domain=Navigation)
      expect(screen.getByText('Benefits Guide')).toBeInTheDocument();
    });

    it('filters case-insensitively for domain (e.g. UPPERCASE vs lowercase)', () => {
      const agentWithMixedCaseDomain: AgentSummary = {
        ...baseAgent,
        id: 'mixed-case-agent',
        title: 'Mixed Case Domain Agent',
        domain: 'WELLNESS' as any,
      };

      render(<MarketplaceClient initialAgents={[agentWithMixedCaseDomain]} />);

      const domainContainer = screen.getByTestId('domain-filters');
      const wellnessTab = within(domainContainer).getByRole('button', { name: 'Wellness' });
      fireEvent.click(wellnessTab);

      expect(screen.getByText('Mixed Case Domain Agent')).toBeInTheDocument();
    });

    it('excludes hidden agents even if they match filters', () => {
      const hiddenAgent: AgentSummary = {
        ...baseAgent,
        id: 'hidden-agent',
        title: 'Hidden Agent',
        hidden: true,
      };

      render(<MarketplaceClient initialAgents={[hiddenAgent]} />);

      expect(screen.queryByText('Hidden Agent')).not.toBeInTheDocument();
      expect(screen.getByText('No agents found')).toBeInTheDocument();
    });

    it('renders unverified agent with distinct warning border and badge', () => {
      const unverifiedAgent: AgentSummary = {
        ...baseAgent,
        id: 'unverified-agent',
        title: 'Unverified Agent',
        verified: false,
      };

      render(<MarketplaceClient initialAgents={[unverifiedAgent]} />);

      expect(screen.getByText('Unverified Agent')).toBeInTheDocument();
      expect(screen.getByText('Unverified')).toBeInTheDocument();
    });

    it('renders agent without skills or tools showing fallback "None" labels', () => {
      const bareAgent: AgentSummary = {
        id: 'bare-agent',
        title: 'Bare Agent',
        version: '0.1.0',
        risk_class: 'wellness',
        skills: [],
        effectiveTools: [],
        tools: [],
        starters: [],
      };

      render(<MarketplaceClient initialAgents={[bareAgent]} />);

      expect(screen.getByText('Bare Agent')).toBeInTheDocument();
      const noneLabels = screen.getAllByText('None');
      expect(noneLabels.length).toBe(2); // One for Skills, one for Tools
    });
  });
});
