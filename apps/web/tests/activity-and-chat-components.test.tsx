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
import { ExecutionPlanCard } from '@/components/chat/ExecutionPlanCard';
import { EmergencyEscalationCard } from '@/components/chat/EmergencyEscalationCard';
import { AppRail } from '@/components/layout/AppRail';
import * as activityApi from '@/lib/activity';
import type { ActivityItemResponse, ActivityUndoResponse, ExecutionPlan } from '@/types/activity';
import type { ChatMessage, ToolTraceItem } from '@/lib/types';

describe('Activity and Chat Components Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    vi.spyOn(global, 'fetch').mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({ modelReachable: false }),
      } as any)
    );
  });

  // =========================================================================
  // 1. Activity Timeline & Single-Click Undo
  // =========================================================================
  describe('1. Activity Timeline & Single-Click Undo Tests', () => {
    const baseItem: ActivityItemResponse = {
      id: 'evt-base',
      profile_id: 'prof-test',
      event: 'tool_executed',
      tool: 'record_vitals',
      actor: 'user',
      principal: 'user',
      summary: 'Logged Blood Pressure 120/80 mmHg',
      description: 'Recorded manual observation',
      risk: 'write_local',
      undoable: true,
      undone: false,
      external_ref: 'health_resource:obs-1',
      details: {},
      ts: '2026-10-13T10:00:00Z',
    };

    it('1.0 ActivityTimelineFeed renders empty state and filters by search query and undoable-only toggle', () => {
      const { unmount } = render(<ActivityTimelineFeed items={[]} />);
      expect(screen.getByTestId('activity-empty-state')).toBeInTheDocument();
      expect(screen.getByText('No activity events found')).toBeInTheDocument();
      unmount();

      const items: ActivityItemResponse[] = [
        baseItem,
        {
          ...baseItem,
          id: 'evt-2',
          summary: 'Medication dose recorded',
          tool: 'create_reminder',
          undoable: false,
        },
      ];

      render(<ActivityTimelineFeed items={items} />);
      expect(screen.getByText('Logged Blood Pressure 120/80 mmHg')).toBeInTheDocument();
      expect(screen.getByText('Medication dose recorded')).toBeInTheDocument();

      // Test undoable-only filter
      fireEvent.click(screen.getByTestId('undoable-only-toggle'));
      expect(screen.getByText('Logged Blood Pressure 120/80 mmHg')).toBeInTheDocument();
      expect(screen.queryByText('Medication dose recorded')).not.toBeInTheDocument();
    });

    it('1.1 verifies active Undo button renders ONLY when undoable === true', () => {
      const onUndo = vi.fn();
      render(<ActivityTimelineItem item={baseItem} onUndo={onUndo} />);

      const activeBtn = screen.getByTestId('undo-action-btn');
      expect(activeBtn).toBeInTheDocument();
      expect(activeBtn).not.toBeDisabled();
      expect(screen.queryByTestId('undo-action-disabled-btn')).not.toBeInTheDocument();
      expect(screen.queryByTestId('undone-badge')).not.toBeInTheDocument();
      expect(screen.getByTestId('activity-summary')).not.toHaveClass('line-through');
    });

    it('1.2 verifies expired actions (> 7 days) render disabled button with exact tooltip', () => {
      const expiredItem: ActivityItemResponse = {
        ...baseItem,
        id: 'evt-expired',
        undoable: false,
        undone: false,
        risk: 'write_local',
        ts: '2026-10-01T00:00:00Z', // > 7 days ago
      };

      render(<ActivityTimelineItem item={expiredItem} />);

      expect(screen.queryByTestId('undo-action-btn')).not.toBeInTheDocument();
      const disabledBtn = screen.getByTestId('undo-action-disabled-btn');
      expect(disabledBtn).toBeInTheDocument();
      expect(disabledBtn).toBeDisabled();
      expect(disabledBtn).toHaveAttribute('title', 'Actions older than 7 days cannot be undone');
    });

    it('1.3 completely hides undo button for non-write_local actions (read, admin, undefined)', () => {
      const readItem: ActivityItemResponse = {
        ...baseItem,
        id: 'evt-read',
        risk: 'read',
        undoable: false,
      };
      const adminItem: ActivityItemResponse = {
        ...baseItem,
        id: 'evt-admin',
        risk: 'admin',
        undoable: false,
      };
      const untypedRiskItem: ActivityItemResponse = {
        ...baseItem,
        id: 'evt-untyped',
        risk: undefined,
        undoable: false,
      };

      const { rerender } = render(<ActivityTimelineItem item={readItem} />);
      expect(screen.queryByTestId('undo-action-btn')).not.toBeInTheDocument();
      expect(screen.queryByTestId('undo-action-disabled-btn')).not.toBeInTheDocument();

      rerender(<ActivityTimelineItem item={adminItem} />);
      expect(screen.queryByTestId('undo-action-btn')).not.toBeInTheDocument();
      expect(screen.queryByTestId('undo-action-disabled-btn')).not.toBeInTheDocument();

      rerender(<ActivityTimelineItem item={untypedRiskItem} />);
      expect(screen.queryByTestId('undo-action-btn')).not.toBeInTheDocument();
      expect(screen.queryByTestId('undo-action-disabled-btn')).not.toBeInTheDocument();
    });

    it('1.4 completely hides undo button when undone === true and applies [UNDONE] pill and strikethrough', () => {
      const alreadyUndoneItem: ActivityItemResponse = {
        ...baseItem,
        id: 'evt-already-undone',
        undoable: false,
        undone: true,
        risk: 'write_local',
      };

      render(<ActivityTimelineItem item={alreadyUndoneItem} />);

      expect(screen.queryByTestId('undo-action-btn')).not.toBeInTheDocument();
      expect(screen.queryByTestId('undo-action-disabled-btn')).not.toBeInTheDocument();
      expect(screen.getByTestId('undone-badge')).toHaveTextContent('[UNDONE]');
      expect(screen.getByTestId('activity-summary')).toHaveClass('line-through');
    });

    it('1.5 Undo Popover displays exact rollback summaries across all supported entity types and fallback', () => {
      const entities = [
        {
          ref: 'health_resource:obs-99',
          expected: 'Tombstones vital signs observation and removes it from trends.',
        },
        {
          ref: 'appointment:apt-88',
          expected: 'Marks the scheduled appointment as cancelled.',
        },
        {
          ref: 'reminder:rem-77',
          expected: 'Cancels the reminder and halts scheduled alerts.',
        },
        {
          ref: 'note:note-66',
          expected: 'Removes note and purges document from search index.',
        },
        {
          ref: 'prescription:rx-55',
          expected: 'Reverts the local state changes created by this action.',
        },
        {
          ref: undefined,
          expected: 'Reverts the local state changes created by this action.',
        },
        {
          ref: '',
          expected: 'Reverts the local state changes created by this action.',
        },
      ];

      for (const { ref, expected } of entities) {
        const testItem: ActivityItemResponse = {
          ...baseItem,
          external_ref: ref,
        };
        const { unmount } = render(
          <UndoConfirmPopover
            isOpen={true}
            onClose={vi.fn()}
            onConfirm={vi.fn()}
            item={testItem}
          />
        );
        expect(screen.getByText(expected)).toBeInTheDocument();
        unmount();
      }
    });

    it('1.6 Undo Popover controls: close via backdrop, cancel, and confirmation callback with loading state', async () => {
      const onClose = vi.fn();
      const onConfirm = vi.fn();

      const { rerender } = render(
        <UndoConfirmPopover
          isOpen={true}
          onClose={onClose}
          onConfirm={onConfirm}
          item={baseItem}
          isLoading={false}
        />
      );

      // Cancel button triggers onClose
      fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
      expect(onClose).toHaveBeenCalledTimes(1);

      // Confirm button triggers onConfirm
      fireEvent.click(screen.getByTestId('confirm-undo-btn'));
      expect(onConfirm).toHaveBeenCalledTimes(1);

      // Re-render in loading state
      rerender(
        <UndoConfirmPopover
          isOpen={true}
          onClose={onClose}
          onConfirm={onConfirm}
          item={baseItem}
          isLoading={true}
        />
      );
      expect(screen.getByText(/reverting.../i)).toBeInTheDocument();
      expect(screen.getByTestId('confirm-undo-btn')).toBeDisabled();
      expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
    });

    it('1.7 ProfileActivityClient executes rollback mutation, optimistically updates [UNDONE] with strikethrough, and prepends reversal event', async () => {
      const mockUndoResult: ActivityUndoResponse = {
        status: 'undone',
        event_id: 'evt-base',
        undo_event_id: 'evt-reversal-123',
        reverted_summary: 'Logged Blood Pressure 120/80 mmHg',
        message: 'Successfully tombstoned observation and purged trends.',
      };

      const spyUndo = vi.spyOn(activityApi, 'undoActivityEvent').mockResolvedValue(mockUndoResult);

      render(
        <ProfileActivityClient
          profileId="prof-test"
          initialItems={[baseItem]}
        />
      );

      // Open popover
      const undoBtn = screen.getByTestId('undo-action-btn');
      await act(async () => {
        fireEvent.click(undoBtn);
      });

      // Confirm undo
      const confirmBtn = screen.getByTestId('confirm-undo-btn');
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      // Verify POST invocation
      expect(spyUndo).toHaveBeenCalledWith('prof-test', 'evt-base');

      // Verify original item optimistically marked undone
      expect(screen.getByTestId('undone-badge')).toHaveTextContent('[UNDONE]');
      expect(screen.getByText('Logged Blood Pressure 120/80 mmHg')).toHaveClass('line-through');

      // Verify prepended reversal event is at top
      const itemsList = screen.getByTestId('activity-items-list');
      expect(itemsList.children.length).toBe(2);
      expect(screen.getByText('Reverted: Logged Blood Pressure 120/80 mmHg')).toBeInTheDocument();

      // Verify toast
      expect(screen.getByTestId('activity-toast-success')).toHaveTextContent('Action reverted successfully.');
    });

    it('1.8 ProfileActivityClient displays error banner and preserves item when rollback mutation rejects', async () => {
      vi.spyOn(activityApi, 'undoActivityEvent').mockRejectedValue(
        new Error('Network failure during rollback')
      );

      render(
        <ProfileActivityClient
          profileId="prof-test"
          initialItems={[baseItem]}
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

      expect(screen.getByText('Network failure during rollback')).toBeInTheDocument();
      expect(screen.queryByTestId('undone-badge')).not.toBeInTheDocument();
      expect(screen.getByText('Logged Blood Pressure 120/80 mmHg')).not.toHaveClass('line-through');
    });
  });

  // =========================================================================
  // 2. Inline Chat Cards Stress Tests
  // =========================================================================
  describe('2. Inline Chat Cards Component Tests', () => {
    describe('2.1 ExecutionPlanCard', () => {
      it('renders all template intent titles correctly', () => {
        const intents: Array<[string | undefined, string]> = [
          ['visit_prep', 'Clinical Visit Preparation Plan'],
          ['log_vitals', 'Vitals Observation Logging Pipeline'],
          ['remind_me', 'Reminder & Recurrence Scheduling Plan'],
          ['custom_flow', 'Execution Plan: custom_flow'],
          ['', 'Multi-Step Execution Plan'],
          [undefined, 'Multi-Step Execution Plan'],
        ];

        for (const [intent, expectedTitle] of intents) {
          const plan: ExecutionPlan = {
            id: 'plan-1',
            intent,
            steps: [],
          };
          const { unmount } = render(<ExecutionPlanCard plan={plan} />);
          expect(screen.getByTestId('execution-plan-intent-title')).toHaveTextContent(expectedTitle);
          unmount();
        }
      });

      it('correlates tool traces accurately across pending, running (in_progress), completed, and failed/denied', () => {
        const plan: ExecutionPlan = {
          id: 'plan-multistep',
          intent: 'visit_prep',
          steps: [
            { step: 1, tool: 'tool_one', description: 'Step 1 description', status: 'pending' },
            { step: 2, tool: 'tool_two', description: 'Step 2 description', status: 'pending' },
            { step: 3, tool: 'tool_three', description: 'Step 3 description', status: 'pending' },
            { step: 4, tool: 'tool_four', description: 'Step 4 description', status: 'pending' },
            { step: 5, description: 'Step without tool', status: 'pending' },
          ],
        };

        const traces: ToolTraceItem[] = [
          { id: 'tr-1', tool: 'tool_one', status: 'running' },
          { id: 'tr-2', tool: 'tool_two', status: 'completed' },
          { id: 'tr-3', tool: 'tool_three', status: 'failed' },
          { id: 'tr-4', tool: 'tool_four', status: 'denied' },
        ];

        render(<ExecutionPlanCard plan={plan} activeTraces={traces} />);

        // Step 1: running -> in_progress
        const step1 = screen.getByTestId('plan-step-1');
        expect(step1).toHaveTextContent(/in progress/i);
        expect(screen.getByTestId('step-icon-in-progress')).toBeInTheDocument();

        // Step 2: completed -> completed
        const step2 = screen.getByTestId('plan-step-2');
        expect(step2).toHaveTextContent(/completed/i);
        expect(screen.getByTestId('step-icon-completed')).toBeInTheDocument();

        // Step 3 & 4: failed & denied -> failed
        const step3 = screen.getByTestId('plan-step-3');
        const step4 = screen.getByTestId('plan-step-4');
        expect(step3).toHaveTextContent(/failed/i);
        expect(step4).toHaveTextContent(/failed/i);
        expect(screen.getAllByTestId('step-icon-failed')).toHaveLength(2);

        // Step 5: untooled -> remains pending
        const step5 = screen.getByTestId('plan-step-5');
        expect(step5).toHaveTextContent(/pending/i);
        expect(screen.getByTestId('step-icon-pending')).toBeInTheDocument();
      });

      it('supports collapsible reasoning accordion and multiple assigned specialists', () => {
        const plan: ExecutionPlan = {
          id: 'plan-advanced',
          intent: 'visit_prep',
          target_agents: ['derma-guide', 'oncology-navigator'],
          reasoning: 'Multi-specialist consultation workflow initialized.',
          steps: [],
        };

        render(<ExecutionPlanCard plan={plan} />);

        expect(screen.getByTestId('target-agent-derma-guide')).toBeInTheDocument();
        expect(screen.getByTestId('target-agent-oncology-navigator')).toBeInTheDocument();

        const toggleBtn = screen.getByTestId('toggle-reasoning-btn');
        expect(screen.queryByTestId('plan-reasoning-content')).not.toBeInTheDocument();

        fireEvent.click(toggleBtn);
        expect(screen.getByTestId('plan-reasoning-content')).toHaveTextContent(
          'Multi-specialist consultation workflow initialized.'
        );

        fireEvent.click(toggleBtn);
        expect(screen.queryByTestId('plan-reasoning-content')).not.toBeInTheDocument();
      });
    });

    describe('2.2 EmergencyEscalationCard', () => {
      const RED_FLAG_SPECS = [
        { category: 'bp_crisis_symptomatic', title: 'Hypertensive Crisis with Symptoms' },
        { category: 'bp_crisis_asymptomatic', title: 'Severe Blood Pressure Elevation' },
        { category: 'severe_hypoxemia', title: 'Severe Hypoxemia (Low Oxygen)' },
        { category: 'severe_hypoglycemia', title: 'Severe Hypoglycemia (Low Blood Sugar)' },
        { category: 'symptomatic_hypotension', title: 'Symptomatic Hypotension' },
        { category: 'suicide_crisis', title: 'Suicide & Crisis Support' },
      ];

      for (const { category, title } of RED_FLAG_SPECS) {
        it(`renders high-visibility card for acute red-flag category: ${category}`, () => {
          const msg: ChatMessage = {
            id: `msg-${category}`,
            role: 'assistant',
            content: `Acute emergency event detected: ${category}`,
            isEmergency: true,
            emergencyCategory: category,
          };

          const { unmount } = render(<EmergencyEscalationCard message={msg} />);
          expect(screen.getByTestId('emergency-escalation-card')).toBeInTheDocument();
          expect(screen.getByTestId('emergency-category-badge')).toHaveTextContent(title);
          expect(screen.getByTestId('emergency-call-911-btn')).toHaveAttribute('href', 'tel:911');
          expect(screen.getByTestId('emergency-find-er-btn')).toBeInTheDocument();
          expect(screen.getByTestId('emergency-nonclinical-disclaimer')).toBeInTheDocument();
          unmount();
        });
      }

      it('conditionally renders 988 touch action ONLY for crisis categories with >= 44px min-height', () => {
        const crisisMsg: ChatMessage = {
          id: 'msg-suicide',
          role: 'assistant',
          content: 'Crisis intervention needed',
          isEmergency: true,
          emergencyCategory: 'suicide_crisis',
        };
        const nonCrisisMsg: ChatMessage = {
          id: 'msg-bp',
          role: 'assistant',
          content: 'Blood pressure crisis',
          isEmergency: true,
          emergencyCategory: 'bp_crisis_symptomatic',
        };

        const { rerender } = render(<EmergencyEscalationCard message={crisisMsg} />);
        const btn988 = screen.getByTestId('emergency-call-988-btn');
        expect(btn988).toBeInTheDocument();
        expect(btn988).toHaveAttribute('href', 'tel:988');
        expect(btn988.className).toContain('min-h-[44px]');

        const btn911 = screen.getByTestId('emergency-call-911-btn');
        expect(btn911.className).toContain('min-h-[44px]');

        rerender(<EmergencyEscalationCard message={nonCrisisMsg} />);
        expect(screen.queryByTestId('emergency-call-988-btn')).not.toBeInTheDocument();
      });

      it('rigorously tests non-clinical safety disclaimer content per AGENTS.md §1.1', () => {
        const msg: ChatMessage = {
          id: 'msg-disc',
          role: 'assistant',
          content: 'Emergency alert',
          isEmergency: true,
          emergencyCategory: 'severe_hypoxemia',
        };

        render(<EmergencyEscalationCard message={msg} />);
        const disclaimer = screen.getByTestId('emergency-nonclinical-disclaimer');
        expect(disclaimer).toHaveTextContent(/educational navigation and visit preparation only/i);
        expect(disclaimer).toHaveTextContent(/cannot diagnose conditions/i);
        expect(disclaimer).toHaveTextContent(/replace emergency medical personnel/i);
      });
    });
  });

  // =========================================================================
  // 3. AppRail Navigation Route Links Stress Tests
  // =========================================================================
  describe('3. AppRail Navigation Route Links Tests', () => {
    it('verifies route links for /p/[profileId]/vitals, /p/[profileId]/appointments, and /p/[profileId]/activity', async () => {
      const customProfile = {
        id: 'patient-42',
        name: 'Arthur Dent',
        role: 'Personal care',
      };

      await act(async () => {
        render(<AppRail activeProfile={customProfile} collapsed={false} />);
      });

      const vitalsLink = screen.getByRole('link', { name: /vitals/i });
      expect(vitalsLink).toHaveAttribute('href', '/p/patient-42/vitals');
      expect(vitalsLink.className).toContain('min-h-[44px]');

      const scheduleLink = screen.getByRole('link', { name: /schedule/i });
      expect(scheduleLink).toHaveAttribute('href', '/p/patient-42/appointments');
      expect(scheduleLink.className).toContain('min-h-[44px]');

      const activityLink = screen.getByRole('link', { name: /activity/i });
      expect(activityLink).toHaveAttribute('href', '/p/patient-42/activity');
      expect(activityLink.className).toContain('min-h-[44px]');
    });
  });
});
