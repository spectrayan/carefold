#!/usr/bin/env node
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
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '..');

const C_STYLE_HEADER = `/*
 * Carefold \u2014 Healthcare AI Agent Marketplace & Runtime
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
 */`;

const HASH_STYLE_HEADER = `# Carefold \u2014 Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.`;

const TARGET_EXTENSIONS = new Set(['.py', '.ts', '.tsx', '.js', '.mjs', '.css']);

const IGNORED_DIRS = new Set([
  'node_modules',
  '.next',
  'dist',
  '.venv',
  '.git',
  '.agents',
  '.idea',
  '.pytest_cache',
  'workspace',
  'logs',
  'chats',
  'attachments',
  '__pycache__',
  '.turbo',
  'out',
  'build'
]);

const IGNORED_FILES = new Set([
  'next-env.d.ts'
]);

function isPython(filePath) {
  return filePath.endsWith('.py');
}

export function hasLicenseHeader(content, isPy) {
  let checkArea = content;
  if (checkArea.startsWith('#!')) {
    const newlineIndex = checkArea.indexOf('\n');
    if (newlineIndex !== -1) {
      checkArea = checkArea.slice(newlineIndex + 1);
    }
  }
  checkArea = checkArea.trimStart();

  const expectedHeader = isPy ? HASH_STYLE_HEADER : C_STYLE_HEADER;
  const normalizedCheck = checkArea.replace(/\r\n/g, '\n');
  const normalizedExpected = expectedHeader.replace(/\r\n/g, '\n');

  if (!normalizedCheck.startsWith(normalizedExpected)) {
    return false;
  }

  // Ensure header does not contain forbidden phrase
  const headerSlice = normalizedCheck.slice(0, normalizedExpected.length);
  if (headerSlice.includes('Open-' + 'Source')) {
    return false;
  }

  return true;
}

export function applyLicenseHeader(content, isPy) {
  if (hasLicenseHeader(content, isPy)) {
    return content;
  }

  const expectedHeader = isPy ? HASH_STYLE_HEADER : C_STYLE_HEADER;

  if (content.startsWith('#!')) {
    const newlineIndex = content.indexOf('\n');
    if (newlineIndex !== -1) {
      const shebang = content.slice(0, newlineIndex + 1);
      const rest = content.slice(newlineIndex + 1);
      const cleanRest = rest.replace(/^\r?\n+/, '');
      return `${shebang}${expectedHeader}\n\n${cleanRest}`;
    } else {
      return `${content}\n${expectedHeader}\n`;
    }
  }

  const cleanContent = content.replace(/^\r?\n+/, '');
  return `${expectedHeader}\n\n${cleanContent}`;
}

function walkDirectory(dir, rootDir = dir) {
  const results = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isSymbolicLink()) {
      continue;
    }
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (IGNORED_DIRS.has(entry.name)) {
        continue;
      }
      results.push(...walkDirectory(fullPath, rootDir));
    } else if (entry.isFile()) {
      if (IGNORED_FILES.has(entry.name)) {
        continue;
      }
      const ext = path.extname(entry.name);
      if (TARGET_EXTENSIONS.has(ext)) {
        results.push(fullPath);
      }
    }
  }
  return results;
}

export function getSourceFiles(rootDir = REPO_ROOT) {
  let files = [];
  try {
    const stdout = execSync('git ls-files', { cwd: rootDir, encoding: 'utf-8' });
    files = stdout
      .split('\n')
      .map(line => line.trim())
      .filter(Boolean)
      .filter(relPath => {
        if (IGNORED_FILES.has(path.basename(relPath))) {
          return false;
        }
        const ext = path.extname(relPath);
        return TARGET_EXTENSIONS.has(ext);
      })
      .map(relPath => path.resolve(rootDir, relPath));
  } catch {
    files = walkDirectory(rootDir);
  }
  return files;
}

export function getAllSourceFilesIncludingUntracked(rootDir = REPO_ROOT) {
  return walkDirectory(rootDir);
}

function run() {
  const args = process.argv.slice(2);

  if (args.length === 0 || args.includes('--help') || args.includes('-h')) {
    console.log(`
Usage:
  node scripts/licenses.mjs --check [files...]
  node scripts/licenses.mjs --fix [files...]

Options:
  --check    Verify that all target source files have the official Spectrayan Apache-2.0 header.
             Exits with code 0 on success, code 1 on violations.
  --fix      Apply the official Spectrayan Apache-2.0 header idempotently to all target source files.
  --all      Include all untracked files discovered by walking directories.
  --help     Show this help message.
`);
    process.exit(0);
  }

  const isCheck = args.includes('--check');
  const isFix = args.includes('--fix');
  const includeAll = args.includes('--all');

  if (!isCheck && !isFix) {
    console.error('Error: Must specify either --check or --fix');
    process.exit(1);
  }

  const fileArgs = args.filter(a => !a.startsWith('-'));
  let filesToProcess;

  if (fileArgs.length > 0) {
    filesToProcess = fileArgs.map(f => path.resolve(process.cwd(), f));
  } else if (includeAll) {
    filesToProcess = getAllSourceFilesIncludingUntracked(REPO_ROOT);
  } else {
    filesToProcess = getSourceFiles(REPO_ROOT);
  }

  if (isCheck) {
    console.log(`Checking license headers across ${filesToProcess.length} source file(s)...`);
    const missing = [];

    for (const filePath of filesToProcess) {
      let content;
      try {
        content = fs.readFileSync(filePath, 'utf-8');
      } catch (err) {
        if (err && (err.code === 'ENOENT' || err.code === 'EISDIR')) continue;
        throw err;
      }
      const isPy = isPython(filePath);
      if (!hasLicenseHeader(content, isPy)) {
        missing.push(path.relative(REPO_ROOT, filePath));
      }
    }

    if (missing.length > 0) {
      console.error(`\nFound ${missing.length} file(s) missing or with invalid Spectrayan license header:`);
      for (const file of missing) {
        console.error(`  ✗ ${file}`);
      }
      console.error(`\nRun 'pnpm run fix:licenses' to automatically apply headers.`);
      process.exit(1);
    } else {
      console.log(`✓ All ${filesToProcess.length} source files contain valid Spectrayan license headers.`);
      process.exit(0);
    }
  }

  if (isFix) {
    console.log(`Applying license headers across source files...`);
    let fixedCount = 0;
    let alreadyValidCount = 0;

    // In fix mode, we also ensure all files found by directory walk (e.g. untracked chat files) are fixed
    const targetSet = new Set(filesToProcess);
    const allDiscovered = getAllSourceFilesIncludingUntracked(REPO_ROOT);
    for (const f of allDiscovered) {
      targetSet.add(f);
    }

    for (const filePath of targetSet) {
      let content;
      try {
        content = fs.readFileSync(filePath, 'utf-8');
      } catch (err) {
        if (err && (err.code === 'ENOENT' || err.code === 'EISDIR')) continue;
        throw err;
      }
      const isPy = isPython(filePath);

      if (hasLicenseHeader(content, isPy)) {
        alreadyValidCount++;
        continue;
      }

      const updated = applyLicenseHeader(content, isPy);
      if (updated !== content) {
        fs.writeFileSync(filePath, updated, 'utf-8');
        fixedCount++;
      }
    }

    console.log(`✓ License header application complete: ${fixedCount} file(s) updated, ${alreadyValidCount} file(s) already valid.`);
    process.exit(0);
  }
}

// Only invoke CLI runner if executed directly
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  run();
}
