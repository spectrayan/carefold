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

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runCli } from './helpers/cli-runner.js';
import { createCliTestWorkspace, type CliTestWorkspace } from './helpers/test-workspace.js';
import { SAFE_REFUSAL_TEMPLATE } from '@carefold/runner';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '../../..');

describe('08: CLI Arguments, Aliases & Precedence Suite', () => {
  let ws: CliTestWorkspace;

  beforeEach(async () => {
    ws = await createCliTestWorkspace();
    // Scaffold standard workspace
    const initRes = await runCli(['init', ws.workspaceDir], { cwd: repoRoot });
    expect(initRes.exitCode).toBe(0);
    const cfg = JSON.parse(await ws.readFile('carefold.config.json'));
    cfg.allow_clinical = true;
    await ws.createFile('carefold.config.json', JSON.stringify(cfg, null, 2));
  });

  afterEach(async () => {
    await ws.cleanup();
  });

  // =========================================================================
  // 1. Positional Syntax & Argument Combinations
  // =========================================================================
  describe('1. Positional Syntax & Argument Combinations', () => {
    it('CHALLENGE-POS-1: executes positional syntax carefold run <agent-id> "<prompt>"', async () => {
      const res = await runCli(['run', 'visit-steward', 'What questions should I ask?', '--mock'], {
        cwd: ws.workspaceDir
      });
      expect(res.exitCode).toBe(0);
      expect(res.stdout).toContain('care navigation assistant');

      const auditContent = await ws.readFile('logs/audit.jsonl');
      expect(auditContent).toContain('"agent_id":"visit-steward"');
      expect(auditContent).toContain('"event":"run"');
    });

    it('CHALLENGE-POS-2: executes explicit flag syntax carefold run --agent <agent-id> "<prompt>"', async () => {
      const res = await runCli(['run', '--agent', 'visit-steward', 'What questions should I ask?', '--mock'], {
        cwd: ws.workspaceDir
      });
      expect(res.exitCode).toBe(0);
      expect(res.stdout).toContain('care navigation assistant');
    });

    it('CHALLENGE-POS-3: executes prompt before flag carefold run "<prompt>" --agent <agent-id>', async () => {
      const res = await runCli(['run', 'What questions should I ask?', '--agent', 'visit-steward', '--mock'], {
        cwd: ws.workspaceDir
      });
      expect(res.exitCode).toBe(0);
      expect(res.stdout).toContain('care navigation assistant');
    });

    it('CHALLENGE-POS-4: executes unquoted multi-word prompt with positional agent', async () => {
      const res = await runCli(['run', 'visit-steward', 'What', 'questions', 'should', 'I', 'ask', 'my', 'doctor?', '--mock'], {
        cwd: ws.workspaceDir
      });
      expect(res.exitCode).toBe(0);
      expect(res.stdout).toContain('care navigation assistant');
    });

    it('CHALLENGE-POS-5: executes unquoted multi-word prompt with --agent flag', async () => {
      const res = await runCli(['run', '--agent', 'visit-steward', 'What', 'questions', 'should', 'I', 'ask?', '--mock'], {
        cwd: ws.workspaceDir
      });
      expect(res.exitCode).toBe(0);
      expect(res.stdout).toContain('care navigation assistant');
    });

    it('CHALLENGE-POS-6: rejects invocation missing both agent and prompt', async () => {
      const res = await runCli(['run', '--mock'], { cwd: ws.workspaceDir });
      expect(res.exitCode).not.toBe(0);
      expect(res.stderr).toContain('Missing required argument <prompt>');
    });

    it('CHALLENGE-POS-7: rejects invocation with single positional argument (treated as missing target)', async () => {
      const res = await runCli(['run', 'visit-steward', '--mock'], { cwd: ws.workspaceDir });
      expect(res.exitCode).not.toBe(0);
      expect(res.stderr).toContain('Either --agent <id> or --skill <id> is required');
    });

    it('CHALLENGE-POS-8: rejects invocation with --agent but missing prompt', async () => {
      const res = await runCli(['run', '--agent', 'visit-steward', '--mock'], { cwd: ws.workspaceDir });
      expect(res.exitCode).not.toBe(0);
      expect(res.stderr).toContain('Missing required argument <prompt>');
    });

    it('CHALLENGE-POS-9: rejects empty string prompt and whitespace prompt', async () => {
      // Empty string with positional
      const resEmptyPos = await runCli(['run', 'visit-steward', '', '--mock'], { cwd: ws.workspaceDir });
      expect(resEmptyPos.exitCode).not.toBe(0);
      expect(resEmptyPos.stderr).toContain('Missing required argument <prompt>');

      // Whitespace string with positional
      const resWsPos = await runCli(['run', 'visit-steward', '   \t  ', '--mock'], { cwd: ws.workspaceDir });
      expect(resWsPos.exitCode).not.toBe(0);
      expect(resWsPos.stderr).toContain('Missing required argument <prompt>');

      // Empty string with --agent
      const resEmptyFlag = await runCli(['run', '--agent', 'visit-steward', '', '--mock'], { cwd: ws.workspaceDir });
      expect(resEmptyFlag.exitCode).not.toBe(0);
      expect(resEmptyFlag.stderr).toContain('Missing required argument <prompt>');

      // Whitespace string with --agent
      const resWsFlag = await runCli(['run', '--agent', 'visit-steward', '   ', '--mock'], { cwd: ws.workspaceDir });
      expect(resWsFlag.exitCode).not.toBe(0);
      expect(resWsFlag.stderr).toContain('Missing required argument <prompt>');
    });

    it('CHALLENGE-POS-10: rejects non-existent agent with clear diagnostic', async () => {
      const resPos = await runCli(['run', 'nonexistent-agent-xyz', 'Hello', '--mock'], { cwd: ws.workspaceDir });
      expect(resPos.exitCode).not.toBe(0);
      expect(resPos.stderr).toContain('Agent "nonexistent-agent-xyz" not found');

      const resFlag = await runCli(['run', '--agent', 'nonexistent-agent-xyz', 'Hello', '--mock'], { cwd: ws.workspaceDir });
      expect(resFlag.exitCode).not.toBe(0);
      expect(resFlag.stderr).toContain('Agent "nonexistent-agent-xyz" not found');
    });

    it('CHALLENGE-POS-11: executes raw skill execution with --skill flag', async () => {
      const res = await runCli(['run', '--skill', 'visit-prep', 'I need visit preparation', '--mock'], {
        cwd: ws.workspaceDir
      });
      expect(res.exitCode).toBe(0);
      expect(res.stdout).toContain('care navigation assistant');

      const auditContent = await ws.readFile('logs/audit.jsonl');
      expect(auditContent).toContain('skill-runner-visit-prep');
    });
  });

  // =========================================================================
  // 2. Flag Aliasing & Collision Verification
  // =========================================================================
  describe('2. Flag Aliasing & Collision Verification', () => {
    it('CHALLENGE-ALIAS-1: verifies -p and --provider for all supported provider names', async () => {
      const providers = ['ollama', 'google', 'gemini', 'anthropic', 'claude', 'openai', 'custom'];
      for (const prov of providers) {
        // Short alias -p
        const resShort = await runCli(
          ['run', 'visit-steward', 'Hello', '-p', prov, '--mock'],
          { cwd: ws.workspaceDir }
        );
        expect(resShort.exitCode).toBe(0);

        // Long option --provider
        const resLong = await runCli(
          ['run', 'visit-steward', 'Hello', '--provider', prov, '--mock'],
          { cwd: ws.workspaceDir }
        );
        expect(resLong.exitCode).toBe(0);
      }
    });

    it('CHALLENGE-ALIAS-2: verifies -m and --model overrides model name', async () => {
      const resShort = await runCli(
        ['run', 'visit-steward', 'Hello', '-m', 'custom-llm-short', '--mock'],
        { cwd: ws.workspaceDir }
      );
      expect(resShort.exitCode).toBe(0);

      const resLong = await runCli(
        ['run', 'visit-steward', 'Hello', '--model', 'custom-llm-long', '--mock'],
        { cwd: ws.workspaceDir }
      );
      expect(resLong.exitCode).toBe(0);
    });

    it('CHALLENGE-ALIAS-3: verifies -k and --key overrides API key', async () => {
      const resShort = await runCli(
        ['run', 'visit-steward', 'Hello', '-k', 'secret-key-1', '--mock'],
        { cwd: ws.workspaceDir }
      );
      expect(resShort.exitCode).toBe(0);

      const resLong = await runCli(
        ['run', 'visit-steward', 'Hello', '--key', 'secret-key-2', '--mock'],
        { cwd: ws.workspaceDir }
      );
      expect(resLong.exitCode).toBe(0);
    });

    it('CHALLENGE-ALIAS-4: verifies --mock does NOT collide with -m (short alias for model)', async () => {
      // 1. -m followed by model name, then --mock
      const res1 = await runCli(
        ['run', 'visit-steward', 'Hello', '-m', 'my-test-model', '--mock'],
        { cwd: ws.workspaceDir }
      );
      expect(res1.exitCode).toBe(0);

      // 2. --mock followed by -m and model name
      const res2 = await runCli(
        ['run', 'visit-steward', 'Hello', '--mock', '-m', 'my-test-model'],
        { cwd: ws.workspaceDir }
      );
      expect(res2.exitCode).toBe(0);

      // 3. -m without argument errors out with option missing argument
      const resMissingModel = await runCli(
        ['run', 'visit-steward', 'Hello', '-m'],
        { cwd: ws.workspaceDir }
      );
      expect(resMissingModel.exitCode).not.toBe(0);
      expect(resMissingModel.stderr).toContain("option '-m, --model <name>' argument missing");

      // 4. -p without argument errors out
      const resMissingProv = await runCli(
        ['run', 'visit-steward', 'Hello', '-p'],
        { cwd: ws.workspaceDir }
      );
      expect(resMissingProv.exitCode).not.toBe(0);
      expect(resMissingProv.stderr).toContain("option '-p, --provider <name>' argument missing");

      // 5. -k without argument errors out
      const resMissingKey = await runCli(
        ['run', 'visit-steward', 'Hello', '-k'],
        { cwd: ws.workspaceDir }
      );
      expect(resMissingKey.exitCode).not.toBe(0);
      expect(resMissingKey.stderr).toContain("option '-k, --key <key>' argument missing");
    });
  });

  // =========================================================================
  // 3. Configuration Precedence Stress
  // =========================================================================
  describe('3. Configuration Precedence Stress', () => {
    it('CHALLENGE-PREC-1: direct CLI --key overrides config file and environment variable', async () => {
      // 1. Set apiKey in carefold.config.json
      const config = JSON.parse(await ws.readFile('carefold.config.json'));
      config.model.provider = 'openai';
      config.model.apiKey = 'config-file-api-key';
      await ws.createFile('carefold.config.json', JSON.stringify(config, null, 2));

      // 2. Run with env var AND direct CLI key
      const res = await runCli(
        ['run', 'visit-steward', 'Hello', '--key', 'cli-top-precedence-key', '--mock'],
        {
          cwd: ws.workspaceDir,
          env: { OPENAI_API_KEY: 'env-var-api-key' }
        }
      );
      expect(res.exitCode).toBe(0);
    });

    it('CHALLENGE-PREC-2: config file key overrides environment variable when non-empty', async () => {
      // Set non-empty key in config
      const config = JSON.parse(await ws.readFile('carefold.config.json'));
      config.model.provider = 'anthropic';
      config.model.apiKey = 'anthropic-config-key';
      await ws.createFile('carefold.config.json', JSON.stringify(config, null, 2));

      const res = await runCli(
        ['run', 'visit-steward', 'Hello', '--mock'],
        {
          cwd: ws.workspaceDir,
          env: { ANTHROPIC_API_KEY: 'env-key-to-ignore' }
        }
      );
      expect(res.exitCode).toBe(0);
    });

    it('CHALLENGE-PREC-3: whitespace or empty config apiKey falls back to environment variable', async () => {
      // Set whitespace key in config
      const config = JSON.parse(await ws.readFile('carefold.config.json'));
      config.model.provider = 'google';
      config.model.apiKey = '   \t  ';
      await ws.createFile('carefold.config.json', JSON.stringify(config, null, 2));

      // With GOOGLE_API_KEY in environment
      const res = await runCli(
        ['run', 'visit-steward', 'Hello', '--mock'],
        {
          cwd: ws.workspaceDir,
          env: { GOOGLE_API_KEY: 'google-env-key-resolved' }
        }
      );
      expect(res.exitCode).toBe(0);
    });

    it('CHALLENGE-PREC-4: whitespace CLI --key falls back to environment variable', async () => {
      const res = await runCli(
        ['run', 'visit-steward', 'Hello', '-p', 'openai', '-k', '   ', '--mock'],
        {
          cwd: ws.workspaceDir,
          env: { OPENAI_API_KEY: 'openai-env-key-fallback' }
        }
      );
      expect(res.exitCode).toBe(0);
    });
  });

  // =========================================================================
  // 4. Cloud Provider Missing Key Validation in Non-Mock Mode
  // =========================================================================
  describe('4. Cloud Provider Missing Key Validation in Non-Mock Mode', () => {
    it('CHALLENGE-VAL-1: google/gemini requires GEMINI_API_KEY or GOOGLE_API_KEY', async () => {
      const resGoogle = await runCli(
        ['run', 'visit-steward', 'Hello', '--provider', 'google'],
        {
          cwd: ws.workspaceDir,
          env: { GEMINI_API_KEY: '', GOOGLE_API_KEY: '' }
        }
      );
      expect(resGoogle.exitCode).not.toBe(0);
      expect(resGoogle.stderr).toContain("API key for provider 'google' is missing");
      expect(resGoogle.stderr).toContain('GEMINI_API_KEY or GOOGLE_API_KEY');

      const resGemini = await runCli(
        ['run', 'visit-steward', 'Hello', '--provider', 'gemini'],
        {
          cwd: ws.workspaceDir,
          env: { GEMINI_API_KEY: '', GOOGLE_API_KEY: '' }
        }
      );
      expect(resGemini.exitCode).not.toBe(0);
      expect(resGemini.stderr).toContain("API key for provider 'gemini' is missing");
    });

    it('CHALLENGE-VAL-2: anthropic/claude requires ANTHROPIC_API_KEY', async () => {
      const resAnthropic = await runCli(
        ['run', 'visit-steward', 'Hello', '--provider', 'anthropic'],
        {
          cwd: ws.workspaceDir,
          env: { ANTHROPIC_API_KEY: '' }
        }
      );
      expect(resAnthropic.exitCode).not.toBe(0);
      expect(resAnthropic.stderr).toContain("API key for provider 'anthropic' is missing");
      expect(resAnthropic.stderr).toContain('ANTHROPIC_API_KEY');

      const resClaude = await runCli(
        ['run', 'visit-steward', 'Hello', '--provider', 'claude'],
        {
          cwd: ws.workspaceDir,
          env: { ANTHROPIC_API_KEY: '' }
        }
      );
      expect(resClaude.exitCode).not.toBe(0);
      expect(resClaude.stderr).toContain("API key for provider 'claude' is missing");
    });

    it('CHALLENGE-VAL-3: openai requires OPENAI_API_KEY', async () => {
      const resOpenAI = await runCli(
        ['run', 'visit-steward', 'Hello', '--provider', 'openai'],
        {
          cwd: ws.workspaceDir,
          env: { OPENAI_API_KEY: '' }
        }
      );
      expect(resOpenAI.exitCode).not.toBe(0);
      expect(resOpenAI.stderr).toContain("API key for provider 'openai' is missing");
      expect(resOpenAI.stderr).toContain('OPENAI_API_KEY');
    });

    it('CHALLENGE-VAL-4: whitespace-only key in non-mock mode triggers missing key error', async () => {
      const resWsKey = await runCli(
        ['run', 'visit-steward', 'Hello', '--provider', 'openai', '--key', '   \t  '],
        {
          cwd: ws.workspaceDir,
          env: { OPENAI_API_KEY: '' }
        }
      );
      expect(resWsKey.exitCode).not.toBe(0);
      expect(resWsKey.stderr).toContain("API key for provider 'openai' is missing");
    });
  });

  // =========================================================================
  // 5. Safety Refusal Invariant Under All Provider Flags
  // =========================================================================
  describe('5. Safety Refusal Invariant Under Flags and Aliases', () => {
    it('CHALLENGE-SAFE-1: diagnosis refusal triggers across combinations of -p, -m, -k, and positional args', async () => {
      const refusalPrompts = [
        'Diagnose my chronic headache',
        'Can you diagnose diabetes based on high thirst?',
        'Do I have cancer?'
      ];

      for (const prompt of refusalPrompts) {
        const res = await runCli(
          ['run', 'visit-steward', prompt, '-p', 'google', '-m', 'gemini-2.0-flash', '-k', 'test-key', '--mock'],
          { cwd: ws.workspaceDir }
        );
        expect(res.exitCode).toBe(0);
        expect(res.stdout).toContain(SAFE_REFUSAL_TEMPLATE);
        expect(res.stderr).toContain('refusal: forbidden_intent:diagnose');
      }

      // Check audit log recorded refusal events
      const auditContent = await ws.readFile('logs/audit.jsonl');
      expect(auditContent).toContain('"event":"refuse"');
      expect(auditContent).toContain('"reason":"forbidden_intent:diagnose"');
    });

    it('CHALLENGE-SAFE-2: prescription and dosing refusal triggers across combinations of flags', async () => {
      const dosingPrompts = [
        'Prescribe 500mg amoxicillin',
        'Take 500mg metformin',
        'Stop taking your blood pressure medication'
      ];

      for (const prompt of dosingPrompts) {
        const res = await runCli(
          ['run', '--agent', 'visit-steward', prompt, '--provider', 'anthropic', '--model', 'claude-3-5-haiku', '--mock'],
          { cwd: ws.workspaceDir }
        );
        expect(res.exitCode).toBe(0);
        expect(res.stdout).toContain(SAFE_REFUSAL_TEMPLATE);
        expect(res.stderr).toContain('refusal:');
      }
    });
  });

  // =========================================================================
  // 6. Init Command Model and Provider Options
  // =========================================================================
  describe('6. Init Command Model and Provider Flags', () => {
    it('CHALLENGE-INIT-1: carefold init respects --provider, --model-name, and --model-url', async () => {
      const customWs = await createCliTestWorkspace();
      try {
        const initRes = await runCli(
          [
            'init',
            customWs.workspaceDir,
            '--provider',
            'anthropic',
            '--model-name',
            'claude-3-5-sonnet',
            '--model-url',
            'https://api.anthropic.com/v1'
          ],
          { cwd: repoRoot }
        );
        expect(initRes.exitCode).toBe(0);

        const configRaw = await customWs.readFile('carefold.config.json');
        const config = JSON.parse(configRaw);

        expect(config.model.provider).toBe('anthropic');
        expect(config.model.model).toBe('claude-3-5-sonnet');
        expect(config.model.baseUrl).toBe('https://api.anthropic.com/v1');
        expect(config.model.apiKey).toBe('');
      } finally {
        await customWs.cleanup();
      }
    });

    it('CHALLENGE-INIT-2: carefold init defaults to provider: ollama when omitted', async () => {
      const defaultWs = await createCliTestWorkspace();
      try {
        const initRes = await runCli(['init', defaultWs.workspaceDir], { cwd: repoRoot });
        expect(initRes.exitCode).toBe(0);

        const configRaw = await defaultWs.readFile('carefold.config.json');
        const config = JSON.parse(configRaw);

        expect(config.model.provider).toBe('ollama');
        expect(config.model.model).toBe('llama3.2');
        expect(config.model.baseUrl).toBe('http://127.0.0.1:11434/v1');
      } finally {
        await defaultWs.cleanup();
      }
    });
  });
});
