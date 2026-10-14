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

export const name = 'F03-B: Skill Manifest Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F03-B01',
      name: 'Skill loader rejects frontmatter missing required intended-use statement',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'skills', 'no-intended-use');
          fs.mkdirSync(sDir, { recursive: true });
          fs.writeFileSync(path.join(sDir, 'SKILL.md'), `---
id: no-intended-use
name: No Intended Use
version: 0.1.0
risk_class: wellness
---
# Missing Mandatory Statements
`);
          const script = `
from carefold.loaders.skill_loader import load_skill, ManifestValidationError
try:
    load_skill('${sDir}')
    assert False, 'Expected ManifestValidationError'
except ManifestValidationError:
    pass
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F03-B02',
      name: 'Skill loader rejects invalid skill id slug syntax',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'skills', 'bad@id!');
          fs.mkdirSync(sDir, { recursive: true });
          fs.writeFileSync(path.join(sDir, 'SKILL.md'), `---
id: "bad@id!"
name: Bad ID
version: 0.1.0
risk_class: wellness
---
This skill is intended for testing.
`);
          const script = `
from carefold.loaders.skill_loader import load_skill, ManifestValidationError
try:
    load_skill('${sDir}')
    assert False, 'Expected ManifestValidationError'
except ManifestValidationError:
    pass
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F03-B03',
      name: 'Skill loader rejects malformed YAML in SKILL.md frontmatter',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'skills', 'bad-fm');
          fs.mkdirSync(sDir, { recursive: true });
          fs.writeFileSync(path.join(sDir, 'SKILL.md'), `---
id: bad-fm
[unclosed array
---
Body
`);
          const script = `
from carefold.loaders.skill_loader import load_skill, ManifestValidationError
try:
    load_skill('${sDir}')
    assert False, 'Expected ManifestValidationError'
except ManifestValidationError:
    pass
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F03-B04',
      name: 'Skill loader rejects skill directory missing both SKILL.md and carefold.yaml',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'skills', 'empty-skill');
          fs.mkdirSync(sDir, { recursive: true });
          const script = `
from carefold.loaders.skill_loader import load_skill, ManifestValidationError
try:
    load_skill('${sDir}')
    assert False, 'Expected ManifestValidationError'
except ManifestValidationError:
    pass
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F03-B05',
      name: 'Skill loader handles carefold.yaml fallback manifest when SKILL.md has no frontmatter',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'skills', 'yaml-skill');
          fs.mkdirSync(sDir, { recursive: true });
          fs.writeFileSync(path.join(sDir, 'carefold.yaml'), `
id: yaml-skill
name: YAML Skill
version: 0.1.0
risk_class: wellness
`);
          fs.writeFileSync(path.join(sDir, 'SKILL.md'), `
# Instructions
This skill is intended for testing.
`);
          const script = `
from carefold.loaders.skill_loader import load_skill
skill = load_skill('${sDir}')
assert skill.id == 'yaml-skill'
assert skill.risk_class.value == 'wellness'
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
