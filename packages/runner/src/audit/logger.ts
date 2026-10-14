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

import fs from 'node:fs/promises';
import path from 'node:path';
import { redactAuditEvent } from './redaction.js';
import type { AuditEvent } from '../types/audit.js';
import type { CarefoldConfig } from '../types/context.js';

let appendQueue: Promise<void> = Promise.resolve();

export async function recordAudit(
  event: AuditEvent,
  configOrOptions?: CarefoldConfig | { workspaceDir?: string; storeBodies?: boolean; logPath?: string; audit?: any },
  workspaceRoot?: string
): Promise<void> {
  try {
    const wsRoot =
      workspaceRoot ||
      (configOrOptions as any)?.workspaceDir ||
      (configOrOptions as any)?.workspaceRoot ||
      process.cwd();

    const relativeLogPath =
      (configOrOptions as any)?.logPath ||
      (configOrOptions as any)?.audit?.log_path ||
      'logs/audit.jsonl';

    const logFilePath = path.resolve(wsRoot, relativeLogPath);

    // Ensure ts is present
    const eventWithTs: AuditEvent = {
      ts: event.ts || new Date().toISOString(),
      ...event
    };

    // Apply zero-body redaction
    const safeEntry = redactAuditEvent(eventWithTs, configOrOptions);
    const line = JSON.stringify(safeEntry);

    // Queue atomic append
    appendQueue = appendQueue
      .then(async () => {
        await fs.mkdir(path.dirname(logFilePath), { recursive: true });
        await fs.appendFile(logFilePath, line + '\n', { flag: 'a', encoding: 'utf8' });
      })
      .catch((err) => {
        // Non-blocking fault isolation: do not crash user execution on log write failure
        console.error('[Carefold Audit Engine Error]: Failed to write audit event', err);
      });

    await appendQueue;
  } catch (err) {
    console.error('[Carefold Audit Engine Error]: Unexpected exception', err);
  }
}

// Alias for test compatibility
export const recordAuditEvent = recordAudit;

/**
 * Reads and parses audit events from a jsonl file
 */
export async function readAuditEvents(logPath: string): Promise<AuditEvent[]> {
  try {
    const content = await fs.readFile(logPath, 'utf8');
    const lines = content.trim().split('\n').filter(Boolean);
    return lines.map(l => JSON.parse(l));
  } catch (err: any) {
    if (err.code === 'ENOENT') {
      return [];
    }
    throw err;
  }
}
