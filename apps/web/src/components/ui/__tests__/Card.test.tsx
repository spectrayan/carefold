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
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter
} from '../Card';

describe('Card Primitive', () => {
  it('renders default card and its subcomponents', () => {
    render(
      <Card data-testid="card">
        <CardHeader>
          <CardTitle>Test Card</CardTitle>
          <CardDescription>Description of the card</CardDescription>
        </CardHeader>
        <CardContent>Content body</CardContent>
        <CardFooter>Footer info</CardFooter>
      </Card>
    );

    expect(screen.getByTestId('card')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: /test card/i })).toBeInTheDocument();
    expect(screen.getByText(/description of the card/i)).toBeInTheDocument();
    expect(screen.getByText(/content body/i)).toBeInTheDocument();
    expect(screen.getByText(/footer info/i)).toBeInTheDocument();
  });

  it('renders interactive variant with button semantics and responds to click and keyboard', () => {
    const handleClick = vi.fn();
    render(
      <Card variant="interactive" onClick={handleClick} data-testid="interactive-card">
        Interactive Card
      </Card>
    );

    const card = screen.getByTestId('interactive-card');
    expect(card).toHaveAttribute('role', 'button');
    expect(card).toHaveAttribute('tabIndex', '0');

    // Click
    fireEvent.click(card);
    expect(handleClick).toHaveBeenCalledTimes(1);

    // Enter key
    fireEvent.keyDown(card, { key: 'Enter' });
    expect(handleClick).toHaveBeenCalledTimes(2);

    // Space key
    fireEvent.keyDown(card, { key: ' ' });
    expect(handleClick).toHaveBeenCalledTimes(3);
  });

  it('renders selected and muted variants', () => {
    const { rerender } = render(<Card variant="selected" data-testid="card">Selected</Card>);
    expect(screen.getByTestId('card')).toHaveClass('border-2');

    rerender(<Card variant="muted" data-testid="card">Muted</Card>);
    expect(screen.getByTestId('card')).toHaveClass('bg-[var(--cf-surface-2)]');
  });

  it('renders with custom element via as prop', () => {
    render(<Card as="section" data-testid="section-card">Section Card</Card>);
    const card = screen.getByTestId('section-card');
    expect(card.tagName.toLowerCase()).toBe('section');
  });
});
