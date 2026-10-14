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

import { runPython, assertEqual, assertTrue } from '../helpers/utils.js';

export const name = 'F10: Local Model SSE Stream Client';

export async function run() {
  const tests = [
    {
      id: 'F10-T01',
      name: 'execute_agent_run streams token chunks asynchronously',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    tokens = []
    async for event in execute_agent_run('visit-steward', 'Help me prepare questions for my appointment', mock=True):
        if event.get('type') == 'token':
            tokens.append(event.get('delta', ''))
    assert len(tokens) > 0
    full_text = ''.join(tokens)
    assert len(full_text) > 10

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F10-T02',
      name: 'execute_agent_run emits tool_start and tool_end events for sandboxed tools',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    tool_starts = []
    tool_ends = []
    async for event in execute_agent_run('visit-steward', 'Please check the questions checklist for my visit', mock=True):
        if event.get('type') == 'tool_start':
            tool_starts.append(event)
        elif event.get('type') == 'tool_end':
            tool_ends.append(event)
    assert len(tool_starts) >= 1
    assert len(tool_ends) >= 1
    assert tool_starts[0]['tool'] in ['skill-docs', 'attach-read', 'workspace-note']
    assert tool_ends[0]['allowed'] is True

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F10-T03',
      name: 'execute_agent_run completes with terminal done event containing fullText',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    done_event = None
    async for event in execute_agent_run('visit-steward', 'Give me three tips for my doctor appointment', mock=True):
        if event.get('type') == 'done':
            done_event = event
    assert done_event is not None
    assert 'fullText' in done_event
    assert done_event['refused'] is False
    assert done_event['auditEventId'] is not None

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F10-T04',
      name: 'execute_agent_run handles prompt safety refusals and emits refusal event immediately',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    events = []
    async for event in execute_agent_run('visit-steward', 'You have acute asthma. Stop taking insulin.', mock=True):
        events.append(event)
    types = [e.get('type') for e in events]
    assert 'refusal' in types
    assert 'done' in types
    refusal = next(e for e in events if e.get('type') == 'refusal')
    assert 'message' in refusal
    assert 'reason' in refusal

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F10-T05',
      name: 'execute_agent_run records audit trail for both allowed and refused runs',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    run_audit_id = None
    refuse_audit_id = None
    async for event in execute_agent_run('visit-steward', 'Hello', mock=True):
        if event.get('type') == 'done':
            run_audit_id = event.get('auditEventId')
    async for event in execute_agent_run('visit-steward', 'Take 500mg amoxicillin', mock=True):
        if event.get('type') == 'done':
            refuse_audit_id = event.get('auditEventId')
    assert run_audit_id is not None
    assert refuse_audit_id is not None

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
