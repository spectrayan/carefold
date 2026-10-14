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

import { runPython, runCli, assertEqual, assertTrue, assertContains } from '../helpers/utils.js';

export const name = 'F23: Offline Python Evals Suite';

export async function run() {
  const tests = [
    {
      id: 'F23-T01',
      name: 'evals/runner.py executes 100% offline without network connectivity or API keys',
      fn: () => {
        const res = runPython('evals/runner.py');
        assertEqual(res.status, 0, `evals runner failed: ${res.stderr}`);
        assertContains(res.stdout, 'All offline evaluations passed successfully with 100% pass rate!');
      }
    },
    {
      id: 'F23-T02',
      name: 'python -m evals.runner supports --agent flag to filter evaluation scope',
      fn: () => {
        const res = runPython('-m', ['evals.runner', '--agent', 'visit-steward']);
        assertEqual(res.status, 0, `evals runner with --agent failed: ${res.stderr}`);
        assertContains(res.stdout, 'Evaluating Agent: visit-steward');
      }
    },
    {
      id: 'F23-T03',
      name: 'evals/safety.golden.jsonl validates refusal boundaries across all safety categories',
      fn: () => {
        const script = `
import json
from pathlib import Path
from carefold.safety.classifier import check_safety_refusal

safety_file = Path('evals/safety.golden.jsonl')
assert safety_file.is_file()
with open(safety_file) as f:
    for line in f:
        line = line.strip()
        if line:
            c = json.loads(line)
            res = check_safety_refusal(c['prompt'])
            if c['expect'] == 'refuse':
                assert res.refused is True, f'Expected refusal on {c[\"id\"]}'
            else:
                assert res.refused is False, f'Expected allow on {c[\"id\"]}'
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F23-T04',
      name: 'carefold eval CLI command runs Python evaluation engine smoothly',
      fn: () => {
        const res = runCli(['eval', '--engine', 'python', '--python', 'backend/.venv/bin/python3', '--agent', 'visit-steward']);
        assertEqual(res.status, 0, `carefold eval failed: ${res.stderr}`);
      }
    },
    {
      id: 'F23-T05',
      name: 'evals runner verifies must_not negative constraints on generated responses',
      fn: () => {
        const res = runPython('-m', ['evals.runner', '--verbose']);
        assertEqual(res.status, 0);
        assertContains(res.stdout, 'Passed: 43');
        assertContains(res.stdout, 'Failed: 0');
      }
    }
  ];

  return tests;
}
