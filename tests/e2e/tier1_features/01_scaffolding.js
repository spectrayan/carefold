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

export const name = 'F01: Workspace Scaffolding';

export async function run() {
  const tests = [
    {
      id: 'F01-T01',
      name: 'carefold init creates all required standard directories',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const res = runCli(['init', ws]);
          assertEqual(res.status, 0, `Init failed: ${res.stderr}`);
          assertTrue(fs.existsSync(path.join(ws, 'skills')), 'skills/ missing');
          assertTrue(fs.existsSync(path.join(ws, 'agents')), 'agents/ missing');
          assertTrue(fs.existsSync(path.join(ws, 'chats')), 'chats/ missing');
          assertTrue(fs.existsSync(path.join(ws, 'attachments')), 'attachments/ missing');
          assertTrue(fs.existsSync(path.join(ws, 'logs')), 'logs/ missing');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F01-T02',
      name: 'carefold init generates valid carefold.config.json',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws]);
          const cfgPath = path.join(ws, 'carefold.config.json');
          assertTrue(fs.existsSync(cfgPath), 'carefold.config.json missing');
          const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
          assertEqual(cfg.version, '0.1.0');
          assertEqual(cfg.audit?.enabled, true);
          assertEqual(cfg.audit?.store_bodies, false);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F01-T03',
      name: 'carefold init bundles reference skills by default',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws]);
          assertTrue(fs.existsSync(path.join(ws, 'skills', 'visit-prep', 'SKILL.md')));
          assertTrue(fs.existsSync(path.join(ws, 'skills', 'benefits-explainer', 'SKILL.md')));
          assertTrue(fs.existsSync(path.join(ws, 'skills', 'habit-checkin', 'SKILL.md')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F01-T04',
      name: 'carefold init bundles reference agents by default',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws]);
          assertTrue(fs.existsSync(path.join(ws, 'agents', 'visit-steward', 'agent.yaml')));
          assertTrue(fs.existsSync(path.join(ws, 'agents', 'benefits-guide', 'agent.yaml')));
          assertTrue(fs.existsSync(path.join(ws, 'agents', 'habit-companion', 'agent.yaml')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F01-T05',
      name: 'carefold init initializes audit.jsonl log file',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws]);
          const logPath = path.join(ws, 'logs', 'audit.jsonl');
          assertTrue(fs.existsSync(logPath), 'logs/audit.jsonl missing');
        } finally {
          removeTempWorkspace(ws);
        }
      }
    }
  ];

  return tests;
}
