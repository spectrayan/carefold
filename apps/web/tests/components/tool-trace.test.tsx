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
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ToolTraceCard, ToolTraceItem } from '@/components/ToolTraceCard';

describe('ToolTraceCard Component (CF-S03)', () => {
  const completedTrace: ToolTraceItem = {
    id: 'trace-1',
    tool: 'attach-read',
    status: 'completed',
    input: { path: 'clinic_summary.txt' },
    output: { format: 'text', size_bytes: 1024 },
    duration_ms: 32,
    allowed: true
  };

  const deniedTrace: ToolTraceItem = {
    id: 'trace-2',
    tool: 'system-exec',
    status: 'denied',
    input: { command: 'rm -rf /' },
    duration_ms: 0,
    allowed: false,
    reason: 'Tool is not in sandbox registry.'
  };

  it('renders collapsed card by default with tool name, badge, and duration', () => {
    render(<ToolTraceCard trace={completedTrace} />);

    expect(screen.getByText('attach-read')).toBeInTheDocument();
    expect(screen.getByTestId('tool-trace-status-badge')).toHaveTextContent('Completed');
    expect(screen.getByTestId('tool-trace-duration')).toHaveTextContent('32 ms');

    // Details are initially collapsed
    expect(screen.queryByTestId('tool-trace-details')).not.toBeInTheDocument();
  });

  it('toggles expansion when header is clicked', () => {
    render(<ToolTraceCard trace={completedTrace} />);

    const button = screen.getByRole('button');
    fireEvent.click(button);

    // Details now visible
    expect(screen.getByTestId('tool-trace-details')).toBeInTheDocument();
    expect(screen.getByTestId('tool-trace-params')).toHaveTextContent('clinic_summary.txt');
    expect(screen.getByTestId('tool-trace-output')).toHaveTextContent('1024');

    // Click again to collapse
    fireEvent.click(button);
    expect(screen.queryByTestId('tool-trace-details')).not.toBeInTheDocument();
  });

  it('displays denial reason and rose badge for denied tool invocations', () => {
    render(<ToolTraceCard trace={deniedTrace} defaultExpanded={true} />);

    expect(screen.getByTestId('tool-trace-status-badge')).toHaveTextContent('Denied');
    expect(screen.getByTestId('tool-trace-reason')).toHaveTextContent('Tool is not in sandbox registry.');
  });
});
