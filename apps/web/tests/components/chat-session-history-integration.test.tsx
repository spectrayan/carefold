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
import { ChatClient } from '@/app/chat/ChatClient';
import type { AgentSummary } from '@/lib/types';
import { CAREFOLD_THREADS_INDEX_KEY } from '@/lib/sessionHistory';

const mockAgents: AgentSummary[] = [
  {
    id: 'visit-steward',
    title: 'Visit Steward',
    version: '0.1.0',
    risk_class: 'wellness',
    skills: ['visit-prep'],
    effectiveTools: ['skill-docs'],
    starters: ['What should I ask my doctor?']
  },
  {
    id: 'cardiology-guide',
    title: 'Cardiology Guide',
    version: '0.1.0',
    risk_class: 'clinical_assist',
    skills: ['cardiology-prep'],
    effectiveTools: ['skill-docs'],
    starters: ['Help me prepare for my cardiology consult']
  }
];

describe('ChatClient Session History Sidebar Integration', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })));
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders history toggle button in header and toggles sidebar visibility', async () => {
    render(<ChatClient initialAgents={mockAgents} />);

    const toggleBtn = screen.getByTestId('history-sidebar-toggle');
    expect(toggleBtn).toBeInTheDocument();
    expect(toggleBtn).toHaveAttribute('aria-label', expect.stringMatching(/history/i));

    // Initially sidebar is rendered (or closed based on default / viewport)
    // Toggling button should make the sidebar accessible
    fireEvent.click(toggleBtn);
    expect(screen.getByTestId('session-history-sidebar')).toBeInTheDocument();
  });

  it('lists past sessions from index and switches sessions cleanly without mixing messages', async () => {
    // Seed index with two past sessions
    const session1 = {
      id: 'thread-visit-steward-111',
      agentId: 'visit-steward',
      agentTitle: 'Visit Steward',
      title: 'First Visit Questions',
      createdAt: '2026-10-07T00:00:00.000Z',
      updatedAt: '2026-10-07T00:05:00.000Z',
      messageCount: 2
    };

    const session2 = {
      id: 'thread-cardiology-guide-222',
      agentId: 'cardiology-guide',
      agentTitle: 'Cardiology Guide',
      title: 'Cardiology Prep',
      createdAt: '2026-10-07T01:00:00.000Z',
      updatedAt: '2026-10-07T01:05:00.000Z',
      messageCount: 2
    };

    localStorage.setItem(
      CAREFOLD_THREADS_INDEX_KEY,
      JSON.stringify([session2, session1])
    );

    // Seed messages for session 1
    localStorage.setItem(
      'carefold_msgs_thread-visit-steward-111',
      JSON.stringify([
        { id: 'm1', role: 'user', content: 'First Visit Questions', timestamp: 1000 },
        { id: 'm2', role: 'assistant', content: 'Here is your visit checklist', timestamp: 2000 }
      ])
    );

    // Seed messages for session 2
    localStorage.setItem(
      'carefold_msgs_thread-cardiology-guide-222',
      JSON.stringify([
        { id: 'm3', role: 'user', content: 'Cardiology Prep', timestamp: 3000 },
        { id: 'm4', role: 'assistant', content: 'Cardiology guidance ready', timestamp: 4000 }
      ])
    );

    render(<ChatClient initialAgents={mockAgents} />);

    // Open sidebar if closed
    const toggleBtn = screen.getByTestId('history-sidebar-toggle');
    fireEvent.click(toggleBtn);

    // Session cards should be visible
    const session1Btn = await screen.findByTestId('session-item-thread-visit-steward-111');
    const session2Btn = screen.getByTestId('session-item-thread-cardiology-guide-222');
    expect(session1Btn).toBeInTheDocument();
    expect(session2Btn).toBeInTheDocument();

    // Click session 1 to switch to it
    fireEvent.click(session1Btn);

    // Should display session 1's messages
    await waitFor(() => {
      expect(screen.getByText('Here is your visit checklist')).toBeInTheDocument();
    });
    expect(screen.queryByText('Cardiology guidance ready')).not.toBeInTheDocument();

    // Click session 2 to switch to it
    fireEvent.click(session2Btn);

    // Should display session 2's messages and NOT session 1's messages
    await waitFor(() => {
      expect(screen.getByText('Cardiology guidance ready')).toBeInTheDocument();
    });
    expect(screen.queryByText('Here is your visit checklist')).not.toBeInTheDocument();
  });

  it('starting a new session keeps earlier session listed in sidebar and resumable', async () => {
    // Seed existing session
    const existing = {
      id: 'thread-visit-steward-prior',
      agentId: 'visit-steward',
      agentTitle: 'Visit Steward',
      title: 'Prior Visit Consultation',
      createdAt: '2026-10-07T00:00:00.000Z',
      updatedAt: '2026-10-07T00:05:00.000Z',
      messageCount: 1
    };
    localStorage.setItem(CAREFOLD_THREADS_INDEX_KEY, JSON.stringify([existing]));
    localStorage.setItem(
      'carefold_msgs_thread-visit-steward-prior',
      JSON.stringify([
        { id: 'm1', role: 'user', content: 'Check blood pressure meds list' },
        { id: 'm2', role: 'assistant', content: 'Here is your blood pressure medication review' }
      ])
    );

    render(<ChatClient initialAgents={mockAgents} />);

    // Click new session in header
    const newSessionBtn = screen.getByTestId('new-session-btn');
    fireEvent.click(newSessionBtn);

    // Open history sidebar
    const toggleBtn = screen.getByTestId('history-sidebar-toggle');
    fireEvent.click(toggleBtn);

    // Prior session remains listed
    const priorItem = await screen.findByTestId('session-item-thread-visit-steward-prior');
    expect(priorItem).toBeInTheDocument();

    // Clicking prior session resumes it
    fireEvent.click(priorItem);
    await waitFor(() => {
      expect(screen.getByText('Here is your blood pressure medication review')).toBeInTheDocument();
    });
  });

  it('deleting a session from sidebar removes its messages from localStorage', async () => {
    const sessionToDelete = {
      id: 'thread-to-delete-999',
      agentId: 'visit-steward',
      agentTitle: 'Visit Steward',
      title: 'Session To Delete',
      createdAt: '2026-10-07T00:00:00.000Z',
      updatedAt: '2026-10-07T00:05:00.000Z',
      messageCount: 1
    };
    localStorage.setItem(CAREFOLD_THREADS_INDEX_KEY, JSON.stringify([sessionToDelete]));
    localStorage.setItem(
      'carefold_msgs_thread-to-delete-999',
      JSON.stringify([{ id: 'm1', role: 'user', content: 'Confidential text to delete' }])
    );

    render(<ChatClient initialAgents={mockAgents} />);

    const toggleBtn = screen.getByTestId('history-sidebar-toggle');
    fireEvent.click(toggleBtn);

    const deleteBtn = await screen.findByTestId('delete-session-thread-to-delete-999');
    fireEvent.click(deleteBtn);

    // Confirm in alert dialog
    const confirmBtn = screen.getByTestId('confirm-delete-session-btn');
    fireEvent.click(confirmBtn);

    // Messages and session should be removed
    await waitFor(() => {
      expect(screen.queryByText('Session To Delete')).not.toBeInTheDocument();
    });
    expect(localStorage.getItem('carefold_msgs_thread-to-delete-999')).toBeNull();
  });
});
