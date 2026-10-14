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

// Type Exports
export type {
  RiskClass,
  AgentManifest,
  AgentModelConfig,
  AgentPersona,
  AgentPersonaObject,
  SkillManifest,
  LoadAgentResult
} from './types/manifest.js';

export type {
  ClosedToolName,
  ToolResult,
  ToolDefinition,
  AttachReadParams,
  WorkspaceNoteParams,
  SkillDocsParams
} from './types/tool.js';
export { PHASE0_CLOSED_TOOLS, PHASE0_CLOSED_TOOLS as PHASE_0_REGISTRY } from './types/tool.js';

export type {
  CarefoldConfig,
  ExecutionContext
} from './types/context.js';

export type {
  AuditEventType,
  AuditEvent
} from './types/audit.js';

export type {
  StreamChunk,
  RunOptions,
  RunResult,
  ToolCallRecord
} from './types/stream.js';

export type {
  SafetyCheckResult
} from './types/safety.js';

export type {
  ChatMessage,
  ToolCallChunk,
  ModelToolDefinition,
  ChatCompletionOptions,
  ModelStreamChunk,
  ModelClientConfig,
  ModelClient
} from './model/types.js';
export { CarefoldModelError } from './model/types.js';

// Manifest Loaders & Schemas
export {
  loadAgent,
  loadAgentManifest,
  loadSkill,
  loadSkillManifest,
  loadAllSkills,
  ManifestValidationError,
  ToolValidationError
} from './manifest/index.js';
export {
  RiskClassSchema,
  AgentManifestSchema,
  CarefoldYamlSchema,
  SkillFrontmatterSchema,
  CarefoldConfigSchema
} from './manifest/schema.js';
export { parseFrontmatter, checkMandatoryIntendedUse } from './manifest/frontmatter.js';

// Tools & Sandboxing
export { computeEffectiveTools, isToolPermitted } from './tools/union.js';
export { CLOSED_TOOL_DEFINITIONS, getClosedTool, executeTool } from './tools/registry.js';
export { executeAttachRead } from './tools/attach-read.js';
export { executeWorkspaceNote } from './tools/workspace-note.js';
export { executeSkillDocs } from './tools/skill-docs.js';
export { resolveSandboxedPath, SandboxSecurityError } from './utils/sandbox.js';

// Safety Refusal Gate
export { checkSafetyRefusal } from './safety/classifier.js';
export { SAFE_REFUSAL_TEMPLATE } from './safety/template.js';
export { buildSafetyPreamble } from './safety/prompt.js';

// Privacy Audit Engine
export { recordAudit, recordAuditEvent, readAuditEvents } from './audit/logger.js';
export { redactAuditEvent } from './audit/redaction.js';

// Model Clients & SSE
export { OpenAIModelClient } from './model/client.js';
export { MockModelClient } from './model/mock.js';
export { parseSSEStream } from './model/sse.js';

// Execution Engine
export { executeAgentRun } from './engine/runner.js';
export { buildSystemPrompt } from './engine/prompt-builder.js';
