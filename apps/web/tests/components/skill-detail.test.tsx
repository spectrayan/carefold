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
import { render, screen } from '@testing-library/react';
import { SkillDetailClient } from '@/app/skills/[id]/SkillDetailClient';
import type { SkillDetailResponse } from '@/types/api';

const mockDetail: SkillDetailResponse = {
  id: 'visit-prep',
  name: 'Visit Prep',
  description: 'Helps users prepare an organized agenda, questions, and symptom history.',
  version: '0.1.0',
  risk_class: 'wellness',
  domain: 'clinical',
  category: 'clinical.general',
  tools: ['attach-read', 'skill-docs'],
  forbidden: ['diagnose', 'prescribe', 'dose', 'replace_emergency_care', 'instruct_stop_medication'],
  instructions: '## Protocol\n1. Ask reason for visit\n2. Organize questions',
  references: ['checklist.md', 'symptom_log_template.md'],
  has_evals: true,
  is_verified: true
};

describe('SkillDetailClient Component (/skills/[id])', () => {
  it('renders skill title, version, badges, and breadcrumb link', () => {
    render(<SkillDetailClient skill={mockDetail} />);

    expect(screen.getByRole('heading', { level: 1, name: /Visit Prep/i })).toBeInTheDocument();
    expect(screen.getByText('v0.1.0')).toBeInTheDocument();
    expect(screen.getByTestId('skill-detail-verified')).toBeInTheDocument();
    expect(screen.getByTestId('skill-detail-evals')).toBeInTheDocument();

    const breadcrumb = screen.getByRole('link', { name: /Back to Skills catalog/i });
    expect(breadcrumb).toHaveAttribute('href', '/skills');
  });

  it('renders operating instructions content', () => {
    render(<SkillDetailClient skill={mockDetail} />);

    const instructions = screen.getByTestId('skill-instructions-content');
    expect(instructions).toHaveTextContent('## Protocol');
    expect(instructions).toHaveTextContent('1. Ask reason for visit');
  });

  it('renders bundled reference documents and permitted sandbox tools', () => {
    render(<SkillDetailClient skill={mockDetail} />);

    expect(screen.getByTestId('skill-references-list')).toBeInTheDocument();
    expect(screen.getByText('checklist.md')).toBeInTheDocument();
    expect(screen.getByText('symptom_log_template.md')).toBeInTheDocument();

    expect(screen.getByTestId('skill-tools-list')).toBeInTheDocument();
    expect(screen.getByText('attach-read')).toBeInTheDocument();
    expect(screen.getByText('skill-docs')).toBeInTheDocument();
  });

  it('renders forbidden intent guardrails with plain-language explanations', () => {
    render(<SkillDetailClient skill={mockDetail} />);

    const forbiddenPanel = screen.getByTestId('skill-forbidden-list');
    expect(forbiddenPanel).toBeInTheDocument();

    // Plain-language explanations
    expect(screen.getByText('Diagnose a condition or tell you what illness you have.')).toBeInTheDocument();
    expect(screen.getByText('Prescribe, recommend, or switch medications or treatments.')).toBeInTheDocument();
    expect(screen.getByText('Replace emergency services or your care team in an urgent situation.')).toBeInTheDocument();
  });

  it('handles empty reference documents gracefully', () => {
    const skillWithoutRefs: SkillDetailResponse = {
      ...mockDetail,
      id: 'habit-checkin',
      name: 'Habit Checkin',
      references: []
    };

    render(<SkillDetailClient skill={skillWithoutRefs} />);

    expect(screen.getByTestId('skill-references-empty')).toHaveTextContent(
      'No static reference documents declared for this skill.'
    );
    expect(screen.queryByTestId('skill-references-list')).not.toBeInTheDocument();
  });
});
