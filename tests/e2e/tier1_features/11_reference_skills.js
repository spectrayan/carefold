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

import { runPython, assertEqual, assertTrue } from '../helpers/utils.js';

export const name = 'F11: Reference Skills Validation';

export async function run() {
  const tests = [
    {
      id: 'F11-T01',
      name: 'Reference skill visit-prep adheres to contract (risk_class=wellness, tools=[attach-read, skill-docs])',
      fn: () => {
        const script = `
from carefold.loaders.skill_loader import load_skill
skill = load_skill('skills/visit-prep')
assert skill.id == 'visit-prep'
assert skill.risk_class.value == 'wellness'
assert sorted(skill.tools) == ['attach-read', 'skill-docs']
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F11-T02',
      name: 'Reference skill benefits-explainer adheres to contract (risk_class=admin, tools=[skill-docs])',
      fn: () => {
        const script = `
from carefold.loaders.skill_loader import load_skill
skill = load_skill('skills/benefits-explainer')
assert skill.id == 'benefits-explainer'
assert skill.risk_class.value == 'admin'
assert skill.tools == ['skill-docs']
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F11-T03',
      name: 'Reference skill habit-checkin adheres to contract (risk_class=wellness, tools=[workspace-note])',
      fn: () => {
        const script = `
from carefold.loaders.skill_loader import load_skill
skill = load_skill('skills/habit-checkin')
assert skill.id == 'habit-checkin'
assert skill.risk_class.value == 'wellness'
assert skill.tools == ['workspace-note']
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F11-T04',
      name: 'Reference skill _template provides developer starting point with valid structure',
      fn: () => {
        const script = `
from carefold.loaders.skill_loader import load_skill
skill = load_skill('skills/_template')
assert skill.id == '_template'
assert skill.risk_class.value == 'wellness'
assert isinstance(skill.tools, list)
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F11-T05',
      name: 'All reference skills include references/ documentation assets',
      fn: () => {
        const script = `
from pathlib import Path
for s in ['visit-prep', 'benefits-explainer']:
    ref_dir = Path('skills') / s / 'references'
    assert ref_dir.is_dir(), f'{s} missing references directory'
    files = list(ref_dir.glob('*.md'))
    assert len(files) >= 1, f'{s} missing reference markdown documents'
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
