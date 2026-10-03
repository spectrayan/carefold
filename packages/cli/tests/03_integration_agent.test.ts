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

describe('03: CLI Integration: carefold agent commands', () => {
  let ws: CliTestWorkspace;

  beforeEach(async () => {
    ws = await createCliTestWorkspace();
  });

  afterEach(async () => {
    await ws.cleanup();
  });

  it('agent list in bare workspace reports no installed agents', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    const res = await runCli(['agent', 'list'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('No installed agents found');
  });

  it('agent add installs bundled reference agent and companion skills', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    const res = await runCli(['agent', 'add', 'visit-steward'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('Added reference agent "visit-steward"');

    expect(await ws.exists('agents/visit-steward/agent.yaml')).toBe(true);
    expect(await ws.exists('agents/visit-steward/starters.json')).toBe(true);
    // Companion skill auto-installed
    expect(await ws.exists('skills/visit-prep/SKILL.md')).toBe(true);
  });

  it('agent add installs benefits-guide and habit-companion', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    const bg = await runCli(['agent', 'add', 'benefits-guide'], { cwd: ws.workspaceDir });
    expect(bg.exitCode).toBe(0);
    expect(await ws.exists('agents/benefits-guide/agent.yaml')).toBe(true);
    expect(await ws.exists('skills/benefits-explainer/SKILL.md')).toBe(true);

    const hc = await runCli(['agent', 'add', 'habit-companion'], { cwd: ws.workspaceDir });
    expect(hc.exitCode).toBe(0);
    expect(await ws.exists('agents/habit-companion/agent.yaml')).toBe(true);
    expect(await ws.exists('skills/habit-checkin/SKILL.md')).toBe(true);
  });

  it('agent add fails cleanly on unknown agent name', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    const res = await runCli(['agent', 'add', 'bogus-agent'], { cwd: ws.workspaceDir });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain('Unknown agent "bogus-agent"');
    expect(res.stderr).toContain('visit-steward');
  });

  it('agent list displays installed agents, versions, and risk classes', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    await runCli(['agent', 'add', 'visit-steward'], { cwd: ws.workspaceDir });

    const res = await runCli(['agent', 'list'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('visit-steward');
    expect(res.stdout).toContain('Visit Steward');
    expect(res.stdout).toContain('0.1.0');
    expect(res.stdout).toContain('clinical_assist');
  });

  it('agent list --json outputs valid JSON array', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    await runCli(['agent', 'add', 'visit-steward'], { cwd: ws.workspaceDir });

    const res = await runCli(['agent', 'list', '--json'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    const parsed = JSON.parse(res.stdout);
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed.length).toBe(1);
    expect(parsed[0].id).toBe('visit-steward');
    expect(parsed[0].risk_class).toBe('clinical_assist');
  });

  it('agent inspect displays detailed manifest metadata and starters', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    await runCli(['agent', 'add', 'visit-steward'], { cwd: ws.workspaceDir });

    const res = await runCli(['agent', 'inspect', 'visit-steward'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('Agent: Visit Steward (visit-steward)');
    expect(res.stdout).toContain('Risk Class:      clinical_assist');
    expect(res.stdout).toContain('Declared Skills');
    expect(res.stdout).toContain('visit-prep');
    expect(res.stdout).toContain('Effective Tools Allowlist');
    expect(res.stdout).toContain('Persona:');
    expect(res.stdout).toContain('Starters / Quick Prompts:');
  });

  it('agent inspect fails for non-existent agent', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    const res = await runCli(['agent', 'inspect', 'missing-agent'], { cwd: ws.workspaceDir });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain('Agent "missing-agent" not found');
  });

  it('agent add rejects local directory with malformed syntax in agent.yaml', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });

    const badDir = await ws.createFile(
      'broken-local-agent/agent.yaml',
      '{ unclosed syntax: invalid yaml %%%'
    );
    const badDirPath = badDir.replace(/\/agent\.yaml$/, '');

    const res = await runCli(['agent', 'add', badDirPath], { cwd: ws.workspaceDir });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toMatch(/manifest|invalid|yaml|syntax|error/i);

    // Ensure the corrupt directory was not installed into workspace agents/
    expect(await ws.exists('agents/broken-local-agent')).toBe(false);
  });

  it('agent add rejects local directory with schema-invalid agent.yaml manifest', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });

    const schemaBadDir = await ws.createFile(
      'schema-bad-agent/agent.yaml',
      'id: schema-bad\n# missing mandatory title, version, risk_class, persona\n'
    );
    const schemaBadDirPath = schemaBadDir.replace(/\/agent\.yaml$/, '');

    const res = await runCli(['agent', 'add', schemaBadDirPath], { cwd: ws.workspaceDir });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toMatch(/manifest|invalid|validation|required/i);
    expect(await ws.exists('agents/schema-bad-agent')).toBe(false);
  });

  it('agent inspect renders string starters correctly without undefined placeholders', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    await runCli(['agent', 'add', 'visit-steward'], { cwd: ws.workspaceDir });

    const res = await runCli(['agent', 'inspect', 'visit-steward'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('Starters / Quick Prompts:');
    expect(res.stdout).not.toContain('[undefined]');
    expect(res.stdout).not.toContain('"undefined"');
    // Assert actual prompt string from visit-steward/starters.json is rendered
    expect(res.stdout).toContain('Help me prepare a prioritized list of questions for my annual physical next week.');
  });

  it('agent inspect renders both string starters and object starters cleanly', async () => {
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });

    await ws.createFile(
      'agents/mixed-agent/agent.yaml',
      `id: mixed-agent
title: Mixed Starter Agent
version: 0.1.0
risk_class: wellness
skills: []
tools: []
persona:
  role: Assistant
  tone: Calm
  instructions: Be helpful.
`
    );
    await ws.createFile(
      'agents/mixed-agent/starters.json',
      JSON.stringify([
        'How should I prepare for therapy?',
        { label: 'Checkup', prompt: 'Walk me through my annual checkup list.' }
      ])
    );

    const res = await runCli(['agent', 'inspect', 'mixed-agent'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).not.toContain('[undefined]');
    expect(res.stdout).not.toContain('"undefined"');
    expect(res.stdout).toContain('How should I prepare for therapy?');
    expect(res.stdout).toContain('[Checkup]');
    expect(res.stdout).toContain('Walk me through my annual checkup list.');
  });
});
