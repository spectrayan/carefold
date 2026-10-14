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

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import * as React from 'react';
import { Badge, BadgeVariant } from '../Badge';

describe('Badge Primitive', () => {
  it('renders default neutral badge with status role', () => {
    render(<Badge>Verified</Badge>);
    const badge = screen.getByRole('status');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Verified');
  });

  const variants: BadgeVariant[] = ['neutral', 'success', 'warning', 'danger', 'info'];
  variants.forEach((v) => {
    it(`renders ${v} variant with appropriate styles`, () => {
      render(<Badge variant={v}>{v}</Badge>);
      expect(screen.getByText(v)).toBeInTheDocument();
    });
  });

  it('renders with dot indicator', () => {
    render(<Badge dot variant="success">Active</Badge>);
    const badge = screen.getByRole('status');
    expect(badge).toBeInTheDocument();
    expect(badge.querySelector('.rounded-full')).toBeInTheDocument();
  });

  it('renders with icon', () => {
    render(<Badge icon={<span data-testid="b-icon">✓</span>}>Complete</Badge>);
    expect(screen.getByTestId('b-icon')).toBeInTheDocument();
    expect(screen.getByText('Complete')).toBeInTheDocument();
  });
});
