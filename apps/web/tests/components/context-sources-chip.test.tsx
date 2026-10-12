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
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ContextSourcesChip } from '@/components/chat/ContextSourcesChip';
import type { ContextSourceItem } from '@/lib/types';

describe('ContextSourcesChip Component (AU-20)', () => {
  const sampleSources: ContextSourceItem[] = [
    {
      id: 'src-1',
      type: 'thread',
      label: 'Visit Thread History',
      description: 'Prior conversational context'
    },
    {
      id: 'src-2',
      type: 'attachments',
      label: 'Blood_Panel_2026.pdf',
      description: 'Extracted patient lab report',
      has_phi: true
    },
    {
      id: 'src-3',
      type: 'connector',
      label: 'MyChart Portal',
      description: 'Encrypted EHR records feed',
      is_tainted: true
    }
  ];

  it('renders collapsed chip with count by default', () => {
    render(<ContextSourcesChip sources={sampleSources} />);

    expect(screen.getByTestId('context-sources-chip-button')).toHaveTextContent('3 Sources');
    expect(screen.queryByTestId('context-sources-popover')).not.toBeInTheDocument();
  });

  it('displays Tainted badge when monotone taint is active', () => {
    render(<ContextSourcesChip sources={sampleSources} isTainted={true} />);

    expect(screen.getByTestId('context-taint-badge')).toHaveTextContent('Tainted');
  });

  it('displays PHI badge when context contains PHI and not tainted', () => {
    render(<ContextSourcesChip sources={sampleSources} hasPhi={true} isTainted={false} />);

    expect(screen.getByTestId('context-phi-badge')).toHaveTextContent('PHI');
  });

  it('opens popover dialog on click and displays source items', () => {
    render(<ContextSourcesChip sources={sampleSources} isTainted={true} />);

    fireEvent.click(screen.getByTestId('context-sources-chip-button'));

    expect(screen.getByTestId('context-sources-popover')).toBeInTheDocument();
    expect(screen.getByTestId('taint-warning-banner')).toBeInTheDocument();
    expect(screen.getByText('Blood_Panel_2026.pdf')).toBeInTheDocument();
    expect(screen.getByText('MyChart Portal')).toBeInTheDocument();
    expect(screen.getAllByTestId('context-source-item')).toHaveLength(3);
  });
});
