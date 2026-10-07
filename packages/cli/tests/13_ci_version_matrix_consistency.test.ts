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
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import yaml from 'yaml';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, '../../..');

describe('13: CI Version Matrix & Documentation Consistency', () => {
  const ciWorkflowPath = path.join(ROOT_DIR, '.github/workflows/ci.yml');
  const rootPkgPath = path.join(ROOT_DIR, 'package.json');
  const webPkgPath = path.join(ROOT_DIR, 'apps/web/package.json');
  const roadmapPath = path.join(ROOT_DIR, 'ROADMAP.md');
  const changelogPath = path.join(ROOT_DIR, 'CHANGELOG.md');
  const contributingPath = path.join(ROOT_DIR, 'CONTRIBUTING.md');
  const readmePath = path.join(ROOT_DIR, 'README.md');

  const ciWorkflow = yaml.parse(fs.readFileSync(ciWorkflowPath, 'utf8'));
  const rootPkg = JSON.parse(fs.readFileSync(rootPkgPath, 'utf8'));
  const webPkg = JSON.parse(fs.readFileSync(webPkgPath, 'utf8'));
  const roadmap = fs.readFileSync(roadmapPath, 'utf8');
  const changelog = fs.readFileSync(changelogPath, 'utf8');
  const contributing = fs.readFileSync(contributingPath, 'utf8');
  const readme = fs.readFileSync(readmePath, 'utf8');

  it('verifies CI backend and security jobs define matrix with Python 3.12 and 3.14', () => {
    // Backend job checks
    const backendJob = ciWorkflow.jobs.backend;
    expect(backendJob).toBeDefined();
    expect(backendJob.strategy?.['fail-fast']).toBe(false);
    expect(backendJob.strategy?.matrix?.['python-version']).toEqual(['3.12', '3.14']);
    expect(backendJob.name).toContain('${{ matrix.python-version }}');

    const backendSetupPython = backendJob.steps?.find(
      (s: any) => s.uses && s.uses.startsWith('actions/setup-python')
    );
    expect(backendSetupPython).toBeDefined();
    expect(backendSetupPython.with?.['python-version']).toBe('${{ matrix.python-version }}');

    // Security job checks
    const securityJob = ciWorkflow.jobs.security;
    expect(securityJob).toBeDefined();
    expect(securityJob.strategy?.['fail-fast']).toBe(false);
    expect(securityJob.strategy?.matrix?.['python-version']).toEqual(['3.12', '3.14']);
    expect(securityJob.name).toContain('${{ matrix.python-version }}');

    const securitySetupPython = securityJob.steps?.find(
      (s: any) => s.uses && s.uses.startsWith('actions/setup-python')
    );
    expect(securitySetupPython).toBeDefined();
    expect(securitySetupPython.with?.['python-version']).toBe('${{ matrix.python-version }}');
  });

  it('verifies CI frontend and license-check steps specify Node 22', () => {
    const licenseCheckJob = ciWorkflow.jobs['license-check'];
    expect(licenseCheckJob).toBeDefined();
    const licenseSetupNode = licenseCheckJob.steps?.find(
      (s: any) => s.uses && s.uses.startsWith('actions/setup-node')
    );
    expect(licenseSetupNode).toBeDefined();
    expect(String(licenseSetupNode.with?.['node-version'])).toBe('22');

    const frontendJob = ciWorkflow.jobs.frontend;
    expect(frontendJob).toBeDefined();
    const frontendSetupNode = frontendJob.steps?.find(
      (s: any) => s.uses && s.uses.startsWith('actions/setup-node')
    );
    expect(frontendSetupNode).toBeDefined();
    expect(String(frontendSetupNode.with?.['node-version'])).toBe('22');
  });

  it('verifies root and web package.json declare engines.node >=22.0.0', () => {
    expect(rootPkg.engines?.node).toBe('>=22.0.0');
    expect(webPkg.engines?.node).toBe('>=22.0.0');
  });

  it('asserts ROADMAP.md and CHANGELOG.md do not claim Node 20 for CI and specify Node 22 LTS', () => {
    // ROADMAP assertions
    expect(roadmap).not.toMatch(/Node 20\/22/i);
    expect(roadmap).toContain('Python 3.12/3.14, Node 22 LTS');

    // CHANGELOG assertions
    expect(changelog).not.toMatch(/Node \(20, 22\)/i);
    expect(changelog).toContain('Python (3.12, 3.14), Node 22 LTS');
  });

  it('asserts CONTRIBUTING.md specifies Node 22 and Python 3.12/3.14', () => {
    expect(contributing).toContain('engines.node >=22.0.0');
    expect(contributing).toContain('3.12');
    expect(contributing).toContain('3.14');
  });

  it('asserts README.md specifies Python 3.12+ (tested on 3.12 and 3.14) and Node.js 22 LTS', () => {
    expect(readme).toContain('Python 3.12+ (tested on 3.12 and 3.14), Node.js 22 LTS, and `pnpm` (>=9.0.0)');
  });
});
