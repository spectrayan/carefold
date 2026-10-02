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
import fsSync from 'node:fs';
import path from 'node:path';
export interface CarefoldConfig {
  allow_clinical?: boolean;
  model?: {
    provider?: string;
    baseUrl?: string;
    model?: string;
    apiKey?: string;
    timeout?: number;
  };
}

export interface WorkspacePaths {
  root: string;
  config: string;
  agents: string;
  skills: string;
  chats: string;
  attachments: string;
  logs: string;
  auditLog: string;
}

export function findWorkspaceRoot(explicitDir?: string): string {
  if (explicitDir) {
    return path.resolve(/*turbopackIgnore: true*/ process.cwd(), explicitDir);
  }

  if (process.env.CAREFOLD_WORKSPACE) {
    return path.resolve(/*turbopackIgnore: true*/ process.cwd(), process.env.CAREFOLD_WORKSPACE);
  }

  // Walk upwards from current working directory
  let current = process.cwd();
  while (true) {
    if (
      fsSync.existsSync(path.join(current, 'carefold.config.json')) ||
      (fsSync.existsSync(path.join(current, 'agents')) && fsSync.existsSync(path.join(current, 'skills')))
    ) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }

  return process.cwd();
}

export function getWorkspacePaths(workspaceRoot: string): WorkspacePaths {
  return {
    root: workspaceRoot,
    config: path.join(workspaceRoot, 'carefold.config.json'),
    agents: path.join(workspaceRoot, 'agents'),
    skills: path.join(workspaceRoot, 'skills'),
    chats: path.join(workspaceRoot, 'chats'),
    attachments: path.join(workspaceRoot, 'attachments'),
    logs: path.join(workspaceRoot, 'logs'),
    auditLog: path.join(workspaceRoot, 'logs', 'audit.jsonl')
  };
}

export async function loadWorkspaceConfig(workspaceRoot: string): Promise<CarefoldConfig> {
  const configPath = path.join(workspaceRoot, 'carefold.config.json');
  try {
    const raw = await fs.readFile(configPath, 'utf8');
    const parsed = JSON.parse(raw);
    let safeBaseUrl: string | undefined;
    if (typeof parsed?.model?.baseUrl === 'string') {
      try {
        const u = new URL(parsed.model.baseUrl);
        if (u.protocol === 'http:' || u.protocol === 'https:') {
          u.username = '';
          u.password = '';
          safeBaseUrl = `${u.protocol}//${u.host}`;
        }
      } catch {}
    }
    return {
      allow_clinical: Boolean(parsed?.allow_clinical),
      model: {
        provider: typeof parsed?.model?.provider === 'string' ? parsed.model.provider : 'ollama',
        model: typeof parsed?.model?.model === 'string' ? parsed.model.model : undefined,
        baseUrl: safeBaseUrl
      }
    };
  } catch {
    return {};
  }
}
