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
