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

export const name = 'F02-B: Agent Manifest Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F02-B01',
      name: 'Agent manifest rejects malformed YAML syntax',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'agents', 'bad-yaml');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), ': : invalid : : [');
          const script = `
from carefold.loaders.agent_loader import load_agent
from carefold.loaders.skill_loader import ManifestValidationError
try:
    load_agent('${aDir}', 'skills')
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
      id: 'F02-B02',
      name: 'Agent manifest rejects invalid risk_class value',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'agents', 'bad-risk');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
id: bad-risk
title: Bad Risk
version: 0.1.0
risk_class: illegal_risk
persona:
  role: role
  tone: tone
  instructions: instructions
skills: []
`);
          const script = `
from carefold.loaders.agent_loader import load_agent
from carefold.loaders.skill_loader import ManifestValidationError
try:
    load_agent('${aDir}', 'skills')
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
      id: 'F02-B03',
      name: 'Agent manifest rejects directory missing agent.yaml',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'agents', 'empty-agent');
          fs.mkdirSync(aDir, { recursive: true });
          const script = `
from carefold.loaders.agent_loader import load_agent
from carefold.loaders.skill_loader import ManifestValidationError
try:
    load_agent('${aDir}', 'skills')
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
      id: 'F02-B04',
      name: 'Agent manifest rejects missing declared skill reference',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'agents', 'missing-skill-agent');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
id: missing-skill-agent
title: Missing Skill
version: 0.1.0
risk_class: wellness
persona:
  role: role
  tone: tone
  instructions: instructions
skills:
  - nonexistent-skill-12345
`);
          const script = `
from carefold.loaders.agent_loader import load_agent
from carefold.loaders.skill_loader import ManifestValidationError
try:
    load_agent('${aDir}', 'skills')
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
      id: 'F02-B05',
      name: 'Agent manifest rejects manifest ID mismatch with directory name',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'agents', 'dir-name');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
id: different-id
title: Mismatch
version: 0.1.0
risk_class: wellness
persona:
  role: role
  tone: tone
  instructions: instructions
skills: []
`);
          const script = `
from carefold.loaders.agent_loader import load_agent
from carefold.loaders.skill_loader import ManifestValidationError
try:
    load_agent('${aDir}', 'skills')
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
    }
  ];

  return tests;
}
