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

import path from 'node:path';
import fs from 'node:fs/promises';

export class SandboxSecurityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SandboxSecurityError';
  }
}

/**
 * Resolves a requested relative path against an allowed base directory.
 * Enforces:
 * 1. Rejection of null bytes
 * 2. Rejection of URI protocols
 * 3. Strict directory prefix boundary containment
 * 4. Symlink resolution (realpath) to prevent symlink traversal outside sandbox
 */
export async function resolveSandboxedPath(
  baseDir: string,
  userPath: string,
  options: { mustExist?: boolean } = {}
): Promise<string> {
  if (!userPath || typeof userPath !== 'string') {
    throw new SandboxSecurityError('Invalid path: path must be a non-empty string.');
  }

  // Reject null bytes (poison null byte attack)
  if (userPath.includes('\0')) {
    throw new SandboxSecurityError('Path traversal forbidden: Null byte detected in path.');
  }

  // Reject explicit URI protocols
  if (/^[a-zA-Z][a-zA-Z0-9+-.]*:\/\//.test(userPath)) {
    throw new SandboxSecurityError('Path traversal forbidden: URI schemes are not permitted.');
  }

  const normalizedBase = path.resolve(baseDir);
  const resolvedTarget = path.resolve(normalizedBase, path.normalize(userPath));

  // Traversal boundary check
  if (resolvedTarget !== normalizedBase && !resolvedTarget.startsWith(normalizedBase + path.sep)) {
    throw new SandboxSecurityError(
      `Path traversal forbidden: Path "${userPath}" escapes allowed directory "${baseDir}".`
    );
  }

  // Ensure base directory exists on disk for realpath resolution
  await fs.mkdir(normalizedBase, { recursive: true });
  const realBase = await fs.realpath(normalizedBase);

  // Check existing ancestor directories for symlinks escaping the sandbox
  let currentDir = path.dirname(resolvedTarget);
  while (currentDir !== normalizedBase && currentDir.startsWith(normalizedBase)) {
    try {
      const dirStat = await fs.lstat(currentDir);
      if (dirStat.isSymbolicLink()) {
        const realDir = await fs.realpath(currentDir);
        if (realDir !== realBase && !realDir.startsWith(realBase + path.sep)) {
          throw new SandboxSecurityError(
            `Path traversal forbidden: Directory symlink "${currentDir}" escapes sandbox "${realBase}".`
          );
        }
      }
    } catch (dirErr: any) {
      if (dirErr instanceof SandboxSecurityError) throw dirErr;
    }
    currentDir = path.dirname(currentDir);
  }

  if (options.mustExist) {
    try {
      const realTarget = await fs.realpath(resolvedTarget);

      // Verify realpath (prevents symlinks pointing outside the sandbox)
      if (realTarget !== realBase && !realTarget.startsWith(realBase + path.sep)) {
        throw new SandboxSecurityError(
          `Path traversal forbidden: Symlink target "${realTarget}" escapes sandbox "${realBase}".`
        );
      }
      return realTarget;
    } catch (err: any) {
      if (err instanceof SandboxSecurityError) throw err;
      throw new Error(`File not found: ${userPath}`);
    }
  }

  // When mustExist is false, if target already exists on disk, ensure it is not a symlink
  try {
    const lstat = await fs.lstat(resolvedTarget);
    if (lstat.isSymbolicLink()) {
      try {
        const realTarget = await fs.realpath(resolvedTarget);
        if (realTarget !== realBase && !realTarget.startsWith(realBase + path.sep)) {
          throw new SandboxSecurityError(
            `Path traversal forbidden: Symlink target "${realTarget}" escapes sandbox "${realBase}".`
          );
        }
      } catch (realpathErr: any) {
        if (realpathErr instanceof SandboxSecurityError) throw realpathErr;
      }
      throw new SandboxSecurityError(
        `Path traversal forbidden: Target path "${userPath}" is a symlink.`
      );
    }
  } catch (err: any) {
    if (err instanceof SandboxSecurityError) throw err;
    // ENOENT is expected when creating a new file
  }

  return resolvedTarget;
}
