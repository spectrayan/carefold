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
  recordAudit,
  readAuditEvents,
  redactAuditEvent
} from '../src/audit/index.js';
import { createTestWorkspace, cleanupTestWorkspace } from './helpers/test-workspace.js';

describe('Audit Logger & Privacy Redaction', () => {
  let ws: string;

  beforeEach(async () => {
    ws = await createTestWorkspace();
  });

  afterEach(async () => {
    await cleanupTestWorkspace(ws);
  });

  it('appends structured JSONL events with required schema fields', async () => {
    await recordAudit(
      {
        agent_id: 'visit-steward',
        event: 'run',
        allowed: true,
        duration_ms: 120
      },
      { workspaceDir: ws, storeBodies: false }
    );

    const auditFile = path.join(ws, 'logs', 'audit.jsonl');
    const content = await fs.readFile(auditFile, 'utf8');
    const lines = content.trim().split('\n');
    expect(lines.length).toBe(1);

    const record = JSON.parse(lines[0]);
    expect(record.agent_id).toBe('visit-steward');
    expect(record.event).toBe('run');
    expect(record.allowed).toBe(true);
    expect(record.ts).toBeDefined();
    expect(record.duration_ms).toBe(120);
  });

  it('strictly redacts prompt and completion bodies when storeBodies is false by default', async () => {
    await recordAudit(
      {
        agent_id: 'visit-steward',
        event: 'run',
        allowed: true,
        prompt: 'Confidential patient question',
        completion: 'Confidential assistant answer'
      },
      { workspaceDir: ws, storeBodies: false }
    );

    const auditFile = path.join(ws, 'logs', 'audit.jsonl');
    const content = await fs.readFile(auditFile, 'utf8');
    expect(content).not.toContain('Confidential patient question');
    expect(content).not.toContain('Confidential assistant answer');

    const record = JSON.parse(content.trim());
    expect(record.prompt).toBeUndefined();
    expect(record.completion).toBeUndefined();
  });

  it('retains prompt and completion only when storeBodies is explicitly true', async () => {
    await recordAudit(
      {
        agent_id: 'visit-steward',
        event: 'run',
        allowed: true,
        prompt: 'Operator test prompt',
        completion: 'Operator test completion'
      },
      { workspaceDir: ws, storeBodies: true }
    );

    const auditFile = path.join(ws, 'logs', 'audit.jsonl');
    const content = await fs.readFile(auditFile, 'utf8');
    const record = JSON.parse(content.trim());
    expect(record.prompt).toBe('Operator test prompt');
    expect(record.completion).toBe('Operator test completion');
  });

  it('records refused events when safety classifier triggers', async () => {
    await recordAudit(
      {
        agent_id: 'visit-steward',
        event: 'refuse',
        allowed: false,
        reason: 'forbidden_intent:diagnose'
      },
      { workspaceDir: ws, storeBodies: false }
    );

    const auditFile = path.join(ws, 'logs', 'audit.jsonl');
    const content = await fs.readFile(auditFile, 'utf8');
    const record = JSON.parse(content.trim());
    expect(record.event).toBe('refuse');
    expect(record.allowed).toBe(false);
    expect(record.reason).toBe('forbidden_intent:diagnose');
  });

  it('records tool authorization and denial events accurately', async () => {
    await recordAudit(
      {
        agent_id: 'visit-steward',
        event: 'tool',
        tool: 'bash',
        allowed: false,
        reason: 'Tool is not in Phase 0 registry'
      },
      { workspaceDir: ws }
    );

    const auditFile = path.join(ws, 'logs', 'audit.jsonl');
    const events = await readAuditEvents(auditFile);
    expect(events.length).toBe(1);
    expect(events[0].tool).toBe('bash');
    expect(events[0].allowed).toBe(false);
  });

  it('safely serializes concurrent audit appends without corruption', async () => {
    const writes = Array.from({ length: 25 }, (_, i) =>
      recordAudit(
        {
          agent_id: 'visit-steward',
          event: 'run',
          allowed: true,
          duration_ms: i
        },
        { workspaceDir: ws }
      )
    );

    await Promise.all(writes);

    const auditFile = path.join(ws, 'logs', 'audit.jsonl');
    const events = await readAuditEvents(auditFile);
    expect(events.length).toBe(25);
    for (const evt of events) {
      expect(evt.agent_id).toBe('visit-steward');
      expect(evt.ts).toBeDefined();
    }
  });
});
