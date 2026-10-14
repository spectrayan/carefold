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

export const name = 'F18-B: Web Marketplace Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F18-B01',
      name: 'GET /api/agents?risk_class=admin filters catalog exclusively to admin agents',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
resp = client.get("/api/agents?risk_class=admin")
assert resp.status_code == 200
data = resp.json()
assert len(data) >= 1
for a in data:
    assert a["risk_class"] == "admin"
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F18-B02',
      name: 'GET /api/agents?search=steward performs case-insensitive substring search',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
resp = client.get("/api/agents?search=STEWARD")
assert resp.status_code == 200
data = resp.json()
assert len(data) == 1
assert data[0]["id"] == "visit-steward"
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F18-B03',
      name: 'GET /api/agents?search=nonexistent returns empty list with 200 OK',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
resp = client.get("/api/agents?search=completely_nonexistent_agent_query_123")
assert resp.status_code == 200
data = resp.json()
assert data == []
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F18-B04',
      name: 'GET /api/agents handles special characters and symbols in query gracefully',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
for query in ["!@#$%^&*()", "'; DROP TABLE agents;--", "../../../etc/passwd"]:
    resp = client.get(f"/api/agents?search={query}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F18-B05',
      name: 'GET /api/agents?risk_class=unsupported_class returns empty list with 200 OK',
      fn: () => {
        const script = `
from fastapi.testclient import TestClient
from carefold.main import app

client = TestClient(app)
resp = client.get("/api/agents?risk_class=unsupported_risk_level")
assert resp.status_code == 200
assert resp.json() == []
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
