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

export const name = 'F09: Audit Logger Engine';

export async function run() {
  const tests = [
    {
      id: 'F09-T01',
      name: 'Audit logger writes append-only JSONL entries to logs/audit.jsonl',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.audit.logger import record_audit
from carefold.schemas.audit import AuditEvent

async def main():
    event = AuditEvent(agent_id='visit-steward', event='run', allowed=True, duration_ms=120.0)
    await record_audit(event, workspace_root=Path('${ws}'))
    log_file = Path('${ws}') / 'logs' / 'audit.jsonl'
    assert log_file.is_file()
    lines = log_file.read_text(encoding='utf-8').strip().split('\\n')
    assert len(lines) == 1
    assert 'visit-steward' in lines[0]

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
      id: 'F09-T02',
      name: 'Audit logger redacts prompt and completion message bodies by default (store_bodies=False)',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio, json
from pathlib import Path
from carefold.audit.logger import record_audit
from carefold.schemas.audit import AuditEvent

async def main():
    event = AuditEvent(
        agent_id='visit-steward',
        event='run',
        allowed=True,
        prompt='Confidential health symptom details',
        completion='Sensitive advice response'
    )
    await record_audit(event, workspace_root=Path('${ws}'), store_bodies=False)
    log_file = Path('${ws}') / 'logs' / 'audit.jsonl'
    data = json.loads(log_file.read_text(encoding='utf-8').strip())
    assert data.get('prompt') is None, 'Prompt should be redacted'
    assert data.get('completion') is None, 'Completion should be redacted'

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
      id: 'F09-T03',
      name: 'Audit logger records refusal events with event="refuse" and refusal reason',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio, json
from pathlib import Path
from carefold.audit.logger import record_audit
from carefold.schemas.audit import AuditEvent

async def main():
    event = AuditEvent(
        agent_id='visit-steward',
        event='refuse',
        allowed=False,
        reason='forbidden_intent:diagnose',
        duration_ms=45.0
    )
    await record_audit(event, workspace_root=Path('${ws}'))
    log_file = Path('${ws}') / 'logs' / 'audit.jsonl'
    data = json.loads(log_file.read_text(encoding='utf-8').strip())
    assert data['event'] == 'refuse'
    assert data['allowed'] is False
    assert data['reason'] == 'forbidden_intent:diagnose'

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
      id: 'F09-T04',
      name: 'Audit logger records tool execution events with tool name and duration',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio, json
from pathlib import Path
from carefold.audit.logger import record_audit
from carefold.schemas.audit import AuditEvent

async def main():
    event = AuditEvent(
        agent_id='visit-steward',
        event='tool',
        tool='attach-read',
        allowed=True,
        duration_ms=12.5
    )
    await record_audit(event, workspace_root=Path('${ws}'))
    log_file = Path('${ws}') / 'logs' / 'audit.jsonl'
    data = json.loads(log_file.read_text(encoding='utf-8').strip())
    assert data['event'] == 'tool'
    assert data['tool'] == 'attach-read'
    assert data['duration_ms'] == 12.5

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
      id: 'F09-T05',
      name: 'read_recent_audit_events retrieves and parses recent entries accurately',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.audit.logger import record_audit, read_recent_audit_events
from carefold.schemas.audit import AuditEvent

async def main():
    for i in range(5):
        await record_audit(
            AuditEvent(agent_id=f'agent-{i}', event='run', allowed=True),
            workspace_root=Path('${ws}')
        )
    events = read_recent_audit_events(limit=3, workspace_root=Path('${ws}'))
    assert len(events) == 3
    assert events[-1].agent_id == 'agent-4'

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
