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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import React from 'react';
import { ActivityTimelineFeed } from '@/components/activity/ActivityTimelineFeed';
import { ActivityTimelineItem } from '@/components/activity/ActivityTimelineItem';
import { UndoConfirmPopover } from '@/components/activity/UndoConfirmPopover';
import { ProfileActivityClient } from '@/app/p/[profileId]/activity/ProfileActivityClient';
import * as activityApi from '@/lib/activity';
import type { ActivityItemResponse, ActivityUndoResponse } from '@/types/activity';


describe('Activity Timeline & Single-Click Undo Engine (AU-44)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const mockActivityItems: ActivityItemResponse[] = [
    {
      id: 'act-1',
      profile_id: 'prof-1',
      event: 'tool_executed',
      tool: 'record_vitals',
      actor: 'user',
      principal: 'user',
      summary: 'Logged blood pressure 135/85 mmHg',
      description: 'Recorded manual observation via vitals modal',
      risk: 'write_local',
      undoable: true,
      undone: false,
      external_ref: 'health_resource:obs-101',
      details: {},
      ts: '2026-10-13T10:00:00Z',
    },
    {
      id: 'act-2',
      profile_id: 'prof-1',
      event: 'tool_executed',
      tool: 'create_appointment',
      actor: 'cardiology-guide',
      principal: 'agent',
      summary: 'Scheduled follow-up with Dr. Helen Vance',
      description: 'Booked consultation for Oct 25 at Mercy Heart Center',
      risk: 'write_local',
      undoable: true,
      undone: false,
      external_ref: 'appointment:apt-202',
      details: {},
      ts: '2026-10-13T09:30:00Z',
    },
    {
      id: 'act-3',
      profile_id: 'prof-1',
      event: 'tool_executed',
      tool: 'create_reminder',
      actor: 'system',
      principal: 'system',
      summary: 'Created daily medication reminder',
      description: 'Daily Amlodipine 5mg at 8:00 AM',
      risk: 'write_local',
      undoable: false,
      undone: false,
      external_ref: 'reminder:rem-303',
      details: {},
      ts: '2026-10-01T08:00:00Z', // >7 days ago => expired write_local
    },
    {
      id: 'act-4',
      profile_id: 'prof-1',
      event: 'undo',
      tool: 'undo',
      actor: 'user',
      principal: 'user',
      summary: 'Reverted vital signs observation',
      description: 'Reversal of vital observation',
      risk: 'write_local',
      undoable: false,
      undone: true,
      details: {},
      ts: '2026-10-12T15:00:00Z',
    },
  ];

  describe('ActivityTimelineFeed Component', () => {
    it('renders list of activity items and supports search filtering', () => {
      render(<ActivityTimelineFeed items={mockActivityItems} />);

      expect(screen.getByTestId('activity-timeline-feed')).toBeInTheDocument();
      expect(screen.getByText('Logged blood pressure 135/85 mmHg')).toBeInTheDocument();
      expect(screen.getByText('Scheduled follow-up with Dr. Helen Vance')).toBeInTheDocument();
      expect(screen.getByText('Created daily medication reminder')).toBeInTheDocument();

      // Search filter
      const searchInput = screen.getByTestId('activity-search-input');
      fireEvent.change(searchInput, { target: { value: 'Amlodipine' } });

      expect(screen.queryByText('Logged blood pressure 135/85 mmHg')).not.toBeInTheDocument();
      expect(screen.getByText('Created daily medication reminder')).toBeInTheDocument();
    });

    it('filters items by tool type', () => {
      render(<ActivityTimelineFeed items={mockActivityItems} />);

      const toolSelect = screen.getByTestId('activity-tool-filter');
      fireEvent.change(toolSelect, { target: { value: 'record_vitals' } });

      expect(screen.getByText('Logged blood pressure 135/85 mmHg')).toBeInTheDocument();
      expect(screen.queryByText('Scheduled follow-up with Dr. Helen Vance')).not.toBeInTheDocument();
    });

    it('filters items by undoable-only checkbox', () => {
      render(<ActivityTimelineFeed items={mockActivityItems} />);

      const undoableCheckbox = screen.getByTestId('undoable-only-toggle');
      fireEvent.click(undoableCheckbox);

      // Only act-1 and act-2 are undoable
      expect(screen.getByText('Logged blood pressure 135/85 mmHg')).toBeInTheDocument();
      expect(screen.getByText('Scheduled follow-up with Dr. Helen Vance')).toBeInTheDocument();
      expect(screen.queryByText('Created daily medication reminder')).not.toBeInTheDocument();
      expect(screen.queryByText('Reverted vital signs observation')).not.toBeInTheDocument();
    });
  });

  describe('ActivityTimelineItem Component', () => {
    it('renders actor badges (You, Carefold Agent, System) and tool chips accurately', () => {
      render(<ActivityTimelineItem item={mockActivityItems[0]} />);
      expect(screen.getByTestId('actor-badge')).toHaveTextContent('You');
      expect(screen.getByTestId('tool-badge')).toHaveTextContent('Vitals Recorded');

      render(<ActivityTimelineItem item={mockActivityItems[1]} />);
      expect(screen.getAllByTestId('actor-badge')[1]).toHaveTextContent('Carefold Agent');
      expect(screen.getAllByTestId('tool-badge')[1]).toHaveTextContent('Appointment');
    });

    it('renders [UNDONE] pill when item has been reverted', () => {
      render(<ActivityTimelineItem item={mockActivityItems[3]} />);
      expect(screen.getByTestId('undone-badge')).toHaveTextContent('[UNDONE]');
      expect(screen.getByTestId('activity-summary')).toHaveClass('line-through');
    });

    it('displays active single-click undo button for undoable items and opens confirmation popover', async () => {
      const onUndo = vi.fn();
      render(<ActivityTimelineItem item={mockActivityItems[0]} onUndo={onUndo} />);

      const undoBtn = screen.getByTestId('undo-action-btn');
      expect(undoBtn).toBeInTheDocument();

      await act(async () => {
        fireEvent.click(undoBtn);
      });
      expect(screen.getByTestId('undo-confirm-popover')).toBeInTheDocument();

      const confirmBtn = screen.getByTestId('confirm-undo-btn');
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      expect(onUndo).toHaveBeenCalledWith('act-1');
    });


    it('displays disabled undo button for expired write_local events older than 7 days', () => {
      render(<ActivityTimelineItem item={mockActivityItems[2]} />);
      const disabledBtn = screen.getByTestId('undo-action-disabled-btn');
      expect(disabledBtn).toBeDisabled();
      expect(disabledBtn).toHaveAttribute('title', expect.stringContaining('7 days'));
    });
  });

  describe('UndoConfirmPopover Component', () => {
    it('displays entity-specific rollback warning for health resources', () => {
      const onClose = vi.fn();
      const onConfirm = vi.fn();

      render(
        <UndoConfirmPopover
          isOpen={true}
          onClose={onClose}
          onConfirm={onConfirm}
          item={mockActivityItems[0]} // health_resource:obs-101
        />
      );

      expect(screen.getByTestId('undo-confirm-popover')).toBeInTheDocument();
      expect(screen.getByText(/Tombstones vital signs observation/i)).toBeInTheDocument();
    });

    it('displays entity-specific rollback warning for appointments', () => {
      const onClose = vi.fn();
      const onConfirm = vi.fn();

      render(
        <UndoConfirmPopover
          isOpen={true}
          onClose={onClose}
          onConfirm={onConfirm}
          item={mockActivityItems[1]} // appointment:apt-202
        />
      );

      expect(screen.getByText(/Marks the scheduled appointment as cancelled/i)).toBeInTheDocument();
    });

    it('displays entity-specific rollback warning for reminders and notes', () => {
      const reminderItem: ActivityItemResponse = {
        ...mockActivityItems[0],
        id: 'act-rem',
        external_ref: 'reminder:rem-505',
      };
      const noteItem: ActivityItemResponse = {
        ...mockActivityItems[0],
        id: 'act-note',
        external_ref: 'note:note-606',
      };
      const unknownItem: ActivityItemResponse = {
        ...mockActivityItems[0],
        id: 'act-unk',
        external_ref: 'custom_entity:custom-707',
      };

      const { rerender } = render(
        <UndoConfirmPopover
          isOpen={true}
          onClose={vi.fn()}
          onConfirm={vi.fn()}
          item={reminderItem}
        />
      );
      expect(screen.getByText(/Cancels the reminder and halts scheduled alerts/i)).toBeInTheDocument();

      rerender(
        <UndoConfirmPopover
          isOpen={true}
          onClose={vi.fn()}
          onConfirm={vi.fn()}
          item={noteItem}
        />
      );
      expect(screen.getByText(/Removes note and purges document from search index/i)).toBeInTheDocument();

      rerender(
        <UndoConfirmPopover
          isOpen={true}
          onClose={vi.fn()}
          onConfirm={vi.fn()}
          item={unknownItem}
        />
      );
      expect(screen.getByText(/Reverts the local state changes created by this action/i)).toBeInTheDocument();
    });
  });

  describe('ActivityTimelineItem Boundary & Negative Edge Cases', () => {
    it('completely hides undo button for non-write_local actions (e.g., read, admin)', () => {
      const readItem: ActivityItemResponse = {
        id: 'act-read-1',
        profile_id: 'prof-1',
        event: 'tool_executed',
        tool: 'search_records',
        actor: 'user',
        principal: 'user',
        summary: 'Searched clinical records',
        description: 'Recorded manual vital signs',
        risk: 'read',
        undoable: false,
        undone: false,
        details: { systolic: 120, diastolic: 80 },
        ts: '2026-10-13T10:00:00Z',
      };

      render(<ActivityTimelineItem item={readItem} />);
      expect(screen.queryByTestId('undo-action-btn')).not.toBeInTheDocument();
      expect(screen.queryByTestId('undo-action-disabled-btn')).not.toBeInTheDocument();
    });

    it('completely hides undo button when item has already been undone', () => {
      const undoneItem: ActivityItemResponse = {
        id: 'act-undone-1',
        profile_id: 'prof-1',
        event: 'tool_executed',
        tool: 'record_vitals',
        actor: 'user',
        principal: 'user',
        summary: 'Logged heart rate 72 bpm',
        description: 'Reverted vital signs observation',
        risk: 'write_local',
        undoable: false,
        undone: true,
        details: {},
        ts: '2026-10-13T10:00:00Z',
      };

      render(<ActivityTimelineItem item={undoneItem} />);
      expect(screen.queryByTestId('undo-action-btn')).not.toBeInTheDocument();
      expect(screen.queryByTestId('undo-action-disabled-btn')).not.toBeInTheDocument();
      expect(screen.getByTestId('undone-badge')).toHaveTextContent('[UNDONE]');
    });

    it('renders tool badges for prep pack, clinical note, reversal, and generic tools', () => {
      const prepItem: ActivityItemResponse = {
        ...mockActivityItems[0],
        id: 'act-p1',
        tool: 'generate_prep_pack',
      };
      const noteItem: ActivityItemResponse = {
        ...mockActivityItems[0],
        id: 'act-n1',
        tool: 'create_typed_note',
      };
      const reversalItem: ActivityItemResponse = {
        ...mockActivityItems[0],
        id: 'act-r1',
        tool: 'undo',
      };

      const { rerender } = render(<ActivityTimelineItem item={prepItem} />);
      expect(screen.getByTestId('tool-badge')).toHaveTextContent('Prep Pack');

      rerender(<ActivityTimelineItem item={noteItem} />);
      expect(screen.getByTestId('tool-badge')).toHaveTextContent('Clinical Note');

      rerender(<ActivityTimelineItem item={reversalItem} />);
      expect(screen.getByTestId('tool-badge')).toHaveTextContent('Reversal');
    });
  });

  describe('ProfileActivityClient Rollback Mutation & Optimistic Feed Update', () => {
    it('executes POST rollback mutation, optimistically marks item [UNDONE], and prepends reversal event', async () => {
      const mockUndoResponse: ActivityUndoResponse = {
        status: 'undone',
        event_id: 'act-1',
        undo_event_id: 'undo-event-999',
        reverted_summary: 'Logged blood pressure 135/85 mmHg',
        message: 'Successfully tombstoned observation and purged trends.',
      };

      vi.spyOn(activityApi, 'undoActivityEvent').mockResolvedValue(mockUndoResponse);


      render(
        <ProfileActivityClient
          profileId="prof-1"
          initialItems={[mockActivityItems[0], mockActivityItems[1]]}
        />
      );

      // Verify initial state
      expect(screen.getByText('Logged blood pressure 135/85 mmHg')).toBeInTheDocument();
      const undoBtns = screen.getAllByTestId('undo-action-btn');
      expect(undoBtns.length).toBeGreaterThanOrEqual(1);
      const undoBtn = undoBtns[0];


      // Open popover
      await act(async () => {
        fireEvent.click(undoBtn);
      });
      expect(screen.getByTestId('undo-confirm-popover')).toBeInTheDocument();

      // Click Confirm Undo
      const confirmBtn = screen.getByTestId('confirm-undo-btn');
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      // Verify mutation invocation
      expect(activityApi.undoActivityEvent).toHaveBeenCalledWith('prof-1', 'act-1');

      // Verify optimistic update on act-1
      expect(screen.getByTestId('undone-badge')).toHaveTextContent('[UNDONE]');
      const summary = screen.getByText('Logged blood pressure 135/85 mmHg');
      expect(summary).toHaveClass('line-through');

      // Verify newly prepended reversal event
      expect(screen.getByText(/Reverted: Logged blood pressure 135\/85 mmHg/i)).toBeInTheDocument();

      // Verify success toast
      expect(screen.getByTestId('activity-toast-success')).toHaveTextContent('Action reverted successfully.');
    });

    it('gracefully displays error when rollback mutation fails (e.g. 7-day expiration)', async () => {
      vi.spyOn(activityApi, 'undoActivityEvent').mockRejectedValue(
        new Error('Action is outside the 7-day undo window.')
      );

      render(
        <ProfileActivityClient
          profileId="prof-1"
          initialItems={[mockActivityItems[0]]}
        />
      );

      const undoBtn = screen.getByTestId('undo-action-btn');
      await act(async () => {
        fireEvent.click(undoBtn);
      });

      const confirmBtn = screen.getByTestId('confirm-undo-btn');
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      // Error banner rendered
      expect(
        screen.getByText('Action is outside the 7-day undo window.')
      ).toBeInTheDocument();

      // Item was NOT marked as undone
      expect(screen.queryByTestId('undone-badge')).not.toBeInTheDocument();
    });
  });
});

