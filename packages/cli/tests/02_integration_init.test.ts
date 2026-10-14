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
import { runCli } from './helpers/cli-runner.js';
import { createCliTestWorkspace, type CliTestWorkspace } from './helpers/test-workspace.js';

describe('02: CLI Integration: carefold init', () => {
  let ws: CliTestWorkspace;

  beforeEach(async () => {
    ws = await createCliTestWorkspace();
  });

  afterEach(async () => {
    await ws.cleanup();
  });

  it('scaffolds a complete workspace with default reference packs', async () => {
    const res = await runCli(['init'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('Initialized Carefold workspace');

    expect(await ws.exists('agents')).toBe(true);
    expect(await ws.exists('skills')).toBe(true);
    expect(await ws.exists('chats')).toBe(true);
    expect(await ws.exists('attachments')).toBe(true);
    expect(await ws.exists('logs/audit.jsonl')).toBe(true);
    expect(await ws.exists('carefold.config.json')).toBe(true);
    expect(await ws.exists('README.md')).toBe(true);

    // Verify bundled agents and skills copied
    expect(await ws.exists('agents/visit-steward/agent.yaml')).toBe(true);
    expect(await ws.exists('agents/benefits-guide/agent.yaml')).toBe(true);
    expect(await ws.exists('agents/habit-companion/agent.yaml')).toBe(true);
    expect(await ws.exists('skills/visit-prep/SKILL.md')).toBe(true);
    expect(await ws.exists('skills/benefits-explainer/SKILL.md')).toBe(true);
    expect(await ws.exists('skills/habit-checkin/SKILL.md')).toBe(true);
  });

  it('verifies default carefold.config.json content', async () => {
    await runCli(['init'], { cwd: ws.workspaceDir });
    const raw = await ws.readFile('carefold.config.json');
    const parsed = JSON.parse(raw);

    expect(parsed.model.provider).toBe('ollama');
    expect(parsed.model.baseUrl).toBe('http://127.0.0.1:11434/v1');
    expect(parsed.model.model).toBe('llama3.2');
    expect(parsed.audit.store_bodies).toBe(false);
    expect(parsed.audit.log_path).toBe('logs/audit.jsonl');
    expect(parsed.allow_clinical).toBe(false);
    expect(parsed.telemetry).toBe(false);
  });

  it('supports --provider option during init to set custom default provider', async () => {
    await runCli(['init', '--provider', 'gemini', '--model-name', 'gemini-2.0-flash'], {
      cwd: ws.workspaceDir
    });
    const raw = await ws.readFile('carefold.config.json');
    const parsed = JSON.parse(raw);

    expect(parsed.model.provider).toBe('gemini');
    expect(parsed.model.model).toBe('gemini-2.0-flash');
  });

  it('verifies README.md contains Apache-2.0 notice and intended use disclaimer', async () => {
    await runCli(['init'], { cwd: ws.workspaceDir });
    const content = await ws.readFile('README.md');

    expect(content).toContain('Apache License, Version 2.0');
    expect(content).toContain('Intended Use');
    expect(content).toContain('wellness, care navigation, and administrative assistant');
    expect(content).toContain('Not for clinical emergencies');
  });

  it('refuses to overwrite existing workspace without --force', async () => {
    // First init
    const first = await runCli(['init'], { cwd: ws.workspaceDir });
    expect(first.exitCode).toBe(0);

    // Second init without --force
    const second = await runCli(['init'], { cwd: ws.workspaceDir });
    expect(second.exitCode).not.toBe(0);
    expect(second.stderr).toContain('already initialized');
    expect(second.stderr).toContain('--force');
  });

  it('overwrites existing workspace when --force is provided', async () => {
    await runCli(['init'], { cwd: ws.workspaceDir });
    const res = await runCli(['init', '--force'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('Initialized Carefold workspace');
  });

  it('scaffolds into specified sub-path', async () => {
    const res = await runCli(['init', './my-workspace'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(await ws.exists('my-workspace/carefold.config.json')).toBe(true);
    expect(await ws.exists('my-workspace/agents')).toBe(true);
  });

  it('supports --no-bundled for bare scaffolding without copying reference packs', async () => {
    const res = await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(await ws.exists('carefold.config.json')).toBe(true);
    expect(await ws.exists('agents')).toBe(true);
    expect(await ws.exists('agents/visit-steward')).toBe(false);
  });
});
