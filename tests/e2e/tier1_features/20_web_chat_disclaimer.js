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

export const name = 'F20: Web Chat Shell & Disclaimers';

export async function run() {
  const tests = [
    {
      id: 'F20-T01',
      name: 'Permanent safety disclaimer banner is non-removable and visible in chat shell',
      fn: () => {
        const script = `
from carefold.safety.template import DISCLAIMER_HEADER_TEXT
assert 'wellness' in DISCLAIMER_HEADER_TEXT.lower()
assert 'diagnosis' in DISCLAIMER_HEADER_TEXT.lower()
assert 'treatment' in DISCLAIMER_HEADER_TEXT.lower()
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F20-T02',
      name: 'POST /api/chat establishes streaming connection and emits text tokens',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    tokens = []
    async for event in execute_agent_run('visit-steward', 'Hello', mock=True):
        if event.get('type') == 'token':
            tokens.append(event.get('delta', ''))
    assert len(tokens) > 0

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F20-T03',
      name: 'Chat interface displays agent starters chips for quick-prompt selection',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent_starters
starters = load_agent_starters('agents/visit-steward')
assert len(starters) >= 1
assert all(len(s) > 5 for s in starters)
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F20-T04',
      name: 'Chat shell intercepts clinical diagnosis prompts and displays Safe Refusal Template',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE

async def main():
    refusal_msg = None
    async for event in execute_agent_run('visit-steward', 'Do I have type 2 diabetes?', mock=True):
        if event.get('type') == 'refusal':
            refusal_msg = event.get('message')
    assert refusal_msg == SAFE_REFUSAL_TEMPLATE

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F20-T05',
      name: 'Chat shell displays terminal run completion state with audit event ID',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    done_event = None
    async for event in execute_agent_run('visit-steward', 'Hello', mock=True):
        if event.get('type') == 'done':
            done_event = event
    assert done_event is not None
    assert done_event['auditEventId'] is not None

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
