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
import path from 'node:path';
import os from 'node:os';

export interface CliTestWorkspace {
  workspaceDir: string;
  cleanup: () => Promise<void>;
  createFile: (relativePath: string, content: string) => Promise<string>;
  readFile: (relativePath: string) => Promise<string>;
  exists: (relativePath: string) => Promise<boolean>;
}

export async function createCliTestWorkspace(): Promise<CliTestWorkspace> {
  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'carefold-cli-test-'));

  const workspace: CliTestWorkspace = {
    workspaceDir: tmpDir,
    cleanup: async () => {
      try {
        await fs.rm(tmpDir, { recursive: true, force: true });
      } catch {}
    },
    createFile: async (relPath: string, content: string) => {
      const fullPath = path.join(tmpDir, relPath);
      await fs.mkdir(path.dirname(fullPath), { recursive: true });
      await fs.writeFile(fullPath, content, 'utf8');
      return fullPath;
    },
    readFile: async (relPath: string) => {
      return fs.readFile(path.join(tmpDir, relPath), 'utf8');
    },
    exists: async (relPath: string) => {
      try {
        await fs.access(path.join(tmpDir, relPath));
        return true;
      } catch {
        return false;
      }
    }
  };

  return workspace;
}
