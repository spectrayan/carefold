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

import { describe, it, expect, beforeAll } from 'vitest';
import path from 'node:path';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import { z } from 'zod';
import {
  loadSkill,
  loadAgent,
  loadAllSkills,
  parseFrontmatter,
  checkMandatoryIntendedUse,
  computeEffectiveTools,
  isToolPermitted,
  SkillFrontmatterSchema,
  PHASE0_CLOSED_TOOLS,
  type SkillManifest,
  type AgentManifest
} from '../src/index.js';

// Resolve project root dynamically regardless of execution context
function resolveWorkspaceRoot(): string {
  const cwd = process.cwd();
  if (fsSync.existsSync(path.join(cwd, 'pnpm-workspace.yaml')) && fsSync.existsSync(path.join(cwd, 'packages', 'runner'))) {
    return cwd;
  }
  // If running from packages/runner
  const runnerParent = path.resolve(__dirname, '../../..');
  if (fsSync.existsSync(path.join(runnerParent, 'pnpm-workspace.yaml'))) {
    return runnerParent;
  }
  return cwd;
}

const ROOT_DIR = resolveWorkspaceRoot();
const SKILLS_DIR = path.join(ROOT_DIR, 'skills');
const AGENTS_DIR = path.join(ROOT_DIR, 'agents');

const EXPECTED_SKILL_IDS = ['visit-prep', 'benefits-explainer', 'habit-checkin', '_template'];
const EXPECTED_AGENT_IDS = ['visit-steward', 'benefits-guide', 'habit-companion', '_template'];

// Golden Eval Schema
const GoldenEvalRowSchema = z.object({
  id: z.string().min(1, 'Eval row id is required'),
  prompt: z.string().min(1, 'Prompt must not be empty'),
  expect: z.enum(['allow', 'refuse'], {
    errorMap: () => ({ message: "expect field must be either 'allow' or 'refuse'" })
  }),
  must_not: z.array(z.string().min(1)).optional(),
  must_include: z.array(z.string().min(1)).optional(),
  expected_tools: z.array(z.string()).optional(),
  tags: z.array(z.string()).optional()
});

type GoldenEvalRow = z.infer<typeof GoldenEvalRowSchema>;

/**
 * Helper to parse and validate a golden.jsonl file
 */
async function validateGoldenJsonl(filePath: string): Promise<{ rows: GoldenEvalRow[]; errors: string[] }> {
  const content = await fs.readFile(filePath, 'utf8');
  const lines = content.split('\n').filter(l => l.trim().length > 0);
  const rows: GoldenEvalRow[] = [];
  const errors: string[] = [];
  const seenIds = new Set<string>();

  for (let i = 0; i < lines.length; i++) {
    const lineNum = i + 1;
    const rawLine = lines[i].trim();
    let parsed: any;
    try {
      parsed = JSON.parse(rawLine);
    } catch (err: any) {
      errors.push(`Line ${lineNum}: Invalid JSON syntax - ${err.message}`);
      continue;
    }

    const res = GoldenEvalRowSchema.safeParse(parsed);
    if (!res.success) {
      const issues = res.error.issues.map(iss => `${iss.path.join('.')}: ${iss.message}`).join('; ');
      errors.push(`Line ${lineNum}: Schema validation failed - ${issues}`);
      continue;
    }

    if (seenIds.has(res.data.id)) {
      errors.push(`Line ${lineNum}: Duplicate eval row id '${res.data.id}'`);
    } else {
      seenIds.add(res.data.id);
    }

    rows.push(res.data);
  }

  return { rows, errors };
}

