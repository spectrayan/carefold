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

import type { AgentManifest, SkillManifest } from './manifest.js';

export interface CarefoldConfig {
  version?: string;
  model?: {
    provider?: string;      // Default: 'ollama'
    baseUrl?: string;       // Default: 'http://127.0.0.1:11434/v1'
    model?: string;         // Default: 'llama3.2'
    apiKey?: string;        // Default: ''
    temperature?: number;
  };
  audit?: {
    enabled?: boolean;      // Default: true
    store_bodies?: boolean; // Default: false
    log_path?: string;      // Default: 'logs/audit.jsonl'
  };
  allow_clinical?: boolean; // Default: false
  telemetry?: boolean;      // Default: false
}

export interface ExecutionContext {
  workspaceRoot: string;
  skillsDir?: string;
  agent: AgentManifest;
  effectiveTools: string[];
  skills: SkillManifest[];
  activeSkillId?: string;
  sessionId?: string;
  config?: CarefoldConfig;
}
