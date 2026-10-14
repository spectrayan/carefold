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
import { runCli } from './helpers/cli-runner.js';
import { createCliTestWorkspace, type CliTestWorkspace } from './helpers/test-workspace.js';

describe('06: CLI Integration: carefold log', () => {
  let ws: CliTestWorkspace;

  beforeEach(async () => {
    ws = await createCliTestWorkspace();
    await runCli(['init', '--no-bundled'], { cwd: ws.workspaceDir });
  });

  afterEach(async () => {
    await ws.cleanup();
  });

  it('LOG-01: handles empty audit log gracefully', async () => {
    const res = await runCli(['log'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('No audit events found');
  });

  it('LOG-02: displays events in tabular format and enforces privacy (zero bodies)', async () => {
    const event1 = {
      ts: '2026-09-29T10:00:00.000Z',
      agent_id: 'visit-steward',
      event: 'run',
      allowed: true,
      duration_ms: 120,
      prompt: 'CONFIDENTIAL MEDICAL QUESTION',
      completion: 'CONFIDENTIAL MEDICAL ANSWER'
    };
    const event2 = {
      ts: '2026-09-29T10:01:00.000Z',
      agent_id: 'visit-steward',
      event: 'refuse',
      reason: 'forbidden_intent:diagnose',
      allowed: false,
      duration_ms: 35
    };

    await ws.createFile('logs/audit.jsonl', `${JSON.stringify(event1)}\n${JSON.stringify(event2)}\n`);

    const res = await runCli(['log'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('TIMESTAMP');
    expect(res.stdout).toContain('EVENT');
    expect(res.stdout).toContain('visit-steward');
    expect(res.stdout).toContain('forbidden_intent:diagnose');

    // PRIVACY VERIFICATION: message bodies MUST NEVER be displayed
    expect(res.stdout).not.toContain('CONFIDENTIAL MEDICAL QUESTION');
    expect(res.stdout).not.toContain('CONFIDENTIAL MEDICAL ANSWER');
  });

  it('LOG-03: --limit flag limits the number of returned events', async () => {
    const lines = [];
    for (let i = 1; i <= 15; i++) {
      lines.push(
        JSON.stringify({
          ts: `2026-09-29T10:${i.toString().padStart(2, '0')}:00.000Z`,
          agent_id: `agent-${i}`,
          event: 'run',
          allowed: true,
          duration_ms: 50
        })
      );
    }
    await ws.createFile('logs/audit.jsonl', lines.join('\n') + '\n');

    const res = await runCli(['log', '--limit', '3'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('agent-15');
    expect(res.stdout).toContain('agent-14');
    expect(res.stdout).toContain('agent-13');
    expect(res.stdout).not.toContain('agent-12');
  });

  it('LOG-04: --event flag filters events by type', async () => {
    const events = [
      { ts: '2026-09-29T10:00:00.000Z', agent_id: 'visit-steward', event: 'run', allowed: true },
      { ts: '2026-09-29T10:01:00.000Z', agent_id: 'visit-steward', event: 'refuse', reason: 'diagnose' },
      { ts: '2026-09-29T10:02:00.000Z', agent_id: 'visit-steward', event: 'tool', tool: 'workspace-note', allowed: true }
    ];
    await ws.createFile('logs/audit.jsonl', events.map((e) => JSON.stringify(e)).join('\n') + '\n');

    const res = await runCli(['log', '--event', 'refuse'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('refuse');
    expect(res.stdout).not.toContain('workspace-note');
  });

  it('LOG-05: rejects invalid event filter name', async () => {
    const res = await runCli(['log', '--event', 'invalid-type'], { cwd: ws.workspaceDir });
    expect(res.exitCode).not.toBe(0);
    expect(res.stderr).toContain('Invalid event filter "invalid-type"');
  });

  it('LOG-06: --full with audit.store_bodies: false hides bodies and emits privacy notice', async () => {
    const event = {
      ts: '2026-09-29T10:00:00.000Z',
      agent_id: 'visit-steward',
      event: 'run',
      allowed: true,
      prompt: 'SECRET PROMPT'
    };
    await ws.createFile('logs/audit.jsonl', JSON.stringify(event) + '\n');

    const res = await runCli(['log', '--full'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stderr).toContain('Notice: Prompt and completion bodies are redacted');
    expect(res.stdout).not.toContain('SECRET PROMPT');
  });

  it('LOG-07: --full with audit.store_bodies: true displays prompt and completion bodies', async () => {
    // Update config to enable store_bodies
    const config = {
      model: { baseUrl: 'http://127.0.0.1:11434/v1', model: 'llama3.2' },
      audit: { store_bodies: true, log_path: 'logs/audit.jsonl' },
      allow_clinical: false
    };
    await ws.createFile('carefold.config.json', JSON.stringify(config, null, 2));

    const event = {
      ts: '2026-09-29T10:00:00.000Z',
      agent_id: 'visit-steward',
      event: 'run',
      allowed: true,
      duration_ms: 150,
      prompt: 'VISIBLE USER PROMPT',
      completion: 'VISIBLE AGENT COMPLETION'
    };
    await ws.createFile('logs/audit.jsonl', JSON.stringify(event) + '\n');

    const res = await runCli(['log', '--full'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('VISIBLE USER PROMPT');
    expect(res.stdout).toContain('VISIBLE AGENT COMPLETION');
  });

  it('LOG-08: --json outputs valid JSON array and redacts bodies unless permitted', async () => {
    const event = {
      ts: '2026-09-29T10:00:00.000Z',
      agent_id: 'visit-steward',
      event: 'run',
      allowed: true,
      prompt: 'SENSITIVE BODY'
    };
    await ws.createFile('logs/audit.jsonl', JSON.stringify(event) + '\n');

    const res = await runCli(['log', '--json'], { cwd: ws.workspaceDir });
    expect(res.exitCode).toBe(0);
    const parsed = JSON.parse(res.stdout);
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed[0].agent_id).toBe('visit-steward');
    expect(parsed[0]).not.toHaveProperty('prompt');
  });
});
