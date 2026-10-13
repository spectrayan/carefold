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

'use client';

import React, { useState } from 'react';
import {
  ListChecks,
  CheckCircle2,
  Loader2,
  XCircle,
  Bot,
  ChevronDown,
  ChevronRight,
  Workflow,
} from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';
import type { ExecutionPlan, ExecutionPlanStep } from '@/types/activity';
import type { ToolTraceItem } from '@/lib/types';

export interface ExecutionPlanCardProps {
  plan: ExecutionPlan;
  activeTraces?: ToolTraceItem[];
  className?: string;
}

export function ExecutionPlanCard({
  plan,
  activeTraces = [],
  className,
}: ExecutionPlanCardProps) {
  const [showReasoning, setShowReasoning] = useState(false);

  const intentTitle = () => {
    switch (plan.intent) {
      case 'visit_prep':
        return 'Clinical Visit Preparation Plan';
      case 'log_vitals':
        return 'Vitals Observation Logging Pipeline';
      case 'remind_me':
        return 'Reminder & Recurrence Scheduling Plan';
      default:
        return plan.intent
          ? `Execution Plan: ${plan.intent}`
          : 'Multi-Step Execution Plan';
    }
  };

  const statusVariant = (status?: string) => {
    switch (status) {
      case 'completed':
        return 'success';
      case 'in_progress':
        return 'warning';
      case 'compiled':
        return 'info';
      default:
        return 'neutral';
    }
  };

  const resolveStepStatus = (step: ExecutionPlanStep) => {
    if (activeTraces && activeTraces.length > 0 && step.tool) {
      const match = activeTraces.find((t) => t.tool === step.tool);
      if (match) {
        if (match.status === 'running') return 'in_progress';
        if (match.status === 'completed') return 'completed';
        if (match.status === 'denied' || match.status === 'failed') return 'failed';
      }
    }
    return step.status || 'pending';
  };

  return (
    <div
      data-testid="execution-plan-card"
      className={cn(
        'p-4 rounded-2xl border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50/50 dark:bg-emerald-950/20 shadow-sm space-y-3 text-xs',
        className
      )}
    >
      {/* Header Row */}
      <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-emerald-200/80 dark:border-emerald-900/40">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-emerald-600 text-white flex items-center justify-center shrink-0">
            <ListChecks className="w-3.5 h-3.5" />
          </div>
          <h4
            data-testid="execution-plan-intent-title"
            className="font-bold text-sm text-[var(--cf-fg)]"
          >
            {intentTitle()}
          </h4>
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          {plan.mode && (
            <span
              data-testid="execution-plan-mode-badge"
              className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 dark:bg-emerald-900/60 text-emerald-800 dark:text-emerald-200 uppercase tracking-wider"
            >
              <Workflow className="w-3 h-3 inline mr-1" />
              {plan.mode}
            </span>
          )}

          <Badge
            data-testid="execution-plan-status-badge"
            variant={statusVariant(plan.status)}
            size="sm"
          >
            {plan.status || 'compiled'}
          </Badge>
        </div>
      </div>

      {/* Progress Steps Checklist */}
      <div data-testid="execution-plan-steps" className="space-y-2">
        {plan.steps && plan.steps.map((step) => {
          const stepStatus = resolveStepStatus(step);

          return (
            <div
              key={step.step}
              data-testid={`plan-step-${step.step}`}
              className={cn(
                'p-2.5 rounded-xl border flex items-start gap-2.5 transition-colors',
                stepStatus === 'completed'
                  ? 'border-emerald-300 dark:border-emerald-900 bg-white/70 dark:bg-zinc-900/70'
                  : stepStatus === 'in_progress'
                  ? 'border-amber-300 dark:border-amber-900 bg-amber-50/40 dark:bg-amber-950/20'
                  : stepStatus === 'failed'
                  ? 'border-rose-300 dark:border-rose-900 bg-rose-50/40 dark:bg-rose-950/20'
                  : 'border-[var(--cf-border)] bg-[var(--cf-surface)]'
              )}
            >
              {/* Step Status Indicator Icon */}
              <div className="mt-0.5 shrink-0">
                {stepStatus === 'completed' ? (
                  <CheckCircle2
                    data-testid="step-icon-completed"
                    className="w-4 h-4 text-emerald-600"
                  />
                ) : stepStatus === 'in_progress' ? (
                  <Loader2
                    data-testid="step-icon-in-progress"
                    className="w-4 h-4 text-amber-600 animate-spin"
                  />
                ) : stepStatus === 'failed' ? (
                  <XCircle
                    data-testid="step-icon-failed"
                    className="w-4 h-4 text-rose-600"
                  />
                ) : (
                  <span
                    data-testid="step-icon-pending"
                    className="w-4 h-4 rounded-full border border-[var(--cf-border-strong)] text-[10px] font-mono font-semibold flex items-center justify-center text-[var(--cf-fg-subtle)]"
                  >
                    {step.step}
                  </span>
                )}
              </div>

              {/* Step Content */}
              <div className="flex-1 min-w-0 space-y-0.5">
                <div className="flex items-center gap-2 flex-wrap">
                  {step.tool && (
                    <span
                      data-testid={`step-tool-${step.tool}`}
                      className="px-1.5 py-0.2 rounded font-mono text-[10px] bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border border-[var(--cf-border)]"
                    >
                      {step.tool}
                    </span>
                  )}
                  <span
                    data-testid="step-status-pill"
                    className={cn(
                      'text-[10px] font-medium capitalize',
                      stepStatus === 'completed' && 'text-emerald-700 dark:text-emerald-300',
                      stepStatus === 'in_progress' && 'text-amber-700 dark:text-amber-300 font-semibold',
                      stepStatus === 'failed' && 'text-rose-700 dark:text-rose-300 font-semibold',
                      stepStatus === 'pending' && 'text-[var(--cf-fg-subtle)]'
                    )}
                  >
                    {stepStatus.replace('_', ' ')}
                  </span>
                </div>
                <p className="text-[var(--cf-fg)] leading-relaxed">
                  {step.description}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Target Agents Row */}
      {plan.target_agents && plan.target_agents.length > 0 && (
        <div className="pt-2 flex items-center gap-1.5 text-[11px] text-[var(--cf-fg-muted)] flex-wrap">
          <Bot className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
          <span>Assigned specialists:</span>
          {plan.target_agents.map((ag) => (
            <span
              key={ag}
              data-testid={`target-agent-${ag}`}
              className="px-2 py-0.5 rounded-full bg-white dark:bg-zinc-800 text-[var(--cf-fg)] font-medium border border-[var(--cf-border)]"
            >
              {ag}
            </span>
          ))}
        </div>
      )}

      {/* Collapsible Rationale / Reasoning */}
      {plan.reasoning && (
        <div className="pt-1 border-t border-emerald-200/60 dark:border-emerald-900/40">
          <button
            type="button"
            data-testid="toggle-reasoning-btn"
            onClick={() => setShowReasoning((prev) => !prev)}
            className="flex items-center gap-1 text-[11px] font-medium text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] transition-colors py-1"
          >
            {showReasoning ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <span>View Orchestrator Rationale</span>
          </button>
          {showReasoning && (
            <div
              data-testid="plan-reasoning-content"
              className="p-2.5 rounded-xl bg-white/60 dark:bg-zinc-900/60 text-[11px] text-[var(--cf-fg-muted)] leading-relaxed border border-[var(--cf-border)] font-mono"
            >
              {plan.reasoning}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ExecutionPlanCard;
