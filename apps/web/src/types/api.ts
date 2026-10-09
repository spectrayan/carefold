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

export type RiskClass = 'wellness' | 'admin' | 'clinical_assist';

export const SAFE_REFUSAL_TEMPLATE =
  'I am a wellness and care navigation assistant, not a licensed medical professional or emergency service. I cannot diagnose conditions, prescribe medications, or alter medical treatments. Please consult a qualified healthcare provider or contact emergency services immediately if you are experiencing a medical emergency.';

export interface AgentModelConfig {
  provider?: string;
  model?: string;
  baseUrl?: string;
  apiKey?: string;
}

export interface AgentPersona {
  role?: string;
  instructions?: string;
}

export interface ToolResult {
  success: boolean;
  output?: any;
  error?: string;
}

// ---------------------------------------------------------------------------
// Health Types
// ---------------------------------------------------------------------------
export interface OllamaHealthStatus {
  status: 'connected' | 'unreachable' | 'error';
  endpoint: string;
  reachable: boolean;
  activeModel?: string;
  availableModels?: string[];
  error?: string;
}

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'error';
  version: string;
  uptime: number; // process uptime in seconds
  timestamp: string; // ISO 8601 string
  modelReachable?: boolean; // convenience alias for tests
  backendReachable?: boolean;
  workspace: {
    root: string;
    agentsCount: number;
    skillsCount: number;
  };
  ollama: OllamaHealthStatus;
}

// ---------------------------------------------------------------------------
// Agent Types
// ---------------------------------------------------------------------------
export interface AgentSummary {
  id: string;
  title: string;
  version: string;
  risk_class: RiskClass | string;
  skills: string[];
  effectiveTools: string[];
  tools?: string[];
  starters: string[];
  startersCount?: number;
  description?: string;
  is_bundled?: boolean;
  isBundled?: boolean;
  verified?: boolean;
  clinical_enabled?: boolean;
  forbidden?: string[];
  hidden?: boolean;
  error?: string;
  domain?: 'clinical' | 'therapy' | 'wellness' | 'navigation' | 'education' | string;
  category?: string;
  care_stages?: string[];
  target_audience?: string[];
  tags?: string[];
  icon?: string;
  maturity?: 'draft' | 'beta' | 'stable' | 'deprecated' | string;
  persona_file?: string;
}

export interface AgentDetailResponse {
  id: string;
  title: string;
  description?: string;
  type?: 'bundled' | 'system' | 'user' | string;
  version: string;
  license?: string;
  risk_class: RiskClass | string;
  model?: string | AgentModelConfig;
  hidden?: boolean;
  persona: AgentPersona;
  personaSummary?: string;
  persona_file?: string;
  skills: string[];
  resolvedSkills: Array<{
    id: string;
    name: string;
    title?: string;
    description: string;
    version: string;
    risk_class: RiskClass | string;
    tools?: string[];
  }>;
  tools?: string[];
  effectiveTools: string[];
  toolDefinitions: Array<{
    name: string;
    description: string;
    parameters: Record<string, any>;
  }>;
  starters: string[];
  forbidden?: string[];
  is_bundled: boolean;
  isBundled?: boolean;
  clinical_requires_flag: boolean;
  readmeText?: string;
  domain?: 'clinical' | 'therapy' | 'wellness' | 'navigation' | 'education' | string;
  category?: string;
  care_stages?: string[];
  target_audience?: string[];
  tags?: string[];
  icon?: string;
  maturity?: 'draft' | 'beta' | 'stable' | 'deprecated' | string;
}

// ---------------------------------------------------------------------------
// Skill Types
// ---------------------------------------------------------------------------
export interface SkillSummary {
  id: string;
  name: string;
  title?: string;
  description: string;
  version: string;
  risk_class: RiskClass | string;
  tools: string[];
  forbidden?: string[];
  is_verified?: boolean;
  is_bundled?: boolean;
  isBundled?: boolean;
  type?: 'bundled' | 'system' | 'user' | string;
  has_evals?: boolean;
  unverified?: boolean;
  error?: string;
  domain?: 'clinical' | 'therapy' | 'wellness' | 'navigation' | 'education' | string;
  category?: string;
  care_stages?: string[];
  target_audience?: string[];
  tags?: string[];
  icon?: string;
  maturity?: 'draft' | 'beta' | 'stable' | 'deprecated' | string;
}

