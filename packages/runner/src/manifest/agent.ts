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

import fs from 'node:fs/promises';
import path from 'node:path';
import yaml from 'yaml';
import { AgentManifestSchema } from './schema.js';
import { loadSkill, ManifestValidationError, ToolValidationError } from './skill.js';
import { PHASE_0_REGISTRY } from '../types/tool.js';
import type { AgentManifest, SkillManifest, LoadAgentResult } from '../types/manifest.js';

export { ManifestValidationError, ToolValidationError };

/**
 * Loads and validates an agent directory containing agent.yaml and resolves declared skills
 */
export async function loadAgent(agentDir: string, skillsDir?: string): Promise<LoadAgentResult> {
  const agentYamlPath = path.join(agentDir, 'agent.yaml');

  let rawYaml: string;
  try {
    rawYaml = await fs.readFile(agentYamlPath, 'utf8');
  } catch (err: any) {
    throw new ManifestValidationError(`Missing required agent.yaml in "${agentDir}": ${err.message}`);
  }

  let parsedYaml: any;
  try {
    parsedYaml = yaml.parse(rawYaml);
  } catch (parseErr: any) {
    throw new ManifestValidationError(`Malformed YAML in "${agentYamlPath}": ${parseErr.message}`);
  }

  const metadataYamlPath = path.join(agentDir, 'metadata.yaml');
  let metaDict: any = {};
  try {
    const rawMeta = await fs.readFile(metadataYamlPath, 'utf8');
    metaDict = yaml.parse(rawMeta) || {};
  } catch {
    // metadata.yaml is optional
  }

  const agentId = parsedYaml.id || metaDict.id || parsedYaml.name || path.basename(agentDir);
  const agentTitle = parsedYaml.title || metaDict.title || agentId.replace(/-/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase());
  const declaredRiskClass = parsedYaml.risk_class || metaDict.risk_class || 'wellness';

  const mergedData: any = {
    ...metaDict,
    ...parsedYaml,
    id: agentId,
    title: agentTitle,
    risk_class: declaredRiskClass,
  };

  if (typeof mergedData.persona === 'string') {
    const personaPath = path.join(agentDir, mergedData.persona);
    try {
      const personaContent = await fs.readFile(personaPath, 'utf8');
      mergedData.persona = personaContent;
    } catch {
      // Keep original persona string if not a file path
    }
  }

  const parseResult = AgentManifestSchema.safeParse(mergedData);
  if (!parseResult.success) {
    const issues = parseResult.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join(', ');
    throw new ManifestValidationError(`Invalid agent.yaml in "${agentDir}": ${issues}`);
  }

  const agentData = parseResult.data;

  // Validate agent-declared tools against Phase 0 closed registry
  const agentTools = agentData.tools || [];
  const allowedToolsSet = new Set<string>(PHASE_0_REGISTRY);
  for (const tool of agentTools) {
    if (!allowedToolsSet.has(tool)) {
      throw new ToolValidationError(
        `Tool '${tool}' is not in Phase 0 closed registry [${PHASE_0_REGISTRY.join(', ')}]`
      );
    }
  }

  // Resolve skills directory
  const resolvedSkillsDir = skillsDir
    ? path.resolve(skillsDir)
    : path.resolve(path.dirname(agentDir), '..', 'skills');

  // Load and validate each declared skill
  const loadedSkills: SkillManifest[] = [];
  for (const skillId of agentData.skills) {
    if (!/^[a-zA-Z0-9_\-]+$/.test(skillId)) {
      throw new ManifestValidationError(
        `Invalid declared skill ID "${skillId}": Skill IDs must be alphanumeric slugs without path characters.`
      );
    }
    const skillPath = path.join(resolvedSkillsDir, skillId);
    try {
      const stats = await fs.stat(skillPath);
      if (!stats.isDirectory()) {
        throw new Error('Not a directory');
      }
    } catch {
      throw new ManifestValidationError(
        `Missing declared skill: ${skillId} (looked in "${skillPath}")`
      );
    }

    try {
      const skill = await loadSkill(skillPath);
      loadedSkills.push(skill);
    } catch (err: any) {
      if (err instanceof ManifestValidationError || err instanceof ToolValidationError) {
        throw err;
      }
      throw new ManifestValidationError(`Failed to load declared skill "${skillId}": ${err.message}`);
    }
  }

  // Compute effective tools union:
  // effective_tools = unique(agent.tools ∪ skill.tools) ∩ Phase0Registry
  const unionSet = new Set<string>(agentTools);
  for (const skill of loadedSkills) {
    for (const tool of skill.tools || []) {
      unionSet.add(tool);
    }
  }

  const effectiveTools = Array.from(unionSet).filter(t => allowedToolsSet.has(t));

  // Risk class elevation: if any skill is clinical_assist, agent risk class is elevated
  let riskClass = agentData.risk_class;
  if (loadedSkills.some(s => s.risk_class === 'clinical_assist')) {
    riskClass = 'clinical_assist';
  }

  const agent: AgentManifest = {
    ...agentData,
    risk_class: riskClass
  };

  return {
    agent,
    effectiveTools,
    skills: loadedSkills
  };
}

// Alias for backwards/test compatibility
export const loadAgentManifest = loadAgent;
export const loadSkillManifest = loadSkill;
