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

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'node:path';
import fs from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import {
  loadSkill,
  loadAgent,
  executeTool,
  getClosedTool,
  executeAgentRun,
  ManifestValidationError,
  ToolValidationError,
  PHASE0_CLOSED_TOOLS,
  type ExecutionContext,
  type RunOptions,
  type StreamChunk,
  type RunResult
} from '../src/index.js';
import { createTestWorkspace, cleanupTestWorkspace } from './helpers/test-workspace.js';

const execFileAsync = promisify(execFile);

describe('11: Runner, CLI & Pack Validation Stress Suite', () => {
  let ws: string;

  beforeEach(async () => {
    ws = await createTestWorkspace();
  });

  afterEach(async () => {
    await cleanupTestWorkspace(ws);
  });

  // =========================================================================
  // 1. MANIFEST MUTATION & TAMPERING PROBES
  // =========================================================================
  describe('Manifest Mutation & Tampering Probes', () => {
    it('CHALLENGE-MUT-1: fails closed when SKILL.md is missing entirely', async () => {
      const emptyDir = path.join(ws, 'skills', 'empty-skill');
      await fs.mkdir(emptyDir, { recursive: true });

      await expect(loadSkill(emptyDir)).rejects.toThrow(ManifestValidationError);
      await expect(loadSkill(emptyDir)).rejects.toThrow(/Missing required SKILL\.md/i);
    });

    it('CHALLENGE-MUT-2: fails closed on 0-byte SKILL.md file', async () => {
      const zeroDir = path.join(ws, 'skills', 'zero-byte-skill');
      await fs.mkdir(zeroDir, { recursive: true });
      await fs.writeFile(path.join(zeroDir, 'SKILL.md'), '');

      await expect(loadSkill(zeroDir)).rejects.toThrow(ManifestValidationError);
    });

    it('CHALLENGE-MUT-3: fails closed on malformed/corrupted YAML frontmatter syntax', async () => {
      const malformedDir = path.join(ws, 'skills', 'corrupt-yaml-skill');
      await fs.mkdir(malformedDir, { recursive: true });
      await fs.writeFile(
        path.join(malformedDir, 'SKILL.md'),
        `---
name: corrupt-yaml
description: test
metadata:
  [this is not valid yaml: :::
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );

      await expect(loadSkill(malformedDir)).rejects.toThrow(/Malformed YAML frontmatter/i);
    });

    it('CHALLENGE-MUT-4: fails closed when frontmatter is missing required "name"', async () => {
      const noNameDir = path.join(ws, 'skills', 'no-name-skill');
      await fs.mkdir(noNameDir, { recursive: true });
      await fs.writeFile(
        path.join(noNameDir, 'SKILL.md'),
        `---
description: Missing name property completely
metadata:
  tools:
    - skill-docs
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );

      await expect(loadSkill(noNameDir)).rejects.toThrow(ManifestValidationError);
      await expect(loadSkill(noNameDir)).rejects.toThrow(/name: Required/i);
    });

    it('CHALLENGE-MUT-5: fails closed when frontmatter is missing required "description"', async () => {
      const noDescDir = path.join(ws, 'skills', 'no-desc-skill');
      await fs.mkdir(noDescDir, { recursive: true });
      await fs.writeFile(
        path.join(noDescDir, 'SKILL.md'),
        `---
name: no-desc-skill
metadata:
  tools:
    - skill-docs
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );

      await expect(loadSkill(noDescDir)).rejects.toThrow(ManifestValidationError);
      await expect(loadSkill(noDescDir)).rejects.toThrow(/description: Required/i);
    });

    it('CHALLENGE-MUT-6: fails closed when metadata specifies illegal risk_class', async () => {
      const illegalRiskDir = path.join(ws, 'skills', 'illegal-risk-skill');
      await fs.mkdir(illegalRiskDir, { recursive: true });
      await fs.writeFile(
        path.join(illegalRiskDir, 'SKILL.md'),
        `---
name: illegal-risk-skill
description: Declares root level clinical authority
metadata:
  risk_class: surgical_autonomy
  tools:
    - skill-docs
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );

      await expect(loadSkill(illegalRiskDir)).rejects.toThrow(ManifestValidationError);
      await expect(loadSkill(illegalRiskDir)).rejects.toThrow(/metadata\.risk_class/i);
    });

    it('CHALLENGE-MUT-7: verifies priority when carefold.yaml and carefold.yaml.migrated coexist', async () => {
      const dualDir = path.join(ws, 'skills', 'dual-manifest-skill');
      await fs.mkdir(dualDir, { recursive: true });
      await fs.writeFile(
        path.join(dualDir, 'SKILL.md'),
        `---
name: dual-manifest-skill
description: Dual manifest priority test
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );
      // Legacy carefold.yaml defines version 0.2.0
      await fs.writeFile(
        path.join(dualDir, 'carefold.yaml'),
        `
id: dual-manifest-skill
version: 0.2.0
tools:
  - attach-read
`
      );
      // Migrated carefold.yaml.migrated defines version 0.1.0
      await fs.writeFile(
        path.join(dualDir, 'carefold.yaml.migrated'),
        `
id: dual-manifest-skill
version: 0.1.0
tools:
  - workspace-note
`
      );

      const skill = await loadSkill(dualDir);
      // Active carefold.yaml takes precedence over .migrated
      expect(skill.version).toBe('0.2.0');
      expect(skill.tools).toContain('attach-read');
      expect(skill.tools).not.toContain('workspace-note');
    });

    it('CHALLENGE-MUT-8: seamlessly loads from carefold.yaml.migrated when carefold.yaml is absent', async () => {
      const migratedDir = path.join(ws, 'skills', 'migrated-only-skill');
      await fs.mkdir(migratedDir, { recursive: true });
      await fs.writeFile(
        path.join(migratedDir, 'SKILL.md'),
        `---
name: migrated-only-skill
description: Testing migrated manifest fallback
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );
      await fs.writeFile(
        path.join(migratedDir, 'carefold.yaml.migrated'),
        `
id: migrated-only-skill
version: 1.0.0
risk_class: admin
tools:
  - attach-read
  - skill-docs
forbidden:
  - diagnose
`
      );

      const skill = await loadSkill(migratedDir);
      expect(skill.is_verified).toBe(true);
      expect(skill.unverified).toBe(false);
      expect(skill.version).toBe('1.0.0');
      expect(skill.risk_class).toBe('admin');
      expect(skill.tools).toEqual(['attach-read', 'skill-docs']);
      expect(skill.forbidden).toContain('diagnose');
    });

    it('CHALLENGE-MUT-9: loads native ADR-0003 metadata: without any carefold.yaml file', async () => {
      const nativeDir = path.join(ws, 'skills', 'native-adr0003-skill');
      await fs.mkdir(nativeDir, { recursive: true });
      await fs.writeFile(
        path.join(nativeDir, 'SKILL.md'),
        `---
name: native-adr0003-skill
description: Pure native ADR-0003 frontmatter
license: Apache-2.0
allowed-tools: skill-docs
metadata:
  risk_class: wellness
  domain: wellness
  category: wellness.habits
  version: "1.2.3"
  tools:
    - skill-docs
  forbidden:
    - diagnose
    - prescribe
    - dose
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );

      const skill = await loadSkill(nativeDir);
      expect(skill.is_verified).toBe(true);
      expect(skill.unverified).toBe(false);
      expect(skill.version).toBe('1.2.3');
      expect(skill.risk_class).toBe('wellness');
      expect(skill.tools).toEqual(['skill-docs']);
      expect(skill.forbidden).toEqual(['diagnose', 'prescribe', 'dose']);
    });

    it('CHALLENGE-MUT-10: fails closed when carefold.yaml.migrated contains malformed YAML', async () => {
      const corruptMigratedDir = path.join(ws, 'skills', 'corrupt-migrated-skill');
      await fs.mkdir(corruptMigratedDir, { recursive: true });
      await fs.writeFile(
        path.join(corruptMigratedDir, 'SKILL.md'),
        `---
name: corrupt-migrated
description: Valid frontmatter
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );
      await fs.writeFile(
        path.join(corruptMigratedDir, 'carefold.yaml.migrated'),
        ': : [ bad yaml syntax {'
      );

      await expect(loadSkill(corruptMigratedDir)).rejects.toThrow(ManifestValidationError);
      await expect(loadSkill(corruptMigratedDir)).rejects.toThrow(/Malformed carefold\.yaml\.migrated/i);
    });
  });

  // =========================================================================
  // 2. UNAUTHORIZED TOOLS FAIL-CLOSED PROBES (e.g. bash, exec, curl)
  // =========================================================================
  describe('Unauthorized Tools Fail-Closed Security Boundary', () => {
    it('CHALLENGE-TOOL-1: fails closed when metadata.tools declares bash', async () => {
      const rogueDir = path.join(ws, 'skills', 'rogue-bash-skill');
      await fs.mkdir(rogueDir, { recursive: true });
      await fs.writeFile(
        path.join(rogueDir, 'SKILL.md'),
        `---
name: rogue-bash-skill
description: Attempts to declare shell bash tool
metadata:
  tools:
    - bash
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );

      await expect(loadSkill(rogueDir)).rejects.toThrow(ToolValidationError);
      await expect(loadSkill(rogueDir)).rejects.toThrow(/Tool 'bash'.*not in Phase 0 closed registry/i);
    });

    it('CHALLENGE-TOOL-2: fails closed when metadata.tools declares curl and exec', async () => {
      const rogueDir = path.join(ws, 'skills', 'rogue-curl-skill');
      await fs.mkdir(rogueDir, { recursive: true });
      await fs.writeFile(
        path.join(rogueDir, 'SKILL.md'),
        `---
name: rogue-curl-skill
description: Attempts to exfiltrate data via curl and exec
metadata:
  tools:
    - curl
    - exec
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );

      await expect(loadSkill(rogueDir)).rejects.toThrow(ToolValidationError);
      await expect(loadSkill(rogueDir)).rejects.toThrow(/not in Phase 0 closed registry/i);
    });

    it('CHALLENGE-TOOL-3: fails closed when allowed-tools declares bash without metadata.tools', async () => {
      const rogueDir = path.join(ws, 'skills', 'rogue-allowed-tools-skill');
      await fs.mkdir(rogueDir, { recursive: true });
      await fs.writeFile(
        path.join(rogueDir, 'SKILL.md'),
        `---
name: rogue-allowed-tools-skill
description: Declares bash in allowed-tools
allowed-tools: bash
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );

      await expect(loadSkill(rogueDir)).rejects.toThrow(ToolValidationError);
      await expect(loadSkill(rogueDir)).rejects.toThrow(/Tool 'bash'.*not in Phase 0 closed registry/i);
    });

    it('CHALLENGE-TOOL-4: fails closed when carefold.yaml.migrated declares unauthorized tool rm', async () => {
      const rogueDir = path.join(ws, 'skills', 'rogue-rm-skill');
      await fs.mkdir(rogueDir, { recursive: true });
      await fs.writeFile(
        path.join(rogueDir, 'SKILL.md'),
        `---
name: rogue-rm-skill
description: Valid skill body
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
      );
      await fs.writeFile(
        path.join(rogueDir, 'carefold.yaml.migrated'),
        `
id: rogue-rm-skill
tools:
  - rm
`
      );

      await expect(loadSkill(rogueDir)).rejects.toThrow(ToolValidationError);
      await expect(loadSkill(rogueDir)).rejects.toThrow(/Tool 'rm'.*not in Phase 0 closed registry/i);
    });

    it('CHALLENGE-TOOL-5: loadAgent fails closed when agent.yaml declares unauthorized tool exec', async () => {
      const rogueAgentDir = path.join(ws, 'agents', 'rogue-exec-agent');
      await fs.mkdir(rogueAgentDir, { recursive: true });
      await fs.writeFile(
        path.join(rogueAgentDir, 'agent.yaml'),
        `
id: rogue-exec-agent
title: Rogue Exec Agent
version: 0.1.0
risk_class: wellness
skills: []
tools:
  - exec
persona: Rogue agent instructions
`
      );

      await expect(loadAgent(rogueAgentDir, path.join(ws, 'skills'))).rejects.toThrow(ToolValidationError);
      await expect(loadAgent(rogueAgentDir, path.join(ws, 'skills'))).rejects.toThrow(
        /Tool 'exec' is not in Phase 0 closed registry/i
      );
    });

    it('CHALLENGE-TOOL-6: executeTool refuses to execute bash, exec, curl, sh, eval, or process.exit', async () => {
      const context: ExecutionContext = {
        workspaceRoot: ws,
        skillsDir: path.join(ws, 'skills'),
        effectiveTools: ['attach-read'],
        config: {
          version: '0.1.0',
          model: { provider: 'ollama', baseUrl: '', model: 'llama3.2', apiKey: '' },
          audit: { enabled: false, store_bodies: false, log_path: '' },
          allow_clinical: false,
          telemetry: false
        }
      };

      const maliciousTools = ['bash', 'exec', 'curl', 'sh', 'eval', 'process.exit', 'child_process', 'spawn'];
      for (const toolName of maliciousTools) {
        // 1. getClosedTool returns undefined
        expect(getClosedTool(toolName)).toBeUndefined();

        // 2. executeTool returns error and success: false
        const res = await executeTool(toolName, { cmd: 'id' }, context);
        expect(res.success).toBe(false);
        expect(res.output).toBeNull();
        expect(res.error).toMatch(/not recognized or not available in the Phase 0 closed tool registry/i);
      }
    });

    it('CHALLENGE-TOOL-7: prototype pollution / property injection in executeTool fails closed', async () => {
      const context: ExecutionContext = {
        workspaceRoot: ws,
        skillsDir: path.join(ws, 'skills'),
        effectiveTools: [],
        config: {
          version: '0.1.0',
          model: { provider: 'ollama', baseUrl: '', model: 'llama3.2', apiKey: '' },
          audit: { enabled: false, store_bodies: false, log_path: '' },
          allow_clinical: false,
          telemetry: false
        }
      };

      const injectionKeys = ['__proto__', 'constructor', 'prototype', 'toString', 'valueOf'];
      for (const key of injectionKeys) {
        expect(getClosedTool(key)).toBeUndefined();
        const res = await executeTool(key, {}, context);
        expect(res.success).toBe(false);
        expect(res.error).toMatch(/not recognized or not available/i);
      }
    });

    it('CHALLENGE-TOOL-8: agent execution rejects model tool-call to bash and fails closed safely', async () => {
      // Mock model client that returns a malicious tool call to 'bash'
      const mockMaliciousModel = {
        getModelName: () => 'malicious-mock',
        checkHealth: async () => ({ reachable: true, model: 'malicious-mock' }),
        streamChat: async function* () {
          yield {
            choices: [
              {
                delta: {
                  tool_calls: [
                    {
                      index: 0,
                      id: 'call_bash_001',
                      type: 'function',
                      function: {
                        name: 'bash',
                        arguments: JSON.stringify({ command: 'rm -rf /' })
                      }
                    }
                  ]
                }
              }
            ]
          };
          yield {
            choices: [
              {
                delta: {
                  content: 'Attempted shell execution.'
                }
              }
            ]
          };
        }
      };

      const runOpts: RunOptions = {
        agentId: 'visit-steward',
        workspaceRoot: ws,
        prompt: 'Please check my appointment checklist',
        modelClient: mockMaliciousModel as any
      };

      const chunks: StreamChunk[] = [];
      let finalResult: RunResult | undefined;
      const gen = executeAgentRun(runOpts);
      let iter = await gen.next();
      while (!iter.done) {
        chunks.push(iter.value);
        iter = await gen.next();
      }
      finalResult = iter.value;

      // Tool call was received and denied
      const toolCallChunk = chunks.find(c => c.type === 'tool_call' && (c as any).tool === 'bash');
      const toolEndChunk = chunks.find(c => c.type === 'tool_end' && (c as any).tool === 'bash');

      expect(toolCallChunk).toBeDefined();
      expect((toolCallChunk as any).status).toBe('denied');
      expect((toolCallChunk as any).result.success).toBe(false);

      expect(toolEndChunk).toBeDefined();
      expect((toolEndChunk as any).allowed).toBe(false);

      // Final run completes without executing shell
      expect(finalResult).toBeDefined();
      expect(finalResult?.toolCalls.length).toBeGreaterThanOrEqual(1);
      expect(finalResult?.toolCalls.every(tc => tc.tool === 'bash' && tc.allowed === false && tc.success === false)).toBe(true);
      expect(finalResult?.toolCalls[0].error).toMatch(/undeclared tool/i);
    });
  });

  // =========================================================================
  // 3. MANDATORY INTENDED-USE DISCLAIMERS BOUNDARY
  // =========================================================================
  describe('Mandatory Intended-Use Disclaimers Boundary', () => {
    it('CHALLENGE-DISC-1: fails when "Not a clinician" is omitted', async () => {
      const dir = path.join(ws, 'skills', 'omit-clinician-skill');
      await fs.mkdir(dir, { recursive: true });
      await fs.writeFile(
        path.join(dir, 'SKILL.md'),
        `---
name: omit-clinician-skill
description: Omission test
metadata:
  tools: []
---
- If this is an emergency, contact local emergency services immediately.
- Do not change medication without the prescribing clinician.
`
      );

      await expect(loadSkill(dir)).rejects.toThrow(ManifestValidationError);
      await expect(loadSkill(dir)).rejects.toThrow(/Not a clinician and not emergency care/i);
    });

    it('CHALLENGE-DISC-2: fails when "Emergency services" is omitted', async () => {
      const dir = path.join(ws, 'skills', 'omit-emergency-skill');
      await fs.mkdir(dir, { recursive: true });
      await fs.writeFile(
        path.join(dir, 'SKILL.md'),
        `---
name: omit-emergency-skill
description: Omission test
metadata:
  tools: []
---
- Not a clinician and not emergency care.
- Do not change medication without the prescribing clinician.
`
      );

      await expect(loadSkill(dir)).rejects.toThrow(ManifestValidationError);
      await expect(loadSkill(dir)).rejects.toThrow(/contact local emergency services/i);
    });

    it('CHALLENGE-DISC-3: fails when "Do not change medication" is omitted', async () => {
      const dir = path.join(ws, 'skills', 'omit-med-skill');
      await fs.mkdir(dir, { recursive: true });
      await fs.writeFile(
        path.join(dir, 'SKILL.md'),
        `---
name: omit-med-skill
description: Omission test
metadata:
  tools: []
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services immediately.
`
      );

      await expect(loadSkill(dir)).rejects.toThrow(ManifestValidationError);
      await expect(loadSkill(dir)).rejects.toThrow(/Do not change medication without the prescribing clinician/i);
    });
  });

  // =========================================================================
  // 4. STANDALONE PACK VALIDATOR (scripts/validate-packs.mjs) TAMPERING PROBES
  // =========================================================================
  describe('Standalone Pack Validator Tampering & Boundary Resistance', () => {
    it('CHALLENGE-PACK-1: validate-packs detects tampered skill missing golden evals', async () => {
      // Create a tampered skill in skills/ directory temporarily
      const rootDir = path.resolve(__dirname, '../../..');
      const scriptPath = path.join(rootDir, 'scripts', 'validate-packs.mjs');
      const testSkillDir = path.join(rootDir, 'skills', '__adversarial_probe_skill');

      try {
        await fs.mkdir(testSkillDir, { recursive: true });
        await fs.writeFile(
          path.join(testSkillDir, 'SKILL.md'),
          `---
name: __adversarial_probe_skill
description: Test skill for pack validator stress
metadata:
  risk_class: wellness
  tools: []
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
        );
        await fs.writeFile(
          path.join(testSkillDir, 'carefold.yaml.migrated'),
          'id: __adversarial_probe_skill\n'
        );
        // Notice: evals/golden.jsonl is intentionally omitted!

        // Execute validate-packs.mjs
        let exitCode = 0;
        let stdout = '';
        let stderr = '';
        try {
          const res = await execFileAsync('node', [scriptPath], { cwd: rootDir });
          stdout = res.stdout;
          stderr = res.stderr;
        } catch (err: any) {
          exitCode = err.code || 1;
          stdout = err.stdout || '';
          stderr = err.stderr || '';
        }

        expect(exitCode).toBe(1);
        expect(stderr + stdout).toMatch(/evals\/golden\.jsonl exists/i);
        expect(stderr + stdout).toMatch(/PACKS VALIDATION FAILED/i);
      } finally {
        await fs.rm(testSkillDir, { recursive: true, force: true });
      }
    });

    it('CHALLENGE-PACK-2: validate-packs detects sub-threshold golden evals count (< 5)', async () => {
      const rootDir = path.resolve(__dirname, '../../..');
      const scriptPath = path.join(rootDir, 'scripts', 'validate-packs.mjs');
      const testSkillDir = path.join(rootDir, 'skills', '__adversarial_probe_evals');

      try {
        await fs.mkdir(path.join(testSkillDir, 'evals'), { recursive: true });
        await fs.writeFile(
          path.join(testSkillDir, 'SKILL.md'),
          `---
name: __adversarial_probe_evals
description: Test skill with too few evals
metadata:
  risk_class: wellness
  tools: []
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
        );
        await fs.writeFile(
          path.join(testSkillDir, 'carefold.yaml.migrated'),
          'id: __adversarial_probe_evals\n'
        );
        // Only 3 eval rows (requires >= 5)
        const goldenContent = [
          JSON.stringify({ id: '1', prompt: 'test', expect: 'allow' }),
          JSON.stringify({ id: '2', prompt: 'diagnose me', expect: 'refuse' }),
          JSON.stringify({ id: '3', prompt: 'prescribe me', expect: 'refuse' })
        ].join('\n');
        await fs.writeFile(path.join(testSkillDir, 'evals', 'golden.jsonl'), goldenContent);

        let exitCode = 0;
        let combined = '';
        try {
          const res = await execFileAsync('node', [scriptPath], { cwd: rootDir });
          combined = res.stdout + res.stderr;
        } catch (err: any) {
          exitCode = err.code || 1;
          combined = (err.stdout || '') + (err.stderr || '');
        }

        expect(exitCode).toBe(1);
        expect(combined).toMatch(/Golden evals count >= 5 \(found 3\)/i);
        expect(combined).toMatch(/PACKS VALIDATION FAILED/i);
      } finally {
        await fs.rm(testSkillDir, { recursive: true, force: true });
      }
    });

    it('CHALLENGE-PACK-3: validate-packs detects sub-threshold refusal cases (< 2)', async () => {
      const rootDir = path.resolve(__dirname, '../../..');
      const scriptPath = path.join(rootDir, 'scripts', 'validate-packs.mjs');
      const testSkillDir = path.join(rootDir, 'skills', '__adversarial_probe_refusal');

      try {
        await fs.mkdir(path.join(testSkillDir, 'evals'), { recursive: true });
        await fs.writeFile(
          path.join(testSkillDir, 'SKILL.md'),
          `---
name: __adversarial_probe_refusal
description: Test skill with only 1 refusal eval
metadata:
  risk_class: wellness
  tools: []
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
        );
        await fs.writeFile(
          path.join(testSkillDir, 'carefold.yaml.migrated'),
          'id: __adversarial_probe_refusal\n'
        );
        // 5 rows but only 1 refusal
        const goldenContent = [
          JSON.stringify({ id: '1', prompt: 'q1', expect: 'allow' }),
          JSON.stringify({ id: '2', prompt: 'q2', expect: 'allow' }),
          JSON.stringify({ id: '3', prompt: 'q3', expect: 'allow' }),
          JSON.stringify({ id: '4', prompt: 'q4', expect: 'allow' }),
          JSON.stringify({ id: '5', prompt: 'diagnose me', expect: 'refuse' })
        ].join('\n');
        await fs.writeFile(path.join(testSkillDir, 'evals', 'golden.jsonl'), goldenContent);

        let exitCode = 0;
        let combined = '';
        try {
          const res = await execFileAsync('node', [scriptPath], { cwd: rootDir });
          combined = res.stdout + res.stderr;
        } catch (err: any) {
          exitCode = err.code || 1;
          combined = (err.stdout || '') + (err.stderr || '');
        }

        expect(exitCode).toBe(1);
        expect(combined).toMatch(/Golden evals refuse cases >= 2 \(found 1\)/i);
        expect(combined).toMatch(/PACKS VALIDATION FAILED/i);
      } finally {
        await fs.rm(testSkillDir, { recursive: true, force: true });
      }
    });

    it('CHALLENGE-PACK-4: validate-packs detects malformed JSON in golden.jsonl', async () => {
      const rootDir = path.resolve(__dirname, '../../..');
      const scriptPath = path.join(rootDir, 'scripts', 'validate-packs.mjs');
      const testSkillDir = path.join(rootDir, 'skills', '__adversarial_probe_malformed');

      try {
        await fs.mkdir(path.join(testSkillDir, 'evals'), { recursive: true });
        await fs.writeFile(
          path.join(testSkillDir, 'SKILL.md'),
          `---
name: __adversarial_probe_malformed
description: Test skill with corrupt JSONL
metadata:
  risk_class: wellness
  tools: []
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
        );
        await fs.writeFile(
          path.join(testSkillDir, 'carefold.yaml.migrated'),
          'id: __adversarial_probe_malformed\n'
        );
        const goldenContent = [
          JSON.stringify({ id: '1', prompt: 'q1', expect: 'allow' }),
          'NOT A VALID JSON LINE',
          JSON.stringify({ id: '2', prompt: 'diagnose me', expect: 'refuse' })
        ].join('\n');
        await fs.writeFile(path.join(testSkillDir, 'evals', 'golden.jsonl'), goldenContent);

        let exitCode = 0;
        let combined = '';
        try {
          const res = await execFileAsync('node', [scriptPath], { cwd: rootDir });
          combined = res.stdout + res.stderr;
        } catch (err: any) {
          exitCode = err.code || 1;
          combined = (err.stdout || '') + (err.stderr || '');
        }

        expect(exitCode).toBe(1);
        expect(combined).toMatch(/Malformed JSON in golden\.jsonl/i);
        expect(combined).toMatch(/PACKS VALIDATION FAILED/i);
      } finally {
        await fs.rm(testSkillDir, { recursive: true, force: true });
      }
    });

    it('CHALLENGE-PACK-5: validate-packs detects missing manifest (no carefold.yaml and no metadata:)', async () => {
      const rootDir = path.resolve(__dirname, '../../..');
      const scriptPath = path.join(rootDir, 'scripts', 'validate-packs.mjs');
      const testSkillDir = path.join(rootDir, 'skills', '__adversarial_probe_no_manifest');

      try {
        await fs.mkdir(path.join(testSkillDir, 'evals'), { recursive: true });
        await fs.writeFile(
          path.join(testSkillDir, 'SKILL.md'),
          `---
name: __adversarial_probe_no_manifest
description: Skill missing carefold.yaml and metadata block
---
- Not a clinician and not emergency care.
- If this is an emergency, contact local emergency services.
- Do not change medication without the prescribing clinician.
`
        );
        // Golden evals present
        const goldenContent = [
          JSON.stringify({ id: '1', prompt: 'q1', expect: 'allow' }),
          JSON.stringify({ id: '2', prompt: 'q2', expect: 'allow' }),
          JSON.stringify({ id: '3', prompt: 'q3', expect: 'allow' }),
          JSON.stringify({ id: '4', prompt: 'diagnose me', expect: 'refuse' }),
          JSON.stringify({ id: '5', prompt: 'prescribe me', expect: 'refuse' })
        ].join('\n');
        await fs.writeFile(path.join(testSkillDir, 'evals', 'golden.jsonl'), goldenContent);

        let exitCode = 0;
        let combined = '';
        try {
          const res = await execFileAsync('node', [scriptPath], { cwd: rootDir });
          combined = res.stdout + res.stderr;
        } catch (err: any) {
          exitCode = err.code || 1;
          combined = (err.stdout || '') + (err.stderr || '');
        }

        expect(exitCode).toBe(1);
        expect(combined).toMatch(/manifest valid/i);
        expect(combined).toMatch(/PACKS VALIDATION FAILED/i);
      } finally {
        await fs.rm(testSkillDir, { recursive: true, force: true });
      }
    });
  });
});
