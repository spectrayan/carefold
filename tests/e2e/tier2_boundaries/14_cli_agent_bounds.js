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
import { runCli, createTempWorkspace, removeTempWorkspace, assertEqual, assertTrue, assertContains } from '../helpers/utils.js';

export const name = 'F14-B: CLI agent Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F14-B01',
      name: 'carefold agent inspect without argument exits with non-zero status',
      fn: () => {
        const res = runCli(['agent', 'inspect']);
        assertTrue(res.status !== 0, 'Inspect without argument should fail');
      }
    },
    {
      id: 'F14-B02',
      name: 'carefold agent add with unknown agent name exits with error',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          const res = runCli(['agent', 'add', 'super-fake-agent-xyz'], { cwd: ws });
          assertTrue(res.status !== 0, 'Adding non-existent agent should fail');
          assertContains((res.stderr + res.stdout).toLowerCase(), 'unknown agent');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F14-B03',
      name: 'carefold agent add already installed agent is handled idempotently without corrupting',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          runCli(['agent', 'add', 'habit-companion'], { cwd: ws });
          // Add again
          const res2 = runCli(['agent', 'add', 'habit-companion'], { cwd: ws });
          assertTrue(res2.status === 0 || res2.status === 1);
          assertTrue(fs.existsSync(path.join(ws, 'agents', 'habit-companion', 'agent.yaml')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F14-B04',
      name: 'carefold agent inspect displays effective tools correctly for multi-tool agent',
      fn: () => {
        const res = runCli(['agent', 'inspect', 'visit-steward']);
        assertEqual(res.status, 0, `Failed inspect: ${res.stderr}`);
        // Effective tools union should list tools
        const out = res.stdout.toLowerCase();
        assertTrue(out.includes('attach-read') || out.includes('workspace-note') || out.includes('skill-docs'));
      }
    },
    {
      id: 'F14-B05',
      name: 'carefold agent list handles workspace with missing agents directory gracefully',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          // Empty directory with no carefold structure
          const res = runCli(['agent', 'list'], { cwd: ws });
          // Should report empty list or exit cleanly
          assertTrue(res.status === 0 || res.status === 1);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    }
  ];

  return tests;
}
