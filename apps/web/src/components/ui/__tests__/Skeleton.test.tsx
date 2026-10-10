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
