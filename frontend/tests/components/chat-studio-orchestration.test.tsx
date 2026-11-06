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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { ChatStudioShell } from '@/components/chat/ChatStudioShell';
import { saveSession } from '@/lib/sessionHistory';
import { saveHouseholdProfiles } from '@/lib/familyProfiles';
import type { ApprovalRecord } from '@/lib/types';

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    }
  });
  return new Response(stream, { status: 200 });
}

const TASK_STARTED =
  'event: task_status\ndata: {"type": "task_status", "turn_id": "t1", "task_id": "call-1", "agent_id": "medication-reviewer", "state": "started"}\n\n';
const TASK_FAILED =
  'event: task_status\ndata: {"type": "task_status", "turn_id": "t1", "task_id": "call-1", "agent_id": "medication-reviewer", "state": "failed", "detail": "Helper error"}\n\n';
const NOTICE =
  'event: orchestration_notice\ndata: {"type": "orchestration_notice", "turn_id": "t1", "code": "partial_failure", "message": "Part of this answer is missing because a helper failed.", "agent_ids": ["medication-reviewer"]}\n\n';

describe('ChatStudioShell orchestration events', () => {
  const approval: ApprovalRecord = {
    id: 'app_orch_1',
    profile_id: 'rosa',
    run_id: 'run-1',
    thread_id: 'thread-rosa-orch',
    tool_name: 'export_clinical_dossier',
    args_redacted: { recipient: 'Dr. Whitfield' },
    payload_hash: 'abc123',
    destination_hosts: ['portal.cityhospital.org'],
    risk_tier: 'write_external',
    status: 'pending',
    expires_at: new Date(Date.now() + 600000).toISOString(),
    created_at: new Date().toISOString(),
    reason: 'Send summary'
  };

  beforeEach(() => {
    localStorage.clear();
    saveHouseholdProfiles([
      { id: 'rosa', name: 'Rosa Rivera', relationship: 'Mom', colorSlot: 3, role: 'guardian', stats: { chats: 1, items: 2 } }
    ]);
    if (typeof Element.prototype.scrollIntoView !== 'function') {
      Element.prototype.scrollIntoView = vi.fn();
    }
    saveSession({
      id: 'thread-rosa-orch',
      agentId: 'appointment-prep-coordinator',
      agentTitle: 'Appointment Prep Coordinator',
      title: 'Orchestration',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      messageCount: 2
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders task status and a partial-failure notice from the chat stream', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/v1/chat') {
        return Promise.resolve(
          sseResponse([
            TASK_STARTED,
            TASK_FAILED,
            NOTICE,
            NOTICE,
            'event: token\ndata: {"delta": "Here is what I found."}\n\n',
            'event: done\ndata: {"fullText": "Here is what I found."}\n\n'
          ])
        );
      }
      return Promise.resolve(new Response(null, { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<ChatStudioShell profileId="rosa" />);
    fireEvent.change(screen.getByRole('textbox', { name: /^Message / }), {
      target: { value: 'Check my medications' }
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => expect(screen.getByTestId('orchestration-notice')).toBeInTheDocument());
    const rows = screen.getAllByTestId('task-status-row');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute('data-state', 'failed');
    expect(rows[0]).toHaveTextContent('medication-reviewer');
    expect(screen.getAllByTestId('orchestration-notice')).toHaveLength(1);
    expect(screen.getByTestId('orchestration-notice')).toHaveTextContent(
      'Part of this answer is missing because a helper failed.'
    );
  });

  it('renders orchestration events from a resumed (approved) stream', async () => {
    localStorage.setItem(
      'carefold_msgs_thread-rosa-orch',
      JSON.stringify([
        { id: 'msg_user_1', role: 'user', content: 'Send my summary.' },
        { id: 'msg_asst_1', role: 'assistant', content: 'Needs approval.', approval }
      ])
    );
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/decide')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({ id: approval.id, status: 'approved', payload_hash: 'abc123', decided_at: new Date().toISOString(), decided_by: 'rosa' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          )
        );
      }
      if (url === '/api/chat/resume') {
        return Promise.resolve(
          sseResponse([TASK_STARTED, NOTICE, 'event: done\ndata: {"fullText": "Sent."}\n\n'])
        );
      }
      return Promise.resolve(new Response(null, { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<ChatStudioShell profileId="rosa" initialThreadId="thread-rosa-orch" />);
    fireEvent.click(screen.getByTestId('approve-button'));

    await waitFor(() => expect(screen.getByTestId('orchestration-notice')).toBeInTheDocument());
    expect(screen.getByTestId('task-status-row')).toHaveAttribute('data-state', 'started');
  });
});
