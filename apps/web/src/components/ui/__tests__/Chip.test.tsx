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
import * as React from 'react';
import { Chip, ChipVariant } from '../Chip';

describe('Chip Primitive', () => {
  it('renders default chip with label', () => {
    render(<Chip>Cardiology</Chip>);
    const chip = screen.getByRole('button', { name: /cardiology/i });
    expect(chip).toBeInTheDocument();
  });

  it('handles toggle selection with aria-pressed', () => {
    const { rerender } = render(<Chip selected={false}>Filter</Chip>);
    const chip = screen.getByRole('button', { name: /filter/i });
    expect(chip).toHaveAttribute('aria-pressed', 'false');

    rerender(<Chip selected={true}>Filter</Chip>);
    expect(chip).toHaveAttribute('aria-pressed', 'true');
  });

  const variants: ChipVariant[] = ['neutral', 'selected', 'solid', 'local', 'warning', 'info'];
  variants.forEach((v) => {
    it(`renders ${v} variant`, () => {
      render(<Chip variant={v}>{v}</Chip>);
      expect(screen.getByRole('button', { name: v })).toBeInTheDocument();
    });
  });

  it('supports removable chips and handles click on remove icon', () => {
    const handleRemove = vi.fn();
    render(<Chip removable onRemove={handleRemove}>Tag</Chip>);

    const removeBtn = screen.getByRole('button', { name: /delete/i });
    expect(removeBtn).toBeInTheDocument();

    fireEvent.click(removeBtn);
    expect(handleRemove).toHaveBeenCalledTimes(1);
  });

  it('handles Backspace and Delete keys to trigger onRemove', () => {
    const handleRemove = vi.fn();
    render(<Chip removable onRemove={handleRemove}>Tag</Chip>);

    const chip = screen.getByRole('button', { name: /tag/i });
    fireEvent.keyDown(chip, { key: 'Backspace' });
    expect(handleRemove).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(chip, { key: 'Delete' });
    expect(handleRemove).toHaveBeenCalledTimes(2);
  });

  it('renders icon slot', () => {
    render(<Chip icon={<span data-testid="chip-icon">★</span>}>Starred</Chip>);
    expect(screen.getByTestId('chip-icon')).toBeInTheDocument();
    expect(screen.getByText('Starred')).toBeInTheDocument();
  });
});
