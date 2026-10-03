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

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { SuggestedQuestionsChips } from '@/components/SuggestedQuestionsChips';

describe('SuggestedQuestionsChips Component', () => {
  const suggestions = [
    'What should I bring to my appointment?',
    'Are there any dietary restrictions for this test?',
    'What insurance codes apply?'
  ];

  it('renders null when suggestions array is empty or undefined', () => {
    const { container: emptyContainer } = render(
      <SuggestedQuestionsChips suggestions={[]} onSelectSuggestion={vi.fn()} />
    );
    expect(emptyContainer.firstChild).toBeNull();

    const { container: nullContainer } = render(
      <SuggestedQuestionsChips suggestions={undefined as any} onSelectSuggestion={vi.fn()} />
    );
    expect(nullContainer.firstChild).toBeNull();
  });

  it('renders container and follow-up chips when suggestions are provided', () => {
    render(
      <SuggestedQuestionsChips
        suggestions={suggestions}
        onSelectSuggestion={vi.fn()}
      />
    );

    const container = screen.getByTestId('suggested-questions-container');
    expect(container).toBeInTheDocument();
    expect(screen.getByText('Suggested follow-ups:')).toBeInTheDocument();

    const chips = screen.getAllByTestId('suggested-question-chip');
    expect(chips).toHaveLength(3);
    expect(chips[0]).toHaveTextContent('What should I bring to my appointment?');
    expect(chips[1]).toHaveTextContent('Are there any dietary restrictions for this test?');
    expect(chips[2]).toHaveTextContent('What insurance codes apply?');
  });

  it('invokes onSelectSuggestion callback with exact question text upon chip click', () => {
    const handleSelect = vi.fn();
    render(
      <SuggestedQuestionsChips
        suggestions={suggestions}
        onSelectSuggestion={handleSelect}
      />
    );

    const secondChip = screen.getByText('Are there any dietary restrictions for this test?');
    fireEvent.click(secondChip);

    expect(handleSelect).toHaveBeenCalledTimes(1);
    expect(handleSelect).toHaveBeenCalledWith('Are there any dietary restrictions for this test?');
  });

  it('disables all chips when disabled prop is true', () => {
    render(
      <SuggestedQuestionsChips
        suggestions={suggestions}
        onSelectSuggestion={vi.fn()}
        disabled={true}
      />
    );

    const chips = screen.getAllByTestId('suggested-question-chip');
    chips.forEach((chip) => {
      expect(chip).toBeDisabled();
    });
  });
});
