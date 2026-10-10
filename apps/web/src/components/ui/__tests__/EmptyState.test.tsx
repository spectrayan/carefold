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
import { EmptyState } from '../EmptyState';

describe('EmptyState Primitive', () => {
  it('renders icon, person-aware title, and description', () => {
    render(
      <EmptyState
        icon={<span data-testid="empty-icon">📁</span>}
        title="No notes for Rosa yet"
        description="When a helper prepares questions or a summary for Rosa, you can save it here."
      />
    );

    expect(screen.getByTestId('empty-icon')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: /no notes for rosa yet/i })).toBeInTheDocument();
    expect(screen.getByText(/when a helper prepares questions/i)).toBeInTheDocument();
  });

  it('renders primary and secondary action triggers and handles clicks', () => {
    const handlePrimary = vi.fn();
    const handleSecondary = vi.fn();

    render(
      <EmptyState
        icon={<span>📄</span>}
        title="No documents for Leo yet"
        description="Upload a record or bill."
        action={{
          label: 'Add document',
          onClick: handlePrimary
        }}
        secondaryAction={{
          label: 'Browse templates',
          onClick: handleSecondary
        }}
      />
    );

    const primaryBtn = screen.getByRole('button', { name: /add document/i });
    const secondaryBtn = screen.getByRole('button', { name: /browse templates/i });

    expect(primaryBtn).toBeInTheDocument();
    expect(secondaryBtn).toBeInTheDocument();

    fireEvent.click(primaryBtn);
    expect(handlePrimary).toHaveBeenCalledTimes(1);

    fireEvent.click(secondaryBtn);
    expect(handleSecondary).toHaveBeenCalledTimes(1);
  });
});
