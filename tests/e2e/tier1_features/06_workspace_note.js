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

export const name = 'F06: Closed Tool workspace-note';

export async function run() {
  const tests = [
    {
      id: 'F06-T01',
      name: 'workspace-note writes markdown file to workspace/notes/<title>.md',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await workspace_note_tool({'title': 'test-note', 'content': '# Note Content'}, ctx)
    assert res.success is True
    note_file = Path('${ws}') / 'workspace' / 'notes' / 'test-note.md'
    assert note_file.is_file()
    assert '# Note Content' in note_file.read_text(encoding='utf-8')

asyncio.run(main())
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F06-T02',
      name: 'workspace-note sanitizes title characters safely',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await workspace_note_tool({'title': 'My Dr. Visit Note!', 'content': 'Symptoms'}, ctx)
    assert res.success is True
    assert res.output['title'] != ''
    assert (Path('${ws}') / 'workspace' / 'notes').is_dir()

asyncio.run(main())
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F06-T03',
      name: 'workspace-note returns structured output with title, path, bytes_written',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await workspace_note_tool({'title': 'cardio-agenda', 'content': 'Check blood pressure'}, ctx)
    assert res.success is True
    assert 'title' in res.output
    assert 'path' in res.output
    assert 'bytes_written' in res.output
    assert res.output['bytes_written'] > 0

asyncio.run(main())
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F06-T04',
      name: 'workspace-note automatically creates workspace/notes/ directory if absent',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    notes_dir = Path('${ws}') / 'workspace' / 'notes'
    assert not notes_dir.exists()
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await workspace_note_tool({'title': 'auto-dir', 'content': 'content'}, ctx)
    assert res.success is True
    assert notes_dir.is_dir()

asyncio.run(main())
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F06-T05',
      name: 'workspace-note overwrites existing note with updated content',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    await workspace_note_tool({'title': 'agenda', 'content': 'v1'}, ctx)
    res = await workspace_note_tool({'title': 'agenda', 'content': 'v2 updated'}, ctx)
    assert res.success is True
    note_file = Path('${ws}') / 'workspace' / 'notes' / 'agenda.md'
    assert 'v2 updated' in note_file.read_text(encoding='utf-8')

asyncio.run(main())
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
