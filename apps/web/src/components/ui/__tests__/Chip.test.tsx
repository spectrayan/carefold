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
