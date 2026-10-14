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

import path from 'node:path';
import { readAuditEvents, type AuditEvent, type AuditEventType } from '@carefold/runner';
import { findWorkspaceRoot, loadWorkspaceConfig } from '../utils/workspace.js';
import { CliError, ExitCodes } from '../utils/errors.js';

export interface LogCommandOptions {
  limit?: string | number;
  event?: string;
  full?: boolean;
  workspace?: string;
  json?: boolean;
}

const VALID_EVENT_TYPES: AuditEventType[] = ['run', 'tool', 'refuse', 'error'];

export async function logCommand(options: LogCommandOptions = {}): Promise<void> {
  const wsRoot = findWorkspaceRoot(options.workspace);
  const config = await loadWorkspaceConfig(wsRoot);

  // Validate limit
  let limit = 10;
  if (options.limit !== undefined) {
    const parsed = typeof options.limit === 'number' ? options.limit : parseInt(options.limit, 10);
    if (isNaN(parsed) || parsed <= 0) {
      throw new CliError('--limit must be a positive integer.', ExitCodes.USER_ERROR);
    }
    limit = parsed;
  }

  // Validate event filter
  let eventFilter: AuditEventType | undefined;
  if (options.event) {
    const normalized = options.event.toLowerCase() as AuditEventType;
    if (!VALID_EVENT_TYPES.includes(normalized)) {
      throw new CliError(
        `Invalid event filter "${options.event}". Allowed values: ${VALID_EVENT_TYPES.join(', ')}`,
        ExitCodes.USER_ERROR
      );
    }
    eventFilter = normalized;
  }

  // Resolve audit log path
  const relativeLogPath = config.audit?.log_path || 'logs/audit.jsonl';
  const logFilePath = path.resolve(wsRoot, relativeLogPath);

  // Read events safely
  let events: AuditEvent[] = [];
  try {
    events = await readAuditEvents(logFilePath);
  } catch (err: any) {
    if (err.code === 'ENOENT') {
      events = [];
    } else {
      throw new CliError(`Error reading audit log at ${logFilePath}: ${err.message}`, ExitCodes.USER_ERROR);
    }
  }

  if (events.length === 0) {
    if (options.json) {
      console.log('[]');
    } else {
      console.log(`No audit events found at ${relativeLogPath}.`);
    }
    return;
  }

  // Filter by event type if specified
  if (eventFilter) {
    events = events.filter((e) => e.event === eventFilter);
  }

  // Take most recent N records
  const recentEvents = events.slice(-limit);

  // Privacy evaluation
  const isStoreBodiesEnabled = Boolean(config.audit?.store_bodies === true);
  const canShowBodies = Boolean(options.full && isStoreBodiesEnabled);

  // If user requested --full but store_bodies is false, emit privacy notice
  if (options.full && !isStoreBodiesEnabled && !options.json) {
    process.stderr.write(
      'Notice: Prompt and completion bodies are redacted because audit.store_bodies is false in carefold.config.json.\n\n'
    );
  }

  if (options.json) {
    // Sanitize records for JSON output if bodies are not permitted
    const sanitized = recentEvents.map((evt) => {
      const copy = { ...evt };
      if (!canShowBodies) {
        delete copy.prompt;
        delete copy.completion;
      }
      return copy;
    });
    console.log(JSON.stringify(sanitized, null, 2));
    return;
  }

  // Formatted Terminal Output
  if (canShowBodies) {
    // Detailed card view with message bodies
    for (const evt of recentEvents) {
      console.log('─'.repeat(80));
      const ts = evt.ts ? evt.ts.replace('T', ' ').slice(0, 19) + ' UTC' : 'UNKNOWN';
      const dur = evt.duration_ms !== undefined ? `${evt.duration_ms}ms` : '-';
      console.log(`[${ts}] EVENT: ${evt.event.toUpperCase()} | AGENT: ${evt.agent_id} | DURATION: ${dur}`);

      if (evt.tool) {
        console.log(`  TOOL:       ${evt.tool} [${evt.allowed ? 'allowed' : 'DENIED'}]`);
      }
      if (evt.reason) {
        console.log(`  REASON:     ${evt.reason}`);
      }
      if (evt.prompt) {
        console.log(`  PROMPT:     ${JSON.stringify(evt.prompt)}`);
      }
      if (evt.completion) {
        console.log(`  COMPLETION: ${JSON.stringify(evt.completion)}`);
      }
    }
    console.log('─'.repeat(80));
  } else {
    // Standard tabular summary
    const header = [
      'TIMESTAMP'.padEnd(24),
      'EVENT'.padEnd(10),
      'AGENT'.padEnd(20),
      'DETAILS'.padEnd(35),
      'DURATION'
    ].join(' ');

    console.log(header);
    console.log('─'.repeat(100));

    for (const evt of recentEvents) {
      const ts = (evt.ts ? evt.ts.replace('T', ' ').slice(0, 19) + ' UTC' : '-').padEnd(24);
      const evType = evt.event.padEnd(10);
      const agent = (evt.agent_id || '-').slice(0, 19).padEnd(20);

      let details = '';
      if (evt.event === 'tool') {
        details = `${evt.tool} [${evt.allowed ? 'allowed' : 'DENIED'}]`;
      } else if (evt.event === 'refuse') {
        details = evt.reason || 'safety refusal';
      } else if (evt.event === 'error') {
        details = evt.reason || 'runtime error';
      } else if (evt.event === 'run') {
        details = evt.allowed ? 'completed' : 'blocked';
      }
      details = details.slice(0, 34).padEnd(35);

      const dur = evt.duration_ms !== undefined ? `${evt.duration_ms}ms` : '-';

      console.log(`${ts} ${evType} ${agent} ${details} ${dur}`);
    }
  }
}
