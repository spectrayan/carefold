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
