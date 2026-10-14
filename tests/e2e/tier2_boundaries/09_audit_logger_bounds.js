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

import fs from 'node:fs';
import path from 'node:path';
import { runPython, createTempWorkspace, removeTempWorkspace, assertEqual, assertTrue } from '../helpers/utils.js';

export const name = 'F09-B: Audit Logger Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F09-B01',
      name: 'Audit logger gracefully ignores corrupted lines in audit.jsonl without failing',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const logDir = path.join(ws, 'logs');
          fs.mkdirSync(logDir, { recursive: true });
          const logPath = path.join(logDir, 'audit.jsonl');
          // Write mix of valid and corrupted lines
          fs.writeFileSync(
            logPath,
            '{"event": "run", "agent_id": "agent-1", "allowed": true}\n' +
            'CORRUPTED_GARBAGE_LINE_NOT_JSON\n' +
            '{"event": "run", "agent_id": "agent-2", "allowed": true}\n'
          );

          const script = `
import asyncio
from pathlib import Path
from carefold.audit.logger import get_recent_audit_events

async def main():
    total, events = await get_recent_audit_events(log_path=Path('${logPath}'), limit=10)
    assert total == 2
    assert len(events) == 2
    assert events[0].agent_id == 'agent-2'
    assert events[1].agent_id == 'agent-1'

asyncio.run(main())
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F09-B02',
      name: 'Audit logger handles limit=0 and limit=1 boundaries accurately',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.audit.logger import record_audit, get_recent_audit_events
from carefold.schemas.audit import AuditEvent

async def main():
    log_path = Path('${ws}') / 'logs' / 'audit.jsonl'
    for i in range(3):
        await record_audit(AuditEvent(agent_id=f'test-{i}', event='run', allowed=True), log_path=log_path)

    total0, events0 = await get_recent_audit_events(log_path=log_path, limit=0)
    assert total0 == 3
    assert len(events0) == 0

    total1, events1 = await get_recent_audit_events(log_path=log_path, limit=1)
    assert total1 == 3
    assert len(events1) == 1
    assert events1[0].agent_id == 'test-2'

asyncio.run(main())
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F09-B03',
      name: 'Audit logger returns (0, []) cleanly when log file does not exist',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.audit.logger import get_recent_audit_events

async def main():
    non_existent = Path('${ws}') / 'missing_dir' / 'missing.jsonl'
    total, events = await get_recent_audit_events(log_path=non_existent)
    assert total == 0
    assert events == []

asyncio.run(main())
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F09-B04',
      name: 'Audit logger filtering isolates specific event types and agents',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.audit.logger import record_audit, get_recent_audit_events
from carefold.schemas.audit import AuditEvent

async def main():
    log_path = Path('${ws}') / 'logs' / 'audit.jsonl'
    await record_audit(AuditEvent(agent_id='agent-a', event='run', allowed=True), log_path=log_path)
    await record_audit(AuditEvent(agent_id='agent-a', event='refuse', allowed=False, reason='blocked'), log_path=log_path)
    await record_audit(AuditEvent(agent_id='agent-b', event='run', allowed=True), log_path=log_path)

    total_refuse, events_refuse = await get_recent_audit_events(log_path=log_path, event='refuse')
    assert total_refuse == 1
    assert events_refuse[0].agent_id == 'agent-a'
    assert events_refuse[0].event == 'refuse'

    total_b, events_b = await get_recent_audit_events(log_path=log_path, agent_id='agent-b')
    assert total_b == 1
    assert events_b[0].agent_id == 'agent-b'

asyncio.run(main())
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F09-B05',
      name: 'Audit logger handles high concurrent async logging without corrupting JSON lines',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.audit.logger import record_audit, get_recent_audit_events
from carefold.schemas.audit import AuditEvent

async def log_worker(idx, log_path):
    await record_audit(
        AuditEvent(agent_id=f'worker-{idx}', event='run', allowed=True, duration_ms=float(idx)),
        log_path=log_path
    )

async def main():
    log_path = Path('${ws}') / 'logs' / 'audit.jsonl'
    tasks = [log_worker(i, log_path) for i in range(25)]
    await asyncio.gather(*tasks)

    total, events = await get_recent_audit_events(log_path=log_path, limit=50)
    assert total == 25
    assert len(events) == 25

asyncio.run(main())
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    }
  ];

  return tests;
}
