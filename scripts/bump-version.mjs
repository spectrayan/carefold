/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, '..');

const rawVersion = process.argv[2];

if (!rawVersion || rawVersion === '--help' || rawVersion === '-h') {
  console.error('Usage: node scripts/bump-version.mjs <version>');
  console.error('Example: node scripts/bump-version.mjs 0.4.0-beta.1');
  process.exit(1);
}

// Clean semver version (remove leading 'v' if provided)
const semverVersion = rawVersion.replace(/^v/, '');

// Convert semver (e.g. 0.4.0-beta.1, 0.4.0-rc.1) to PEP 440 (e.g. 0.4.0b1, 0.4.0rc1)
function toPep440(v) {
  return v
    .replace(/-beta\.(\d+)/i, 'b$1')
    .replace(/-rc\.(\d+)/i, 'rc$1')
    .replace(/-alpha\.(\d+)/i, 'a$1');
}

const pep440Version = toPep440(semverVersion);
const today = new Date().toISOString().split('T')[0];

console.log(`Bumping Carefold monorepo to version: ${semverVersion} (Python PEP 440: ${pep440Version})`);

// Helper to update JSON files safely without TOCTOU race conditions
function updateJsonFile(filePath, updater) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    const data = JSON.parse(raw);
    updater(data);
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2) + '\n', 'utf8');
    console.log(`  ✓ Updated ${path.relative(ROOT_DIR, filePath)} -> ${data.version}`);
  } catch (err) {
    if (err && err.code !== 'ENOENT') {
      throw err;
    }
  }
}

// Helper to update text files safely without TOCTOU race conditions
function updateTextFile(filePath, updater, label) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    const updated = updater(raw);
    fs.writeFileSync(filePath, updated, 'utf8');
    console.log(`  ✓ Updated ${label}`);
  } catch (err) {
    if (err && err.code !== 'ENOENT') {
      throw err;
    }
  }
}

// 1. Update Node package.json files
const packageFiles = [
  path.join(ROOT_DIR, 'package.json'),
  path.join(ROOT_DIR, 'apps/web/package.json'),
  path.join(ROOT_DIR, 'packages/cli/package.json'),
  path.join(ROOT_DIR, 'packages/runner/package.json'),
];

for (const pkgPath of packageFiles) {
  updateJsonFile(pkgPath, (pkg) => {
    pkg.version = semverVersion;
  });
}

// 2. Update backend/pyproject.toml
updateTextFile(
  path.join(ROOT_DIR, 'backend/pyproject.toml'),
  (content) => content.replace(/^version\s*=\s*["'][^"']+["']/m, `version = "${pep440Version}"`),
  `backend/pyproject.toml -> ${pep440Version}`
);

// 3. Update backend/src/carefold/__init__.py
updateTextFile(
  path.join(ROOT_DIR, 'backend/src/carefold/__init__.py'),
  (content) => content.replace(/^__version__\s*=\s*["'][^"']+["']/m, `__version__ = "${pep440Version}"`),
  `backend/src/carefold/__init__.py -> ${pep440Version}`
);

// 4. Update AGENTS.md
updateTextFile(
  path.join(ROOT_DIR, 'AGENTS.md'),
  (content) =>
    content
      .replace(/Runtime version: Carefold [^\n]+/g, `Runtime version: Carefold ${semverVersion}`)
      .replace(/Last updated: \d{4}-\d{2}-\d{2}/g, `Last updated: ${today}`),
  `AGENTS.md -> ${semverVersion} (${today})`
);

// 5. Update .github/workflows/release.yml default tag
updateTextFile(
  path.join(ROOT_DIR, '.github/workflows/release.yml'),
  (content) => content.replace(/default:\s*['"]v[0-9a-zA-Z.-]+['"]/g, `default: 'v${semverVersion}'`),
  `.github/workflows/release.yml default tag -> v${semverVersion}`
);

console.log('\nAll version references successfully synchronized!');
