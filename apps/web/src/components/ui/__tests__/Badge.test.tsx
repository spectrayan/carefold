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
