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
import yaml from 'yaml';
import { loadAgent, AgentManifestSchema, PHASE_0_REGISTRY } from '@carefold/runner';
import { findWorkspaceRoot, getWorkspacePaths, loadWorkspaceConfig } from '../utils/workspace.js';
import { resolveBundledAssets, copyPackDirectory, BUNDLED_AGENTS } from '../utils/assets.js';
import { formatTable, formatRiskBadge } from '../utils/format.js';
import { CliError, ExitCodes } from '../utils/errors.js';

export interface AgentListOptions {
  workspace?: string;
  json?: boolean;
  allowClinical?: boolean;
}

export interface AgentAddOptions {
  workspace?: string;
  force?: boolean;
}

export interface AgentInspectOptions {
  workspace?: string;
  json?: boolean;
}

export async function agentListCommand(options: AgentListOptions = {}): Promise<void> {
  const wsRoot = findWorkspaceRoot(options.workspace);
  const paths = getWorkspacePaths(wsRoot);
  const config = await loadWorkspaceConfig(wsRoot);
  const allowClinical = Boolean(options.allowClinical || config.allow_clinical);

  if (!fsSync.existsSync(paths.agents)) {
    if (options.json) {
      console.log('[]');
    } else {
      console.log(`No installed agents found in ${paths.agents}`);
    }
    return;
  }

  const entries = await fs.readdir(paths.agents, { withFileTypes: true });
  const agentDirs = entries.filter((e) => e.isDirectory()).map((e) => e.name);

  if (agentDirs.length === 0) {
    if (options.json) {
      console.log('[]');
    } else {
      console.log(`No installed agents found in ${paths.agents}`);
    }
    return;
  }

  const agentSummaries: any[] = [];
  const tableRows: string[][] = [];

  for (const dirName of agentDirs) {
    const agentDir = path.join(paths.agents, dirName);
    try {
      const { agent, effectiveTools } = await loadAgent(agentDir, paths.skills);
      const isClinical = agent.risk_class === 'clinical_assist';

      if (isClinical && !allowClinical) {
        process.stderr.write(
          `Warning: Agent "${agent.id}" is classified as "clinical_assist" and disabled. Pass --allow-clinical to enable.\n`
        );
      }

      agentSummaries.push({
        id: agent.id,
        title: agent.title,
        version: agent.version,
        risk_class: agent.risk_class,
        skills: agent.skills,
        effectiveTools,
        clinical_enabled: isClinical ? allowClinical : true
      });

      tableRows.push([
        agent.id,
        agent.title,
        agent.version,
        formatRiskBadge(agent.risk_class),
        agent.skills.join(', ') || '(none)',
        effectiveTools.join(', ') || '(none)'
      ]);
    } catch (err: any) {
      agentSummaries.push({
        id: dirName,
        title: '[INVALID]',
        version: '-',
        risk_class: 'unknown',
        skills: [],
        effectiveTools: [],
        error: err.message
      });

      tableRows.push([dirName, `[INVALID: ${err.message}]`, '-', 'unknown', '-', '-']);
    }
  }

  if (options.json) {
    console.log(JSON.stringify(agentSummaries, null, 2));
  } else {
    const headers = ['ID', 'TITLE', 'VERSION', 'RISK CLASS', 'SKILLS', 'EFFECTIVE TOOLS'];
    console.log(formatTable(headers, tableRows));
  }
}

