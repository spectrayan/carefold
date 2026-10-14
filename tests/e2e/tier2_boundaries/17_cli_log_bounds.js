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

import { runCli, assertEqual, assertTrue, assertContains } from '../helpers/utils.js';

export const name = 'F17-B: CLI carefold log Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F17-B01',
      name: 'carefold log --json outputs a valid JSON array of audit events',
      fn: () => {
        const res = runCli(['log', '--json', '-n', '5']);
        assertEqual(res.status, 0, `carefold log --json failed: ${res.stderr}`);
        const parsed = JSON.parse(res.stdout);
        assertTrue(Array.isArray(parsed), 'JSON output should be an array');
      }
    },
    {
      id: 'F17-B02',
      name: 'carefold log -e / --event filters records strictly by event type',
      fn: () => {
        const res = runCli(['log', '-e', 'refuse', '--json', '-n', '10']);
        assertEqual(res.status, 0, `Filter failed: ${res.stderr}`);
        const events = JSON.parse(res.stdout);
        assertTrue(Array.isArray(events));
        for (const ev of events) {
          assertEqual(ev.event, 'refuse', 'Filtered events must all have event="refuse"');
        }
      }
    },
    {
      id: 'F17-B03',
      name: 'carefold log -n 1 returns at most one event in JSON output',
      fn: () => {
        const res = runCli(['log', '-n', '1', '--json']);
        assertEqual(res.status, 0, `Limit 1 failed: ${res.stderr}`);
        const events = JSON.parse(res.stdout);
        assertTrue(events.length <= 1, 'Should return at most 1 event');
      }
    },
    {
      id: 'F17-B04',
      name: 'carefold log rejects limit <= 0 with validation error',
      fn: () => {
        const res = runCli(['log', '-n', '0']);
        assertTrue(res.status !== 0, 'Limit 0 should exit with non-zero');
        assertContains(res.stderr + res.stdout, 'positive integer');
      }
    },
    {
      id: 'F17-B05',
      name: 'carefold log against empty workspace directory reports no events found',
      fn: () => {
        const res = runCli(['log', '--workspace', '/tmp']);
        assertEqual(res.status, 0, `Failed on empty workspace: ${res.stderr}`);
        assertContains(res.stdout, 'No audit events found');
      }
    }
  ];

  return tests;
}
