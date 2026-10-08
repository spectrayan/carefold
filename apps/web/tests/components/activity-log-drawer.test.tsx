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
import { ActivityLogDrawer } from '@/components/chat/ActivityLogDrawer';
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
  },
  {
    ts: '2026-10-07T12:15:00.000Z',
    agent_id: 'visit-steward',
    event: 'run',
    allowed: true,
    reason: null,
    duration_ms: 350.0
  },
  {
    ts: '2026-10-07T12:20:00.000Z',
    agent_id: 'neurology-guide',
    event: 'boundary_warning',
    allowed: true,
    reason: 'clinical_boundary_candidate',
    duration_ms: 5.0
  }
];

describe('ActivityLogDrawer Component (apps/web/src/components/chat/ActivityLogDrawer.tsx)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            total: mockAuditEvents.length,
            limit: 100,
            events: mockAuditEvents
          })
      })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders nothing when isOpen is false', () => {
    const { container } = render(
      <ActivityLogDrawer isOpen={false} onClose={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders drawer header, badges, and events when open', async () => {
    render(<ActivityLogDrawer isOpen={true} onClose={vi.fn()} />);

    expect(screen.getByTestId('activity-log-drawer')).toBeInTheDocument();
    expect(screen.getByText('Activity & Safety Log')).toBeInTheDocument();
    expect(screen.getByTestId('redacted-mode-badge')).toBeInTheDocument();

    await waitFor(() => {
      const cards = screen.getAllByTestId('audit-event-card');
      expect(cards.length).toBe(5);
    });

    const countBadge = screen.getByTestId('audit-count-badge');
    expect(countBadge).toHaveTextContent('5 events');
  });

  it('dismisses when backdrop or close button is clicked', async () => {
    const onClose = vi.fn();
    render(<ActivityLogDrawer isOpen={true} onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    // Click backdrop
    const backdrop = screen.getByTestId('activity-drawer-backdrop');
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);

    // Click close button
    const closeBtn = screen.getByTestId('close-drawer-btn');
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('dismisses when Escape key is pressed', async () => {
    const onClose = vi.fn();
    render(<ActivityLogDrawer isOpen={true} onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('NON-COLOR DISTINCTION INVARIANT: renders explicit text badges and icons for denied, refused, and allowed events', async () => {
    render(<ActivityLogDrawer isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    // Check denied tool text badge
    expect(screen.getByText('[TOOL DENIED]')).toBeInTheDocument();

    // Check safety refusal text badge
    expect(screen.getByText('[SAFETY REFUSAL]')).toBeInTheDocument();

    // Check allowed tool text badge
    expect(screen.getByText('[ALLOWED]')).toBeInTheDocument();

    // Check completed run text badge
    expect(screen.getByText('[COMPLETED]')).toBeInTheDocument();

    // Check boundary warning text badge
    expect(screen.getByText('[BOUNDARY WARNING]')).toBeInTheDocument();
  });

  it('filters events by agent dropdown', async () => {
    render(<ActivityLogDrawer isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    const agentSelect = screen.getByTestId('audit-agent-filter');
    fireEvent.change(agentSelect, { target: { value: 'cardiology-guide' } });

    await waitFor(() => {
      const cards = screen.getAllByTestId('audit-event-card');
      expect(cards.length).toBe(2);
    });

    expect(screen.getByTestId('audit-count-badge')).toHaveTextContent('2 events');
  });

  it('filters events by event type dropdown', async () => {
    render(<ActivityLogDrawer isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    const eventSelect = screen.getByTestId('audit-event-filter');
    fireEvent.change(eventSelect, { target: { value: 'refuse' } });

    await waitFor(() => {
      const cards = screen.getAllByTestId('audit-event-card');
      expect(cards.length).toBe(1);
    });

    expect(screen.getByText('emergency_red_flag:cardiac')).toBeInTheDocument();
  });

  it('filters by "Only Blocked & Refused" toggle', async () => {
    render(<ActivityLogDrawer isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    const blockedToggle = screen.getByTestId('audit-blocked-toggle');
    fireEvent.click(blockedToggle);

    await waitFor(() => {
      const cards = screen.getAllByTestId('audit-event-card');
      // Exactly 2 events are blocked (tool denied & refusal)
      expect(cards.length).toBe(2);
    });

    expect(screen.getByText('[TOOL DENIED]')).toBeInTheDocument();
    expect(screen.getByText('[SAFETY REFUSAL]')).toBeInTheDocument();
    expect(screen.queryByText('[ALLOWED]')).not.toBeInTheDocument();
    expect(screen.queryByText('[COMPLETED]')).not.toBeInTheDocument();
  });

  it('filters by search input text across tools and reasons', async () => {
    render(<ActivityLogDrawer isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    const searchInput = screen.getByTestId('audit-search-input');
    fireEvent.change(searchInput, { target: { value: 'attach-read' } });

    await waitFor(() => {
      const cards = screen.getAllByTestId('audit-event-card');
      expect(cards.length).toBe(1);
    });

    expect(screen.getByText('attach-read')).toBeInTheDocument();
  });

  it('shows empty state when no events match filters', async () => {
    render(<ActivityLogDrawer isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    const searchInput = screen.getByTestId('audit-search-input');
    fireEvent.change(searchInput, { target: { value: 'nonexistent-query-xyz' } });

    await waitFor(() => {
      expect(screen.getByTestId('audit-empty-state')).toBeInTheDocument();
    });

    expect(screen.getByText('No activity events found')).toBeInTheDocument();

    // Reset button restores events
    const resetBtn = screen.getByText('Reset all filters');
    fireEvent.click(resetBtn);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });
  });

  it('toggles collapsible JSON details card per event', async () => {
    render(<ActivityLogDrawer isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    expect(screen.queryByTestId('audit-raw-json')).not.toBeInTheDocument();

    // Click "Inspect Raw Details" on first event
    const inspectButtons = screen.getAllByText('Inspect Raw Details');
    fireEvent.click(inspectButtons[0]);

    expect(screen.getByTestId('audit-raw-json')).toBeInTheDocument();
    expect(screen.getByText('Hide Raw Details')).toBeInTheDocument();

    // Click again to collapse
    fireEvent.click(screen.getByText('Hide Raw Details'));
    expect(screen.queryByTestId('audit-raw-json')).not.toBeInTheDocument();
  });

  it('supports copy to clipboard and JSON export actions', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      configurable: true,
      writable: true
    });

    render(<ActivityLogDrawer isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByTestId('audit-event-card').length).toBe(5);
    });

    const copyBtn = screen.getByTestId('copy-audit-btn');
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledTimes(1);
    });
  });
});
