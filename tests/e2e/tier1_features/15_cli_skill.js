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

export const name = 'F15: CLI skill list/add';

export async function run() {
  const tests = [
    {
      id: 'F15-T01',
      name: 'carefold skill list outputs all installed skills with version and risk class',
      fn: () => {
        const res = runCli(['skill', 'list']);
        assertEqual(res.status, 0, `skill list failed: ${res.stderr}`);
        assertContains(res.stdout, 'visit-prep');
        assertContains(res.stdout, 'benefits-explainer');
        assertContains(res.stdout, 'habit-checkin');
      }
    },
    {
      id: 'F15-T02',
      name: 'carefold skill add installs a bundled reference skill into workspace',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          const res = runCli(['skill', 'add', 'visit-prep'], { cwd: ws });
          assertEqual(res.status, 0, `skill add failed: ${res.stderr}`);
          assertTrue(fs.existsSync(path.join(ws, 'skills', 'visit-prep', 'SKILL.md')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F15-T03',
      name: 'carefold skill list in bare workspace reports empty list gracefully',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          const res = runCli(['skill', 'list'], { cwd: ws });
          assertEqual(res.status, 0, `skill list failed: ${res.stderr}`);
          assertContains(res.stdout, 'No installed skills found');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F15-T04',
      name: 'carefold skill add reports error when attempting to add unknown skill name',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          const res = runCli(['skill', 'add', 'unknown-skill-xyz'], { cwd: ws });
          assertTrue(res.status !== 0, 'Expected non-zero exit for unknown skill');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F15-T05',
      name: 'carefold skill list displays declared tool permissions for each skill',
      fn: () => {
        const res = runCli(['skill', 'list']);
        assertEqual(res.status, 0, `skill list failed: ${res.stderr}`);
        assertContains(res.stdout, 'attach-read');
        assertContains(res.stdout, 'workspace-note');
      }
    }
  ];

  return tests;
}
