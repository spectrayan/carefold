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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ExecutionPlanCard } from '@/components/chat/ExecutionPlanCard';
import { EmergencyEscalationCard } from '@/components/chat/EmergencyEscalationCard';
import type { ExecutionPlan } from '@/types/activity';
import type { ChatMessage, ToolTraceItem } from '@/lib/types';

describe('Inline Chat Cards (ExecutionPlanCard & EmergencyEscalationCard)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('ExecutionPlanCard Component', () => {
    const mockPlan: ExecutionPlan = {
      id: 'plan-101',
      intent: 'visit_prep',
      mode: 'pipeline',
      status: 'in_progress',
      target_agents: ['visit-steward', 'cardiology-guide'],
      reasoning: 'Deterministic 3-step pipeline compiled for cardiology consultation prep.',
      steps: [
        {
          step: 1,
          tool: 'search_records',
          description: 'Retrieve prior EKG and cardiology notes from health vault',
          status: 'completed',
        },
        {
          step: 2,
          tool: 'calculate_trends',
          description: 'Compute 30-day diurnal blood pressure spread',
          status: 'pending',
        },
        {
          step: 3,
          tool: 'generate_prep_pack',
          description: 'Compile consultation prep pack dossier and questions',
          status: 'pending',
        },
      ],
    };

    it('renders intent title, execution mode badge, and status pill', () => {
      render(<ExecutionPlanCard plan={mockPlan} />);

      expect(screen.getByTestId('execution-plan-card')).toBeInTheDocument();
      expect(screen.getByTestId('execution-plan-intent-title')).toHaveTextContent(
        'Clinical Visit Preparation Plan'
      );
      expect(screen.getByTestId('execution-plan-mode-badge')).toHaveTextContent('pipeline');
      expect(screen.getByTestId('execution-plan-status-badge')).toHaveTextContent('in_progress');
    });

    it('renders checklist steps with step tools and descriptions', () => {
      render(<ExecutionPlanCard plan={mockPlan} />);

      expect(screen.getByTestId('plan-step-1')).toBeInTheDocument();
      expect(screen.getByTestId('plan-step-2')).toBeInTheDocument();
      expect(screen.getByTestId('plan-step-3')).toBeInTheDocument();

      expect(screen.getByTestId('step-tool-search_records')).toBeInTheDocument();
      expect(screen.getByTestId('step-tool-calculate_trends')).toBeInTheDocument();
      expect(screen.getByTestId('step-tool-generate_prep_pack')).toBeInTheDocument();

      expect(
        screen.getByText('Retrieve prior EKG and cardiology notes from health vault')
      ).toBeInTheDocument();
    });

    it('dynamically updates step status from active tool traces', () => {
      const activeTraces: ToolTraceItem[] = [
        {
          id: 'trace-1',
          tool: 'calculate_trends',
          status: 'running',
        },
      ];

      render(<ExecutionPlanCard plan={mockPlan} activeTraces={activeTraces} />);

      const step2 = screen.getByTestId('plan-step-2');
      expect(step2).toHaveTextContent(/in progress/i);
      expect(screen.getByTestId('step-icon-in-progress')).toBeInTheDocument();
    });

    it('renders assigned specialists and toggles collapsible reasoning drawer', () => {
      render(<ExecutionPlanCard plan={mockPlan} />);

      expect(screen.getByTestId('target-agent-visit-steward')).toBeInTheDocument();
      expect(screen.getByTestId('target-agent-cardiology-guide')).toBeInTheDocument();

      const toggleBtn = screen.getByTestId('toggle-reasoning-btn');
      expect(screen.queryByTestId('execution-plan-reasoning')).not.toBeInTheDocument();

      fireEvent.click(toggleBtn);
      expect(screen.getByTestId('plan-reasoning-content')).toBeInTheDocument();
      expect(
        screen.getByText(/Deterministic 3-step pipeline compiled for cardiology consultation prep/i)
      ).toBeInTheDocument();
    });

    it('renders correct titles across template intents: log_vitals, remind_me, generic, and undefined', () => {
      const vitalsPlan: ExecutionPlan = {
        id: 'plan-vitals',
        intent: 'log_vitals',
        mode: 'pipeline',
        status: 'completed',
        steps: [],
      };
      const reminderPlan: ExecutionPlan = {
        id: 'plan-remind',
        intent: 'remind_me',
        mode: 'parallel',
        status: 'compiled',
        steps: [],
      };
      const genericPlan: ExecutionPlan = {
        id: 'plan-generic',
        intent: 'extract_records',
        steps: [],
      };
      const untitledPlan: ExecutionPlan = {
        id: 'plan-empty',
        steps: [],
      };

      const { rerender } = render(<ExecutionPlanCard plan={vitalsPlan} />);
      expect(screen.getByTestId('execution-plan-intent-title')).toHaveTextContent(
        'Vitals Observation Logging Pipeline'
      );
      expect(screen.getByTestId('execution-plan-status-badge')).toHaveTextContent('completed');

      rerender(<ExecutionPlanCard plan={reminderPlan} />);
      expect(screen.getByTestId('execution-plan-intent-title')).toHaveTextContent(
        'Reminder & Recurrence Scheduling Plan'
      );
      expect(screen.getByTestId('execution-plan-mode-badge')).toHaveTextContent('parallel');

      rerender(<ExecutionPlanCard plan={genericPlan} />);
      expect(screen.getByTestId('execution-plan-intent-title')).toHaveTextContent(
        'Execution Plan: extract_records'
      );

      rerender(<ExecutionPlanCard plan={untitledPlan} />);
      expect(screen.getByTestId('execution-plan-intent-title')).toHaveTextContent(
        'Multi-Step Execution Plan'
      );
    });

    it('correlates tool traces across all states: running, completed, failed, denied, and unmatched', () => {
      const stepPlan: ExecutionPlan = {
        id: 'plan-trace-test',
        intent: 'visit_prep',
        steps: [
          { step: 1, tool: 'tool_a', description: 'Step A', status: 'pending' },
          { step: 2, tool: 'tool_b', description: 'Step B', status: 'pending' },
          { step: 3, tool: 'tool_c', description: 'Step C', status: 'pending' },
          { step: 4, tool: 'tool_d', description: 'Step D', status: 'pending' },
          { step: 5, description: 'Step without tool', status: 'pending' },
        ],
      };

      const traces: ToolTraceItem[] = [
        { id: 't1', tool: 'tool_a', status: 'running' },
        { id: 't2', tool: 'tool_b', status: 'completed' },
        { id: 't3', tool: 'tool_c', status: 'failed' },
        { id: 't4', tool: 'tool_d', status: 'denied' },
      ];

      render(<ExecutionPlanCard plan={stepPlan} activeTraces={traces} />);

      expect(screen.getByTestId('step-icon-in-progress')).toBeInTheDocument();
      expect(screen.getByTestId('step-icon-completed')).toBeInTheDocument();
      const failedIcons = screen.getAllByTestId('step-icon-failed');
      expect(failedIcons.length).toBe(2); // failed and denied both map to failed

      expect(screen.getByTestId('step-icon-pending')).toBeInTheDocument();
    });
  });

  describe('EmergencyEscalationCard Component', () => {
    it('renders hypertensive crisis red-flag category and 911 action button', () => {
      const emergencyMessage: ChatMessage = {
        id: 'msg-emergency-1',
        role: 'assistant',
        content: 'EMERGENCY: Systolic BP 190 mmHg with acute chest pain detected.',
        isEmergency: true,
        emergencyCategory: 'bp_crisis_symptomatic',
      };

      render(<EmergencyEscalationCard message={emergencyMessage} />);

      expect(screen.getByTestId('emergency-escalation-card')).toBeInTheDocument();
      expect(screen.getByTestId('emergency-card-heading')).toHaveTextContent(
        'This may be an emergency'
      );
      expect(screen.getByTestId('emergency-category-badge')).toHaveTextContent(
        'Hypertensive Crisis with Symptoms'
      );
      expect(screen.getByTestId('emergency-call-911-btn')).toHaveAttribute('href', 'tel:911');
      expect(screen.getByTestId('emergency-find-er-btn')).toBeInTheDocument();
      expect(screen.getByTestId('emergency-nonclinical-disclaimer')).toBeInTheDocument();
    });

    it('renders severe hypoxemia red flag category correctly', () => {
      const hypoxemiaMessage: ChatMessage = {
        id: 'msg-emergency-2',
        role: 'assistant',
        content: 'EMERGENCY: SpO2 reading is 86%. Immediate medical attention is required.',
        isEmergency: true,
        emergencyCategory: 'severe_hypoxemia',
      };

      render(<EmergencyEscalationCard message={hypoxemiaMessage} />);
      expect(screen.getByTestId('emergency-category-badge')).toHaveTextContent(
        'Severe Hypoxemia (Low Oxygen)'
      );
    });

    it('renders severe hypoglycemia, symptomatic hypotension, and asymptomatic BP elevation', () => {
      const hypoglyMessage: ChatMessage = {
        id: 'msg-emergency-gly',
        role: 'assistant',
        content: 'EMERGENCY: Blood glucose 45 mg/dL. Immediate Rule of 15 directive required.',
        isEmergency: true,
        emergencyCategory: 'severe_hypoglycemia',
      };
      const hypotensMessage: ChatMessage = {
        id: 'msg-emergency-hypo',
        role: 'assistant',
        content: 'Blood pressure 80/50 mmHg with acute lightheadedness and fainting.',
        isEmergency: true,
        emergencyCategory: 'symptomatic_hypotension',
      };
      const asympMessage: ChatMessage = {
        id: 'msg-emergency-asymp',
        role: 'assistant',
        content: 'Blood pressure 185/122 mmHg without acute symptoms.',
        isEmergency: true,
        emergencyCategory: 'bp_crisis_asymptomatic',
      };

      const { rerender } = render(<EmergencyEscalationCard message={hypoglyMessage} />);
      expect(screen.getByTestId('emergency-category-badge')).toHaveTextContent(
        'Severe Hypoglycemia (Low Blood Sugar)'
      );

      rerender(<EmergencyEscalationCard message={hypotensMessage} />);
      expect(screen.getByTestId('emergency-category-badge')).toHaveTextContent(
        'Symptomatic Hypotension'
      );

      rerender(<EmergencyEscalationCard message={asympMessage} />);
      expect(screen.getByTestId('emergency-category-badge')).toHaveTextContent(
        'Severe Blood Pressure Elevation'
      );
    });

    it('extracts red flag category from refusalReason fallback when emergencyCategory is omitted', () => {
      const fallbackMessage: ChatMessage = {
        id: 'msg-fallback',
        role: 'assistant',
        content: 'Critical vitals detected.',
        isEmergency: true,
        refusalReason: 'emergency_red_flag:severe_hypoglycemia',
      };

      render(<EmergencyEscalationCard message={fallbackMessage} />);
      expect(screen.getByTestId('emergency-category-badge')).toHaveTextContent(
        'Severe Hypoglycemia (Low Blood Sugar)'
      );
    });

    it('renders 988 Suicide & Crisis Lifeline link for crisis category and enforces >= 44px touch targets', () => {
      const crisisMessage: ChatMessage = {
        id: 'msg-emergency-3',
        role: 'assistant',
        content: 'Please reach out for help. Support is available right now.',
        isEmergency: true,
        emergencyCategory: 'suicide_crisis',
      };

      render(<EmergencyEscalationCard message={crisisMessage} />);
      expect(screen.getByTestId('emergency-category-badge')).toHaveTextContent(
        'Suicide & Crisis Support'
      );
      const btn988 = screen.getByTestId('emergency-call-988-btn');
      expect(btn988).toBeInTheDocument();
      expect(btn988).toHaveAttribute('href', 'tel:988');
      expect(btn988.className).toContain('min-h-[44px]');

      const btn911 = screen.getByTestId('emergency-call-911-btn');
      expect(btn911.className).toContain('min-h-[44px]');

      const erBtn = screen.getByTestId('emergency-find-er-btn');
      expect(erBtn.className).toContain('min-h-[44px]');
      expect(erBtn).toHaveAttribute('target', '_blank');
      expect(erBtn).toHaveAttribute('rel', 'noopener noreferrer');
    });

    it('verifies non-clinical safety disclaimer text conforms to AGENTS.md §1.1', () => {
      const msg: ChatMessage = {
        id: 'msg-disclaimer',
        role: 'assistant',
        content: 'Emergency alert',
        isEmergency: true,
        emergencyCategory: 'bp_crisis_symptomatic',
      };

      render(<EmergencyEscalationCard message={msg} />);
      const disclaimer = screen.getByTestId('emergency-nonclinical-disclaimer');
      expect(disclaimer).toHaveTextContent(/educational navigation and visit preparation only/i);
      expect(disclaimer).toHaveTextContent(/cannot diagnose conditions/i);
      expect(disclaimer).toHaveTextContent(/replace emergency medical personnel/i);
    });
  });
});

