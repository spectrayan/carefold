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
import { runPython, assertEqual, assertTrue, assertContains } from '../helpers/utils.js';

export const name = 'F24-B: Container Packaging & Compose Boundaries';

export async function run() {
  const tests = [
    {
      id: 'F24-B01',
      name: 'docker-compose.yml parses as valid YAML with required service structure',
      fn: () => {
        const script = `
import yaml
from pathlib import Path

compose_file = Path('docker/docker-compose.yml')
assert compose_file.is_file()
data = yaml.safe_load(compose_file.read_text())
assert 'services' in data
assert 'backend' in data['services']
assert 'web' in data['services']
assert 'volumes' in data
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F24-B02',
      name: 'docker-compose.yml sets offline-first environment defaults for backend and web',
      fn: () => {
        const script = `
import yaml
from pathlib import Path

compose_file = Path('docker/docker-compose.yml')
data = yaml.safe_load(compose_file.read_text())
backend_env = data['services']['backend']['environment']
web_env = data['services']['web']['environment']

# Ensure correct variable names for workspace root, audit log path, and Ollama endpoint
assert any(k.startswith('CAREFOLD_WORKSPACE_ROOT=') for k in backend_env), "Missing CAREFOLD_WORKSPACE_ROOT on backend"
assert any(k.startswith('CAREFOLD_OLLAMA_URL=') for k in backend_env), "Missing CAREFOLD_OLLAMA_URL on backend"
assert any(k.startswith('CAREFOLD_AUDIT_LOG_PATH=') for k in backend_env), "Missing CAREFOLD_AUDIT_LOG_PATH on backend"

# Ensure obsolete/unused variable names are removed from backend
assert not any(k.startswith('OLLAMA_URL=') for k in backend_env), "OLLAMA_URL must be replaced by CAREFOLD_OLLAMA_URL on backend"
assert not any(k.startswith('CAREFOLD_DATA=') for k in backend_env), "CAREFOLD_DATA must be removed from backend"

# Ensure web service sets CAREFOLD_WORKSPACE
assert any(k.startswith('CAREFOLD_WORKSPACE=') for k in web_env), "Web service missing CAREFOLD_WORKSPACE"
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F24-B03',
      name: 'docker-compose.yml defines robust health check on backend service',
      fn: () => {
        const script = `
import yaml
from pathlib import Path

compose_file = Path('docker/docker-compose.yml')
data = yaml.safe_load(compose_file.read_text())
backend = data['services']['backend']
assert 'healthcheck' in backend
hc = backend['healthcheck']
assert 'test' in hc
assert 'interval' in hc
assert 'retries' in hc
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    },
    {
      id: 'F24-B04',
      name: 'Dockerfile exposes backend port 8000 and web port 3000',
      fn: () => {
        const content = fs.readFileSync(path.join(process.cwd(), 'docker', 'Dockerfile'), 'utf8');
        assertContains(content, 'EXPOSE 8000');
        assertContains(content, 'EXPOSE 3000');
      }
    },
    {
      id: 'F24-B05',
      name: 'docker-compose.yml mounts carefold-data volume to preserve audit logs',
      fn: () => {
        const script = `
import yaml
from pathlib import Path

compose_file = Path('docker/docker-compose.yml')
data = yaml.safe_load(compose_file.read_text())
backend = data['services']['backend']
assert 'volumes' in backend
has_data_vol = any('carefold-data' in v for v in backend['volumes'])
assert has_data_vol, "Backend service must mount carefold-data volume"
`;
        const res = runPython(script);
        assertEqual(res.status, 0, `Python test failed: ${res.stderr}`);
      }
    }
  ];

  return tests;
}
