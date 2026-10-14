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

export const name = 'F12: Reference Agents Validation';

export async function run() {
  const tests = [
    {
      id: 'F12-T01',
      name: 'Reference agent visit-steward adheres to contract (risk=wellness, skills=[visit-prep])',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent
agent, tools, skills = load_agent('agents/visit-steward', 'skills')
assert agent.id == 'visit-steward'
assert agent.risk_class.value == 'wellness'
assert agent.skills == ['visit-prep']
assert 'attach-read' in tools
assert 'workspace-note' in tools
assert 'skill-docs' in tools
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F12-T02',
      name: 'Reference agent benefits-guide adheres to contract (risk=admin, skills=[benefits-explainer])',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent
agent, tools, skills = load_agent('agents/benefits-guide', 'skills')
assert agent.id == 'benefits-guide'
assert agent.risk_class.value == 'admin'
assert agent.skills == ['benefits-explainer']
assert 'skill-docs' in tools
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F12-T03',
      name: 'Reference agent habit-companion adheres to contract (risk=wellness, skills=[habit-checkin])',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent
agent, tools, skills = load_agent('agents/habit-companion', 'skills')
assert agent.id == 'habit-companion'
assert agent.risk_class.value == 'wellness'
assert agent.skills == ['habit-checkin']
assert 'workspace-note' in tools
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F12-T04',
      name: 'Reference agent _template provides developer baseline with valid configuration',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent
agent, tools, skills = load_agent('agents/_template', 'skills')
assert agent.id == '_template'
assert agent.risk_class.value == 'wellness'
assert agent.skills == ['_template']
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F12-T05',
      name: 'All reference agents contain valid README.md documentation files',
      fn: () => {
        const script = `
from pathlib import Path
for a in ['visit-steward', 'benefits-guide', 'habit-companion', '_template']:
    readme = Path('agents') / a / 'README.md'
    assert readme.is_file(), f'{a} missing README.md'
    content = readme.read_text(encoding='utf-8')
    assert len(content) > 50
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
