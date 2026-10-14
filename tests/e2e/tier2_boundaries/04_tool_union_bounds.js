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

export const name = 'F04-B: Tool Allowlist Union Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F04-B01',
      name: 'Union engine handles empty agent tools and empty skill tools cleanly',
      fn: () => {
        const script = `
from carefold.loaders.union import compute_effective_tools
res = compute_effective_tools([], [])
assert res == []
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F04-B02',
      name: 'Union engine handles None tools inputs safely without throwing TypeError',
      fn: () => {
        const script = `
from carefold.loaders.union import compute_effective_tools
res = compute_effective_tools(None, None)
assert res == []
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F04-B03',
      name: 'Union engine preserves deterministic ordering across multiple runs',
      fn: () => {
        const script = `
from carefold.loaders.union import compute_effective_tools
r1 = compute_effective_tools(['workspace-note'], [['skill-docs'], ['attach-read']])
r2 = compute_effective_tools(['workspace-note'], [['skill-docs'], ['attach-read']])
assert r1 == r2
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F04-B04',
      name: 'validate_tools_in_phase0 rejects shell and file-write tools outside closed registry',
      fn: () => {
        const script = `
from carefold.loaders.union import validate_tools_in_phase0, ToolValidationError
for dangerous_tool in ['bash', 'sh', 'exec', 'file-write', 'network-fetch', 'sql']:
    try:
        validate_tools_in_phase0([dangerous_tool])
        assert False, f'Failed to reject {dangerous_tool}'
    except ToolValidationError:
        pass
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F04-B05',
      name: 'Union engine ignores duplicate tool declarations across multiple skills',
      fn: () => {
        const script = `
from carefold.loaders.union import compute_effective_tools
res = compute_effective_tools(
    ['attach-read'],
    [['attach-read', 'skill-docs'], ['skill-docs'], ['attach-read']]
)
assert len(res) == 2
assert set(res) == {'attach-read', 'skill-docs'}
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
