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

export const name = 'F07: Closed Tool skill-docs';

export async function run() {
  const tests = [
    {
      id: 'F07-T01',
      name: 'skill-docs reads documentation file inside skill references/',
      fn: () => {
        const script = `
import asyncio
from pathlib import Path
from carefold.tools.skill_docs import skill_docs_tool

async def main():
    agent = type('Agent', (), {'id': 'visit-steward', 'skills': ['visit-prep']})()
    skill = type('Skill', (), {'id': 'visit-prep'})()
    ctx = type('Ctx', (), {
        'workspace_root': Path('.').resolve(),
        'skills_dir': Path('skills').resolve(),
        'agent': agent,
        'effective_tools': ['skill-docs'],
        'skills': [skill]
    })()
    res = await skill_docs_tool({'skill_id': 'visit-prep', 'doc': 'questions_guide.md'}, ctx)
    assert res.success is True
    assert 'Questions Guide' in res.output['content'] or len(res.output['content']) > 20

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F07-T02',
      name: 'skill-docs returns structured metadata (skill_id, doc, path, content)',
      fn: () => {
        const script = `
import asyncio
from pathlib import Path
from carefold.tools.skill_docs import skill_docs_tool

async def main():
    agent = type('Agent', (), {'id': 'benefits-guide', 'skills': ['benefits-explainer']})()
    skill = type('Skill', (), {'id': 'benefits-explainer'})()
    ctx = type('Ctx', (), {
        'workspace_root': Path('.').resolve(),
        'skills_dir': Path('skills').resolve(),
        'agent': agent,
        'effective_tools': ['skill-docs'],
        'skills': [skill]
    })()
    res = await skill_docs_tool({'skill_id': 'benefits-explainer', 'doc': 'glossary.md'}, ctx)
    assert res.success is True
    assert res.output['skill_id'] == 'benefits-explainer'
    assert res.output['doc'] == 'glossary.md'
    assert 'content' in res.output

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F07-T03',
      name: 'skill-docs enforces declared skill authorization restriction',
      fn: () => {
        const script = `
import asyncio
from pathlib import Path
from carefold.tools.skill_docs import skill_docs_tool

async def main():
    agent = type('Agent', (), {'id': 'visit-steward', 'skills': ['visit-prep']})()
    skill = type('Skill', (), {'id': 'visit-prep'})()
    ctx = type('Ctx', (), {
        'workspace_root': Path('.').resolve(),
        'skills_dir': Path('skills').resolve(),
        'agent': agent,
        'effective_tools': ['skill-docs'],
        'skills': [skill]
    })()
    # benefits-explainer is undeclared on visit-steward
    res = await skill_docs_tool({'skill_id': 'benefits-explainer', 'doc': 'glossary.md'}, ctx)
    assert res.success is False
    assert 'undeclared' in res.error.lower() or 'not declared' in res.error.lower()

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F07-T04',
      name: 'skill-docs returns error when requested doc does not exist',
      fn: () => {
        const script = `
import asyncio
from pathlib import Path
from carefold.tools.skill_docs import skill_docs_tool

async def main():
    agent = type('Agent', (), {'id': 'visit-steward', 'skills': ['visit-prep']})()
    skill = type('Skill', (), {'id': 'visit-prep'})()
    ctx = type('Ctx', (), {
        'workspace_root': Path('.').resolve(),
        'skills_dir': Path('skills').resolve(),
        'agent': agent,
        'effective_tools': ['skill-docs'],
        'skills': [skill]
    })()
    res = await skill_docs_tool({'skill_id': 'visit-prep', 'doc': 'missing.md'}, ctx)
    assert res.success is False
    assert 'not found' in res.error.lower()

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F07-T05',
      name: 'skill-docs requires valid agent execution context',
      fn: () => {
        const script = `
import asyncio
from carefold.tools.skill_docs import skill_docs_tool

async def main():
    res = await skill_docs_tool({'skill_id': 'visit-prep', 'doc': 'checklist.md'}, None)
    assert res.success is False
    assert 'context' in res.error.lower()

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
