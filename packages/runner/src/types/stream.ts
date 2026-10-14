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

import type { ToolResult } from './tool.js';
import type { AuditEvent } from './audit.js';
import type { CarefoldConfig } from './context.js';
import type { ModelClient } from '../model/types.js';

export type StreamChunk =
  | { type: 'token'; delta: string; token: string }
  | { type: 'tool_start'; tool: string; input: Record<string, any> }
  | { type: 'tool_end'; tool: string; result: ToolResult; duration_ms: number; allowed?: boolean; status?: 'completed' | 'denied' | 'failed' }
  | { type: 'tool_call'; tool: string; status: 'allowed' | 'denied'; input?: Record<string, any>; result?: ToolResult; duration_ms?: number }
  | { type: 'refusal'; reason: string; message: string }
  | { type: 'error'; error: string };

export interface ToolCallRecord {
  tool: string;
  input: Record<string, any>;
  allowed: boolean;
  duration_ms: number;
  success?: boolean;
  output?: any;
  error?: string;
}

export interface RunOptions {
  agentDir?: string;
  agentId?: string;
  skillsDir?: string;
  workspaceDir?: string;
  workspaceRoot?: string;
  prompt: string;
  attachments?: string[];
  config?: CarefoldConfig;
  mockModel?: boolean | ModelClient | ((messages: any[], tools: any[]) => AsyncGenerator<any, any, any>);
  modelClient?: ModelClient;
}

export interface RunResult {
  text: string;
  refused: boolean;
  refusalReason?: string;
  toolCalls: ToolCallRecord[];
  auditEvents: AuditEvent[];
}
