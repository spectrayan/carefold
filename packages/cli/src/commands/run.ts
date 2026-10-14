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
import fsSync from 'node:fs';
import os from 'node:os';
import yaml from 'yaml';
import {
  executeAgentRun,
  loadAgent,
  loadSkill,
  recordAudit,
  SAFE_REFUSAL_TEMPLATE,
  type RunOptions,
  type AuditEvent
} from '@carefold/runner';
import { findWorkspaceRoot, getWorkspacePaths, loadWorkspaceConfig } from '../utils/workspace.js';
import { CliError, ExitCodes } from '../utils/errors.js';

export interface RunCommandOptions {
  agent?: string;
  skill?: string;
  provider?: string;
  model?: string;
  key?: string;
  endpoint?: string;
  mock?: boolean;
  allowClinical?: boolean;
  workspace?: string;
  json?: boolean;
}

export async function runCommand(
  prompt: string | undefined,
  options: RunCommandOptions,
  extraArgs?: string[]
): Promise<void> {
  // Support positional invocation: carefold run <agent-id> "<prompt>"
  let effectivePrompt = prompt;
  if (!options.agent && !options.skill && extraArgs && extraArgs.length >= 2) {
    options.agent = extraArgs[0];
    effectivePrompt = extraArgs.slice(1).join(' ');
  } else if (!effectivePrompt && extraArgs && extraArgs.length === 1) {
    effectivePrompt = extraArgs[0];
  }

  // Validate prompt argument
  const trimmedPrompt = (effectivePrompt || '').trim();
  if (!trimmedPrompt) {
    throw new CliError(
      'Missing required argument <prompt>.\nUsage: carefold run --agent <id> "<prompt>"',
      ExitCodes.USER_ERROR
    );
  }

  // Validate agent or skill target
  if (!options.agent && !options.skill) {
    throw new CliError(
      'Either --agent <id> or --skill <id> is required.\nRun "carefold agent list" to view installed agents.',
      ExitCodes.USER_ERROR
    );
  }

  const wsRoot = findWorkspaceRoot(options.workspace);
  const paths = getWorkspacePaths(wsRoot);
  const config = await loadWorkspaceConfig(wsRoot);

  // Apply CLI overrides to config
  if (options.allowClinical) {
    config.allow_clinical = true;
  }

  // Ensure config.model is defined
  config.model = {
    provider: 'ollama',
    baseUrl: 'http://127.0.0.1:11434/v1',
    model: 'llama3.2',
    apiKey: '',
    ...config.model
  };

  // 1. Model provider override
  if (options.provider) {
    config.model.provider = options.provider.trim();
  }

  // 2. Model name override (with smart defaults if provider changed and model omitted)
  if (options.model) {
    config.model.model = options.model.trim();
  } else if (options.provider) {
    const prov = (config.model.provider || '').toLowerCase();
    if ((prov === 'google' || prov === 'gemini') && (!config.model.model || config.model.model === 'llama3.2')) {
      config.model.model = 'gemini-2.0-flash';
    } else if ((prov === 'anthropic' || prov === 'claude') && (!config.model.model || config.model.model === 'llama3.2')) {
      config.model.model = 'claude-3-5-sonnet-latest';
    } else if (prov === 'openai' && (!config.model.model || config.model.model === 'llama3.2')) {
      config.model.model = 'gpt-4o';
    }
  }

  // 3. Model endpoint (baseUrl) override
  if (options.endpoint) {
    config.model.baseUrl = options.endpoint.trim();
  } else if (config.model.provider?.toLowerCase() === 'openai' && (!config.model.baseUrl || config.model.baseUrl.includes('11434'))) {
    config.model.baseUrl = 'https://api.openai.com/v1';
  }

  // 4. API key override: direct option takes top precedence
  if (options.key) {
    config.model.apiKey = options.key.trim();
  }

  // 5. Environment variable fallback if apiKey is empty
  const provider = (config.model.provider || 'ollama').toLowerCase();
  if (!config.model.apiKey || !config.model.apiKey.trim()) {
    if (provider === 'google' || provider === 'gemini') {
      const envKey = process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
      if (envKey && envKey.trim()) {
        config.model.apiKey = envKey.trim();
      }
    } else if (provider === 'anthropic' || provider === 'claude') {
      const envKey = process.env.ANTHROPIC_API_KEY;
      if (envKey && envKey.trim()) {
        config.model.apiKey = envKey.trim();
      }
    } else if (provider === 'openai') {
      const envKey = process.env.OPENAI_API_KEY;
      if (envKey && envKey.trim()) {
        config.model.apiKey = envKey.trim();
      }
    } else if (provider === 'custom') {
      const envKey = process.env.CUSTOM_API_KEY || process.env.OPENAI_API_KEY;
      if (envKey && envKey.trim()) {
        config.model.apiKey = envKey.trim();
      }
    }
  }

  // 6. Validate API key for cloud providers in non-mock execution
  if (!options.mock && (provider === 'google' || provider === 'gemini' || provider === 'anthropic' || provider === 'claude' || provider === 'openai')) {
    if (!config.model.apiKey || !config.model.apiKey.trim()) {
      const envVarMap: Record<string, string> = {
        google: 'GEMINI_API_KEY or GOOGLE_API_KEY',
        gemini: 'GEMINI_API_KEY or GOOGLE_API_KEY',
        anthropic: 'ANTHROPIC_API_KEY',
        claude: 'ANTHROPIC_API_KEY',
        openai: 'OPENAI_API_KEY'
      };
      throw new CliError(
        `API key for provider '${provider}' is missing.\n` +
        `Please pass --key <key> or set ${envVarMap[provider] || 'API key'} in environment.`,
        ExitCodes.USER_ERROR
      );
    }
  }

  let agentDir: string;
  let agentId: string;
  let tempAgentDir: string | null = null;
  const skillsDir = paths.skills;

  try {
    if (options.agent) {
      agentId = options.agent;
      agentDir = path.resolve(paths.agents, agentId);

      // Verify agent directory exists
      if (!fsSync.existsSync(agentDir)) {
        throw new CliError(
          `Agent "${agentId}" not found in ${paths.agents}.\nRun "carefold agent list" to see installed agents.`,
          ExitCodes.USER_ERROR
        );
      }

      // Pre-flight manifest check & clinical risk gate
      const { agent } = await loadAgent(agentDir, skillsDir);
      if (agent.risk_class === 'clinical_assist' && !config.allow_clinical) {
        throw new CliError(
          `Agent "${agent.id}" (or an attached skill) is classified as "clinical_assist".\n` +
          `Execution blocked. Pass --allow-clinical to run clinical assist agents.`,
          ExitCodes.USER_ERROR
        );
      }
    } else {
      // Contributor raw skill run
      const skillId = options.skill!;
      const skillPath = path.resolve(skillsDir, skillId);
      if (!fsSync.existsSync(skillPath)) {
        throw new CliError(
          `Skill "${skillId}" not found in ${skillsDir}.\nRun "carefold skill list" to see installed skills.`,
          ExitCodes.USER_ERROR
        );
      }

      const skill = await loadSkill(skillPath);

      if (skill.risk_class === 'clinical_assist' && !config.allow_clinical) {
        throw new CliError(
          `Skill "${skill.id}" is classified as "clinical_assist".\n` +
          `Execution blocked. Pass --allow-clinical to run clinical assist skills.`,
          ExitCodes.USER_ERROR
        );
      }

      // Create ephemeral agent harness for the raw skill
      agentId = `skill-runner-${skillId}`;
      tempAgentDir = await fs.mkdtemp(path.join(os.tmpdir(), 'carefold-skill-run-'));
      agentDir = tempAgentDir;

      const syntheticAgent = {
        id: agentId,
        title: `Skill Runner: ${skill.name}`,
        version: '0.1.0',
        risk_class: skill.risk_class,
        skills: [skillId],
        tools: skill.tools || [],
        persona: {
          role: 'Skill Runner',
          tone: 'neutral',
          instructions: `You are an evaluation assistant running skill '${skill.name}'. ${skill.instructions || ''}`
        }
      };

      await fs.writeFile(path.join(tempAgentDir, 'agent.yaml'), yaml.stringify(syntheticAgent), 'utf8');
    }

    const runOptions: RunOptions = {
      agentDir,
      agentId,
      skillsDir,
      workspaceDir: wsRoot,
      workspaceRoot: wsRoot,
      prompt: trimmedPrompt,
      config,
      mockModel: options.mock ? true : undefined
    };

    let tokenStreamed = false;
    let refusalEncountered = false;

    for await (const chunk of executeAgentRun(runOptions)) {
      if (options.json) {
        process.stdout.write(JSON.stringify(chunk) + '\n');
        continue;
      }

      switch (chunk.type) {
        case 'token':
          process.stdout.write(chunk.delta);
          tokenStreamed = true;
          break;

        case 'tool_start':
          process.stderr.write(`\n[tool: ${chunk.tool} params: ${JSON.stringify(chunk.input)}]\n`);
          break;

        case 'tool_end':
          process.stderr.write(`[tool: ${chunk.tool} ${chunk.status} (${chunk.duration_ms}ms)]\n\n`);
          break;

        case 'tool_call':
          if (chunk.status === 'denied') {
            process.stderr.write(`[tool: ${chunk.tool} DENIED: ${chunk.result?.error || 'Undeclared tool'}]\n\n`);
          }
          break;

        case 'refusal':
          refusalEncountered = true;
          if (tokenStreamed) {
            process.stdout.write('\n\n');
          }
          process.stderr.write(`[refusal: ${chunk.reason}]\n`);
          process.stdout.write(`${chunk.message || SAFE_REFUSAL_TEMPLATE}\n`);
          break;

        case 'error':
          process.stderr.write(`\n[error: ${chunk.error}]\n`);
          break;
      }
    }

    // Trailing newline for clean terminal prompt if tokens were printed
    if (tokenStreamed && !refusalEncountered && !options.json) {
      process.stdout.write('\n');
    }
  } catch (err: any) {
    if (err instanceof CliError) {
      throw err;
    }

    // Record audit event for unexpected runtime failure
    try {
      const errorAuditEvent: AuditEvent = {
        ts: new Date().toISOString(),
        agent_id: agentId! || options.agent || options.skill || 'unknown',
        event: 'error',
        allowed: false,
        reason: err.message || 'Execution failed'
      };
      await recordAudit(errorAuditEvent, config, wsRoot);
    } catch {}

    if (err.message && (err.message.includes('fetch failed') || err.message.includes('ECONNREFUSED'))) {
      throw new CliError(
        `Failed to connect to model endpoint at ${config.model?.baseUrl || 'http://127.0.0.1:11434/v1'}.\n` +
        `Hint: Ensure Ollama is running, or pass --mock for offline mode.`,
        ExitCodes.USER_ERROR
      );
    }

    throw new CliError(err.message || String(err), ExitCodes.USER_ERROR);
  } finally {
    if (tempAgentDir) {
      await fs.rm(tempAgentDir, { recursive: true, force: true }).catch(() => {});
    }
  }
}
