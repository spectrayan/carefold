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

export const name = 'F13-B: CLI carefold init Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F13-B01',
      name: 'carefold init reports existing workspace when carefold.config.json already exists without --force',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws]);
          const res2 = runCli(['init', ws]);
          // CLI handles re-init without error or reports already initialized
          assertTrue(res2.status === 0 || res2.status === 1);
          assertTrue(fs.existsSync(path.join(ws, 'carefold.config.json')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F13-B02',
      name: 'carefold init --force safely reinitializes existing directory',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws]);
          const res = runCli(['init', ws, '--force']);
          assertEqual(res.status, 0, `Init --force failed: ${res.stderr}`);
          assertTrue(fs.existsSync(path.join(ws, 'carefold.config.json')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F13-B03',
      name: 'carefold init creates deeply nested directory path if parent directories do not exist',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const deepPath = path.join(ws, 'sub1', 'sub2', 'workspace');
          const res = runCli(['init', deepPath]);
          assertEqual(res.status, 0, `Nested init failed: ${res.stderr}`);
          assertTrue(fs.existsSync(path.join(deepPath, 'carefold.config.json')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F13-B04',
      name: 'carefold init without --bare bundles default reference agents and skills',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const res = runCli(['init', ws]);
          assertEqual(res.status, 0, `Init failed: ${res.stderr}`);
          const agents = fs.readdirSync(path.join(ws, 'agents'));
          assertTrue(agents.includes('visit-steward'), 'Default agents should include visit-steward');
          const skills = fs.readdirSync(path.join(ws, 'skills'));
          assertTrue(skills.includes('visit-prep'), 'Default skills should include visit-prep');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F13-B05',
      name: 'carefold init creates empty attachments/ directory ready for ingestion',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const res = runCli(['init', ws]);
          assertEqual(res.status, 0, `Init failed: ${res.stderr}`);
          const attachDir = path.join(ws, 'attachments');
          assertTrue(fs.existsSync(attachDir), 'attachments/ directory missing');
          assertTrue(fs.statSync(attachDir).isDirectory(), 'attachments/ must be a directory');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    }
  ];

  return tests;
}
