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

export const name = 'F19-B: Web Agent Detail Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F19-B01',
      name: 'GET /api/agents/{id} returns 404 Not Found for non-existent agent',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
resp = client.get("/api/agents/totally-fake-agent-404")
assert resp.status_code == 404
assert "not found" in resp.json().get("detail", "").lower()
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F19-B02',
      name: 'GET /api/agents/{id} enforces 403 Forbidden on clinical_assist agent without explicit consent',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          // Create clinical agent
          const aDir = path.join(ws, 'agents', 'clinical-tester');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
schema_version: "1.0"
id: "clinical-tester"
title: "Clinical Tester"
persona: "Diagnostic assistant"
version: "0.1.0"
risk_class: "clinical_assist"
tools: []
skills: []
`);

          const script = `
from fastapi.testclient import TestClient
from carefold.main import app
from carefold.config import settings
from pathlib import Path

old_root = settings.workspace_root
settings.workspace_root = Path('${ws}')
try:
    client = TestClient(app)
    # 1. Without allow_clinical -> 403
    r1 = client.get("/api/agents/clinical-tester")
    assert r1.status_code == 403, f"Expected 403, got {r1.status_code}"

    # 2. With allow_clinical=true -> 200
    r2 = client.get("/api/agents/clinical-tester?allow_clinical=true")
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}"
finally:
    settings.workspace_root = old_root
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F19-B03',
      name: 'GET /api/agents/{id} neutralizes directory traversal in agent_id parameter',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
resp = client.get("/api/agents/..%2F..%2Fetc%2Fpasswd")
# Must not return 200
assert resp.status_code in [400, 404]
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F19-B04',
      name: 'GET /api/agents/{id} handles missing starters.json cleanly without failing',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'agents', 'no-starters-agent');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
schema_version: "1.0"
id: "no-starters-agent"
title: "No Starters"
persona: "Tester"
version: "0.1.0"
risk_class: "wellness"
tools: []
skills: []
`);

          const script = `
from fastapi.testclient import TestClient
from carefold.main import app
from carefold.config import settings
from pathlib import Path

old_root = settings.workspace_root
settings.workspace_root = Path('${ws}')
try:
    client = TestClient(app)
    resp = client.get("/api/agents/no-starters-agent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["starters"] == []
finally:
    settings.workspace_root = old_root
`;
          const res = runPython(script);
          assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
        } finally {
          removeTempWorkspace(ws);
        }
      }
    },
    {
      id: 'F19-B05',
      name: 'GET /api/agents/{id} handles missing README.md gracefully',
      fn: () => {
        const ws = createTempWorkspace();
        try {
          const aDir = path.join(ws, 'agents', 'no-readme-agent');
          fs.mkdirSync(aDir, { recursive: true });
          fs.writeFileSync(path.join(aDir, 'agent.yaml'), `
schema_version: "1.0"
id: "no-readme-agent"
title: "No Readme"
persona: "Tester"
version: "0.1.0"
risk_class: "wellness"
tools: []
skills: []
`);

          const script = `
from fastapi.testclient import TestClient
from carefold.main import app
from carefold.config import settings
from pathlib import Path

old_root = settings.workspace_root
settings.workspace_root = Path('${ws}')
try:
    client = TestClient(app)
    resp = client.get("/api/agents/no-readme-agent")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("readme") is None
finally:
    settings.workspace_root = old_root
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
