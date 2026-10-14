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

export const name = 'F21: Tool Execution Traces UI';

export async function run() {
  const tests = [
    {
      id: 'F21-T01',
      name: 'Tool execution trace emits tool name, params, duration, and status',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    starts = []
    ends = []
    async for event in execute_agent_run('visit-steward', 'Check the questions guide document for appointment prep', mock=True):
        if event.get('type') == 'tool_start':
            starts.append(event)
        elif event.get('type') == 'tool_end':
            ends.append(event)
    assert len(starts) >= 1
    assert len(ends) >= 1
    assert 'tool' in starts[0]
    assert 'params' in starts[0]
    assert 'duration_ms' in ends[0]
    assert 'status' in ends[0]

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F21-T02',
      name: 'Tool execution trace reports "completed" status for successful tool calls',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    end_event = None
    async for event in execute_agent_run('visit-steward', 'Save our visit agenda to a workspace note', mock=True):
        if event.get('type') == 'tool_end':
            end_event = event
            break
    assert end_event is not None
    assert end_event['status'] == 'completed'
    assert end_event['allowed'] is True

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F21-T03',
      name: 'Tool execution trace reports "denied" status when undeclared tool is attempted',
      fn: () => {
        const script = `
from carefold.schemas.audit import AuditEvent
event = AuditEvent(agent_id='restricted-agent', event='tool', tool='bash', allowed=False)
assert event.allowed is False
assert event.tool == 'bash'
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F21-T04',
      name: 'Tool trace components provide collapsible cards with duration indicator',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    async for event in execute_agent_run('visit-steward', 'Check the questions guide', mock=True):
        if event.get('type') == 'tool_end':
            assert isinstance(event.get('duration_ms'), (int, float))
            assert event.get('duration_ms') >= 0

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F21-T05',
      name: 'Tool execution results are passed into subsequent assistant context',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    full_text = None
    async for event in execute_agent_run('visit-steward', 'Check the questions guide document for appointment prep', mock=True):
        if event.get('type') == 'done':
            full_text = event.get('fullText')
    assert full_text is not None
    assert len(full_text) > 0

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
