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

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { runCli } from './helpers/cli-runner.js';
import { createCliTestWorkspace, type CliTestWorkspace } from './helpers/test-workspace.js';

describe('04: CLI Integration: carefold skill commands', () => {
  let ws: CliTestWorkspace;

  beforeEach(async () => {
    ws = await createCliTestWorkspace();
  });

  afterEach(async () => {
    await ws.cleanup();
  });

  it('skill list in bare workspace reports no installed skills', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    const res = await runCli(['skill', 'list'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('No installed skills found');
  });

  it('skill add installs bundled reference skill', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    const res = await runCli(['skill', 'add', 'visit-prep'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('Added reference skill "visit-prep"');

    expect(await ws.exists('skills/visit-prep/SKILL.md')).toBe(true);
    expect(await ws.exists('skills/visit-prep/references')).toBe(true);
  });

  it('skill add fails on unknown skill name', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    const res = await runCli(['skill', 'add', 'non-existent-skill'], { cwd: ws.workspaceDir });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain('Unknown skill "non-existent-skill"');
    expect(res.stderr).toContain('visit-prep');
  });

  it('skill list displays installed skills with risk classes and tools', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    await runCli(['skill', 'add', 'visit-prep'], { cwd: ws.workspaceDir });

    const res = await runCli(['skill', 'list'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('visit-prep');
    expect(res.stdout).toContain('wellness');
    expect(res.stdout).toContain('skill-docs');
  });

  it('handles unverified community skill lacking carefold.yaml', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });

    const customSkillMd = `---
name: community-tips
description: Community healthy habits tips
metadata:
  version: 0.1.0
---

# Community Tips

## Intended Use & Safety Disclosures
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician

## Instructions
Share helpful tips.
`;

    await ws.createFile('skills/community-tips/SKILL.md', customSkillMd);

    const res = await runCli(['skill', 'list'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('community-tips');
    expect(res.stdout).toContain('wellness [unverified]');
  });

  it('gates clinical assist skills unless --allow-clinical is specified', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });

    const clinicalSkillMd = `---
name: triage-guide
description: Experimental triage assistant
---

# Triage Guide

## Intended Use & Safety Disclosures
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
`;

    const clinicalYaml = `
id: triage-guide
version: 0.1.0
risk_class: clinical_assist
tools: []
`;

    await ws.createFile('skills/triage-guide/SKILL.md', clinicalSkillMd);
    await ws.createFile('skills/triage-guide/carefold.yaml', clinicalYaml);

    // Run without --allow-clinical
    const blocked = await runCli(['skill', 'list'], { cwd: ws.workspaceDir });
    expect(blocked.exitCode).toBe(0);
    expect(blocked.stderr).toContain('Warning: Clinical assist skills detected');
    expect(blocked.stdout).not.toContain('triage-guide');

    // Run with --allow-clinical
    const allowed = await runCli(['skill', 'list', '--allow-clinical'], { cwd: ws.workspaceDir });
    expect(allowed.exitCode).toBe(0);
    expect(allowed.stderr).toContain('Notice: Clinical assist mode enabled');
    expect(allowed.stdout).toContain('triage-guide');
  });

  it('skill list --json outputs structured JSON array', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    await runCli(['skill', 'add', 'visit-prep'], { cwd: ws.workspaceDir });

    const res = await runCli(['skill', 'list', '--json'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    const parsed = JSON.parse(res.stdout);
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed[0].id).toBe('visit-prep');
    expect(parsed[0].risk_class).toBe('wellness');
  });

  it('skill list isolates corrupt skill folder as [INVALID] and continues listing valid skills', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    await runCli(['skill', 'add', 'visit-prep'], { cwd: ws.workspaceDir });

    // Inject a corrupted skill folder into skills/
    await ws.createFile('skills/corrupt-skill/SKILL.md', 'not markdown frontmatter at all');

    // 1. Verify standard table output
    const res = await runCli(['skill', 'list'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('visit-prep');
    expect(res.stdout).toContain('corrupt-skill');
    expect(res.stdout).toContain('[INVALID');

    // 2. Verify JSON output
    const jsonRes = await runCli(['skill', 'list', '--json'], { cwd: ws.workspaceDir });
    expect(jsonRes.exitCode).toBe(0);
    const parsed = JSON.parse(jsonRes.stdout);
    expect(Array.isArray(parsed)).toBe(true);

    const validSkill = parsed.find((s: any) => s.id === 'visit-prep');
    const invalidSkill = parsed.find((s: any) => s.id === 'corrupt-skill');

    expect(validSkill).toBeDefined();
    expect(validSkill.name).toBe('visit-prep');
    expect(validSkill.risk_class).toBe('wellness');

    expect(invalidSkill).toBeDefined();
    expect(invalidSkill.name || invalidSkill.title).toMatch(/INVALID/i);
  });

  it('skill list isolates skill folder missing required safety disclosures section', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    await runCli(['skill', 'add', 'visit-prep'], { cwd: ws.workspaceDir });

    // Inject skill missing disclosures section
    await ws.createFile(
      'skills/no-disclosures-skill/SKILL.md',
      `---
name: no-disclosures-skill
description: Skill missing disclosures
---
# No Disclosures
Instructions without mandatory disclosures.
`
    );

    const res = await runCli(['skill', 'list'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('visit-prep');
    expect(res.stdout).toContain('no-disclosures-skill');
    expect(res.stdout).toContain('[INVALID');
  });
});
