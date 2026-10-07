/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fsSync from 'node:fs';
import { runCli } from './helpers/cli-runner.js';
import {
  checkNodeVersion,
  checkBackendApi,
  checkOllamaDaemon,
  checkMemoryStore,
  checkCatalog,
  runDiagnostics,
  healthCommand
} from '../src/commands/health.js';
import { getCliVersion } from '../src/utils/version.js';
import { stripAnsi, visibleLength, padAnsiEnd, formatTable } from '../src/utils/format.js';
import { colors, isColorSupported, formatStatusPill } from '../src/utils/colors.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const cliPkg = JSON.parse(fsSync.readFileSync(path.resolve(__dirname, '../package.json'), 'utf8'));
const expectedVersion = cliPkg.version;

describe('11: Carefold CLI Health Diagnostics & Version Subsystem', () => {
  describe('Version Utilities & CLI Commands', () => {
    it('resolves semantic version dynamically matching package.json', () => {
      const ver = getCliVersion();
      expect(ver).toBe(expectedVersion);
      expect(ver).toMatch(/^\d+\.\d+\.\d+/);
    });

    it('outputs version string with --version', async () => {
      const res = await runCli(['--version']);
      expect(res.exitCode).toBe(0);
      expect(res.stdout.trim()).toBe(expectedVersion);
    });

    it('outputs version string with -v flag', async () => {
      const res = await runCli(['-v']);
      expect(res.exitCode).toBe(0);
      expect(res.stdout.trim()).toBe(expectedVersion);
    });

    it('outputs version string with version command', async () => {
      const res = await runCli(['version']);
      expect(res.exitCode).toBe(0);
      expect(res.stdout.trim()).toBe(expectedVersion);
    });

    it('outputs valid JSON schema with version --json', async () => {
      const res = await runCli(['version', '--json']);
      expect(res.exitCode).toBe(0);
      const parsed = JSON.parse(res.stdout);
      expect(parsed).toEqual({ version: expectedVersion });
    });
  });

  describe('Formatting & ANSI Utilities', () => {
    it('strips ANSI escape codes cleanly', () => {
      const colored = '\x1b[32m[PASS]\x1b[0m';
      expect(stripAnsi(colored)).toBe('[PASS]');
      expect(visibleLength(colored)).toBe(6);
    });

    it('pads ANSI strings accurately without shifting columns', () => {
      const coloredPass = '\x1b[32m[PASS]\x1b[0m';
      const padded = padAnsiEnd(coloredPass, 10);
      expect(visibleLength(padded)).toBe(10);
      expect(padded.endsWith('    ')).toBe(true);
    });

    it('formats table with aligned columns even with ANSI badges', () => {
      const headers = ['Component', 'Status', 'Target'];
      const rows = [
        ['Node.js Runtime', '\x1b[32m[PASS]\x1b[0m', '>= 20.0.0'],
        ['Backend API', '\x1b[31m[FAIL]\x1b[0m', 'http://localhost:8010']
      ];
      const table = formatTable(headers, rows);
      expect(table).toContain('Component');
      expect(table).toContain('Status');
      expect(table).toContain('─');
    });

    it('formats status pills with appropriate badges', () => {
      expect(stripAnsi(formatStatusPill('PASS'))).toBe('[PASS]');
      expect(stripAnsi(formatStatusPill('WARN'))).toBe('[WARN]');
      expect(stripAnsi(formatStatusPill('FAIL'))).toBe('[FAIL]');
    });
  });

  describe('Offline Health Diagnostics Resiliency', () => {
    it('runs carefold health without crashing when backend and ollama are unreachable', async () => {
      // Pointing to random unused ports to guarantee connection failure
      const res = await runCli([
        'health',
        '--backend-url',
        'http://127.0.0.1:59123',
        '--model-url',
        'http://127.0.0.1:59124',
        '--timeout',
        '500'
      ]);

      expect(res.exitCode).toBe(1);
      expect(res.stdout).toContain('Carefold System Diagnostics');
      expect(res.stdout).toContain('Node Runtime');
      expect(res.stdout).toContain('Backend API');
      expect(res.stdout).toContain('Ollama Daemon');
      expect(res.stdout).toContain('Overall Status: UNHEALTHY');
      expect(res.stderr).not.toContain('UnhandledPromiseRejection');
      expect(res.stderr).not.toContain('TypeError');
    });

    it('supports status command alias identical to health', async () => {
      const res = await runCli([
        'status',
        '--backend-url',
        'http://127.0.0.1:59123',
        '--model-url',
        'http://127.0.0.1:59124',
        '--timeout',
        '500'
      ]);

      expect(res.exitCode).toBe(1);
      expect(res.stdout).toContain('Carefold System Diagnostics');
      expect(res.stdout).toContain('Overall Status: UNHEALTHY');
    });

    it('supports root --health and -H flag aliases', async () => {
      const res1 = await runCli([
        '--health',
        '--backend-url',
        'http://127.0.0.1:59123',
        '--model-url',
        'http://127.0.0.1:59124',
        '--timeout',
        '500'
      ]);
      expect(res1.exitCode).toBe(1);
      expect(res1.stdout).toContain('Carefold System Diagnostics');

      const res2 = await runCli([
        '-H',
        '--backend-url',
        'http://127.0.0.1:59123',
        '--model-url',
        'http://127.0.0.1:59124',
        '--timeout',
        '500'
      ]);
      expect(res2.exitCode).toBe(1);
      expect(res2.stdout).toContain('Carefold System Diagnostics');
    });

    it('outputs valid JSON schema when offline via health --json', async () => {
      const res = await runCli([
        'health',
        '--json',
        '--backend-url',
        'http://127.0.0.1:59123',
        '--model-url',
        'http://127.0.0.1:59124',
        '--timeout',
        '500'
      ]);

      expect(res.exitCode).toBe(1);
      const data = JSON.parse(res.stdout);
      expect(data.status).toBe('unhealthy');
      expect(data.healthy).toBe(false);
      expect(data.version).toBe(expectedVersion);
      expect(typeof data.timestamp).toBe('string');
      expect(data.checks).toBeDefined();
      expect(data.checks.node.status).toBe('pass');
      expect(data.checks.backend.status).toBe('fail');
      expect(data.checks.backend.reachable).toBe(false);
      expect(data.checks.ollama.status).toBe('fail');
      expect(data.checks.memory.status).toBe('pass');
      expect(data.checks.catalog.status).toBe('pass');
    });

    it('suppresses output with --quiet flag while retaining exit code', async () => {
      const res = await runCli([
        'health',
        '--quiet',
        '--backend-url',
        'http://127.0.0.1:59123',
        '--model-url',
        'http://127.0.0.1:59124',
        '--timeout',
        '500'
      ]);

      expect(res.exitCode).toBe(1);
      expect(res.stdout.trim()).toBe('');
      expect(res.stderr).not.toContain('UnhandledPromiseRejection');
      expect(res.stderr).not.toContain('TypeError');
    });
  });

  describe('Direct Unit Checks & Mocked Endpoint Probes', () => {
    let mockBackendServer: http.Server;
    let mockBackendPort: number;
    let mockBackendUrl: string;

    let mockOllamaServer: http.Server;
    let mockOllamaPort: number;
    let mockOllamaUrl: string;

    let backendResponseStatus = 200;
    let backendResponseBody: any = {
      status: 'ok',
      version: '0.4.0-beta.1',
      uptime: 100,
      workspace: { agentsCount: 22, skillsCount: 24 }
    };

    let ollamaResponseStatus = 200;
    let ollamaResponseBody: any = {
      models: [{ name: 'llama3.2:latest' }, { name: 'medgemma:latest' }]
    };

    let hangBackend = false;

    beforeAll(async () => {
      // Start mock Backend API server
      await new Promise<void>((resolve) => {
        mockBackendServer = http.createServer((req, res) => {
          if (hangBackend) {
            // Intentionally do not respond to test timeout handling
            return;
          }
          if (req.url === '/api/health') {
            res.writeHead(backendResponseStatus, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(backendResponseBody));
          } else if (req.url === '/api/memory/status') {
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ healthy: true, fallback_active: false, backend: 'sqlite' }));
          } else {
            res.writeHead(404);
            res.end();
          }
        });
        mockBackendServer.listen(0, '127.0.0.1', () => {
          const addr = mockBackendServer.address() as AddressInfo;
          mockBackendPort = addr.port;
          mockBackendUrl = `http://127.0.0.1:${mockBackendPort}`;
          resolve();
        });
      });

      // Start mock Ollama server
      await new Promise<void>((resolve) => {
        mockOllamaServer = http.createServer((req, res) => {
          if (req.url === '/api/tags') {
            res.writeHead(ollamaResponseStatus, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(ollamaResponseBody));
          } else {
            res.writeHead(404);
            res.end();
          }
        });
        mockOllamaServer.listen(0, '127.0.0.1', () => {
          const addr = mockOllamaServer.address() as AddressInfo;
          mockOllamaPort = addr.port;
          mockOllamaUrl = `http://127.0.0.1:${mockOllamaPort}`;
          resolve();
        });
      });
    });

    afterAll(async () => {
      await new Promise<void>((resolve) => mockBackendServer.close(() => resolve()));
      await new Promise<void>((resolve) => mockOllamaServer.close(() => resolve()));
    });

    it('verifies Node runtime version check passes for current node (>= 20.0.0)', async () => {
      const nodeCheck = await checkNodeVersion();
      expect(nodeCheck.status).toBe('PASS');
      expect(nodeCheck.details).toContain('>=20.0.0 required');
    });

    it('verifies catalog probe identifies specialist agents and skills', () => {
      const catalog = checkCatalog();
      expect(catalog.status).toBe('PASS');
      expect(catalog.meta?.agentsCount).toBeGreaterThan(0);
      expect(catalog.meta?.skillsCount).toBeGreaterThan(0);
      expect(catalog.details).toContain('specialist agent(s)');
    });

    it('verifies healthy diagnostics when backend and ollama are online and responsive', async () => {
      backendResponseStatus = 200;
      backendResponseBody = {
        status: 'ok',
        version: '0.4.0-beta.1',
        workspace: { agentsCount: 22, skillsCount: 24 }
      };

      ollamaResponseStatus = 200;
      ollamaResponseBody = {
        models: [{ name: 'llama3.2:latest' }]
      };
      hangBackend = false;

      const report = await runDiagnostics({
        backendUrl: mockBackendUrl,
        modelUrl: mockOllamaUrl,
        timeout: 1000
      });

      expect(report.healthy).toBe(true);
      expect(report.status).toBe('healthy');
      expect(report.checks.backend.status).toBe('pass');
      expect(report.checks.ollama.status).toBe('pass');
      expect(report.checks.ollama.models).toContain('llama3.2:latest');
    });

    it('verifies degraded status when backend reports degraded', async () => {
      backendResponseStatus = 200;
      backendResponseBody = {
        status: 'degraded',
        version: '0.4.0-beta.1',
        ollama: { status: 'disconnected' }
      };

      const backendCheck = await checkBackendApi(mockBackendUrl, 1000);
      expect(backendCheck.status).toBe('WARN');
      expect(backendCheck.details).toContain('Degraded');
    });

    it('verifies degraded status when Ollama returns 0 models', async () => {
      ollamaResponseStatus = 200;
      ollamaResponseBody = { models: [] };

      const ollamaCheck = await checkOllamaDaemon(mockOllamaUrl, 1000);
      expect(ollamaCheck.status).toBe('WARN');
      expect(ollamaCheck.details).toContain('0 models found');
    });

    it('verifies cloud provider API key fallback when Ollama is offline', async () => {
      const originalKey = process.env.OPENAI_API_KEY;
      try {
        process.env.OPENAI_API_KEY = 'sk-test-key-mock';
        const offlineCheck = await checkOllamaDaemon('http://127.0.0.1:59125', 200);
        expect(offlineCheck.status).toBe('WARN');
        expect(offlineCheck.details).toContain('cloud provider API key detected');
      } finally {
        if (originalKey === undefined) {
          delete process.env.OPENAI_API_KEY;
        } else {
          process.env.OPENAI_API_KEY = originalKey;
        }
      }
    });

    it('handles request timeout gracefully without hanging', async () => {
      hangBackend = true;
      const timeoutCheck = await checkBackendApi(mockBackendUrl, 300);
      hangBackend = false;

      expect(timeoutCheck.status).toBe('FAIL');
      expect(timeoutCheck.details).toContain('timed out');
    });
  });
});
