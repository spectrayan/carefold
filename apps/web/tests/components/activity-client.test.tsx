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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { ActivityClient } from '@/app/activity/ActivityClient';
import { AuditEvent } from '@/types/api';

const mockAuditEvents: AuditEvent[] = [
  {
    ts: '2026-10-07T12:00:00.000Z',
    agent_id: 'cardiology-guide',
    event: 'tool',
    tool: 'exec',
    allowed: false,
    reason: "Tool 'exec' execution denied: undeclared tool for agent 'cardiology-guide'.",
    duration_ms: 14.5
  },
  {
    ts: '2026-10-07T12:05:00.000Z',
    agent_id: 'visit-steward',
    event: 'refuse',
    allowed: false,
    reason: 'emergency_red_flag:cardiac',
    duration_ms: 8.2
  },
  {
    ts: '2026-10-07T12:10:00.000Z',
    agent_id: 'cardiology-guide',
    event: 'tool',
    tool: 'attach-read',
    allowed: true,
    reason: null,
    duration_ms: 22.0
  }
];

describe('ActivityClient Page Component (apps/web/src/app/activity/ActivityClient.tsx)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders standalone activity view with initial events and non-color denial badges', () => {
    render(<ActivityClient initialEvents={mockAuditEvents} />);

    expect(screen.getByRole('heading', { name: /Activity & Safety Log/i })).toBeInTheDocument();
    expect(screen.getByTestId('redacted-mode-badge')).toBeInTheDocument();
    expect(screen.getByTestId('audit-count-badge')).toHaveTextContent('3 events');

    expect(screen.getAllByTestId('audit-event-card').length).toBe(3);
    expect(screen.getByText('[TOOL DENIED]')).toBeInTheDocument();
    expect(screen.getByText('[SAFETY REFUSAL]')).toBeInTheDocument();
    expect(screen.getByText('[ALLOWED]')).toBeInTheDocument();
  });

  it('filters events with agent selector and search query', async () => {
    render(<ActivityClient initialEvents={mockAuditEvents} />);

    const searchInput = screen.getByTestId('audit-search-input');
    fireEvent.change(searchInput, { target: { value: 'cardiac' } });

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(1);
    });
    expect(screen.getByText('emergency_red_flag:cardiac')).toBeInTheDocument();
  });

  it('filters with only blocked checkbox', async () => {
    render(<ActivityClient initialEvents={mockAuditEvents} />);

    const blockedToggle = screen.getByTestId('audit-blocked-toggle');
    fireEvent.click(blockedToggle);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(2);
    });

    expect(screen.getByText('[TOOL DENIED]')).toBeInTheDocument();
    expect(screen.getByText('[SAFETY REFUSAL]')).toBeInTheDocument();
    expect(screen.queryByText('[ALLOWED]')).not.toBeInTheDocument();
  });

  it('expands raw JSON view on inspect click', async () => {
    render(<ActivityClient initialEvents={mockAuditEvents} />);

    const inspectButtons = screen.getAllByText('Inspect Raw Details');
    fireEvent.click(inspectButtons[0]);

    expect(screen.getByTestId('audit-raw-json')).toBeInTheDocument();
    expect(screen.getByText('Hide Raw Details')).toBeInTheDocument();
  });
});
