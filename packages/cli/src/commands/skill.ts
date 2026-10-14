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
import { loadSkill, type SkillManifest } from '@carefold/runner';
import { findWorkspaceRoot, getWorkspacePaths, loadWorkspaceConfig } from '../utils/workspace.js';
import { resolveBundledAssets, copyPackDirectory, BUNDLED_SKILLS } from '../utils/assets.js';
import { formatTable, formatRiskBadge } from '../utils/format.js';
import { CliError, ExitCodes } from '../utils/errors.js';

export interface SkillListOptions {
  workspace?: string;
  json?: boolean;
  allowClinical?: boolean;
}

export interface SkillAddOptions {
  workspace?: string;
  force?: boolean;
}

export async function skillListCommand(options: SkillListOptions = {}): Promise<void> {
  const wsRoot = findWorkspaceRoot(options.workspace);
  const paths = getWorkspacePaths(wsRoot);
  const config = await loadWorkspaceConfig(wsRoot);
  const allowClinical = Boolean(options.allowClinical || config.allow_clinical);

  if (!fsSync.existsSync(paths.skills)) {
    if (options.json) {
      console.log('[]');
    } else {
      console.log(`No installed skills found in ${paths.skills}`);
    }
    return;
  }

  const entries = await fs.readdir(paths.skills, { withFileTypes: true });
  const skillDirs = entries.filter((e) => e.isDirectory() && !e.name.startsWith('.')).map((e) => e.name);

  if (skillDirs.length === 0) {
    if (options.json) {
      console.log('[]');
    } else {
      console.log(`No installed skills found in ${paths.skills}`);
    }
    return;
  }

  const validSkills: SkillManifest[] = [];
  const brokenSkills: { id: string; error: string }[] = [];

  for (const dirName of skillDirs) {
    const skillDir = path.join(paths.skills, dirName);
    try {
      const skill = await loadSkill(skillDir);
      validSkills.push(skill);
    } catch (err: any) {
      brokenSkills.push({ id: dirName, error: err.message });
    }
  }

  // Handle clinical_assist gating
  let visibleSkills = validSkills;
  const clinicalSkills = validSkills.filter((s) => s.risk_class === 'clinical_assist');
  if (clinicalSkills.length > 0) {
    if (!allowClinical) {
      process.stderr.write(
        `Warning: Clinical assist skills detected (${clinicalSkills.map((s) => s.id).join(', ')}). ` +
        `Pass --allow-clinical to enable clinical assist skills.\n`
      );
      visibleSkills = validSkills.filter((s) => s.risk_class !== 'clinical_assist');
    } else {
      process.stderr.write(
        `Notice: Clinical assist mode enabled. Clinical skills require appropriate clinical governance.\n`
      );
    }
  }

  if (options.json) {
    const jsonOutput: any[] = [
      ...visibleSkills.map((s) => ({
        id: s.id,
        name: s.name,
        description: s.description,
        version: s.version || '0.1.0',
        risk_class: s.risk_class,
        tools: s.tools || [],
        is_verified: s.is_verified,
        unverified: s.unverified
      })),
      ...brokenSkills.map((b) => ({
        id: b.id,
        name: '[INVALID]',
        description: '',
        version: '-',
        risk_class: 'unknown',
        tools: [],
        error: b.error
      }))
    ];
    console.log(JSON.stringify(jsonOutput, null, 2));
    return;
  }

  const tableRows: string[][] = [
    ...visibleSkills.map((s) => {
      let riskDisplay = formatRiskBadge(s.risk_class);
      if ((s as any).unverified) {
        riskDisplay += ' [unverified]';
      }
      return [
        s.id,
        s.name,
        s.version || '0.1.0',
        riskDisplay,
        (s.tools || []).join(', ') || '(none)'
      ];
    }),
    ...brokenSkills.map((b) => [
      b.id,
      `[INVALID: ${b.error}]`,
      '-',
      'unknown',
      '-'
    ])
  ];

  const headers = ['ID', 'NAME', 'VERSION', 'RISK CLASS', 'TOOLS'];
  console.log(formatTable(headers, tableRows));
}

export async function skillAddCommand(nameOrPath: string, options: SkillAddOptions = {}): Promise<void> {
  if (!nameOrPath || !nameOrPath.trim()) {
    throw new CliError('Missing required argument: <name|path>.', ExitCodes.USER_ERROR);
  }

  const targetName = nameOrPath.trim();
  const wsRoot = findWorkspaceRoot(options.workspace);
  const paths = getWorkspacePaths(wsRoot);

  await fs.mkdir(paths.skills, { recursive: true });

  const isBundled = (BUNDLED_SKILLS as readonly string[]).includes(targetName);

  if (isBundled) {
    const assets = resolveBundledAssets();
    const srcDir = path.join(assets.skillsDir, targetName);
    const destDir = path.join(paths.skills, targetName);

    if (!fsSync.existsSync(srcDir)) {
      throw new CliError(`Bundled skill pack "${targetName}" not found at ${srcDir}.`, ExitCodes.INTERNAL_ERROR);
    }

    await copyPackDirectory(srcDir, destDir, Boolean(options.force));
    console.log(`✓ Added reference skill "${targetName}" into skills/${targetName}`);
    return;
  }

  // Check if targetName is a local filesystem directory
  const resolvedLocal = path.resolve(process.cwd(), targetName);
  if (fsSync.existsSync(resolvedLocal)) {
    const stat = await fs.stat(resolvedLocal);
    if (stat.isDirectory()) {
      const skillMdPath = path.join(resolvedLocal, 'SKILL.md');
      if (!fsSync.existsSync(skillMdPath)) {
        throw new CliError(
          `Directory "${resolvedLocal}" does not contain a required SKILL.md file.`,
          ExitCodes.USER_ERROR
        );
      }

      // Verify skill loading
      await loadSkill(resolvedLocal);

      const folderName = path.basename(resolvedLocal);
      const destDir = path.join(paths.skills, folderName);
      await copyPackDirectory(resolvedLocal, destDir, Boolean(options.force));
      console.log(`✓ Added local skill pack from "${resolvedLocal}" into skills/${folderName}`);
      return;
    }
  }

  throw new CliError(
    `Unknown skill "${targetName}". Available bundled skills: ${BUNDLED_SKILLS.join(', ')}.`,
    ExitCodes.USER_ERROR
  );
}
