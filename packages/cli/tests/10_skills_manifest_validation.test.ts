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
import path from 'node:path';
import fs from 'node:fs/promises';
import { runCli } from './helpers/cli-runner.js';
import { createCliTestWorkspace, type CliTestWorkspace } from './helpers/test-workspace.js';

describe('10: CLI Skills Manifest & Tool Hardening Suite', () => {
  let ws: CliTestWorkspace;

  beforeEach(async () => {
    ws = await createCliTestWorkspace();
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
  });

  afterEach(async () => {
    await ws.cleanup();
  });

  it('CLI-CHALLENGE-1: rejects adding local skill declaring unauthorized tool bash in metadata.tools', async () => {
    const rogueLocalDir = path.join(ws.workspaceDir, 'rogue_source_bash');
    await fs.mkdir(rogueLocalDir, { recursive: true });
    await fs.writeFile(
      path.join(rogueLocalDir, 'SKILL.md'),
      `---
name: rogue-bash
description: Rogue skill declaring shell execution
metadata:
  risk_class: wellness
  tools:
    - bash
---
# Instructions
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
    );

    const res = await runCli(['skill', 'add', rogueLocalDir], { cwd: ws.workspaceDir });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toMatch(/Tool 'bash'.*not in Phase 0 closed registry/i);

    // Verify it was NOT installed into skills/
    expect(await ws.exists('skills/rogue-bash')).toBe(false);
  });

  it('CLI-CHALLENGE-2: rejects adding local skill declaring unauthorized tool in allowed-tools', async () => {
    const rogueLocalDir = path.join(ws.workspaceDir, 'rogue_source_allowed_tools');
    await fs.mkdir(rogueLocalDir, { recursive: true });
    await fs.writeFile(
      path.join(rogueLocalDir, 'SKILL.md'),
      `---
name: rogue-allowed
description: Rogue skill declaring curl via allowed-tools
allowed-tools: curl
---
# Instructions
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
    );

    const res = await runCli(['skill', 'add', rogueLocalDir], { cwd: ws.workspaceDir });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toMatch(/Tool 'curl'.*not in Phase 0 closed registry/i);
    expect(await ws.exists('skills/rogue-allowed')).toBe(false);
  });

  it('CLI-CHALLENGE-3: rejects adding local skill missing mandatory intended-use statements', async () => {
    const badLocalDir = path.join(ws.workspaceDir, 'bad_disclaimers');
    await fs.mkdir(badLocalDir, { recursive: true });
    await fs.writeFile(
      path.join(badLocalDir, 'SKILL.md'),
      `---
name: bad-disclaimers
description: Skill missing all clinical boundaries
metadata:
  tools:
    - skill-docs
---
# Rogue Instructions
No safety boundaries declared here.
`
    );

    const res = await runCli(['skill', 'add', badLocalDir], { cwd: ws.workspaceDir });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toMatch(/Mandatory intended-use line missing/i);
    expect(await ws.exists('skills/bad-disclaimers')).toBe(false);
  });

  it('CLI-CHALLENGE-4: handles broken skills in skill list gracefully without crashing', async () => {
    // Create an invalid skill directly in skills/
    await ws.createFile(
      'skills/broken-skill/SKILL.md',
      `---
name: broken-skill
description: Invalid tools in existing installation
metadata:
  tools:
    - exec
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
    );

    const res = await runCli(['skill', 'list'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('broken-skill');
    expect(res.stdout).toContain('[INVALID:');
    expect(res.stdout).toContain('exec');
  });

  it('CLI-CHALLENGE-5: blocks running raw skill declaring unauthorized tools via carefold run --skill', async () => {
    // Plant an unauthorized skill directly in skills/
    await ws.createFile(
      'skills/unauth-skill/SKILL.md',
      `---
name: unauth-skill
description: Skill with unauthorized tool
metadata:
  tools:
    - rm
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
    );

    const res = await runCli(['run', '--skill', 'unauth-skill', '--mock', 'Check my checklist'], {
      cwd: ws.workspaceDir
    });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toMatch(/Tool 'rm'.*not in Phase 0 closed registry/i);
  });

  it('CLI-CHALLENGE-6: successfully installs and runs native ADR-0003 skill via skill add and run --skill', async () => {
    const validLocalDir = path.join(ws.workspaceDir, 'my_custom_skill');
    await fs.mkdir(validLocalDir, { recursive: true });
    await fs.writeFile(
      path.join(validLocalDir, 'SKILL.md'),
      `---
name: custom-prep
description: A clean custom native ADR-0003 prep skill
license: Apache-2.0
allowed-tools: skill-docs
metadata:
  risk_class: wellness
  domain: clinical
  category: clinical.prep
  version: "1.0.0"
  tools:
    - skill-docs
  forbidden:
    - diagnose
    - prescribe
    - dose
---
# Clean Instructions
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
    );

    // 1. Add skill
    const addRes = await runCli(['skill', 'add', validLocalDir], { cwd: ws.workspaceDir });
    expect(addRes.exitCode).toBe(0);
    expect(addRes.stdout).toContain('Added local skill pack');

    // 2. List skills
    const listRes = await runCli(['skill', 'list'], { cwd: ws.workspaceDir });
    expect(listRes.exitCode).toBe(0);
    expect(listRes.stdout).toContain('custom-prep');
    expect(listRes.stdout).toContain('skill-docs');
    expect(listRes.stdout).toContain('wellness');

    // 3. Run raw skill with mock
    const runRes = await runCli(['run', '--skill', 'my_custom_skill', '--mock', 'Help me prepare for my visit'], {
      cwd: ws.workspaceDir
    });
    expect(runRes.exitCode).toBe(0);
  });
});
