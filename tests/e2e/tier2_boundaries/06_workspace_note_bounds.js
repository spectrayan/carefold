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

export const name = 'F06-B: workspace-note Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F06-B01',
      name: 'workspace-note neutralizes directory traversal characters in title without escaping notes directory',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await workspace_note_tool({'title': '../../evil_escape', 'content': 'injected payload'}, ctx)
    assert res.success is True
    assert '..' not in res.output['title']
    assert not (Path('${ws}') / 'evil_escape.md').exists()
    # Confirm it was confined within notes directory
    assert (Path('${ws}') / 'workspace' / 'notes' / f"{res.output['title']}.md").is_file()

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
      id: 'F06-B02',
      name: 'workspace-note rejects empty title or whitespace-only title',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await workspace_note_tool({'title': '', 'content': 'content'}, ctx)
    assert res.success is False
    assert 'title' in res.error.lower()

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
      id: 'F06-B03',
      name: 'workspace-note rejects non-string content parameter',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await workspace_note_tool({'title': 'valid-title', 'content': None}, ctx)
    assert res.success is False
    assert 'content' in res.error.lower()

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
      id: 'F06-B04',
      name: 'workspace-note safely falls back to default slug when title consists purely of stripped symbols',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await workspace_note_tool({'title': '$$$###@@@', 'content': 'symbolic note'}, ctx)
    assert res.success is True
    assert res.output['title'] == 'note'
    note_file = Path('${ws}') / 'workspace' / 'notes' / 'note.md'
    assert note_file.is_file()

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
      id: 'F06-B05',
      name: 'workspace-note prevents overwriting existing symlink targets',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const notesDir = path.join(ws, 'workspace', 'notes');
          fs.mkdirSync(notesDir, { recursive: true });
          const secretFile = path.join(ws, 'sensitive_system.txt');
          fs.writeFileSync(secretFile, 'ORIGINAL SENSITIVE CONTENT');
          try {
            fs.symlinkSync(secretFile, path.join(notesDir, 'exploit.md'));
          } catch {}

          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await workspace_note_tool({'title': 'exploit', 'content': 'OVERWRITE MALICIOUS DATA'}, ctx)
    assert res.success is False
    assert 'symlink' in res.error.lower() or 'forbidden' in res.error.lower()
    # Confirm external target was not overwritten
    orig = Path('${secretFile}').read_text()
    assert orig == 'ORIGINAL SENSITIVE CONTENT'

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