export async function agentAddCommand(nameOrPath: string, options: AgentAddOptions = {}): Promise<void> {
  if (!nameOrPath || !nameOrPath.trim()) {
    throw new CliError('Missing required argument: <name|path>.', ExitCodes.USER_ERROR);
  }

  const targetName = nameOrPath.trim();
  const wsRoot = findWorkspaceRoot(options.workspace);
  const paths = getWorkspacePaths(wsRoot);

  await fs.mkdir(paths.agents, { recursive: true });
  await fs.mkdir(paths.skills, { recursive: true });

  const isBundled = (BUNDLED_AGENTS as readonly string[]).includes(targetName);

  if (isBundled) {
    const assets = resolveBundledAssets();
    const srcDir = path.join(assets.agentsDir, targetName);
    const destDir = path.join(paths.agents, targetName);

    if (!fsSync.existsSync(srcDir)) {
      throw new CliError(`Bundled agent pack "${targetName}" not found at ${srcDir}.`, ExitCodes.INTERNAL_ERROR);
    }

    await copyPackDirectory(srcDir, destDir, Boolean(options.force));

    // Companion skill auto-resolution
    try {
      const { agent } = await loadAgent(destDir, assets.skillsDir);
      for (const skillId of agent.skills) {
        const destSkillDir = path.join(paths.skills, skillId);
        if (!fsSync.existsSync(destSkillDir)) {
          const srcSkillDir = path.join(assets.skillsDir, skillId);
          if (fsSync.existsSync(srcSkillDir)) {
            await copyPackDirectory(srcSkillDir, destSkillDir, true);
            console.log(`  ✓ Auto-installed companion skill "${skillId}" into skills/${skillId}`);
          }
        }
      }
    } catch {
      // If validation fails during companion copy, proceed
    }

    console.log(`✓ Added reference agent "${targetName}" into agents/${targetName}`);
    return;
  }

  // Check if targetName is a local filesystem directory
  const resolvedLocal = path.resolve(process.cwd(), targetName);
  if (fsSync.existsSync(resolvedLocal)) {
    const stat = await fs.stat(resolvedLocal);
    if (stat.isDirectory()) {
      const agentYamlPath = path.join(resolvedLocal, 'agent.yaml');
      if (!fsSync.existsSync(agentYamlPath)) {
        throw new CliError(
          `Directory "${resolvedLocal}" does not contain a valid agent.yaml manifest.`,
          ExitCodes.USER_ERROR
        );
      }

      // Pre-installation manifest validation
      let manifest: any;
      try {
        const rawYaml = await fs.readFile(agentYamlPath, 'utf8');
        let parsed: any;
        try {
          parsed = yaml.parse(rawYaml);
        } catch (yamlErr: any) {
          throw new CliError(
            `Malformed YAML in "${agentYamlPath}": ${yamlErr.message}`,
            ExitCodes.USER_ERROR
          );
        }
        const parseResult = AgentManifestSchema.safeParse(parsed);
        if (!parseResult.success) {
          const issues = parseResult.error.issues
            .map((i) => `${i.path.join('.')}: ${i.message}`)
            .join(', ');
          throw new CliError(
            `Invalid agent.yaml in "${resolvedLocal}": ${issues}`,
            ExitCodes.USER_ERROR
          );
        }
        manifest = parseResult.data;
        for (const tool of manifest.tools || []) {
          if (!PHASE_0_REGISTRY.includes(tool)) {
            throw new CliError(
              `Tool '${tool}' is not in Phase 0 closed registry [${PHASE_0_REGISTRY.join(', ')}]`,
              ExitCodes.USER_ERROR
            );
          }
        }
      } catch (err: any) {
        if (err instanceof CliError) throw err;
        throw new CliError(
          `Failed to validate agent manifest in "${resolvedLocal}": ${err.message}`,
          ExitCodes.USER_ERROR
        );
      }

      const folderName = path.basename(resolvedLocal);
      const destDir = path.join(paths.agents, folderName);
      await copyPackDirectory(resolvedLocal, destDir, Boolean(options.force));

      // Auto-install companion skills from bundled reference assets if available
      try {
        const assets = resolveBundledAssets();
        for (const skillId of manifest.skills || []) {
          const destSkillDir = path.join(paths.skills, skillId);
          if (!fsSync.existsSync(destSkillDir)) {
            const srcSkillDir = path.join(assets.skillsDir, skillId);
            if (fsSync.existsSync(srcSkillDir)) {
              await copyPackDirectory(srcSkillDir, destSkillDir, true);
              console.log(`  ✓ Auto-installed companion skill "${skillId}" into skills/${skillId}`);
            }
          }
        }
      } catch {
        // If bundled assets are unavailable, proceed cleanly
      }

      console.log(`✓ Added local agent pack from "${resolvedLocal}" into agents/${folderName}`);
      return;
    }
  }

  throw new CliError(
    `Unknown agent "${targetName}". Available bundled agents: ${BUNDLED_AGENTS.join(', ')}.`,
    ExitCodes.USER_ERROR
  );
}

