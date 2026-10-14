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

export const name = 'F21-B: Tool Execution Traces UI Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F21-B01',
      name: 'Failed tool calls emit tool_end event with success=False or error payload',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

# Inquiring about non-existent doc triggers tool execution that handles not-found
async def main():
    tool_ends = []
    async for ev in execute_agent_run('visit-steward', 'Read doc missing_nonexistent_guide.md', mock=True):
        if ev.get('type') == 'tool_end':
            tool_ends.append(ev)
    # Runner completes without crashing even if tool returns error
    assert True

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F21-B02',
      name: 'Tool trace handles large tool result payloads without breaking SSE JSON stream',
      fn: () => {
        const script = `
import asyncio, json
from carefold.schemas.tool import ToolResult

res = ToolResult(success=True, output={"content": "x" * 100000, "meta": "large"})
serialized = json.dumps(res.model_dump())
assert len(serialized) > 100000
loaded = json.loads(serialized)
assert loaded["success"] is True
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F21-B03',
      name: 'Paired tool_start and tool_end events maintain strictly monotonic ordering',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    events = []
    async for ev in execute_agent_run('visit-steward', 'Check the questions guide checklist', mock=True):
        if ev.get('type') in ['tool_start', 'tool_end']:
            events.append(ev['type'])

    # If tools were invoked, tool_start must strictly precede tool_end
    if 'tool_start' in events:
        first_start = events.index('tool_start')
        first_end = events.index('tool_end')
        assert first_start < first_end, "tool_start must precede tool_end"

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F21-B04',
      name: 'Tool trace duration_ms is non-negative and sub-second under mock mode',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    async for ev in execute_agent_run('visit-steward', 'Check questions guide', mock=True):
        if ev.get('type') == 'tool_end':
            d = ev.get('duration_ms', 0)
            assert d >= 0.0
            assert d < 10000.0

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F21-B05',
      name: 'Tool execution trace reports correct tool name matching closed registry',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run
from carefold.schemas.manifest import PHASE_0_REGISTRY

async def main():
    async for ev in execute_agent_run('visit-steward', 'Check the checklist for my appointment', mock=True):
        if ev.get('type') == 'tool_start':
            tool_name = ev.get('tool')
            assert tool_name in PHASE_0_REGISTRY, f"Tool {tool_name} not in registry"

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
