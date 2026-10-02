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

import fs from 'node:fs/promises';
import path from 'node:path';
import { getWorkspacePaths } from '../utils/workspace.js';
import { resolveBundledAssets, copyPackDirectory } from '../utils/assets.js';
import { CliError, ExitCodes } from '../utils/errors.js';

export interface InitOptions {
  force?: boolean;
  bundled?: boolean;
  provider?: string;
  modelUrl?: string;
  modelName?: string;
}

export async function initCommand(dirArg?: string, options: InitOptions = {}): Promise<void> {
  const targetDir = path.resolve(process.cwd(), dirArg || '.');
  const paths = getWorkspacePaths(targetDir);

  // 1. Guard against accidental overwrite by checking config existence if not force
  if (!options.force) {
    try {
      await fs.access(paths.config);
      throw new CliError(
        `Workspace already initialized at "${targetDir}". Use --force to reinitialize.`,
        ExitCodes.USER_ERROR
      );
    } catch (err: any) {
      if (err instanceof CliError) throw err;
      // File does not exist, proceed
    }
  }

  // 2. Create core directories
  await fs.mkdir(paths.agents, { recursive: true });
  await fs.mkdir(paths.skills, { recursive: true });
  await fs.mkdir(paths.chats, { recursive: true });
  await fs.mkdir(paths.attachments, { recursive: true });
  await fs.mkdir(paths.logs, { recursive: true });

  // 3. Create logs/audit.jsonl (append-only audit log)
  try {
    await fs.writeFile(paths.auditLog, '', { flag: options.force ? 'w' : 'a', encoding: 'utf8' });
  } catch (err: any) {
    if (err.code !== 'EEXIST') throw err;
  }

  // 4. Create carefold.config.json
  const config = {
    version: '0.1.0',
    model: {
      provider: options.provider || 'ollama',
      baseUrl: options.modelUrl || 'http://127.0.0.1:11434/v1',
      model: options.modelName || 'llama3.2',
      apiKey: ''
    },
    audit: {
      enabled: true,
      store_bodies: false,
      log_path: 'logs/audit.jsonl'
    },
    allow_clinical: false,
    telemetry: false
  };
  try {
    await fs.writeFile(paths.config, JSON.stringify(config, null, 2) + '\n', {
      flag: options.force ? 'w' : 'wx',
      encoding: 'utf8'
    });
  } catch (err: any) {
    if (err.code === 'EEXIST' && !options.force) {
      throw new CliError(
        `Workspace already initialized at "${targetDir}". Use --force to reinitialize.`,
        ExitCodes.USER_ERROR
      );
    }
    if (err.code !== 'EEXIST') throw err;
  }

  // 5. Create README.md stub with Apache-2.0 notice & intended use
  const readmeContent = `# Carefold Workspace

Local-first specialist health agent runtime workspace.

## Intended Use
Carefold is a wellness, care navigation, and administrative assistant runtime. It does not provide medical diagnosis, clinical treatment, drug dosing, or emergency triage.
Not for clinical emergencies. If experiencing an emergency, contact local emergency services immediately.

## License
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
`;
  try {
    await fs.writeFile(paths.readme, readmeContent, {
      flag: options.force ? 'w' : 'wx',
      encoding: 'utf8'
    });
  } catch (err: any) {
    if (err.code !== 'EEXIST') throw err;
  }

  // 6. Copy bundled reference agents and skills unless --no-bundled
  if (options.bundled !== false) {
    try {
      const assets = resolveBundledAssets();
      const defaultAgents = ['visit-steward', 'benefits-guide', 'habit-companion'];
      const defaultSkills = ['visit-prep', 'benefits-explainer', 'habit-checkin'];

      for (const skillName of defaultSkills) {
        const src = path.join(assets.skillsDir, skillName);
        const dest = path.join(paths.skills, skillName);
        try {
          await copyPackDirectory(src, dest, Boolean(options.force));
        } catch (err: any) {
          if (err.code !== 'ENOENT') throw err;
        }
      }

      for (const agentName of defaultAgents) {
        const src = path.join(assets.agentsDir, agentName);
        const dest = path.join(paths.agents, agentName);
        try {
          await copyPackDirectory(src, dest, Boolean(options.force));
        } catch (err: any) {
          if (err.code !== 'ENOENT') throw err;
        }
      }
    } catch (err: any) {
      // If bundled assets cannot be found in test isolation, proceed with bare workspace
      if (!options.bundled) {
        throw err;
      }
    }
  }

  console.log(`✓ Initialized Carefold workspace in ${targetDir}`);
  console.log(`  • Config: carefold.config.json (Provider: ${config.model.provider}, Model: ${config.model.model} @ ${config.model.baseUrl})`);
  console.log(`  • Directories: agents/, skills/, chats/, attachments/, logs/`);
  console.log(`\nNext steps:`);
  console.log(`  carefold agent list`);
  console.log(`  carefold run --agent visit-steward "What questions should I ask my doctor?"`);
}
