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

/**
 * Carefold E2E Test Suite - Shared Utilities & Helpers
 * Pure Node.js implementation with zero external dependencies.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { execSync, spawnSync } from 'node:child_process';
import http from 'node:http';

export const REPO_ROOT = path.resolve(process.cwd());
export const CLI_BIN = path.join(REPO_ROOT, 'packages', 'cli', 'bin', 'carefold.js');
export const PYTHON_BIN = path.join(REPO_ROOT, 'backend', '.venv', 'bin', 'python3');

export function runCli(args, options = {}) {
  const nodeArgs = [CLI_BIN, ...args];
  const res = spawnSync(process.execPath, nodeArgs, {
    cwd: options.cwd || REPO_ROOT,
    env: { ...process.env, ...options.env },
    encoding: 'utf8',
    timeout: options.timeout || 30000,
  });
  return {
    status: res.status,
    stdout: res.stdout || '',
    stderr: res.stderr || '',
    error: res.error,
  };
}

export function runPython(codeOrScript, args = [], options = {}) {
  let pyArgs;
  if (codeOrScript === '-m') {
    pyArgs = ['-m', ...args];
  } else if (fs.existsSync(codeOrScript)) {
    pyArgs = [codeOrScript, ...args];
  } else {
    pyArgs = ['-c', codeOrScript, ...args];
  }
  const res = spawnSync(PYTHON_BIN, pyArgs, {
    cwd: options.cwd || REPO_ROOT,
    env: {
      ...process.env,
      PYTHONPATH: `${path.join(REPO_ROOT, 'backend', 'src')}:${REPO_ROOT}`,
      ...options.env,
    },
    encoding: 'utf8',
    timeout: options.timeout || 30000,
  });
  return {
    status: res.status,
    stdout: res.stdout || '',
    stderr: res.stderr || '',
    error: res.error,
  };
}

export function createTempWorkspace(prefix = 'carefold-e2e-') {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  return tmpDir;
}

export function removeTempWorkspace(dir) {
  if (dir && fs.existsSync(dir)) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {}
  }
}

export function assert(condition, message = 'Assertion failed') {
  if (!condition) {
    throw new Error(message);
  }
}

export function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(message || `Expected ${JSON.stringify(expected)} but got ${JSON.stringify(actual)}`);
  }
}

export function assertTrue(condition, message) {
  assert(Boolean(condition), message || 'Expected true condition');
}

export function assertFalse(condition, message) {
  assert(!condition, message || 'Expected false condition');
}

export function assertContains(haystack, needle, message) {
  const str = String(haystack);
  if (!str.includes(needle)) {
    throw new Error(message || `Expected string to contain ${JSON.stringify(needle)}, got:\n${str.slice(0, 500)}`);
  }
}

export function assertNotContains(haystack, needle, message) {
  const str = String(haystack);
  if (str.includes(needle)) {
    throw new Error(message || `Expected string to NOT contain ${JSON.stringify(needle)}, got:\n${str.slice(0, 500)}`);
  }
}
