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

  if (process.env.CAREFOLD_HOME) {
    return path.resolve(/*turbopackIgnore: true*/ process.cwd(), process.env.CAREFOLD_HOME);
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
