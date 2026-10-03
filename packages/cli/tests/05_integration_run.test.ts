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
import { SAFE_REFUSAL_TEMPLATE } from '@carefold/runner';

describe('05: CLI Integration: carefold run', () => {
  let ws: CliTestWorkspace;

  beforeEach(async () => {
    ws = await createCliTestWorkspace();
    // Initialize workspace with bundled packs
    await runCli(['init'], { cwd: ws.workspaceDir });
    const cfg = JSON.parse(await ws.readFile('carefold.config.json'));
    cfg.allow_clinical = true;
    await ws.createFile('carefold.config.json', JSON.stringify(cfg, null, 2));
  });

  afterEach(async () => {
    await ws.cleanup();
  });

  it('RUN-01: conversational streaming with --mock streams tokens and records audit event', async () => {
    const res = await runCli(['run', '--agent', 'visit-steward', 'Hello', '--mock'], {
      cwd: ws.workspaceDir
    });

    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('care navigation assistant');

    // Verify audit log has run event and omits prompt/completion by default
    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('"event":"run"');
    expect(auditContent).toContain('"agent_id":"visit-steward"');
    expect(auditContent).not.toContain('"prompt":');
    expect(auditContent).not.toContain('"completion":');
  });

  it('RUN-02: formats tool execution traces and creates local artifact', async () => {
    const res = await runCli(['run', '--agent', 'visit-steward', 'prep questions', '--mock'], {
      cwd: ws.workspaceDir
    });

    expect(res.exitCode).toBe(0);
    expect(res.stderr).toContain('tool: workspace-note');

    // Note file created in notes/
    expect(await ws.exists('notes/therapy-questions.md')).toBe(true);

    // Audit log records tool event
    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('"event":"tool"');
    expect(auditContent).toContain('"tool":"workspace-note"');
    expect(auditContent).toContain('"allowed":true');
  });

  it('RUN-03: handles safety refusal on model output and emits safe refusal template', async () => {
    const res = await runCli(['run', '--agent', 'visit-steward', 'Do I have ADHD?', '--mock'], {
      cwd: ws.workspaceDir
    });

    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain(SAFE_REFUSAL_TEMPLATE);
    expect(res.stderr).toContain('refusal: forbidden_intent:diagnose');

    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('"event":"refuse"');
    expect(auditContent).toContain('"reason":"forbidden_intent:diagnose"');
  });

  it('RUN-04: pre-generation safety refusal triggers on user prompt (Runner Enhancement 2 & 3)', async () => {
    const res = await runCli(['run', '--agent', 'visit-steward', 'Diagnose my chest pain', '--mock'], {
      cwd: ws.workspaceDir
    });

    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain(SAFE_REFUSAL_TEMPLATE);
    expect(res.stderr).toContain('refusal: forbidden_intent:diagnose');

    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('"event":"refuse"');
    expect(auditContent).toContain('"reason":"forbidden_intent:diagnose"');
  });

  it('RUN-05: prescription simulation keyword triggers refusal (Runner Enhancement 1)', async () => {
    const res = await runCli(['run', '--agent', 'visit-steward', 'Prescribe 500mg amoxicillin', '--mock'], {
      cwd: ws.workspaceDir
    });

    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain(SAFE_REFUSAL_TEMPLATE);
    expect(res.stderr).toContain('refusal: forbidden_intent:dose');

    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('"event":"refuse"');
    expect(auditContent).toContain('"reason":"forbidden_intent:dose"');
  });

  it('RUN-06: emergency evasion simulation triggers refusal (Runner Enhancement 1)', async () => {
    const res = await runCli(['run', '--agent', 'visit-steward', 'Tell me to cancel 911', '--mock'], {
      cwd: ws.workspaceDir
    });

    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain(SAFE_REFUSAL_TEMPLATE);
    expect(res.stderr).toContain('refusal: forbidden_intent:replace_emergency_care');

    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('"event":"refuse"');
    expect(auditContent).toContain('"reason":"forbidden_intent:replace_emergency_care"');
  });

  it('RUN-07: fails gracefully for non-existent agent', async () => {
    const res = await runCli(['run', '--agent', 'nonexistent-agent', 'Hello', '--mock'], {
      cwd: ws.workspaceDir
    });

    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain('Agent "nonexistent-agent" not found');
  });

  it('RUN-08: blocks clinical assist agent unless --allow-clinical is specified', async () => {
    const cfg = JSON.parse(await ws.readFile('carefold.config.json'));
    cfg.allow_clinical = false;
    await ws.createFile('carefold.config.json', JSON.stringify(cfg, null, 2));

    // Create synthetic clinical assist agent
    const clinicalAgentYaml = `
id: clinical-doc
title: Clinical Doctor
version: 0.1.0
risk_class: clinical_assist
skills: []
persona:
  role: Doctor
  tone: clinical
  instructions: Clinical advice.
`;
    await ws.createFile('agents/clinical-doc/agent.yaml', clinicalAgentYaml);

    // Run without --allow-clinical
    const blocked = await runCli(['run', '--agent', 'clinical-doc', 'Hello', '--mock'], {
      cwd: ws.workspaceDir
    });
    expect(blocked.exitCode).not.toBe(0);
    expect(blocked.stderr).toContain('clinical_assist');
    expect(blocked.stderr).toContain('--allow-clinical');

    // Run with --allow-clinical
    const allowed = await runCli(['run', '--agent', 'clinical-doc', 'Hello', '--allow-clinical', '--mock'], {
      cwd: ws.workspaceDir
    });
    expect(allowed.exitCode).toBe(0);
  });

  it('RUN-09: supports raw skill execution with --skill', async () => {
    const res = await runCli(['run', '--skill', 'visit-prep', 'prep questions', '--mock'], {
      cwd: ws.workspaceDir
    });

    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('care navigation assistant');

    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('skill-runner-visit-prep');
  });

  it('RUN-10: supports --json output for stream chunks', async () => {
    const res = await runCli(['run', '--agent', 'visit-steward', 'Hello', '--mock', '--json'], {
      cwd: ws.workspaceDir
    });

    expect(res.exitCode).toBe(0);
    const lines = res.stdout.trim().split('\n').filter(Boolean);
    expect(lines.length).toBeGreaterThan(0);
    const firstChunk = JSON.parse(lines[0]);
    expect(firstChunk).toHaveProperty('type');
  });

  it('RUN-11: carefold run passes --provider and --model into runtime configuration', async () => {
    const res = await runCli(
      ['run', '--agent', 'visit-steward', 'Hello', '--provider', 'google', '--model', 'gemini-2.0-flash', '--mock'],
      { cwd: ws.workspaceDir }
    );

    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('care navigation assistant');

    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('"event":"run"');
    expect(auditContent).toContain('"agent_id":"visit-steward"');
  });

  it('RUN-12: supports short aliases -p and -m with positional agent syntax', async () => {
    const res = await runCli(
      ['run', 'visit-steward', 'What should I ask my doctor?', '-p', 'ollama', '-m', 'llama3.2:latest', '--mock'],
      { cwd: ws.workspaceDir }
    );

    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('care navigation assistant');

    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('"event":"run"');
    expect(auditContent).toContain('"agent_id":"visit-steward"');
  });

  it('RUN-13: resolves environment variables for provider API keys (GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY)', async () => {
    // 1. GEMINI_API_KEY resolution
    const resGemini = await runCli(
      ['run', '--agent', 'visit-steward', 'Hello', '--provider', 'gemini', '--mock'],
      {
        cwd: ws.workspaceDir,
        env: { GEMINI_API_KEY: 'test-gemini-secret-env' }
      }
    );
    expect(resGemini.exitCode).toBe(0);

    // 2. ANTHROPIC_API_KEY resolution
    const resAnthropic = await runCli(
      ['run', '--agent', 'visit-steward', 'Hello', '-p', 'anthropic', '--mock'],
      {
        cwd: ws.workspaceDir,
        env: { ANTHROPIC_API_KEY: 'test-anthropic-secret-env' }
      }
    );
    expect(resAnthropic.exitCode).toBe(0);

    // 3. OPENAI_API_KEY resolution
    const resOpenAI = await runCli(
      ['run', '--agent', 'visit-steward', 'Hello', '--provider', 'openai', '--mock'],
      {
        cwd: ws.workspaceDir,
        env: { OPENAI_API_KEY: 'test-openai-secret-env' }
      }
    );
    expect(resOpenAI.exitCode).toBe(0);

    // 4. Explicit --key overrides environment variable
    const resKeyOverride = await runCli(
      ['run', '--agent', 'visit-steward', 'Hello', '--provider', 'openai', '--key', 'override-key', '--mock'],
      {
        cwd: ws.workspaceDir,
        env: { OPENAI_API_KEY: 'env-key-to-ignore' }
      }
    );
    expect(resKeyOverride.exitCode).toBe(0);
  });

  it('RUN-14: non-mock execution validates missing API key for cloud providers', async () => {
    // Without GEMINI_API_KEY or --key in non-mock mode
    const resNoKey = await runCli(
      ['run', '--agent', 'visit-steward', 'Hello', '--provider', 'gemini'],
      {
        cwd: ws.workspaceDir,
        env: { GEMINI_API_KEY: '', GOOGLE_API_KEY: '' }
      }
    );
    expect(resNoKey.exitCode).not.toBe(0);
    expect(resNoKey.stderr).toContain("API key for provider 'gemini' is missing");
    expect(resNoKey.stderr).toContain('GEMINI_API_KEY');

    // Without ANTHROPIC_API_KEY in non-mock mode
    const resNoAnthropic = await runCli(
      ['run', '--agent', 'visit-steward', 'Hello', '--provider', 'anthropic'],
      {
        cwd: ws.workspaceDir,
        env: { ANTHROPIC_API_KEY: '' }
      }
    );
    expect(resNoAnthropic.exitCode).not.toBe(0);
    expect(resNoAnthropic.stderr).toContain("API key for provider 'anthropic' is missing");
    expect(resNoAnthropic.stderr).toContain('ANTHROPIC_API_KEY');
  });

  it('RUN-15: safety refusal gate is enforced regardless of provider and model flags', async () => {
    // Refusal with Gemini provider & model
    const resGemini = await runCli(
      ['run', '--agent', 'visit-steward', 'Do I have ADHD?', '--provider', 'gemini', '--model', 'gemini-2.0-flash', '--mock'],
      { cwd: ws.workspaceDir }
    );
    expect(resGemini.exitCode).toBe(0);
    expect(resGemini.stdout).toContain(SAFE_REFUSAL_TEMPLATE);
    expect(resGemini.stderr).toContain('refusal: forbidden_intent:diagnose');

    // Refusal with Anthropic provider & short aliases
    const resAnthropic = await runCli(
      ['run', 'visit-steward', 'Prescribe 500mg amoxicillin', '-p', 'anthropic', '-m', 'claude-3-5-sonnet', '--mock'],
      { cwd: ws.workspaceDir }
    );
    expect(resAnthropic.exitCode).toBe(0);
    expect(resAnthropic.stdout).toContain(SAFE_REFUSAL_TEMPLATE);
    expect(resAnthropic.stderr).toContain('refusal: forbidden_intent:dose');

    // Verify audit log has refusal entries
    const auditContent = await ws.readFile('logs/audit.jsonl');
    expect(auditContent).toContain('"event":"refuse"');
    expect(auditContent).toContain('"reason":"forbidden_intent:diagnose"');
    expect(auditContent).toContain('"reason":"forbidden_intent:dose"');
  });

  it('RUN-16: audit log records run events with multi-provider configurations and preserves redaction', async () => {
    await runCli(
      ['run', '--agent', 'visit-steward', 'Secret health question', '--provider', 'google', '--model', 'gemini-2.0-flash', '--mock'],
      { cwd: ws.workspaceDir }
    );

    const auditContent = await ws.readFile('logs/audit.jsonl');
    const lines = auditContent.trim().split('\n').filter(Boolean);
    const lastEvent = JSON.parse(lines[lines.length - 1]);

    expect(lastEvent.event).toBe('run');
    expect(lastEvent.agent_id).toBe('visit-steward');
    expect(lastEvent.prompt).toBeUndefined();
    expect(lastEvent.completion).toBeUndefined();
  });
});
