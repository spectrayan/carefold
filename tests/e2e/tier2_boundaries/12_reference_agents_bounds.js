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

export const name = 'F12-B: Reference Agents Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F12-B01',
      name: 'Agent loader raises ManifestValidationError when agent.yaml is missing',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'missing-yaml-agent');
          fs.mkdirSync(aDir, { recursive: true });

          const script = `
from carefold.loaders.agent_loader import load_agent, ManifestValidationError
try:
    load_agent('${aDir}', 'skills')
    assert False, "Should have failed on missing agent.yaml"
except ManifestValidationError as e:
    assert 'missing required agent.yaml' in str(e).lower()
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F12-B02',
      name: 'Agent loader raises ManifestValidationError when declared skill is missing from disk',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'broken-skill-agent');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
schema_version: "1.0"
id: "broken-skill-agent"
title: "Broken Agent"
persona: "Tester"
version: "0.1.0"
risk_class: "wellness"
tools: []
skills:
  - "nonexistent-skill-uuid"
`);

          const script = `
from carefold.loaders.agent_loader import load_agent, ManifestValidationError
try:
    load_agent('${aDir}', 'skills')
    assert False, "Should have failed on missing declared skill"
except ManifestValidationError as e:
    assert 'missing declared skill' in str(e).lower()
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F12-B03',
      name: 'Agent loader rejects tools outside Phase 0 closed tool registry',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'rogue-agent');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
schema_version: "1.0"
id: "rogue-agent"
title: "Rogue Agent"
persona: "Tester"
version: "0.1.0"
risk_class: "wellness"
tools:
  - "exec-bash-command"
skills: []
`);

          const script = `
from carefold.loaders.agent_loader import load_agent
from carefold.loaders.union import ToolValidationError
try:
    load_agent('${aDir}', 'skills')
    assert False, "Should have rejected unclosed tool"
except (ToolValidationError, Exception) as e:
    assert 'exec-bash-command' in str(e)
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F12-B04',
      name: 'Agent loader elevates agent risk_class to clinical_assist if any declared skill is clinical_assist',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const sDir = path.join(ws, 'skills', 'clinical-skill');
          fs.mkdirSync(sDir, { recursive: true });
          fs.writeFileSync(path.join(sDir, 'SKILL.md'), `---
name: clinical-skill
description: Clinical assist skill
---
# Skill
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
`);
          fs.writeFileSync(path.join(sDir, 'carefold.yaml'), `
schema_version: "1.0"
id: "clinical-skill"
name: "Clinical Skill"
version: "0.1.0"
risk_class: "clinical_assist"
tools: []
`);

          const aDir = path.join(ws, 'agents', 'elevated-agent');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
schema_version: "1.0"
id: "elevated-agent"
title: "Elevated Agent"
persona: "Tester"
version: "0.1.0"
risk_class: "wellness"
tools: []
skills:
  - "clinical-skill"
`);

          const script = `
from carefold.loaders.agent_loader import load_agent
from carefold.schemas.manifest import RiskClass
agent, tools, skills = load_agent('${aDir}', '${path.join(ws, 'skills')}')
assert agent.risk_class == RiskClass.CLINICAL_ASSIST
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F12-B05',
      name: 'Agent loader rejects invalid agent id syntax',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'bad_agent');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
schema_version: "1.0"
id: "Bad Agent With Spaces!"
title: "Invalid ID"
persona: "Tester"
version: "0.1.0"
risk_class: "wellness"
tools: []
skills: []
`);

          const script = `
from carefold.loaders.agent_loader import load_agent, ManifestValidationError
try:
    load_agent('${aDir}', 'skills')
    assert False, "Should have failed slug validation"
except ManifestValidationError as e:
    assert True
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
