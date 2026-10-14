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

import { describe, it, expect } from 'vitest';
import {
  computeEffectiveTools,
  isToolPermitted,
  PHASE_0_REGISTRY,
  ToolValidationError
} from '../src/tools/index.js';
import type { AgentManifest, SkillManifest } from '../src/types/manifest.js';

describe('Tool Allowlist Union Engine', () => {
  it('computes union of agent.tools and skill.tools without duplicates', () => {
    const agentTools = ['workspace-note', 'skill-docs'];
    const skillTools = [['workspace-note', 'attach-read']];

    const effective = computeEffectiveTools(agentTools, skillTools);
    expect(effective).toContain('workspace-note');
    expect(effective).toContain('skill-docs');
    expect(effective).toContain('attach-read');
    expect(effective.length).toBe(3);
  });

  it('computes union from AgentManifest and SkillManifest objects', () => {
    const agent: AgentManifest = {
      id: 'visit-steward',
      title: 'Visit Steward',
      version: '0.1.0',
      risk_class: 'wellness',
      skills: ['visit-prep'],
      tools: ['workspace-note'],
      persona: 'Instructions'
    };

    const skill: SkillManifest = {
      id: 'visit-prep',
      name: 'visit-prep',
      description: 'Visit prep',
      version: '0.1.0',
      risk_class: 'wellness',
      tools: ['skill-docs']
    };

    const effective = computeEffectiveTools(agent, [skill]);
    expect(effective).toEqual(['workspace-note', 'skill-docs']);
  });

  it('ignores tools from skills not declared on the agent', () => {
    const agent: AgentManifest = {
      id: 'visit-steward',
      title: 'Visit Steward',
      version: '0.1.0',
      risk_class: 'wellness',
      skills: ['visit-prep'], // Only visit-prep declared
      tools: ['workspace-note'],
      persona: 'Instructions'
    };

    const activeSkill: SkillManifest = {
      id: 'visit-prep',
      name: 'visit-prep',
      description: 'Visit prep',
      version: '0.1.0',
      risk_class: 'wellness',
      tools: ['skill-docs']
    };

    const undeclaredSkill: SkillManifest = {
      id: 'benefits-explainer',
      name: 'benefits-explainer',
      description: 'Benefits',
      version: '0.1.0',
      risk_class: 'wellness',
      tools: ['attach-read'] // Not declared on agent
    };

    const effective = computeEffectiveTools(agent, [activeSkill, undeclaredSkill]);
    expect(effective).toContain('workspace-note');
    expect(effective).toContain('skill-docs');
    expect(effective).not.toContain('attach-read');
  });

  it('strictly intersects with Phase 0 closed registry', () => {
    const agentTools = ['workspace-note', 'shell-exec'];
    const skillTools = [['attach-read', 'curl', 'eval']];

    const effective = computeEffectiveTools(agentTools, skillTools);
    expect(effective).toContain('workspace-note');
    expect(effective).toContain('attach-read');
    expect(effective).not.toContain('shell-exec');
    expect(effective).not.toContain('curl');
    expect(effective).not.toContain('eval');
  });

  it('handles empty declarations resulting in empty tool list', () => {
    const effective = computeEffectiveTools([], []);
    expect(effective).toEqual([]);
  });

  it('correctly evaluates isToolPermitted against effective allowlist', () => {
    const effective = ['workspace-note', 'attach-read'];
    expect(isToolPermitted('workspace-note', effective)).toBe(true);
    expect(isToolPermitted('attach-read', effective)).toBe(true);
    expect(isToolPermitted('skill-docs', effective)).toBe(false);
    expect(isToolPermitted('unauthorized-tool', effective)).toBe(false);
  });
});
