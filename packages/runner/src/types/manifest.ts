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

export type RiskClass = 'wellness' | 'admin' | 'education' | 'clinical_assist';

export interface AgentModelConfig {
  provider?: string;
  name: string;
  temperature?: number;
}

export interface AgentPersonaObject {
  role: string;
  tone: string;
  instructions: string;
}

export type AgentPersona = string | AgentPersonaObject;

export interface AgentManifest {
  id: string;
  title: string;
  version: string;
  license?: string;
  risk_class: RiskClass;
  model?: string | AgentModelConfig;
  skills: string[];
  tools?: string[];
  forbidden?: string[];
  hidden?: boolean;
  can_delegate?: boolean;
  max_iterations?: number;
  description?: string;
  persona: AgentPersona;
}

export interface SkillManifest {
  id: string;
  name: string;
  description: string;
  version: string;
  license?: string;
  risk_class: RiskClass;
  tools?: string[];
  forbidden?: string[];
  instructions?: string;
  evals?: string;
  is_verified?: boolean; // true if carefold.yaml was present; false if fallback
  unverified?: boolean; // alias for compatibility
}

export interface LoadAgentResult {
  agent: AgentManifest;
  effectiveTools: string[];
  skills: SkillManifest[];
}