export interface SkillDetailResponse {
  id: string;
  name: string;
  title?: string;
  description: string;
  version: string;
  risk_class: RiskClass | string;
  tools: string[];
  forbidden?: string[];
  instructions?: string;
  references?: string[];
  has_evals?: boolean;
  is_verified?: boolean;
  is_bundled?: boolean;
  isBundled?: boolean;
  type?: 'bundled' | 'system' | 'user' | string;
  domain?: 'clinical' | 'therapy' | 'wellness' | 'navigation' | 'education' | string;
  category?: string;
  care_stages?: string[];
  target_audience?: string[];
  tags?: string[];
  icon?: string;
  maturity?: 'draft' | 'beta' | 'stable' | 'deprecated' | string;
}

// ---------------------------------------------------------------------------
// Chat Request & SSE Event Types
// ---------------------------------------------------------------------------
export interface ChatMessageInput {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatRequestBody {
  agentId?: string;
  agent_id?: string;
  prompt: string;
  messages?: ChatMessageInput[];
  attachments?: string[];
  allow_clinical?: boolean;
  allowClinical?: boolean;
  provider?: string;
  model?: string;
  apiKey?: string;
  api_key?: string;
  customEndpoint?: string;
  custom_endpoint?: string;
  threadId?: string;
  thread_id?: string;
}

export type SSEEventName =
  | 'token'
  | 'tool_start'
  | 'tool_end'
  | 'refusal'
  | 'suggestions'
  | 'done'
  | 'error';

export type SSEEventType = SSEEventName;

export interface SSETokenData {
  delta: string;
}

export interface SSEToolStartData {
  tool: string;
  params: Record<string, any>;
}

export interface SSEToolEndData {
  tool: string;
  duration_ms: number;
  result?: ToolResult;
  allowed?: boolean;
  status?: 'completed' | 'denied' | 'failed';
}

export interface SSERefusalData {
  reason: string;
  message: string;
}

export interface SSESuggestionsData {
  type?: string;
  suggestions: string[];
}

export interface SSEDoneData {
  fullText: string;
  auditEventId?: string;
  refused?: boolean;
  refusalReason?: string;
  suggestions?: string[];
  followUpSuggestions?: string[];
  threadId?: string;
}

export interface SSEErrorData {
  message: string;
  code?: string;
}

// ---------------------------------------------------------------------------
// Attachment Upload Types
// ---------------------------------------------------------------------------
export interface AttachmentUploadResponse {
  success?: boolean;
  filename: string;
  path: string;
  size: number;
  type?: string;
  timestamp?: string;
  renamed?: boolean;
}

export interface AttachmentItem {
  filename: string;
  path: string;
  size: number;
  timestamp: string;
}

export interface WorkspaceNoteSummary {
  slug: string;
  title: string;
  agent?: string | null;
  created_at: string;
  size_bytes: number;
}

export interface WorkspaceNoteDetail {
  slug: string;
  title: string;
  agent?: string | null;
  created_at: string;
  size_bytes: number;
  content: string;
  raw_content: string;
  metadata: Record<string, any>;
  path: string;
}

// ---------------------------------------------------------------------------
// Audit & Activity Types (Issue #97)
// ---------------------------------------------------------------------------
export type AuditEventType =
  | 'run'
  | 'tool'
  | 'refuse'
  | 'error'
  | 'boundary_warning'
  | 'synthesis';

export interface AuditEvent {
  ts: string;
  agent_id: string;
  skill_id?: string | null;
  skill_version?: string | null;
  event: AuditEventType;
  tool?: string | null;
  allowed?: boolean | null;
  reason?: string | null;
  duration_ms?: number | null;
  prompt?: string | null;
  completion?: string | null;
  thread_id?: string | null;
}

export interface AuditListResponse {
  total: number;
  limit: number;
  events: AuditEvent[];
}

export interface AuditFilterParams {
  limit?: number;
  agent_id?: string;
  event?: AuditEventType | string;
}

// ---------------------------------------------------------------------------
// Memory Types (Issue #102)
// ---------------------------------------------------------------------------
export type MemoryTier = 'working' | 'episodic' | 'semantic' | 'procedural';

export interface MemoryRecord {
  key: string;
  value: any;
  tier: MemoryTier | string;
  namespace: string;
  created_at?: string | null;
  updated_at?: string | null;
  last_accessed_at?: string | null;
  metadata?: {
    source?: string;
    agent_id?: string;
    session_id?: string;
    category?: string;
    [key: string]: any;
  } | null;
  score?: number | null;
  salience?: number | null;
  access_count?: number;
}

export interface MemoryFilterParams {
  query?: string;
  tier?: MemoryTier | 'all';
  namespace?: string;
  limit?: number;
}

export interface MemoryStatus {
  backend: 'sqlite' | 'spector' | string;
  healthy: boolean;
  fallback_active: boolean;
  spector_url?: string;
  cooldown_seconds?: number;
}

export interface MemoryDeleteResponse {
  deleted: boolean;
  key: string;
  namespace: string;
}

export interface MemoryBulkDeleteResponse {
  deleted: boolean;
  deleted_count: number;
  namespace: string;
}

export interface MemoryUpdateRequest {
  value: any;
  tier?: MemoryTier | string;
  namespace?: string;
  metadata?: Record<string, any>;
}

// ---------------------------------------------------------------------------
// Authentication & User Types
// ---------------------------------------------------------------------------
export type UserRole = 'admin' | 'steward' | 'member';
export type UserStatus = 'active' | 'disabled';
export type AuthProviderType = 'local' | 'oidc' | 'google' | 'github' | 'disabled';

export interface UserProfile {
  id: string; // UUID v4
  email: string;
  username: string;
  full_name?: string | null;
  role: UserRole;
  status: UserStatus;
  auth_provider: AuthProviderType;
  created_at: string;
  updated_at?: string;
  last_login_at?: string | null;
}

export type User = UserProfile;

export interface AuthProvidersInfo {
  active_provider: 'local' | 'oidc' | 'disabled';
  sso_providers: string[];
  registration_enabled: boolean;
  allow_registration?: boolean;
  min_password_length?: number;
  has_admin?: boolean;
  needs_admin_setup?: boolean;
}

export interface UserSessionItem {
  id: string;
  user_id: string;
  client_ip: string | null;
  user_agent: string | null;
  created_at: string;
  last_active_at: string | null;
  expires_at: string;
  is_current?: boolean;
}

export interface SystemSettings {
  [key: string]: any;
}

// ---------------------------------------------------------------------------
// Knowledge Base & Documentation Types
// ---------------------------------------------------------------------------
export interface DocSummary {
  id: string;
  name: string;
  title: string;
  size_bytes: number;
  updated_at?: string;
  created_at?: string;
  source?: string;
  source_id?: string;
}

export interface DocDetailResponse {
  id: string;
  name: string;
  title: string;
  content: string;
  size_bytes: number;
  updated_at?: string;
  created_at?: string;
  source?: string;
  source_id?: string;
}

export interface AgentDocsResponse {
  agent_id: string;
  docs: DocSummary[];
}

export interface DocCreateRequest {
  name: string;
  title?: string;
  content: string;
}

export interface DocUpdateRequest {
  title?: string;
  content?: string;
}

export interface SkillCreateRequest {
  id?: string;
  name: string;
  title?: string;
  description: string;
  version?: string;
  risk_class?: string;
  tools?: string[];
  instructions?: string;
  domain?: string;
  category?: string;
  tags?: string[];
}

export interface SkillUpdateRequest {
  name?: string;
  title?: string;
  description?: string;
  version?: string;
  risk_class?: string;
  tools?: string[];
  instructions?: string;
  domain?: string;
  category?: string;
  tags?: string[];
}

export interface AgentCreateRequest {
  id?: string;
  title: string;
  description?: string;
  version?: string;
  risk_class?: string;
  model?: string | AgentModelConfig;
  skills?: string[];
  tools?: string[];
  persona?: AgentPersona;
  starters?: string[];
  domain?: string;
  category?: string;
  tags?: string[];
}

export interface AgentUpdateRequest {
  title?: string;
  description?: string;
  version?: string;
  risk_class?: string;
  model?: string | AgentModelConfig;
  skills?: string[];
  tools?: string[];
  persona?: AgentPersona;
  starters?: string[];
  domain?: string;
  category?: string;
  tags?: string[];
}

export interface NoteCreateRequest {
  slug?: string;
  title: string;
  content: string;
  type?: string;
  tags?: string[];
}

export interface NoteUpdateRequest {
  title?: string;
  content?: string;
  type?: string;
  tags?: string[];
}
