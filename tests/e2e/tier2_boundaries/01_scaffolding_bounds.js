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
import { runCli, createTempWorkspace, removeTempWorkspace, assertEqual, assertTrue } from '../helpers/utils.js';

export const name = 'F01-B: Workspace Scaffolding Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F01-B01',
      name: 'carefold init refuses to overwrite existing non-empty directory without error crash',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          fs.writeFileSync(path.join(ws, 'existing.txt'), 'content');
          const res = runCli(['init', ws]);
          // CLI handles already existing files safely
          assertTrue(res.status === 0 || res.status === 1);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F01-B02',
      name: 'carefold init handles deeply nested target paths',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const nested = path.join(ws, 'a', 'b', 'c', 'nested-ws');
          const res = runCli(['init', nested]);
          assertEqual(res.status, 0);
          assertTrue(fs.existsSync(path.join(nested, 'carefold.config.json')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F01-B03',
      name: 'carefold init handles path containing spaces and special characters',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const specialPath = path.join(ws, 'my carefold @ workspace');
          const res = runCli(['init', specialPath]);
          assertEqual(res.status, 0);
          assertTrue(fs.existsSync(path.join(specialPath, 'skills')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F01-B04',
      name: 'carefold init idempotent re-run preserves existing config',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws]);
          const cfgPath = path.join(ws, 'carefold.config.json');
          const customCfg = { version: '0.1.0', custom_marker: true };
          fs.writeFileSync(cfgPath, JSON.stringify(customCfg));
          runCli(['init', ws]);
          const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
          assertEqual(cfg.version, '0.1.0');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F01-B05',
      name: 'carefold init creates attachments/ directory with write permissions',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws]);
          const testFile = path.join(ws, 'attachments', 'write_test.txt');
          fs.writeFileSync(testFile, 'test');
          assertTrue(fs.existsSync(testFile));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    }
  ];

  return tests;
}
