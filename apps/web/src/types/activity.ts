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

export interface ActivityItemResponse {
  id: string;
  event_id?: string;
  ts: string; // ISO UTC
  profile_id: string;
  actor_user_id?: string | null;
  principal: string; // 'user' | 'agent' | 'orchestrator' | 'system'
  actor: string; // 'user' | 'agent' | 'system'
  event: string; // 'tool' | 'run' | 'refuse' | 'undo' | 'create'
  action?: string | null;
  tool?: string | null;
  risk?: string | null; // 'write_local' | 'read' | 'write_external' | 'irreversible'
  external_ref?: string | null; // '<entity_type>:<entity_id>'
  summary: string; // e.g. "Logged blood pressure 120/80 mmHg"
  description: string; // e.g. "Recorded pulse oximetry reading of 98% SpO2."
  undoable: boolean; // true if write_local, <= 7 days, not undone, valid external_ref
  undone: boolean; // true if already reverted
  details: Record<string, any>;
}

export interface ActivityTimelineResponse {
  items: ActivityItemResponse[];
  total: number;
  limit: number;
  offset: number;
  profile_id: string;
  has_more: boolean;
}

export interface ActivityUndoResponse {
  status: 'undone';
  event_id: string;
  undo_event_id?: string;
  external_ref?: string;
  reverted_summary?: string;
  message?: string;
}

export interface ExecutionPlanStep {
  step: number;
  tool?: string;
  description: string;
  status?: 'pending' | 'in_progress' | 'completed' | 'failed';
}

export interface AgentTask {
  agent_id: string;
  instructions?: string;
  task_description?: string;
  priority?: number;
  depends_on?: string[];
  dependencies?: string[];
  required_docs?: string[];
}

export interface ExecutionPlan {
  id: string;
  intent?: 'visit_prep' | 'log_vitals' | 'remind_me' | string;
  parameters?: Record<string, any>;
  steps: ExecutionPlanStep[];
  status?: 'compiled' | 'in_progress' | 'completed' | 'draft' | string;
  mode?: 'single' | 'parallel' | 'pipeline';
  target_agents?: string[];
  tasks?: AgentTask[];
  reasoning?: string;
}
