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

import { runPython, assertEqual, assertTrue, assertContains } from '../helpers/utils.js';

export const name = 'F23-B: Offline Python Evals Suite Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F23-B01',
      name: 'evals runner handles filtering by non-existent agent gracefully with exit code 0',
      fn: () => {
        const res = runPython('evals/runner.py', ['--agent', 'nonexistent-agent-id']);
        assertEqual(res.status, 0, `Evals runner should handle non-matching filter: ${res.stderr}`);
        // Evaluates safety suite and completes
        assertContains(res.stdout, 'Passed:');
      }
    },
    {
      id: 'F23-B02',
      name: 'All golden test case datasets have strictly unique IDs and valid schema',
      fn: () => {
        const script = `
import json, glob
from pathlib import Path

seen_ids = set()
for fpath in glob.glob("evals/*.golden.jsonl") + glob.glob("agents/*/evals/*.jsonl"):
    with open(fpath) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            cid = item.get("id")
            assert cid, f"Missing id at {fpath}:{line_no}"
            assert cid not in seen_ids, f"Duplicate case id: {cid} in {fpath}"
            seen_ids.add(cid)
            assert item.get("prompt"), f"Empty prompt in {cid}"
            assert item.get("expect") in ["allow", "refuse"], f"Invalid expect in {cid}"
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F23-B03',
      name: 'All reference agents contain dedicated golden evaluation datasets',
      fn: () => {
        const script = `
from pathlib import Path

for agent_id in ['visit-steward', 'benefits-guide', 'habit-companion']:
    agent_eval_file = Path('agents') / agent_id / 'evals' / 'golden.jsonl'
    assert agent_eval_file.is_file(), f"Missing golden evals for {agent_id}"
    lines = [l for l in agent_eval_file.read_text().splitlines() if l.strip()]
    assert len(lines) >= 5, f"Insufficient evals for {agent_id}: {len(lines)}"
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F23-B04',
      name: 'evals runner operates without network even when OLLAMA_HOST is unreachable',
      fn: () => {
        const res = runPython('evals/runner.py', ['--agent', 'visit-steward'], {
          env: { OLLAMA_HOST: 'http://127.0.0.1:59999/broken' }
        });
        assertEqual(res.status, 0, `Evals failed under unreachable Ollama host: ${res.stderr}`);
        assertContains(res.stdout, '100% pass rate');
      }
    },
    {
      id: 'F23-B05',
      name: 'evals runner verbose mode displays individual test case IDs and statuses',
      fn: () => {
        const res = runPython('evals/runner.py', ['--verbose', '--agent', 'benefits-guide']);
        assertEqual(res.status, 0, `Verbose evals failed: ${res.stderr}`);
        assertContains(res.stdout, '[PASS]');
        assertContains(res.stdout, 'benefits-guide');
      }
    }
  ];

  return tests;
}
