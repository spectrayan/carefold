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
