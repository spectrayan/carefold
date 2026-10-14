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
import { render, screen, act } from '@testing-library/react';
import * as React from 'react';
import { Skeleton, SkeletonVariant } from '../Skeleton';

describe('Skeleton Primitive', () => {
  it('renders default rectangular skeleton with status role and aria-busy', () => {
    render(<Skeleton data-testid="skeleton" />);
    const el = screen.getByTestId('skeleton');
    expect(el).toBeInTheDocument();
    expect(el).toHaveAttribute('role', 'status');
    expect(el).toHaveAttribute('aria-busy', 'true');
    expect(el).toHaveClass('rounded-[var(--cf-radius-md)]');
  });

  const variants: SkeletonVariant[] = ['text', 'circular', 'rectangular'];
  variants.forEach((v) => {
    it(`renders ${v} variant`, () => {
      render(<Skeleton variant={v} data-testid={`sk-${v}`} />);
      expect(screen.getByTestId(`sk-${v}`)).toBeInTheDocument();
    });
  });

  it('applies custom dimensions and inline styles', () => {
    render(<Skeleton width={120} height={40} data-testid="sized-sk" />);
    const el = screen.getByTestId('sized-sk');
    expect(el).toHaveStyle({ width: '120px', height: '40px' });
  });

  it('respects delay before displaying', () => {
    vi.useFakeTimers();

    render(<Skeleton delay={300} data-testid="delayed-sk" />);
    expect(screen.queryByTestId('delayed-sk')).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(screen.getByTestId('delayed-sk')).toBeInTheDocument();

    vi.useRealTimers();
  });
});
