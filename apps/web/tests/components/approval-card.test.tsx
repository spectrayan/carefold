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
import { ApprovalCard } from '@/components/chat/ApprovalCard';
import type { ApprovalRecord } from '@/lib/types';

describe('ApprovalCard Component (AU-18)', () => {
  const mockPendingApproval: ApprovalRecord = {
    id: 'app_thread-1_call_1',
    profile_id: 'prof-1',
    run_id: 'run-1',
    thread_id: 'thread-1',
    tool_name: 'schedule_appointment',
    args_redacted: {
      provider: 'Dr. Jane Smith',
      date: '2026-10-25',
      copay: '$20'
    },
    payload_hash: 'a1b2c3d4e5f67890abcdef1234567890',
    destination_hosts: ['api.healthportal.org'],
    risk_tier: 'write_external',
    status: 'pending',
    expires_at: new Date(Date.now() + 600000).toISOString(),
    created_at: new Date().toISOString()
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders pending approval card with tool name, risk tier, hosts, and argument table', () => {
    render(<ApprovalCard approval={mockPendingApproval} profileId="prof-1" />);

    expect(screen.getByText('schedule_appointment')).toBeInTheDocument();
    expect(screen.getByTestId('approval-risk-badge')).toHaveTextContent('External Write');
    expect(screen.getByTestId('approval-status-badge')).toHaveTextContent('pending');
    expect(screen.getByTestId('destination-host-pill')).toHaveTextContent('api.healthportal.org');
    expect(screen.getByText('Dr. Jane Smith')).toBeInTheDocument();
    expect(screen.getByText('$20')).toBeInTheDocument();
    expect(screen.getByTestId('approve-button')).toBeInTheDocument();
    expect(screen.getByTestId('reject-button')).toBeInTheDocument();
  });

  it('renders local sandbox notice when destination hosts are empty', () => {
    const localApproval: ApprovalRecord = {
      ...mockPendingApproval,
      risk_tier: 'write_local',
      destination_hosts: []
    };

    render(<ApprovalCard approval={localApproval} profileId="prof-1" />);

    expect(screen.getByText(/Local profile sandbox/i)).toBeInTheDocument();
    expect(screen.getByTestId('approval-risk-badge')).toHaveTextContent('Local Write');
  });

  it('handles approve action and invokes callbacks on success', async () => {
    const onDecided = vi.fn();
    const onResume = vi.fn();

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: mockPendingApproval.id,
        status: 'approved',
        payload_hash: mockPendingApproval.payload_hash,
        decided_at: new Date().toISOString(),
        decided_by: 'user-1'
      })
    });

    render(
      <ApprovalCard
        approval={mockPendingApproval}
        profileId="prof-1"
        onDecided={onDecided}
        onResume={onResume}
      />
    );

    const approveBtn = screen.getByTestId('approve-button');
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/profiles/prof-1/approvals/app_thread-1_call_1/decide',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ decision: 'approved' })
        })
      );
      expect(onDecided).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'approved' })
      );
      expect(onResume).toHaveBeenCalledWith('app_thread-1_call_1', 'thread-1');
    });

    expect(screen.getByTestId('approval-approved-notice')).toBeInTheDocument();
  });

  it('handles reject action and updates UI', async () => {
    const onDecided = vi.fn();
    const onResume = vi.fn();

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: mockPendingApproval.id,
        status: 'rejected',
        payload_hash: mockPendingApproval.payload_hash,
        decided_at: new Date().toISOString()
      })
    });

    render(
      <ApprovalCard
        approval={mockPendingApproval}
        profileId="prof-1"
        onDecided={onDecided}
        onResume={onResume}
      />
    );

    const rejectBtn = screen.getByTestId('reject-button');
    fireEvent.click(rejectBtn);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/profiles/prof-1/approvals/app_thread-1_call_1/decide',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ decision: 'rejected' })
        })
      );
      expect(onDecided).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'rejected' })
      );
      expect(onResume).not.toHaveBeenCalled();
    });

    expect(screen.getByTestId('approval-rejected-notice')).toBeInTheDocument();
  });

  it('supports inline JSON argument editing and sends edited_args upon approval', async () => {
    const onDecided = vi.fn();

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: mockPendingApproval.id,
        status: 'approved',
        payload_hash: 'new_computed_hash_5678',
        decided_at: new Date().toISOString()
      })
    });

    render(
      <ApprovalCard
        approval={mockPendingApproval}
        profileId="prof-1"
        onDecided={onDecided}
      />
    );

    // Click Edit Arguments
    const editBtn = screen.getByTestId('edit-arguments-button');
    fireEvent.click(editBtn);

    // Edit textarea
    const textarea = screen.getByTestId('arguments-json-editor');
    const newArgs = { provider: 'Dr. Jane Smith', date: '2026-10-26', copay: '$15' };
    fireEvent.change(textarea, { target: { value: JSON.stringify(newArgs, null, 2) } });

    // Apply edits
    const applyBtn = screen.getByTestId('save-edits-button');
    fireEvent.click(applyBtn);

    // Verify modified badge
    expect(screen.getByText('Modified Arguments')).toBeInTheDocument();
    expect(screen.getByText('$15')).toBeInTheDocument();

    // Approve with modified args
    const approveBtn = screen.getByTestId('approve-button');
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/profiles/prof-1/approvals/app_thread-1_call_1/decide',
        expect.objectContaining({
          body: JSON.stringify({
            decision: 'approved',
            edited_args: newArgs
          })
        })
      );
    });
  });

  it('displays JSON validation error when argument syntax is malformed', () => {
    render(<ApprovalCard approval={mockPendingApproval} profileId="prof-1" />);

    fireEvent.click(screen.getByTestId('edit-arguments-button'));
    const textarea = screen.getByTestId('arguments-json-editor');

    fireEvent.change(textarea, { target: { value: '{ invalid json ...' } });

    expect(screen.getByTestId('arguments-json-error')).toBeInTheDocument();
    expect(screen.getByTestId('save-edits-button')).toBeDisabled();
  });

  it('renders consumed status notice when token has already been consumed', () => {
    const consumedApproval: ApprovalRecord = {
      ...mockPendingApproval,
      status: 'consumed'
    };

    render(<ApprovalCard approval={consumedApproval} profileId="prof-1" />);

    expect(screen.getByTestId('approval-consumed-notice')).toBeInTheDocument();
    expect(screen.queryByTestId('approve-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('reject-button')).not.toBeInTheDocument();
  });

  it('renders expired notice when approval TTL has expired', () => {
    const expiredApproval: ApprovalRecord = {
      ...mockPendingApproval,
      status: 'expired'
    };

    render(<ApprovalCard approval={expiredApproval} profileId="prof-1" />);

    expect(screen.getByTestId('approval-expired-notice')).toBeInTheDocument();
    expect(screen.queryByTestId('approve-button')).not.toBeInTheDocument();
  });
});
