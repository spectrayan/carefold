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

import type { ExecutionContext } from './context.js';

export type ClosedToolName = 'attach-read' | 'workspace-note' | 'skill-docs';

export const PHASE0_CLOSED_TOOLS: readonly ClosedToolName[] = [
  'attach-read',
  'workspace-note',
  'skill-docs'
] as const;

export const PHASE_0_REGISTRY = PHASE0_CLOSED_TOOLS;

export interface ToolResult {
  success: boolean;
  output: any;
  error?: string;
}

export interface ToolDefinition {
  name: ClosedToolName;
  description: string;
  parameters: Record<string, any>;
  execute: (params: any, context: ExecutionContext) => Promise<ToolResult>;
}

export interface AttachReadParams {
  path?: string;
  file_path?: string;
}

export interface WorkspaceNoteParams {
  title: string;
  content: string;
}

export interface SkillDocsParams {
  skill_id: string;
  doc?: string;
  doc_name?: string;
}
