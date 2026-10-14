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

import fsSync from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FALLBACK_VERSION = '0.4.0-beta.1';

/**
 * Dynamically resolves the CLI package version from package.json
 */
export function getCliVersion(): string {
  try {
    const currentDir = path.dirname(fileURLToPath(import.meta.url));

    // Check direct candidate locations relative to this module
    const candidates = [
      path.resolve(currentDir, '../package.json'),      // From dist/
      path.resolve(currentDir, '../../package.json'),   // From src/utils/
      path.resolve(currentDir, '../../../package.json') // Fallback monorepo root
    ];

    for (const candidate of candidates) {
      if (fsSync.existsSync(candidate)) {
        try {
          const raw = fsSync.readFileSync(candidate, 'utf8');
          const data = JSON.parse(raw);
          if (typeof data.version === 'string' && data.version.trim()) {
            return data.version.trim();
          }
        } catch {
          // Continue searching
        }
      }
    }

    // Walk up looking for package.json with @carefold/cli or version
    let dir = currentDir;
    for (let i = 0; i < 6; i++) {
      const pkgPath = path.join(dir, 'package.json');
      if (fsSync.existsSync(pkgPath)) {
        try {
          const raw = fsSync.readFileSync(pkgPath, 'utf8');
          const data = JSON.parse(raw);
          if (typeof data.version === 'string' && data.version.trim()) {
            return data.version.trim();
          }
        } catch {
          // Continue search
        }
      }
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  } catch {
    // Return fallback on any unexpected error
  }

  return FALLBACK_VERSION;
}
