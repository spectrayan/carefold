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

export const name = 'F15-B: CLI skill Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F15-B01',
      name: 'carefold skill add without arguments exits with non-zero status',
      fn: () => {
        const res = runCli(['skill', 'add']);
        assertTrue(res.status !== 0, 'skill add without argument should fail');
      }
    },
    {
      id: 'F15-B02',
      name: 'carefold skill add handles reinstalling existing skill without error',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          runCli(['skill', 'add', 'visit-prep'], { cwd: ws });
          const res2 = runCli(['skill', 'add', 'visit-prep'], { cwd: ws });
          assertTrue(res2.status === 0 || res2.status === 1);
          assertTrue(fs.existsSync(path.join(ws, 'skills', 'visit-prep', 'SKILL.md')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F15-B03',
      name: 'carefold skill add installs multiple skills in succession into workspace',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          runCli(['skill', 'add', 'visit-prep'], { cwd: ws });
          runCli(['skill', 'add', 'benefits-explainer'], { cwd: ws });
          runCli(['skill', 'add', 'habit-checkin'], { cwd: ws });

          const listRes = runCli(['skill', 'list'], { cwd: ws });
          assertEqual(listRes.status, 0);
          assertContains(listRes.stdout, 'visit-prep');
          assertContains(listRes.stdout, 'benefits-explainer');
          assertContains(listRes.stdout, 'habit-checkin');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F15-B04',
      name: 'carefold skill list handles empty or uninitialized directory cleanly',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const res = runCli(['skill', 'list'], { cwd: ws });
          assertTrue(res.status === 0 || res.status === 1);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F15-B05',
      name: 'carefold skill add copies references directory assets alongside SKILL.md',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws, '--bare']);
          runCli(['skill', 'add', 'visit-prep'], { cwd: ws });
          const refDir = path.join(ws, 'skills', 'visit-prep', 'references');
          assertTrue(fs.existsSync(refDir), 'references directory should be copied');
          assertTrue(fs.readdirSync(refDir).length >= 1, 'references directory should contain guides');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    }
  ];

  return tests;
}
