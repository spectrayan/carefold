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
  refusalReason?: string;
  boundaryWarning?: boolean;
  boundaryReason?: string;
  toolTraces?: ToolTraceItem[];
  traces?: ToolTraceItem[];
  attachments?: string[];
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
