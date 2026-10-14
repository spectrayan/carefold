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
import { runPython, createTempWorkspace, removeTempWorkspace, assertEqual, assertTrue } from '../helpers/utils.js';

export const name = 'F11-B: Reference Skills Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F11-B01',
      name: 'Skill loader raises ManifestValidationError for non-existent skill path',
      fn: () => {
        const script = `
from carefold.loaders.skill_loader import load_skill, ManifestValidationError
try:
    load_skill('skills/completely-nonexistent-skill-dir')
    assert False, "Should have raised exception"
except ManifestValidationError as e:
    assert 'not found' in str(e).lower()
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F11-B02',
      name: 'Skill loader raises ManifestValidationError when SKILL.md is missing',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'no-md-skill');
          fs.mkdirSync(sDir, { recursive: true });

          const script = `
from carefold.loaders.skill_loader import load_skill, ManifestValidationError
try:
    load_skill('${sDir}')
    assert False, "Should have raised ManifestValidationError"
except ManifestValidationError as e:
    assert 'missing required skill.md' in str(e).lower()
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F11-B03',
      name: 'Skill loader enforces 3 mandatory intended-use statements in SKILL.md',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'bad-use-skill');
          fs.mkdirSync(sDir, { recursive: true });
          fs.writeFileSync(path.join(sDir, 'SKILL.md'), `---
name: bad-use-skill
description: Missing disclosures
---
# Bad Use Skill
Some content here without safety lines.
`);

          const script = `
from carefold.loaders.skill_loader import load_skill, ManifestValidationError
try:
    load_skill('${sDir}')
    assert False, "Should have failed mandatory disclosure check"
except ManifestValidationError as e:
    assert 'mandatory intended-use' in str(e).lower()
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F11-B04',
      name: 'Skill loader rejects unsupported risk_class values in carefold.yaml',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'bad-risk-skill');
          fs.mkdirSync(sDir, { recursive: true });
          fs.writeFileSync(path.join(sDir, 'SKILL.md'), `---
name: bad-risk-skill
description: Bad risk test
---
# Skill
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
`);
          fs.writeFileSync(path.join(sDir, 'carefold.yaml'), `
schema_version: "1.0"
id: "bad-risk-skill"
name: "Bad Risk"
version: "0.1.0"
risk_class: "critical-diagnostic"
tools: []
`);

          const script = `
from carefold.loaders.skill_loader import load_skill, ManifestValidationError
try:
    load_skill('${sDir}')
    assert False, "Should have rejected invalid risk_class"
except ManifestValidationError as e:
    assert 'invalid carefold.yaml' in str(e).lower()
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F11-B05',
      name: 'Skill loader rejects tools outside Phase 0 closed tool registry in carefold.yaml',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'rogue-tool-skill');
          fs.mkdirSync(sDir, { recursive: true });
          fs.writeFileSync(path.join(sDir, 'SKILL.md'), `---
name: rogue-tool-skill
description: Rogue tool test
---
# Skill
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
`);
          fs.writeFileSync(path.join(sDir, 'carefold.yaml'), `
schema_version: "1.0"
id: "rogue-tool-skill"
name: "Rogue Tool"
version: "0.1.0"
risk_class: "wellness"
tools:
  - "bash-execute"
`);

          const script = `
from carefold.loaders.skill_loader import load_skill
from carefold.loaders.union import ToolValidationError
try:
    load_skill('${sDir}')
    assert False, "Should have rejected unclosed tool"
except (ToolValidationError, Exception) as e:
    assert 'bash-execute' in str(e)
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    }
  ];

  return tests;
}
