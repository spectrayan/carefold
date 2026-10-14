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
import { InlineError } from '../InlineError';

describe('InlineError Primitive', () => {
  it('renders alert container with assertive announcement', () => {
    render(
      <InlineError
        title="Connection Failed"
        message="Carefold cannot reach the local model on this computer."
      />
    );

    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveAttribute('aria-live', 'assertive');
    expect(alert).toHaveAttribute('aria-atomic', 'true');
    expect(screen.getByText('Connection Failed')).toBeInTheDocument();
    expect(screen.getByText(/carefold cannot reach the local model/i)).toBeInTheDocument();
  });

  it('renders retry button and fires callback on click', () => {
    const handleRetry = vi.fn();
    render(
      <InlineError
        message="Failed to generate response."
        onRetry={handleRetry}
        retryLabel="Try again"
      />
    );

    const retryBtn = screen.getByRole('button', { name: /try again/i });
    expect(retryBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);
    expect(handleRetry).toHaveBeenCalledTimes(1);
  });

  it('renders warning severity variant', () => {
    render(
      <InlineError
        severity="warning"
        message="Using cloud provider; conversation is sent to external API."
      />
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveClass('bg-[var(--cf-warn-bg)]');
  });

  it('renders expandable technical details disclosure', () => {
    render(
      <InlineError
        message="Something went wrong."
        technicalDetails="Error: ECONNREFUSED 127.0.0.1:11434 at TCPConnectWrap.afterConnect"
      />
    );

    expect(screen.getByText(/show technical details/i)).toBeInTheDocument();
    expect(screen.getByText(/ECONNREFUSED/i)).toBeInTheDocument();
  });
});
