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
