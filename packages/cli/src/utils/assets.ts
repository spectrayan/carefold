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
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CliError, ExitCodes } from './errors.js';

export interface BundledAssets {
  agentsDir: string;
  skillsDir: string;
  evalsDir?: string;
}

export const BUNDLED_AGENTS = ['visit-steward', 'benefits-guide', 'habit-companion', '_template'] as const;
export const BUNDLED_SKILLS = ['visit-prep', 'benefits-explainer', 'habit-checkin', '_template'] as const;

export function resolveBundledAssets(): BundledAssets {
  if (process.env.CAREFOLD_BUNDLED_ASSETS) {
    const agentsDir = path.join(process.env.CAREFOLD_BUNDLED_ASSETS, 'agents');
    const skillsDir = path.join(process.env.CAREFOLD_BUNDLED_ASSETS, 'skills');
    if (fsSync.existsSync(agentsDir) && fsSync.existsSync(skillsDir)) {
      return {
        agentsDir,
        skillsDir,
        evalsDir: path.join(process.env.CAREFOLD_BUNDLED_ASSETS, 'evals')
      };
    }
  }

  // Walk up from current module file to find repository root containing agents/ and skills/
  let current = path.dirname(fileURLToPath(import.meta.url));
  for (let i = 0; i < 8; i++) {
    const candidateAgents = path.join(current, 'agents');
    const candidateSkills = path.join(current, 'skills');
    if (
      fsSync.existsSync(candidateAgents) &&
      fsSync.existsSync(candidateSkills) &&
      fsSync.existsSync(path.join(candidateAgents, 'visit-steward'))
    ) {
      return {
        agentsDir: candidateAgents,
        skillsDir: candidateSkills,
        evalsDir: path.join(current, 'evals')
      };
    }
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }

  // Fallback check against process.cwd()
  const cwdAgents = path.join(process.cwd(), 'agents');
  const cwdSkills = path.join(process.cwd(), 'skills');
  if (
    fsSync.existsSync(cwdAgents) &&
    fsSync.existsSync(cwdSkills) &&
    fsSync.existsSync(path.join(cwdAgents, 'visit-steward'))
  ) {
    return {
      agentsDir: cwdAgents,
      skillsDir: cwdSkills,
      evalsDir: path.join(process.cwd(), 'evals')
    };
  }

  throw new CliError(
    'Unable to locate bundled reference agents and skills in environment or package distribution.',
    ExitCodes.INTERNAL_ERROR
  );
}

export async function copyPackDirectory(src: string, dest: string, overwrite = false): Promise<void> {
  const destExists = fsSync.existsSync(dest);
  if (destExists && !overwrite) {
    throw new CliError(`Target directory "${dest}" already exists. Use --force to overwrite.`, ExitCodes.USER_ERROR);
  }

  await fs.mkdir(dest, { recursive: true });
  await fs.cp(src, dest, { recursive: true, force: overwrite });
}
