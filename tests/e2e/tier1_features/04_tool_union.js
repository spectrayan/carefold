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

export const name = 'F04: Tool Allowlist Union Engine';

export async function run() {
  const tests = [
    {
      id: 'F04-T01',
      name: 'Union engine computes unique union of agent tools and skill tools',
      fn: () => {
        const script = `
from carefold.loaders.union import compute_effective_tools
res = compute_effective_tools(['workspace-note'], [['attach-read'], ['skill-docs']])
assert sorted(res) == ['attach-read', 'skill-docs', 'workspace-note']
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F04-T02',
      name: 'Union engine deduplicates tools declared in both agent and skill',
      fn: () => {
        const script = `
from carefold.loaders.union import compute_effective_tools
res = compute_effective_tools(['attach-read', 'workspace-note'], [['attach-read']])
assert len(res) == 2
assert sorted(res) == ['attach-read', 'workspace-note']
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F04-T03',
      name: 'Union engine filters tools to closed Phase 0 registry (attach-read, workspace-note, skill-docs)',
      fn: () => {
        const script = `
from carefold.loaders.union import validate_tools_in_phase0
validate_tools_in_phase0(['attach-read', 'workspace-note', 'skill-docs'])
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F04-T04',
      name: 'Union engine raises ToolValidationError for tools outside Phase 0 registry',
      fn: () => {
        const script = `
from carefold.loaders.union import validate_tools_in_phase0, ToolValidationError
try:
    validate_tools_in_phase0(['attach-read', 'unauthorized-tool'])
    assert False, 'Expected ToolValidationError'
except ToolValidationError:
    pass
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F04-T05',
      name: 'visit-steward resolves exact effective tools union [attach-read, workspace-note, skill-docs]',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent
agent, tools, skills = load_agent('agents/visit-steward', 'skills')
assert sorted(tools) == ['attach-read', 'skill-docs', 'workspace-note']
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
