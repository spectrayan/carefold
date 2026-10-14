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

import { z } from 'zod';

export const RiskClassSchema = z.enum(['wellness', 'admin', 'education', 'clinical_assist']);

export const AgentManifestSchema = z.object({
  id: z.string().min(1, 'Agent id is required'),
  title: z.string().min(1, 'Agent title is required'),
  version: z.string().default('0.1.0'),
  license: z.string().optional(),
  risk_class: RiskClassSchema.default('wellness'),
  model: z.union([
    z.string(),
    z.object({
      provider: z.string().optional(),
      name: z.string(),
      temperature: z.number().optional()
    })
  ]).optional(),
  skills: z.array(z.string().regex(/^[a-zA-Z0-9_\-]+$/, 'Skill ID must be an alphanumeric slug')).default([]),
  tools: z.array(z.string()).default([]),
  forbidden: z.array(z.string()).default([]),
  hidden: z.boolean().default(false),
  can_delegate: z.boolean().default(false),
  max_iterations: z.number().default(3),
  description: z.string().optional(),
  persona: z.union([
    z.string().min(1, 'Persona instructions required'),
    z.object({
      role: z.string(),
      tone: z.string(),
      instructions: z.string()
    })
  ])
});

export const CarefoldYamlSchema = z.object({
  id: z.string().optional(),
  version: z.string().optional(),
  license: z.string().optional(),
  risk_class: RiskClassSchema.optional(),
  tools: z.array(z.string()).optional(),
  forbidden: z.array(z.string()).optional(),
  evals: z.string().optional()
});

export const SkillMetadataSchema = z.object({
  author: z.string().optional(),
  version: z.string().optional(),
  risk_class: RiskClassSchema.optional(),
  domain: z.string().optional(),
  category: z.string().optional(),
  tools: z.array(z.string()).optional(),
  forbidden: z.array(z.string()).optional(),
  evals: z.string().nullable().optional(),
  tags: z.array(z.string()).optional()
}).passthrough();

export const SkillFrontmatterSchema = z.object({
  name: z.string().min(1, 'Skill name is required in SKILL.md frontmatter'),
  description: z.string().min(1, 'Skill description is required in SKILL.md frontmatter'),
  license: z.string().optional(),
  'allowed-tools': z.string().optional(),
  compatibility: z.string().optional(),
  metadata: SkillMetadataSchema.optional()
}).passthrough();

export const CarefoldConfigSchema = z.object({
  version: z.string().default('0.1.0'),
  model: z.object({
    provider: z.string().default('ollama'),
    baseUrl: z.string().default('http://127.0.0.1:11434/v1'),
    model: z.string().default('llama3.2'),
    apiKey: z.string().default(''),
    temperature: z.number().optional()
  }).default({}),
  audit: z.object({
    enabled: z.boolean().default(true),
    store_bodies: z.boolean().default(false),
    log_path: z.string().default('logs/audit.jsonl')
  }).default({}),
  allow_clinical: z.boolean().default(false),
  telemetry: z.boolean().default(false)
}).default({});