export async function agentInspectCommand(agentId: string, options: AgentInspectOptions = {}): Promise<void> {
  if (!agentId || !agentId.trim()) {
    throw new CliError('Missing required argument: <id>.', ExitCodes.USER_ERROR);
  }

  const id = agentId.trim();
  const wsRoot = findWorkspaceRoot(options.workspace);
  const paths = getWorkspacePaths(wsRoot);
  const agentDir = path.join(paths.agents, id);

  if (!fsSync.existsSync(agentDir)) {
    throw new CliError(`Agent "${id}" not found in ${paths.agents}.`, ExitCodes.USER_ERROR);
  }

  const { agent, effectiveTools, skills } = await loadAgent(agentDir, paths.skills);

  // Read starters if available
  let starters: any[] = [];
  const startersPath = path.join(agentDir, 'starters.json');
  if (fsSync.existsSync(startersPath)) {
    try {
      const rawStarters = await fs.readFile(startersPath, 'utf8');
      starters = JSON.parse(rawStarters);
    } catch {}
  }

  if (options.json) {
    console.log(
      JSON.stringify(
        {
          ...agent,
          effectiveTools,
          resolvedSkills: skills.map((s) => ({ id: s.id, name: s.name, version: s.version })),
          starters
        },
        null,
        2
      )
    );
    return;
  }

  console.log(`\n============================================================`);
  console.log(` Agent: ${agent.title} (${agent.id}) v${agent.version}`);
  console.log(`============================================================`);
  console.log(`Risk Class:      ${formatRiskBadge(agent.risk_class)}`);
  console.log(`License:         ${agent.license || 'Proprietary / Unspecified'}`);
  if (agent.model) {
    if (typeof agent.model === 'string') {
      console.log(`Model Override:  ${agent.model}`);
    } else {
      console.log(`Model Override:  ${agent.model.name} (${agent.model.provider || 'default'})`);
    }
  }

  console.log(`\nDeclared Skills (${agent.skills.length}):`);
  for (const s of skills) {
    console.log(`  • ${s.id} (v${s.version}) — ${s.name}: ${s.description}`);
  }

  console.log(`\nEffective Tools Allowlist (${effectiveTools.length}):`);
  for (const tool of effectiveTools) {
    console.log(`  • ${tool}`);
  }

  if (agent.forbidden && agent.forbidden.length > 0) {
    console.log(`\nForbidden Intents (${agent.forbidden.length}):`);
    for (const f of agent.forbidden) {
      console.log(`  • ${f}`);
    }
  }

  console.log(`\nPersona:`);
  if (typeof agent.persona === 'string') {
    console.log(`  Instructions: ${agent.persona.split('\n')[0]}...`);
  } else {
    console.log(`  Role:         ${agent.persona.role}`);
    console.log(`  Tone:         ${agent.persona.tone}`);
    console.log(`  Instructions: ${agent.persona.instructions.split('\n')[0]}...`);
  }

  if (starters.length > 0) {
    console.log(`\nStarters / Quick Prompts:`);
    for (const st of starters) {
      if (typeof st === 'string') {
        console.log(`  • "${st}"`);
      } else if (typeof st === 'object' && st !== null) {
        const prompt = (st as any).prompt ?? (st as any).text ?? '';
        const label = (st as any).label;
        if (label) {
          console.log(`  • [${label}] "${prompt}"`);
        } else {
          console.log(`  • "${prompt}"`);
        }
      } else {
        console.log(`  • "${String(st)}"`);
      }
    }
  }
  console.log('');
}
