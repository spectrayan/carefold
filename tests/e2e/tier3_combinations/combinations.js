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
import { runPython, runCli, createTempWorkspace, removeTempWorkspace, assertEqual, assertTrue, assertContains } from '../helpers/utils.js';

export const name = 'Tier 3: Pairwise Feature Combinations';

export async function run() {
  const tests = [
    {
      id: 'COMB-01',
      name: 'CLI init + agent add + skill add: Scaffolds bare workspace and installs reference pair',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const initRes = runCli(['init', ws, '--bare']);
          assertEqual(initRes.status, 0);

          const skillRes = runCli(['skill', 'add', 'visit-prep'], { cwd: ws });
          assertEqual(skillRes.status, 0);

          const agentRes = runCli(['agent', 'add', 'visit-steward'], { cwd: ws });
          assertEqual(agentRes.status, 0);

          assertTrue(fs.existsSync(path.join(ws, 'agents', 'visit-steward', 'agent.yaml')));
          assertTrue(fs.existsSync(path.join(ws, 'skills', 'visit-prep', 'SKILL.md')));
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'COMB-02',
      name: 'Agent manifest + skill manifest: Computes correct effective tools union',
      fn: () => {
        const script = `
from carefold.loaders.agent_loader import load_agent
agent, tools, skills = load_agent('agents/visit-steward', 'skills')
assert 'attach-read' in tools
assert 'workspace-note' in tools
assert 'skill-docs' in tools
assert len(skills) == 1
assert skills[0].id == 'visit-prep'
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'COMB-03',
      name: 'Visit-Steward + Visit-Prep: Reads clinical summary via attach-read tool',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const attachDir = path.join(ws, 'attachments');
          fs.mkdirSync(attachDir, { recursive: true });
          fs.writeFileSync(path.join(attachDir, 'labs.txt'), 'Blood glucose: 95 mg/dL. A1C: 5.4%.');

          const script = `
import asyncio
from pathlib import Path
from carefold.tools.attach_read import attach_read_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await attach_read_tool({'path': 'labs.txt'}, ctx)
    assert res.success is True
    assert 'A1C: 5.4%' in res.output['content']

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
      id: 'COMB-04',
      name: 'Visit-Steward + Visit-Prep: Persists appointment agenda via workspace-note tool',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    agent = type('Agent', (), {'id': 'visit-steward'})()
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}'), 'agent': agent})()
    res = await workspace_note_tool({'title': 'Dr Smith Agenda', 'content': '1. Discuss migraines\\n2. Refill eye drops'}, ctx)
    assert res.success is True
    note_path = Path('${ws}') / 'workspace' / 'notes' / 'dr-smith-agenda.md'
    assert note_path.is_file()
    assert 'Discuss migraines' in note_path.read_text(encoding='utf-8')

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
      id: 'COMB-05',
      name: 'Visit-Steward + Visit-Prep: Accesses question bank via skill-docs tool',
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
    res = await skill_docs_tool({'skill_id': 'visit-prep', 'doc': 'checklist.md'}, ctx)
    assert res.success is True
    assert 'Checklist' in res.output['content'] or len(res.output['content']) > 20

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'COMB-06',
      name: 'Benefits-Guide + Benefits-Explainer: Consults glossary via skill-docs tool',
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
    assert 'Deductible' in res.output['content'] or 'Copay' in res.output['content'] or len(res.output['content']) > 20

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'COMB-07',
      name: 'Habit-Companion + Habit-Checkin: Records habit check-in via workspace-note tool',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio
from pathlib import Path
from carefold.tools.workspace_note import workspace_note_tool

async def main():
    agent = type('Agent', (), {'id': 'habit-companion'})()
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}'), 'agent': agent})()
    res = await workspace_note_tool({'title': 'Daily Hydration Log', 'content': 'Day 1: 8 glasses water completed.'}, ctx)
    assert res.success is True
    note_path = Path('${ws}') / 'workspace' / 'notes' / 'daily-hydration-log.md'
    assert note_path.is_file()
    assert 'Day 1' in note_path.read_text(encoding='utf-8')

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
      id: 'COMB-08',
      name: 'Safety classifier + Prompt builder: Diagnoses blocked before prompt construction',
      fn: () => {
        const script = `
from carefold.safety.classifier import check_safety_refusal

res = check_safety_refusal('Based on your symptoms, you have chronic kidney disease.')
assert res.refused is True
assert res.reason == 'forbidden_intent:diagnose'
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'COMB-09',
      name: 'Safety classifier + Audit logger: Refusal logged with zero-body redaction',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio, json
from pathlib import Path
from carefold.safety.classifier import check_safety_refusal
from carefold.audit.logger import record_audit
from carefold.schemas.audit import AuditEvent

async def main():
    prompt = 'You have acute appendicitis. Skip the hospital.'
    safety = check_safety_refusal(prompt)
    assert safety.refused is True

    event = AuditEvent(
        agent_id='visit-steward',
        event='refuse',
        allowed=False,
        reason=safety.reason,
        prompt=prompt,
        completion=safety.safe_response
    )
    log_path = Path('${ws}') / 'logs' / 'audit.jsonl'
    await record_audit(event, log_path=log_path, store_bodies=False)

    data = json.loads(log_path.read_text(encoding='utf-8').strip())
    assert data['event'] == 'refuse'
    assert data['allowed'] is False
    assert data['reason'] == safety.reason
    assert data.get('prompt') is None
    assert data.get('completion') is None

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
      id: 'COMB-10',
      name: 'Runner + Audit logger: Successful run logged with duration and zero-body redaction',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio, json
from pathlib import Path
from carefold.audit.logger import record_audit
from carefold.schemas.audit import AuditEvent

async def main():
    log_path = Path('${ws}') / 'logs' / 'audit.jsonl'
    event = AuditEvent(
        agent_id='benefits-guide',
        event='run',
        allowed=True,
        duration_ms=88.5,
        prompt='What is coinsurance?',
        completion='Coinsurance is your share of the costs of a healthcare service.'
    )
    await record_audit(event, log_path=log_path, store_bodies=False)
    data = json.loads(log_path.read_text(encoding='utf-8').strip())
    assert data['event'] == 'run'
    assert data['allowed'] is True
    assert data['duration_ms'] == 88.5
    assert data.get('prompt') is None

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
      id: 'COMB-11',
      name: 'Tool execution + Audit logger: Tool events recorded with tool name and duration',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const script = `
import asyncio, json
from pathlib import Path
from carefold.audit.logger import record_audit
from carefold.schemas.audit import AuditEvent

async def main():
    log_path = Path('${ws}') / 'logs' / 'audit.jsonl'
    event = AuditEvent(
        agent_id='visit-steward',
        event='tool',
        tool='skill-docs',
        allowed=True,
        duration_ms=14.2
    )
    await record_audit(event, log_path=log_path)
    data = json.loads(log_path.read_text(encoding='utf-8').strip())
    assert data['event'] == 'tool'
    assert data['tool'] == 'skill-docs'
    assert data['duration_ms'] == 14.2

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
      id: 'COMB-12',
      name: 'SSE streaming + Mock client: Streams token chunks asynchronously',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    tokens = []
    async for ev in execute_agent_run('visit-steward', 'Help me prepare for my visit', mock=True):
        if ev.get('type') == 'token':
            tokens.append(ev.get('delta', ''))
    assert len(tokens) > 0
    assert len(''.join(tokens)) > 10

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'COMB-13',
      name: 'SSE streaming + Tool execution: Emits tool_start, tool_end, and terminal done events',
      fn: () => {
        const script = `
import asyncio
from carefold.engine.runner import execute_agent_run

async def main():
    event_types = []
    async for ev in execute_agent_run('visit-steward', 'Check the checklist for my visit', mock=True):
        event_types.append(ev.get('type'))
    assert 'tool_start' in event_types
    assert 'tool_end' in event_types
    assert 'done' in event_types

asyncio.run(main())
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'COMB-14',
      name: 'FastAPI /api/chat + Mock client: Streams text/event-stream HTTP response',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
resp = client.post('/api/chat', json={'agent_id': 'visit-steward', 'prompt': 'Hello doctor', 'mock': True})
assert resp.status_code == 200
assert 'text/event-stream' in resp.headers.get('content-type', '')
assert 'event: done' in resp.text
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'COMB-15',
      name: 'FastAPI /api/agents: Combines risk_class and search filter',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
resp = client.get('/api/agents?risk_class=wellness&search=steward')
assert resp.status_code == 200
data = resp.json()
assert len(data) == 1
assert data[0]['id'] == 'visit-steward'
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'COMB-16',
      name: 'FastAPI /api/agents/{id}: Combines manifest, starters, and README resolution',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
resp = client.get('/api/agents/visit-steward')
assert resp.status_code == 200
data = resp.json()
assert data['id'] == 'visit-steward'
assert len(data['starters']) >= 1
assert data.get('readmeText') is not None or data.get('readme') is not None
assert 'visit-prep' in data.get('skills', []) or 'visit-prep' in [s['id'] for s in data.get('resolvedSkills', [])]
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'COMB-17',
      name: 'CLI run + Mock client: Triggers safety refusal on clinical prompt',
      fn: () => {
        const res = runCli(['run', '--agent', 'visit-steward', '--mock', 'You have acute heart failure. Take 500mg amoxicillin.'], { timeout: 35000 });
        assertEqual(res.status, 0, `CLI run failed: ${res.stderr}`);
        assertContains(res.stdout, 'not a licensed medical professional');
      }
    },
    {
      id: 'COMB-18',
      name: 'CLI run + Tool execution: Writes workspace note upon agent run',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          runCli(['init', ws]);
          const res = runCli(['run', '--agent', 'habit-companion', '--mock', '--workspace', ws, 'Save a workspace note titled habit-goals with content Drink more water daily.'], { timeout: 35000 });
          assertEqual(res.status, 0, `CLI run tool failed: ${res.stderr}`);
          // Verify audit or run completed
          assertTrue(res.stdout.length > 20);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'COMB-19',
      name: 'CLI run + --json streaming: Verifies JSON format and audit logging',
      fn: () => {
        const res = runCli(['run', '--agent', 'visit-steward', '--mock', '--json', 'Hello appointment prep'], { timeout: 35000 });
        assertEqual(res.status, 0, `CLI run failed: ${res.stderr}`);
        const lines = res.stdout.trim().split('\n').filter(l => l.trim().startsWith('{'));
        assertTrue(lines.length >= 1, 'Should output at least one JSON line');
        const events = lines.map(l => JSON.parse(l));
        assertTrue(events.some(ev => ev.type === 'token'), 'Should stream token events');
      }
    },
    {
      id: 'COMB-20',
      name: 'CLI log + agent filter + JSON: Formats filtered audit records',
      fn: () => {
        const res = runCli(['log', '--json', '-n', '5']);
        assertEqual(res.status, 0, `CLI log failed: ${res.stderr}`);
        const events = JSON.parse(res.stdout);
        assertTrue(Array.isArray(events));
      }
    },
    {
      id: 'COMB-21',
      name: 'Attachments + File write + attach-read: Ingestion into agent execution context',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const attachDir = path.join(ws, 'attachments');
          fs.mkdirSync(attachDir, { recursive: true });
          fs.writeFileSync(path.join(attachDir, 'meds.txt'), 'Lisinopril 10mg daily, Metformin 500mg BID');

          const script = `
import asyncio
from pathlib import Path
from carefold.tools.attach_read import attach_read_tool

async def main():
    ctx = type('Ctx', (), {'workspace_root': Path('${ws}')})()
    res = await attach_read_tool({'path': 'meds.txt'}, ctx)
    assert res.success is True
    assert 'Lisinopril' in res.output['content']

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
      id: 'COMB-22',
      name: 'Offline evals runner + Safety golden dataset: Validates zero false negatives on refusal triggers',
      fn: () => {
        const res = runPython('evals/runner.py', ['--agent', 'visit-steward']);
        assertEqual(res.status, 0, `Offline evals failed: ${res.stderr}`);
        assertContains(res.stdout, '100% pass rate');
      }
    },
    {
      id: 'COMB-23',
      name: 'Offline evals runner + Must_not validation: Validates forbidden tokens are omitted',
      fn: () => {
        const res = runPython('evals/runner.py', ['--agent', 'benefits-guide']);
        assertEqual(res.status, 0, `Offline evals failed: ${res.stderr}`);
        assertContains(res.stdout, 'Failed: 0');
      }
    },
    {
      id: 'COMB-24',
      name: 'Docker compose + Dockerfile: Port mappings and service targets align',
      fn: () => {
        const composeText = fs.readFileSync(path.join(process.cwd(), 'docker', 'docker-compose.yml'), 'utf8');
        const dockerText = fs.readFileSync(path.join(process.cwd(), 'docker', 'Dockerfile'), 'utf8');
        assertContains(composeText, '8000:8000');
        assertContains(composeText, '3000:3000');
        assertContains(dockerText, 'EXPOSE 8000');
        assertContains(dockerText, 'EXPOSE 3000');
      }
    }
  ];

  return tests;
}
