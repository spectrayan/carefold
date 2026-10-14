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

export const name = 'F14: CLI agent list/add/inspect';

export async function run() {
  const tests = [
    {
      id: 'F14-T01',
      name: 'carefold agent list outputs all installed agents with risk class and effective tools',
      fn: () => {
        const res = runCli(['agent', 'list']);
        assertEqual(res.status, 0, `agent list failed: ${res.stderr}`);
        assertContains(res.stdout, 'visit-steward');
        assertContains(res.stdout, 'benefits-guide');
        assertContains(res.stdout, 'habit-companion');
      }
    },
    {
      id: 'F14-T02',
      name: 'carefold agent inspect displays detailed agent manifest and persona configuration',
      fn: () => {
        const res = runCli(['agent', 'inspect', 'visit-steward']);
        assertEqual(res.status, 0, `agent inspect failed: ${res.stderr}`);
        assertContains(res.stdout, 'Visit Steward');
        assertContains(res.stdout, 'wellness');
        assertContains(res.stdout, 'visit-prep');
      }
    },
    {
      id: 'F14-T03',
      name: 'carefold agent add installs a bundled reference agent into workspace',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          const res = runCli(['agent', 'add', 'visit-steward'], { cwd: ws });
          assertEqual(res.status, 0, `agent add failed: ${res.stderr}`);
          assertTrue(fs.existsSync(path.join(ws, 'agents', 'visit-steward', 'agent.yaml')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F14-T04',
      name: 'carefold agent list in bare workspace reports empty list gracefully',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          const res = runCli(['agent', 'list'], { cwd: ws });
          assertEqual(res.status, 0, `agent list failed: ${res.stderr}`);
          assertContains(res.stdout, 'No installed agents found');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F14-T05',
      name: 'carefold agent inspect reports error for nonexistent agent ID',
      fn: () => {
        const res = runCli(['agent', 'inspect', 'nonexistent-agent']);
        assertTrue(res.status !== 0, 'Expected non-zero exit for nonexistent agent');
      }
    }
  ];

  return tests;
}
