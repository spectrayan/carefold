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

/**
 * Generates and synchronizes the Specialist Agent Topology table in README.md
 * directly from specialist agent manifests in agents/.
 *
 * Usage:
 *   node scripts/generate-readme-table.mjs           # Updates README.md between marker tags
 *   node scripts/generate-readme-table.mjs --check   # Verifies README.md table is in sync (CI check)
 *   node scripts/generate-readme-table.mjs --stdout  # Emits markdown table to stdout
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import process from 'node:process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, '..');
export const DEFAULT_AGENTS_DIR = path.join(ROOT_DIR, 'agents');
export const DEFAULT_README_PATH = path.join(ROOT_DIR, 'README.md');

export const START_MARKER = '<!-- agents-table:start -->';
export const END_MARKER = '<!-- agents-table:end -->';

/**
 * Extracts folded or single-line description from agent.yaml.
 * Escapes backslashes first, then table pipe delimiters.
 */
function parseDescription(agentYamlContent) {
  const descMatch = agentYamlContent.match(/^description:\s*(?:>-\s*|\|\s*|["']?)([\s\S]*?)(?=^\w[\w-]*:|\Z)/m);
  if (!descMatch) return '';
  let raw = descMatch[1].trim();
  if ((raw.startsWith('"') && raw.endsWith('"')) || (raw.startsWith("'") && raw.endsWith("'"))) {
    raw = raw.slice(1, -1);
  }
  return raw
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .join(' ')
    .trim()
    .replace(/\\/g, '\\\\')
    .replace(/\|/g, '\\|');
}

/**
 * Scans agents/ directory and reads specialist manifests, excluding _system, _template, and hidden files.
 */
export function readAgentManifests(agentsDir = DEFAULT_AGENTS_DIR) {
  if (!fs.existsSync(agentsDir)) {
    throw new Error(`Agents directory not found: ${agentsDir}`);
  }

  const entries = fs.readdirSync(agentsDir).filter(dirName => {
    const fullPath = path.join(agentsDir, dirName);
    return (
      fs.statSync(fullPath).isDirectory() &&
      !dirName.startsWith('.') &&
      !dirName.startsWith('_')
    );
  });

  const agents = [];

  for (const dirName of entries) {
    const agentDirPath = path.join(agentsDir, dirName);
    const metadataPath = path.join(agentDirPath, 'metadata.yaml');
    const agentYamlPath = path.join(agentDirPath, 'agent.yaml');

    if (!fs.existsSync(metadataPath)) {
      throw new Error(`Missing metadata.yaml for agent: ${dirName}`);
    }
    if (!fs.existsSync(agentYamlPath)) {
      throw new Error(`Missing agent.yaml for agent: ${dirName}`);
    }

    const metaContent = fs.readFileSync(metadataPath, 'utf8');
    const agentContent = fs.readFileSync(agentYamlPath, 'utf8');

    const idMatch = metaContent.match(/^\s*id:\s*['"]?([a-zA-Z0-9_\-]+)['"]?/m);
    const domainMatch = metaContent.match(/^\s*domain:\s*['"]?([a-zA-Z0-9_\-]+)['"]?/m);
    const categoryMatch = metaContent.match(/^\s*category:\s*['"]?([a-zA-Z0-9_.\-]+)['"]?/m);
    const riskMatch = metaContent.match(/^\s*risk_class:\s*['"]?([a-zA-Z0-9_\-]+)['"]?/m);

    const id = idMatch ? idMatch[1].trim() : dirName;
    const domain = domainMatch ? domainMatch[1].trim() : '';
    const category = categoryMatch ? categoryMatch[1].trim() : '';
    const risk_class = riskMatch ? riskMatch[1].trim() : '';
    const description = parseDescription(agentContent);

    agents.push({
      id,
      domain,
      category,
      risk_class,
      description
    });
  }

  // Sort deterministically A-Z by agent id
  agents.sort((a, b) => a.id.localeCompare(b.id));
  return agents;
}

/**
 * Generates the 5-column GFM Markdown table.
 */
export function generateMarkdownTable(agents) {
  const header = '| Agent Identifier | Domain | Category | Risk Class | Clinical Scope & Capabilities |';
  const separator = '|---|---|---|---|---|';
  const rows = agents.map(agent =>
    `| \`${agent.id}\` | \`${agent.domain}\` | \`${agent.category}\` | \`${agent.risk_class}\` | ${agent.description} |`
  );
  return [header, separator, ...rows].join('\n');
}

/**
 * Updates README.md between the marker comments.
 * Avoids TOCTOU race conditions by reading directly inside try/catch rather than checking existence first.
 */
export function updateReadmeTable(readmePath = DEFAULT_README_PATH, agentsDir = DEFAULT_AGENTS_DIR) {
  let content;
  try {
    content = fs.readFileSync(readmePath, 'utf8');
  } catch (err) {
    if (err && err.code === 'ENOENT') {
      throw new Error(`README file not found: ${readmePath}`);
    }
    throw err;
  }

  const startIndex = content.indexOf(START_MARKER);
  const endIndex = content.indexOf(END_MARKER);

  if (startIndex === -1 || endIndex === -1 || endIndex < startIndex) {
    throw new Error(
      `Markers ${START_MARKER} and/or ${END_MARKER} missing or misplaced in ${readmePath}.`
    );
  }

  const agents = readAgentManifests(agentsDir);
  const table = generateMarkdownTable(agents);
  const before = content.slice(0, startIndex + START_MARKER.length);
  const after = content.slice(endIndex);

  const updated = `${before}\n${table}\n${after}`;
  fs.writeFileSync(readmePath, updated, 'utf8');

  return { agentsCount: agents.length, table };
}

/**
 * Checks if the table in README.md is in sync with manifests.
 * Avoids TOCTOU race conditions by reading directly inside try/catch.
 */
export function checkReadmeTable(readmePath = DEFAULT_README_PATH, agentsDir = DEFAULT_AGENTS_DIR) {
  let content;
  try {
    content = fs.readFileSync(readmePath, 'utf8');
  } catch (err) {
    if (err && err.code === 'ENOENT') {
      return {
        synced: false,
        reason: `README file not found: ${readmePath}`
      };
    }
    throw err;
  }

  const startIndex = content.indexOf(START_MARKER);
  const endIndex = content.indexOf(END_MARKER);

  if (startIndex === -1 || endIndex === -1 || endIndex < startIndex) {
    return {
      synced: false,
      reason: `Markers ${START_MARKER} and/or ${END_MARKER} missing or misplaced in ${readmePath}.`
    };
  }

  const currentTable = content.slice(startIndex + START_MARKER.length, endIndex).trim();
  const agents = readAgentManifests(agentsDir);
  const expectedTable = generateMarkdownTable(agents).trim();

  if (currentTable === expectedTable) {
    return {
      synced: true,
      agentsCount: agents.length
    };
  }

  return {
    synced: false,
    reason: `Specialist agent table in ${readmePath} has drifted from agent manifests.`,
    currentTable,
    expectedTable,
    agentsCount: agents.length
  };
}

/**
 * CLI Entry point
 */
export function main(argv = process.argv.slice(2)) {
  let mode = 'update';
  let customReadme = DEFAULT_README_PATH;
  let customAgentsDir = DEFAULT_AGENTS_DIR;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--stdout' || arg === '--print' || arg === '--table') {
      mode = 'stdout';
    } else if (arg === '--check') {
      mode = 'check';
    } else if (arg === '--update') {
      mode = 'update';
    } else if (arg === '--file' || arg === '--readme') {
      customReadme = path.resolve(argv[++i]);
    } else if (arg === '--agents-dir') {
      customAgentsDir = path.resolve(argv[++i]);
    } else if (arg === '--help' || arg === '-h') {
      console.log(`Carefold README Agent Table Generator
Usage:
  node scripts/generate-readme-table.mjs [options]

Options:
  --update         Update README.md between marker tags (default)
  --check          Assert table in README.md matches manifests (exits 1 on drift)
  --stdout, --table, --print
                   Output markdown table directly to stdout
  --file, --readme <path>
                   Specify custom path to README.md
  --agents-dir <path>
                   Specify custom path to agents directory
  --help, -h       Display this help message
`);
      process.exit(0);
    }
  }

  try {
    if (mode === 'stdout') {
      const agents = readAgentManifests(customAgentsDir);
      const table = generateMarkdownTable(agents);
      console.log(table);
      process.exit(0);
    } else if (mode === 'check') {
      const res = checkReadmeTable(customReadme, customAgentsDir);
      if (res.synced) {
        console.log(`✓ README.md specialist agent table is up-to-date with manifests (${res.agentsCount} agents)`);
        process.exit(0);
      } else {
        console.error(`✗ FAIL: ${res.reason}`);
        if (res.currentTable && res.expectedTable) {
          console.error(`\nRun 'pnpm run generate:readme' to synchronize.`);
        }
        process.exit(1);
      }
    } else {
      const res = updateReadmeTable(customReadme, customAgentsDir);
      console.log(`✓ Successfully updated Specialist Agent Topology table in ${path.relative(ROOT_DIR, customReadme) || customReadme} (${res.agentsCount} agents)`);
      process.exit(0);
    }
  } catch (err) {
    console.error(`✗ Error: ${err.message}`);
    process.exit(1);
  }
}

const isDirectRun = process.argv[1] && (
  process.argv[1] === __filename ||
  process.argv[1].endsWith('generate-readme-table.mjs')
);

if (isDirectRun) {
  main();
}
