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

export const name = 'F02: Agent Manifest Schema & Load';

export async function run() {
  const tests = [
    {
      id: 'F02-T01',
      name: 'Agent manifest validates required fields (id, title, version, risk_class, persona)',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent
from pathlib import Path
agent, tools, skills = load_agent('agents/visit-steward', 'skills')
assert agent.id == 'visit-steward'
assert agent.version == '0.1.0'
assert agent.risk_class.value == 'wellness'
assert agent.persona is not None
if isinstance(agent.persona, str):
    assert len(agent.persona.strip()) > 0
else:
    assert agent.persona.role != ''
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F02-T02',
      name: 'Agent manifest resolves declared skills list accurately',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent
agent, tools, skills = load_agent('agents/visit-steward', 'skills')
skill_ids = [s.id for s in skills]
assert 'visit-prep' in skill_ids
assert len(skills) >= 1
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F02-T03',
      name: 'Agent manifest parses model configuration when present',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent
agent, tools, skills = load_agent('agents/visit-steward', 'skills')
assert hasattr(agent, 'model')
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F02-T04',
      name: 'load_all_agents enumerates all installed agent manifests',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_all_agents
agents = load_all_agents('agents', 'skills')
ids = [a.id for a in agents]
assert 'visit-steward' in ids
assert 'benefits-guide' in ids
assert 'habit-companion' in ids
assert '_template' in ids
assert len(agents) == 4
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F02-T05',
      name: 'Agent manifest loads starters chips from starters.json if present',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent_starters
starters = load_agent_starters('agents/visit-steward')
assert isinstance(starters, list)
assert len(starters) >= 1
assert any('question' in s.lower() for s in starters)
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
