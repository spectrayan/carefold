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

describe('ChatStudioShell ApprovalCard Wiring (Step U0)', () => {
  const mockApproval: ApprovalRecord = {
    id: 'app_thread_cardio_1',
    profile_id: 'rosa',
    run_id: 'run-1',
    thread_id: 'thread-rosa-approval',
    tool_name: 'export_clinical_dossier',
    args_redacted: {
      recipient: 'Dr. Whitfield',
      destination: 'Hospital Portal',
      include_vitals: true
    },
    payload_hash: '9a8b7c6d5e4f3a2b1c0d',
    destination_hosts: ['portal.cityhospital.org'],
    risk_tier: 'write_external',
    status: 'pending',
    expires_at: new Date(Date.now() + 600000).toISOString(),
    created_at: new Date().toISOString(),
    reason: 'Transmission of protected health summary to external clinical portal'
  };

  beforeEach(() => {
    localStorage.clear();
    saveHouseholdProfiles([
      {
        id: 'rosa',
        name: 'Rosa Rivera',
        relationship: 'Mom',
        colorSlot: 3,
        role: 'guardian',
        stats: { chats: 1, items: 2 }
      }
    ]);
    if (typeof Element.prototype.scrollIntoView !== 'function') {
      Element.prototype.scrollIntoView = vi.fn();
    }
    saveSession({
      id: 'thread-rosa-approval',
      agentId: 'appointment-prep-coordinator',
      agentTitle: 'Visit Steward',
      title: 'Cardiology Visit Prep',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      messageCount: 2
    });
    localStorage.setItem(
      'carefold_msgs_thread-rosa-approval',
      JSON.stringify([
        {
          id: 'msg_user_1',
          role: 'user',
          content: 'Please export my cardiology visit prep to Dr. Whitfield.'
        },
        {
          id: 'msg_asst_1',
          role: 'assistant',
          content: 'I have prepared your cardiology dossier. Exporting to the external hospital portal requires your approval.',
          approval: mockApproval
        }
      ])
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders ApprovalCard inside ChatStudioShell when message contains approval record', () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 200 })));

    render(<ChatStudioShell profileId="rosa" initialThreadId="thread-rosa-approval" />);

    expect(screen.getByTestId('embedded-approval-card')).toBeInTheDocument();
    expect(screen.getByText('export_clinical_dossier')).toBeInTheDocument();
    expect(screen.getByTestId('approval-risk-badge')).toHaveTextContent('External Write');
    expect(screen.getByTestId('destination-host-pill')).toHaveTextContent('portal.cityhospital.org');
    expect(screen.getByText('Dr. Whitfield')).toBeInTheDocument();
    expect(screen.getByTestId('approve-button')).toBeInTheDocument();
    expect(screen.getByTestId('reject-button')).toBeInTheDocument();
  });

  it('submits decision to /api/profiles/rosa/approvals/[id]/decide and triggers resume on approve', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/decide')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              id: mockApproval.id,
              status: 'approved',
              payload_hash: '9a8b7c6d5e4f3a2b1c0d',
              decided_at: new Date().toISOString(),
              decided_by: 'rosa'
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          )
        );
      }
      if (url.includes('/resume')) {
        // Return a mock SSE stream
        const encoder = new TextEncoder();
        const stream = new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode('event: token\ndata: {"delta": " Dossier exported successfully."}\n\n'));
            controller.enqueue(encoder.encode('event: tool_end\ndata: {"tool": "export_clinical_dossier", "status": "completed"}\n\n'));
            controller.enqueue(encoder.encode('event: done\ndata: {"fullText": "Dossier exported successfully."}\n\n'));
            controller.close();
          }
        });
        return Promise.resolve(new Response(stream, { status: 200 }));
      }
      return Promise.resolve(new Response(null, { status: 200 }));
    });

    vi.stubGlobal('fetch', fetchMock);

    render(<ChatStudioShell profileId="rosa" initialThreadId="thread-rosa-approval" />);

    const approveBtn = screen.getByTestId('approve-button');
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/decide'),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"decision":"approved"')
        })
      );
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/chat/resume',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"decision":"approved"')
        })
      );
    });
  });

  it('provides an active AttachmentPicker trigger button', () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 200 })));

    render(<ChatStudioShell profileId="rosa" initialThreadId="thread-rosa-approval" />);

    const pickerTrigger = screen.getByTestId('attachment-picker-trigger');
    expect(pickerTrigger).toBeInTheDocument();
    expect(pickerTrigger).toHaveAttribute('aria-label', 'Attach document');
    expect(screen.getByTestId('attachment-file-input')).toBeInTheDocument();
  });
});
