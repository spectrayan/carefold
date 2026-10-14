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
import { StartersChips } from '@/components/StartersChips';

describe('StartersChips Component (CF-S50)', () => {
  const starters = [
    'Help me prepare questions for my physical next week.',
    'Organize my symptoms into a timeline.'
  ];

  it('renders list of starter prompt buttons', () => {
    render(<StartersChips starters={starters} onSelectStarter={vi.fn()} />);

    expect(screen.getByText('Help me prepare questions for my physical next week.')).toBeInTheDocument();
    expect(screen.getByText('Organize my symptoms into a timeline.')).toBeInTheDocument();
  });

  it('invokes onSelectStarter callback when a chip is clicked', () => {
    const handleSelect = vi.fn();
    render(<StartersChips starters={starters} onSelectStarter={handleSelect} />);

    const firstChip = screen.getByText('Help me prepare questions for my physical next week.');
    fireEvent.click(firstChip);

    expect(handleSelect).toHaveBeenCalledWith('Help me prepare questions for my physical next week.', true);
  });

  it('renders null when starters array is empty', () => {
    const { container } = render(<StartersChips starters={[]} onSelectStarter={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });
});
