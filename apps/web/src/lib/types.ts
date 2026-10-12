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

/**
 * Carefold Web Application Shared Types
 * Centralizes chat, agent, tool trace, and API request schemas.
 */

export * from '../types/api.js';

// ---------------------------------------------------------------------------
// Tool Trace Types (Canonical Domain Definitions)
// ---------------------------------------------------------------------------
export type ToolTraceStatus = 'running' | 'completed' | 'denied' | 'failed';

export interface ToolTraceItem {
  id?: string;
  tool: string;
  status: ToolTraceStatus;
  input?: Record<string, any>;
  params?: Record<string, any>;
  output?: any;
  result?: any;
  error?: string;
  duration_ms?: number;
  allowed?: boolean;
  reason?: string;
  startTime?: number;
}

export type ToolTrace = ToolTraceItem;

// ---------------------------------------------------------------------------
// Chat Message Interface
// ---------------------------------------------------------------------------
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  isStreaming?: boolean;
  isRefusal?: boolean;
  isEmergency?: boolean;
  emergencyCategory?: string;
  refusalReason?: string;
  boundaryWarning?: boolean;
  boundaryReason?: string;
  toolTraces?: ToolTraceItem[];
  traces?: ToolTraceItem[];
  attachments?: string[];
  approval?: ApprovalRecord;
  contextSources?: ContextSourceItem[];
}

// ---------------------------------------------------------------------------
// Agent Detail ViewModel
// ---------------------------------------------------------------------------
export interface AgentDetail {
  id: string;
  title: string;
  version: string;
  license?: string;
  risk_class: string;
  model: string;
  hidden?: boolean;
  skills: Array<{
    id: string;
    name: string;
    title?: string;
    description: string;
    version: string;
    risk_class: string;
    tools: string[];
  }>;
  effectiveTools: string[];
  forbidden: string[];
  persona: string;
  starters: string[];
  readmeText?: string;
  description?: string;
}

// ---------------------------------------------------------------------------
// Extracted Dossier Types (Issue #94)
// ---------------------------------------------------------------------------
export interface ClinicalVisitDossierData {
  reason_for_visit?: string;
  physician_instructions?: string[];
  follow_up_timeline?: string;
  questions_to_ask?: string[];
}

export interface InsuranceBenefitsDossierData {
  deductible?: string;
  copays?: Record<string, string>;
  coinsurance?: string;
  out_of_pocket_maximum?: string;
  in_out_network_rules?: string;
  prior_authorization_flags?: string[];
}

export interface GenericDocumentDossierData {
  summary?: string;
  key_numerical_values?: Record<string, string>;
  sections?: string[];
}

export type DossierType =
  | 'clinical_visit'
  | 'clinical'
  | 'insurance_benefits'
  | 'insurance'
  | 'generic_document'
  | 'generic'
  | 'unknown';

export interface ExtractedDossierPayload {
  status?: string;
  dossier_type?: string;
  dossier?:
    | ClinicalVisitDossierData
    | InsuranceBenefitsDossierData
    | GenericDocumentDossierData
    | Record<string, any>;
  is_grounded?: boolean;
  unmatched_values?: string[];
  source_file?: string;
}

export interface ChecklistItemState {
  id: string;
  text: string;
  completed: boolean;
  isCustom?: boolean;
}

// ---------------------------------------------------------------------------
// Audit & Activity Types (Re-exported from types/api.ts for convenience)
// ---------------------------------------------------------------------------
export type {
  AuditEventType,
  AuditEvent,
  AuditListResponse,
  AuditFilterParams
} from '../types/api.js';

// ---------------------------------------------------------------------------
// Memory Types (Re-exported from types/api.ts for convenience)
// ---------------------------------------------------------------------------
export type {
  MemoryTier,
  MemoryRecord,
  MemoryFilterParams,
  MemoryStatus,
  MemoryDeleteResponse,
  MemoryBulkDeleteResponse,
  MemoryUpdateRequest,
} from '../types/api.js';

// ---------------------------------------------------------------------------
// Human-in-the-Loop Approvals Engine Types (AU-18)
// ---------------------------------------------------------------------------
export type RiskTier = 'read' | 'write_local' | 'write_workspace' | 'write_external' | 'admin' | 'irreversible';

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'consumed' | 'expired';

export interface ApprovalRecord {
  id: string;
  profile_id?: string;
  run_id?: string;
  thread_id?: string;
  tool_name: string;
  args_redacted: Record<string, any> | string;
  payload_hash: string;
  destination_hosts?: string[] | string;
  risk_tier: RiskTier;
  status: ApprovalStatus;
  expires_at?: string;
  created_at?: string;
  decided_at?: string;
  decided_by?: string;
  reason?: string;
}

export interface ApprovalDecisionRequest {
  decision: 'approved' | 'rejected';
  edited_args?: Record<string, any>;
  reason?: string;
}

export interface ApprovalDecisionResponse {
  id: string;
  status: ApprovalStatus;
  payload_hash: string;
  decided_at: string;
  decided_by?: string;
}

// ---------------------------------------------------------------------------
// Context Sources Streaming Types (AU-20)
// ---------------------------------------------------------------------------
export type ContextSourceType = 'thread' | 'attachments' | 'records' | 'vault' | 'connector' | 'web';

export interface ContextSourceItem {
  id: string;
  type: ContextSourceType;
  label: string;
  description?: string;
  has_phi?: boolean;
  is_tainted?: boolean;
  metadata?: Record<string, any>;
}

export interface ContextSourcesEventPayload {
  type: 'context_sources';
  sources: ContextSourceItem[];
  tainted: boolean;
  has_phi: boolean;
}

