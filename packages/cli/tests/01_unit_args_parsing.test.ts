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

import { describe, it, expect } from 'vitest';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runCli } from './helpers/cli-runner.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '../../..');

describe('01: CLI Unit Argument Parsing & Help Outputs', () => {
  it('displays top-level help text with all commands', async () => {
    const res = await runCli(['--help']);
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('carefold');
    expect(res.stdout).toContain('init');
    expect(res.stdout).toContain('agent');
    expect(res.stdout).toContain('skill');
    expect(res.stdout).toContain('run');
    expect(res.stdout).toContain('log');
    expect(res.stdout).toContain('eval');
  });

  it('reports the correct version number with --version', async () => {
    const res = await runCli(['--version']);
    expect(res.exitCode).toBe(0);
    expect(res.stdout.trim()).toBe('0.1.0');
  });

  it('fails with non-zero exit code on unknown command', async () => {
    const res = await runCli(['unknown-command']);
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain("unknown command 'unknown-command'");
  });

  it('displays help for carefold init', async () => {
    const res = await runCli(['init', '--help']);
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('init [options] [dir]');
    expect(res.stdout).toContain('--force');
    expect(res.stdout).toContain('--no-bundled');
    expect(res.stdout).toContain('--provider');
    expect(res.stdout).toContain('--model-url');
  });

  it('displays help for carefold agent', async () => {
    const res = await runCli(['agent', '--help']);
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('list');
    expect(res.stdout).toContain('add');
    expect(res.stdout).toContain('inspect');
  });

  it('displays help for carefold skill', async () => {
    const res = await runCli(['skill', '--help']);
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('list');
    expect(res.stdout).toContain('add');
  });

  it('displays help for carefold run', async () => {
    const res = await runCli(['run', '--help']);
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('--agent');
    expect(res.stdout).toContain('--skill');
    expect(res.stdout).toContain('--mock');
    expect(res.stdout).toContain('--allow-clinical');
    expect(res.stdout).toContain('-p, --provider');
    expect(res.stdout).toContain('-m, --model');
    expect(res.stdout).toContain('-k, --key');
  });

  it('displays help for carefold log', async () => {
    const res = await runCli(['log', '--help']);
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('--limit');
    expect(res.stdout).toContain('--event');
    expect(res.stdout).toContain('--full');
    expect(res.stdout).toContain('--json');
  });

  it('displays help for carefold eval', async () => {
    const res = await runCli(['eval', '--help']);
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('--agent');
    expect(res.stdout).toContain('--skill');
    expect(res.stdout).toContain('--engine');
  });

  it('fails when carefold run is missing prompt and target', async () => {
    const res = await runCli(['run']);
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain('Missing required argument <prompt>');
  });

  it('fails when carefold agent add is missing required argument', async () => {
    const res = await runCli(['agent', 'add']);
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain("missing required argument 'name|path'");
  });

  it('fails when carefold agent inspect is missing required argument', async () => {
    const res = await runCli(['agent', 'inspect']);
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain("missing required argument 'id'");
  });

  it('fails when carefold skill add is missing required argument', async () => {
    const res = await runCli(['skill', 'add']);
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain("missing required argument 'name|path'");
  });

  it('parses --provider option and -p alias', async () => {
    const resLong = await runCli([
      'run',
      '--agent',
      'visit-steward',
      'Hello',
      '--provider',
      'google',
      '--allow-clinical',
      '--mock'
    ], { cwd: repoRoot });
    expect(resLong.exitCode).toBe(0);

    const resShort = await runCli([
      'run',
      '--agent',
      'visit-steward',
      'Hello',
      '-p',
      'ollama',
      '--allow-clinical',
      '--mock'
    ], { cwd: repoRoot });
    expect(resShort.exitCode).toBe(0);

    const resCustom = await runCli([
      'run',
      '--agent',
      'visit-steward',
      'Hello',
      '--provider',
      'custom',
      '--allow-clinical',
      '--mock'
    ], { cwd: repoRoot });
    expect(resCustom.exitCode).toBe(0);
  });

  it('parses --model option and -m alias with positional agent and prompt', async () => {
    const resLong = await runCli([
      'run',
      'visit-steward',
      'Hello from Gemini',
      '--provider',
      'google',
      '--model',
      'gemini-2.0-flash',
      '--allow-clinical',
      '--mock'
    ], { cwd: repoRoot });
    expect(resLong.exitCode).toBe(0);

    const resShort = await runCli([
      'run',
      'visit-steward',
      'Hello from Ollama',
      '-p',
      'ollama',
      '-m',
      'llama3.2:latest',
      '--allow-clinical',
      '--mock'
    ], { cwd: repoRoot });
    expect(resShort.exitCode).toBe(0);
  });

  it('parses --key and -k option for provider authentication', async () => {
    const resKey = await runCli([
      'run',
      'visit-steward',
      'Hello with key',
      '--provider',
      'google',
      '--key',
      'test-api-key-12345',
      '--allow-clinical',
      '--mock'
    ], { cwd: repoRoot });
    expect(resKey.exitCode).toBe(0);

    const resShortKey = await runCli([
      'run',
      'visit-steward',
      'Hello with short key',
      '-p',
      'anthropic',
      '-k',
      'sk-ant-test-key-67890',
      '--allow-clinical',
      '--mock'
    ], { cwd: repoRoot });
    expect(resShortKey.exitCode).toBe(0);
  });
});

