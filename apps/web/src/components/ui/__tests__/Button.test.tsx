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
import { Button, ButtonVariant, ButtonSize } from '../Button';

describe('Button Primitive', () => {
  it('renders with children and default props', () => {
    render(<Button>Click me</Button>);
    const button = screen.getByRole('button', { name: /click me/i });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute('type', 'button');
    expect(button).not.toBeDisabled();
    expect(button).toHaveClass('bg-[var(--cf-primary)]');
  });

  const variants: ButtonVariant[] = ['primary', 'secondary', 'ghost', 'danger', 'outline'];
  variants.forEach((variant) => {
    it(`renders ${variant} variant correctly`, () => {
      render(<Button variant={variant}>{variant} button</Button>);
      const button = screen.getByRole('button', { name: new RegExp(`${variant} button`, 'i') });
      expect(button).toBeInTheDocument();
    });
  });

  const sizes: ButtonSize[] = ['sm', 'md', 'lg'];
  sizes.forEach((size) => {
    it(`renders ${size} size correctly`, () => {
      render(<Button size={size}>{size} button</Button>);
      const button = screen.getByRole('button', { name: new RegExp(`${size} button`, 'i') });
      expect(button).toBeInTheDocument();
    });
  });

  it('handles click events when enabled', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Action</Button>);
    const button = screen.getByRole('button', { name: /action/i });
    fireEvent.click(button);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('prevents click events and sets aria-disabled when disabled', () => {
    const handleClick = vi.fn();
    render(<Button disabled onClick={handleClick}>Disabled</Button>);
    const button = screen.getByRole('button', { name: /disabled/i });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(handleClick).not.toHaveBeenCalled();
  });

  it('displays loading spinner and sets aria-busy="true"', () => {
    const handleClick = vi.fn();
    render(<Button loading onClick={handleClick}>Loading button</Button>);
    const button = screen.getByRole('button', { name: /loading button/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(button);
    expect(handleClick).not.toHaveBeenCalled();
    expect(button.querySelector('svg')).toBeInTheDocument();
  });

  it('renders left and right icon slots', () => {
    render(
      <Button
        leftIcon={<span data-testid="left-icon">Left</span>}
        rightIcon={<span data-testid="right-icon">Right</span>}
      >
        Icon Button
      </Button>
    );
    expect(screen.getByTestId('left-icon')).toBeInTheDocument();
    expect(screen.getByTestId('right-icon')).toBeInTheDocument();
    expect(screen.getByText('Icon Button')).toBeInTheDocument();
  });
});
