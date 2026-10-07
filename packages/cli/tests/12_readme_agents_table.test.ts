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

import { describe, it, expect } from 'vitest';
import { execFile } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import fs from 'node:fs';
import os from 'node:os';

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, '../../..');
const GENERATE_SCRIPT = path.join(ROOT_DIR, 'scripts/generate-readme-table.mjs');
const VALIDATE_SCRIPT = path.join(ROOT_DIR, 'scripts/validate-packs.mjs');
const README_PATH = path.join(ROOT_DIR, 'README.md');

async function runScript(scriptPath: string, args: string[], cwd: string = ROOT_DIR) {
  try {
    const { stdout, stderr } = await execFileAsync(process.execPath, [scriptPath, ...args], {
      cwd,
      timeout: 15000
    });
    return {
      exitCode: 0,
      stdout: stdout.toString(),
      stderr: stderr.toString()
    };
  } catch (err: any) {
    return {
      exitCode: typeof err.code === 'number' ? err.code : 1,
      stdout: err.stdout ? err.stdout.toString() : '',
      stderr: err.stderr ? err.stderr.toString() : err.message
    };
  }
}

describe('12: README Specialist Agent Table Generator & Sync Check', () => {
  it('exits with 0 when running --check on the synchronized repository', async () => {
    const res = await runScript(GENERATE_SCRIPT, ['--check']);
    expect(res.exitCode).toBe(0);
    expect(res.stdout).toContain('README.md specialist agent table is up-to-date with manifests (22 agents)');
  });

  it('outputs the full 5-column GFM table with all 22 specialist agents with --stdout', async () => {
    const res = await runScript(GENERATE_SCRIPT, ['--stdout']);
    expect(res.exitCode).toBe(0);

    const lines = res.stdout.trim().split('\n');
    expect(lines[0]).toBe('| Agent Identifier | Domain | Category | Risk Class | Clinical Scope & Capabilities |');
    expect(lines[1]).toBe('|---|---|---|---|---|');

    const dataRows = lines.slice(2).filter(line => line.startsWith('| `'));
    expect(dataRows.length).toBe(22);

    // Verify key specialist agents including newest additions
    expect(res.stdout).toContain('| `benefits-guide` | `navigation` | `navigation.insurance` | `admin` |');
    expect(res.stdout).toContain('| `podiatry-guide` | `clinical` | `clinical.podiatry` | `clinical_assist` |');
    expect(res.stdout).toContain('| `vascular-guide` | `clinical` | `clinical.vascular` | `clinical_assist` |');
    expect(res.stdout).toContain('| `visit-steward` | `navigation` | `navigation.appointments` | `clinical_assist` |');
    expect(res.stdout).toContain('| `habit-companion` | `wellness` | `wellness.habits` | `wellness` |');
  });

  it('detects drift and exits with code 1 when README table is mutated', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'carefold-readme-drift-'));
    const tmpReadme = path.join(tmpDir, 'README.md');

    try {
      const realReadme = fs.readFileSync(README_PATH, 'utf8');
      // Mutate one risk class in the table to introduce deliberate drift
      const driftedReadme = realReadme.replace(
        '| `cardiology-guide` | `clinical` | `clinical.cardiology` | `clinical_assist` |',
        '| `cardiology-guide` | `clinical` | `clinical.cardiology` | `wellness` |'
      );
      fs.writeFileSync(tmpReadme, driftedReadme, 'utf8');

      const res = await runScript(GENERATE_SCRIPT, ['--check', '--file', tmpReadme]);
      expect(res.exitCode).toBe(1);
      expect(res.stderr).toContain('has drifted from agent manifests');
      expect(res.stderr).toContain("Run 'pnpm run generate:readme' to synchronize.");
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('detects missing markers and exits with code 1', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'carefold-readme-missing-'));
    const tmpReadme = path.join(tmpDir, 'README.md');

    try {
      // README without markers
      const strippedReadme = '# Carefold\n\nNo markers in this file.\n';
      fs.writeFileSync(tmpReadme, strippedReadme, 'utf8');

      const checkRes = await runScript(GENERATE_SCRIPT, ['--check', '--file', tmpReadme]);
      expect(checkRes.exitCode).toBe(1);
      expect(checkRes.stderr).toContain('missing or misplaced');

      const updateRes = await runScript(GENERATE_SCRIPT, ['--update', '--file', tmpReadme]);
      expect(updateRes.exitCode).toBe(1);
      expect(updateRes.stderr).toContain('missing or misplaced');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('outputs the generated table when invoked via validate-packs.mjs --table with exit code 0', async () => {
    const res = await runScript(VALIDATE_SCRIPT, ['--table']);
    expect(res.exitCode).toBe(0);

    const lines = res.stdout.trim().split('\n');
    expect(lines[0]).toBe('| Agent Identifier | Domain | Category | Risk Class | Clinical Scope & Capabilities |');
    const dataRows = lines.slice(2).filter(line => line.startsWith('| `'));
    expect(dataRows.length).toBe(22);
  });
});