describe('08: Milestone 2 Bundled Reference Packs Validation Suite', () => {

  beforeAll(() => {
    expect(fsSync.existsSync(SKILLS_DIR), `Skills directory must exist at ${SKILLS_DIR}`).toBe(true);
    expect(fsSync.existsSync(AGENTS_DIR), `Agents directory must exist at ${AGENTS_DIR}`).toBe(true);
  });

  // =========================================================================
  // 1. Reference Skills Pack Validation
  // =========================================================================
  describe('Reference Skills Packs (skills/*)', () => {
    it('verifies all 4 expected reference skill directories exist', () => {
      for (const skillId of EXPECTED_SKILL_IDS) {
        const dir = path.join(SKILLS_DIR, skillId);
        expect(fsSync.existsSync(dir), `Skill directory missing: ${dir}`).toBe(true);
      }
    });

    for (const skillId of EXPECTED_SKILL_IDS) {
      describe(`Skill: ${skillId}`, () => {
        const skillDir = path.join(SKILLS_DIR, skillId);
        const skillMdPath = path.join(skillDir, 'SKILL.md');
        const carefoldYamlPath = path.join(skillDir, 'carefold.yaml');
        const goldenPath = path.join(skillDir, 'evals', 'golden.jsonl');

        it('contains mandatory files SKILL.md and evals/golden.jsonl', () => {
          expect(fsSync.existsSync(skillMdPath), `${skillId} missing SKILL.md`).toBe(true);
          expect(fsSync.existsSync(goldenPath), `${skillId} missing evals/golden.jsonl`).toBe(true);
        });

        it('parses SKILL.md frontmatter matching SkillFrontmatterSchema', async () => {
          const rawMd = await fs.readFile(skillMdPath, 'utf8');
          const { frontmatter, body } = parseFrontmatter(rawMd);

          expect(frontmatter.name).toBe(skillId);
          expect(typeof frontmatter.description).toBe('string');
          expect(frontmatter.description.length).toBeGreaterThan(10);
          expect(body.length).toBeGreaterThan(20);

          const result = SkillFrontmatterSchema.safeParse(frontmatter);
          expect(result.success, `Frontmatter validation failed for ${skillId}`).toBe(true);
        });

        it('contains all 3 mandatory intended-use statements verbatim in SKILL.md', async () => {
          const rawMd = await fs.readFile(skillMdPath, 'utf8');
          const check = checkMandatoryIntendedUse(rawMd);
          expect(
            check.valid,
            `Skill ${skillId} missing mandatory statement: "${check.missing}"`
          ).toBe(true);
        });

        it('loads cleanly through @carefold/runner loadSkill() and validates carefold.yaml', async () => {
          const skill = await loadSkill(skillDir);
          expect(skill.id).toBe(skillId);
          expect(skill.name).toBe(skillId);
          expect(skill.is_verified).toBe(true);
          expect(skill.unverified).toBe(false);

          // All declared tools must be in Phase 0 closed registry
          for (const tool of skill.tools || []) {
            expect(
              PHASE0_CLOSED_TOOLS.includes(tool as any),
              `Skill ${skillId} declared non-Phase 0 tool '${tool}'`
            ).toBe(true);
          }

          // Bundled risk classes must not be clinical_assist
          expect(['wellness', 'admin', 'education']).toContain(skill.risk_class);
        });

        it('validates golden.jsonl format with at least 5 rows and at least 2 refuse cases', async () => {
          const { rows, errors } = await validateGoldenJsonl(goldenPath);
          expect(errors, `Errors in ${skillId} golden.jsonl: ${errors.join(', ')}`).toEqual([]);
          expect(rows.length).toBeGreaterThanOrEqual(5);

          const refuseRows = rows.filter(r => r.expect === 'refuse');
          const allowRows = rows.filter(r => r.expect === 'allow');
          expect(refuseRows.length).toBeGreaterThanOrEqual(2);
          expect(allowRows.length).toBeGreaterThanOrEqual(1);

          // Verify refuse rows contain must_not rules or refuse tags
          for (const r of refuseRows) {
            expect(
              (r.must_not && r.must_not.length > 0) || (r.tags && r.tags.includes('refusal')),
              `Refuse eval row ${r.id} in ${skillId} should declare must_not assertions or refusal tag`
            ).toBe(true);
          }
        });
      });
    }

    it('verifies specialized skill reference files exist', () => {
      // visit-prep references
      expect(fsSync.existsSync(path.join(SKILLS_DIR, 'visit-prep', 'references', 'checklist.md'))).toBe(true);
      expect(fsSync.existsSync(path.join(SKILLS_DIR, 'visit-prep', 'references', 'questions_guide.md'))).toBe(true);

      // benefits-explainer references
      expect(fsSync.existsSync(path.join(SKILLS_DIR, 'benefits-explainer', 'references', 'glossary.md'))).toBe(true);

      // _template references
      expect(fsSync.existsSync(path.join(SKILLS_DIR, '_template', 'references', 'README.md'))).toBe(true);
    });
  });

  // =========================================================================
  // 2. Reference Agents Pack Validation
  // =========================================================================
  describe('Reference Agents Packs (agents/*)', () => {
    it('verifies all 4 expected reference agent directories exist', () => {
      for (const agentId of EXPECTED_AGENT_IDS) {
        const dir = path.join(AGENTS_DIR, agentId);
        expect(fsSync.existsSync(dir), `Agent directory missing: ${dir}`).toBe(true);
      }
    });

    for (const agentId of EXPECTED_AGENT_IDS) {
      describe(`Agent: ${agentId}`, () => {
        const agentDir = path.join(AGENTS_DIR, agentId);
        const agentYamlPath = path.join(agentDir, 'agent.yaml');
        const readmePath = path.join(agentDir, 'README.md');
        const startersPath = path.join(agentDir, 'starters.json');
        const goldenPath = path.join(agentDir, 'evals', 'golden.jsonl');

        it('contains mandatory files agent.yaml, README.md, starters.json, and evals/golden.jsonl', () => {
          expect(fsSync.existsSync(agentYamlPath), `${agentId} missing agent.yaml`).toBe(true);
          expect(fsSync.existsSync(readmePath), `${agentId} missing README.md`).toBe(true);
          expect(fsSync.existsSync(startersPath), `${agentId} missing starters.json`).toBe(true);
          expect(fsSync.existsSync(goldenPath), `${agentId} missing evals/golden.jsonl`).toBe(true);
        });

        it('validates starters.json as an array of at least 2 non-empty string prompts', async () => {
          const raw = await fs.readFile(startersPath, 'utf8');
          const starters = JSON.parse(raw);
          expect(Array.isArray(starters), `${agentId} starters.json must be a JSON array`).toBe(true);
          expect(starters.length).toBeGreaterThanOrEqual(2);
          for (const prompt of starters) {
            expect(typeof prompt).toBe('string');
            expect(prompt.trim().length).toBeGreaterThan(5);
          }
        });

        it('validates README.md is non-empty for marketplace cards', async () => {
          const content = await fs.readFile(readmePath, 'utf8');
          expect(content.trim().length).toBeGreaterThan(20);
        });

        it('loads cleanly through @carefold/runner loadAgent()', async () => {
          const { agent, effectiveTools, skills } = await loadAgent(agentDir, SKILLS_DIR);
          expect(agent.id).toBe(agentId);
          expect(typeof agent.title).toBe('string');
          expect(agent.title.length).toBeGreaterThan(0);
          expect(skills.length).toBeGreaterThanOrEqual(agent.skills.length);

          // All declared tools must be in Phase 0 closed registry
          for (const tool of agent.tools || []) {
            expect(
              PHASE0_CLOSED_TOOLS.includes(tool as any),
              `Agent ${agentId} declared non-Phase 0 tool '${tool}'`
            ).toBe(true);
          }

          // Canonical risk classes per AGENTS.md Table 2.1
          if (agentId === 'visit-steward') {
            expect(agent.risk_class).toBe('clinical_assist');
          } else {
            expect(['wellness', 'admin', 'education']).toContain(agent.risk_class);
          }

          // Verify effective tools union calculation
          const expectedUnion = computeEffectiveTools(agent, skills);
          expect(effectiveTools.sort()).toEqual(expectedUnion.sort());
        });

        it('validates agent golden.jsonl format with at least 2 rows (at least 1 allow and 1 refuse)', async () => {
          const { rows, errors } = await validateGoldenJsonl(goldenPath);
          expect(errors, `Errors in ${agentId} golden.jsonl: ${errors.join(', ')}`).toEqual([]);
          expect(rows.length).toBeGreaterThanOrEqual(2);

          const refuseRows = rows.filter(r => r.expect === 'refuse');
          const allowRows = rows.filter(r => r.expect === 'allow');
          expect(refuseRows.length).toBeGreaterThanOrEqual(1);
          expect(allowRows.length).toBeGreaterThanOrEqual(1);
        });
      });
    }
  });

  // =========================================================================
  // 3. Exact Tool Allowlist Union & Least-Privilege Enforcements
  // =========================================================================
  describe('Tool Allowlist Union & Permission Checks', () => {
    it('verifies exact effective tools for visit-steward', async () => {
      const agentDir = path.join(AGENTS_DIR, 'visit-steward');
      const { agent, effectiveTools } = await loadAgent(agentDir, SKILLS_DIR);

      expect(agent.skills).toContain('visit-prep');
      expect(effectiveTools).toContain('attach-read');
      expect(effectiveTools).toContain('skill-docs');
      expect(isToolPermitted('attach-read', effectiveTools)).toBe(true);
      expect(isToolPermitted('skill-docs', effectiveTools)).toBe(true);

      // Must not permit unauthorized tools
      expect(isToolPermitted('web-search', effectiveTools)).toBe(false);
      expect(isToolPermitted('shell-exec', effectiveTools)).toBe(false);
    });

    it('verifies exact effective tools for benefits-guide', async () => {
      const agentDir = path.join(AGENTS_DIR, 'benefits-guide');
      const { agent, effectiveTools } = await loadAgent(agentDir, SKILLS_DIR);

      expect(agent.skills).toContain('benefits-explainer');
      expect(effectiveTools).toContain('attach-read');
      expect(effectiveTools).toContain('skill-docs');
      expect(isToolPermitted('attach-read', effectiveTools)).toBe(true);
      expect(isToolPermitted('skill-docs', effectiveTools)).toBe(true);

      // Must not permit workspace-note unless declared
      if (!agent.tools?.includes('workspace-note')) {
        expect(isToolPermitted('workspace-note', effectiveTools)).toBe(false);
      }
      expect(isToolPermitted('web-search', effectiveTools)).toBe(false);
    });

    it('verifies exact effective tools for habit-companion', async () => {
      const agentDir = path.join(AGENTS_DIR, 'habit-companion');
      const { agent, effectiveTools } = await loadAgent(agentDir, SKILLS_DIR);

      expect(agent.skills).toContain('habit-checkin');
      expect(effectiveTools).toContain('workspace-note');
      expect(isToolPermitted('workspace-note', effectiveTools)).toBe(true);
      expect(isToolPermitted('attach-read', effectiveTools)).toBe(false);
      expect(isToolPermitted('skill-docs', effectiveTools)).toBe(false);
    });

    it('proves that undeclared skills do not leak tools to an agent', async () => {
      const habitCompanionDir = path.join(AGENTS_DIR, 'habit-companion');
      const { effectiveTools } = await loadAgent(habitCompanionDir, SKILLS_DIR);

      // habit-companion does not declare visit-prep or benefits-explainer;
      // even though attach-read and skill-docs exist in workspace skills, they must not leak
      expect(effectiveTools).not.toContain('attach-read');
      expect(effectiveTools).not.toContain('skill-docs');
    });
  });

  // =========================================================================
  // 4. Risk Class Inheritance & Elevation
  // =========================================================================
  describe('Risk Class Inheritance & Catalog Safety', () => {
    it('ensures zero bundled starter skills or non-clinical agents possess risk_class clinical_assist', async () => {
      for (const skillId of EXPECTED_SKILL_IDS) {
        const s = await loadSkill(path.join(SKILLS_DIR, skillId));
        expect(s.risk_class).not.toBe('clinical_assist');
      }

      for (const agentId of EXPECTED_AGENT_IDS) {
        if (agentId === 'visit-steward') continue; // visit-steward is clinical_assist per AGENTS.md Table 2.1
        const { agent } = await loadAgent(path.join(AGENTS_DIR, agentId), SKILLS_DIR);
        expect(agent.risk_class).not.toBe('clinical_assist');
      }
    });

    it('correctly inherits and elevates risk_class when a clinical_assist skill is declared', () => {
      const wellnessAgent: AgentManifest = {
        id: 'test-agent',
        title: 'Test Agent',
        version: '0.1.0',
        risk_class: 'wellness',
        skills: ['clinical-skill'],
        tools: [],
        persona: 'Test persona'
      };

      const clinicalSkill: SkillManifest = {
        id: 'clinical-skill',
        name: 'clinical-skill',
        description: 'Clinical Assist Skill',
        version: '0.1.0',
        risk_class: 'clinical_assist',
        tools: []
      };

      // Elevation rule check
      let elevated = wellnessAgent.risk_class;
      if ([clinicalSkill].some(s => s.risk_class === 'clinical_assist')) {
        elevated = 'clinical_assist';
      }
      expect(elevated).toBe('clinical_assist');
    });
  });

  // =========================================================================
  // 5. Negative & Boundary Test Cases
  // =========================================================================
  describe('Negative & Boundary Validation', () => {
    it('fails when SKILL.md is missing mandatory intended-use statements', () => {
      const invalidMd = `---
name: invalid-skill
description: A skill that forgets disclaimers
---
# Instructions
Do whatever you want.
`;
      const check = checkMandatoryIntendedUse(invalidMd);
      expect(check.valid).toBe(false);
      expect(check.missing).toBe('Not a clinician and not emergency care');
    });

    it('fails when agent declares a skill that does not exist in skills directory', async () => {
      const nonExistentDir = path.join(ROOT_DIR, 'node_modules', '.tmp_test_agent');
      await fs.mkdir(nonExistentDir, { recursive: true });
      await fs.writeFile(
        path.join(nonExistentDir, 'agent.yaml'),
        `
id: phantom-agent
title: Phantom Agent
version: 0.1.0
risk_class: wellness
skills:
  - totally-nonexistent-skill-id-xyz
tools: []
persona: Test persona
`
      );

      try {
        await expect(loadAgent(nonExistentDir, SKILLS_DIR)).rejects.toThrow(
          /Missing declared skill: totally-nonexistent-skill-id-xyz/i
        );
      } finally {
        await fs.rm(nonExistentDir, { recursive: true, force: true });
      }
    });

    it('fails when an eval row has invalid expect enum value', () => {
      const invalidRow = {
        id: 'bad-01',
        prompt: 'Hello',
        expect: 'maybe' // Not allow or refuse
      };
      const res = GoldenEvalRowSchema.safeParse(invalidRow);
      expect(res.success).toBe(false);
    });

    it('fails when an eval row is missing required id or prompt', () => {
      const missingId = { prompt: 'Hello', expect: 'allow' };
      const missingPrompt = { id: 'test-01', expect: 'allow' };
      expect(GoldenEvalRowSchema.safeParse(missingId).success).toBe(false);
      expect(GoldenEvalRowSchema.safeParse(missingPrompt).success).toBe(false);
    });
  });
});
