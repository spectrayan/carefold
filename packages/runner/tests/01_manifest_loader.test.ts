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

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'node:path';
import fs from 'node:fs/promises';
import {
  loadAgent,
  loadSkill,
  ManifestValidationError,
  ToolValidationError
} from '../src/manifest/index.js';
import { createTestWorkspace, cleanupTestWorkspace } from './helpers/test-workspace.js';

describe('Manifest Loader & Validator', () => {
  let ws: string;

  beforeEach(async () => {
    ws = await createTestWorkspace();
  });

  afterEach(async () => {
    await cleanupTestWorkspace(ws);
  });

  it('successfully loads a valid agent.yaml with persona and declared skills', async () => {
    const agentDir = path.join(ws, 'agents', 'visit-steward');
    const skillsDir = path.join(ws, 'skills');
    const { agent, effectiveTools, skills } = await loadAgent(agentDir, skillsDir);

    expect(agent.id).toBe('visit-steward');
    expect(agent.risk_class).toBe('wellness');
    expect(agent.skills).toContain('visit-prep');
    expect(skills.length).toBe(1);
    expect(skills[0].id).toBe('visit-prep');
    expect(effectiveTools).toContain('workspace-note');
    expect(effectiveTools).toContain('skill-docs');
  });

  it('fails with clear error naming missing skill if declared skill does not exist', async () => {
    const agentDir = path.join(ws, 'agents', 'bad-agent');
    await fs.mkdir(agentDir, { recursive: true });
    await fs.writeFile(
      path.join(agentDir, 'agent.yaml'),
      `
id: bad-agent
title: Bad Agent
version: 0.1.0
risk_class: wellness
skills:
  - non-existent-skill
tools: []
persona: Test persona instructions
`
    );

    const skillsDir = path.join(ws, 'skills');
    await expect(loadAgent(agentDir, skillsDir)).rejects.toThrow(
      /Missing declared skill: non-existent-skill/i
    );
  });

  it('fails validation when agent.yaml declares tool outside Phase 0 closed registry', async () => {
    const agentDir = path.join(ws, 'agents', 'unauthorized-tool-agent');
    await fs.mkdir(agentDir, { recursive: true });
    await fs.writeFile(
      path.join(agentDir, 'agent.yaml'),
      `
id: unauthorized-tool-agent
title: Rogue Tool Agent
version: 0.1.0
risk_class: wellness
skills: []
tools:
  - web-search
persona: Rogue agent instructions
`
    );

    const skillsDir = path.join(ws, 'skills');
    await expect(loadAgent(agentDir, skillsDir)).rejects.toThrow(
      /Tool 'web-search' is not in Phase 0 closed registry/i
    );
  });

  it('handles missing carefold.yaml by falling back to unverified, wellness, tools: []', async () => {
    const skillDir = path.join(ws, 'skills', 'unverified-skill');
    const skill = await loadSkill(skillDir);

    expect(skill.unverified).toBe(true);
    expect(skill.is_verified).toBe(false);
    expect(skill.risk_class).toBe('wellness');
    expect(skill.tools).toEqual([]);
  });

  it('fails if SKILL.md is missing mandatory intended-use disclaimer lines', async () => {
    const badSkillDir = path.join(ws, 'skills', 'bad-skill');
    await fs.mkdir(badSkillDir, { recursive: true });
    await fs.writeFile(
      path.join(badSkillDir, 'SKILL.md'),
      `---
name: bad-skill
description: A skill without intended use disclosures
---
# Just some instructions
No disclaimers here!
`
    );

    await expect(loadSkill(badSkillDir)).rejects.toThrow(
      /Mandatory intended-use line missing/i
    );
  });

  it('elevates agent risk_class to clinical_assist if any declared skill is clinical_assist', async () => {
    const clinicalSkillDir = path.join(ws, 'skills', 'clinical-skill');
    await fs.mkdir(clinicalSkillDir, { recursive: true });
    await fs.writeFile(
      path.join(clinicalSkillDir, 'SKILL.md'),
      `---
name: clinical-skill
description: A clinical assist skill
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
    );
    await fs.writeFile(
      path.join(clinicalSkillDir, 'carefold.yaml'),
      `
id: clinical-skill
risk_class: clinical_assist
tools: []
`
    );

    const agentDir = path.join(ws, 'agents', 'elevated-agent');
    await fs.mkdir(agentDir, { recursive: true });
    await fs.writeFile(
      path.join(agentDir, 'agent.yaml'),
      `
id: elevated-agent
title: Elevated Agent
version: 0.1.0
risk_class: wellness
skills:
  - clinical-skill
tools: []
persona: Normal wellness persona
`
    );

    const { agent } = await loadAgent(agentDir, path.join(ws, 'skills'));
    expect(agent.risk_class).toBe('clinical_assist');
  });

  it('fails with ManifestValidationError on malformed YAML syntax', async () => {
    const malformedDir = path.join(ws, 'agents', 'malformed-agent');
    await fs.mkdir(malformedDir, { recursive: true });
    await fs.writeFile(path.join(malformedDir, 'agent.yaml'), ': : bad yaml [');

    await expect(loadAgent(malformedDir, path.join(ws, 'skills'))).rejects.toThrow(
      ManifestValidationError
    );
  });
});
