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

import { Command } from 'commander';
import { initCommand } from './commands/init.js';
import { agentListCommand, agentAddCommand, agentInspectCommand } from './commands/agent.js';
import { skillListCommand, skillAddCommand } from './commands/skill.js';
import { runCommand } from './commands/run.js';
import { logCommand } from './commands/log.js';
import { evalCommand } from './commands/eval.js';
import { healthCommand } from './commands/health.js';
import { getCliVersion } from './utils/version.js';

export function createProgram(): Command {
  const program = new Command();

  program
    .name('carefold')
    .description('Carefold CLI: Local-first runtime for specialist health agents')
    .version(getCliVersion(), '-v, --version', 'Output the current version')
    .option('-H, --health', 'Run system health diagnostics', false);

  // version
  program
    .command('version')
    .description('Display Carefold CLI version')
    .option('-j, --json', 'Output version as JSON', false)
    .action(async (opts) => {
      const version = getCliVersion();
      if (opts.json) {
        console.log(JSON.stringify({ version }, null, 2));
      } else {
        console.log(version);
      }
    });

  // health / status
  program
    .command('health')
    .alias('status')
    .description('Run Carefold runtime and environment health diagnostics')
    .option('-j, --json', 'Output health report as machine-readable JSON', false)
    .option('-w, --workspace <path>', 'Path to Carefold workspace root')
    .option('--backend-url <url>', 'Override backend API endpoint URL')
    .option('--model-url <url>', 'Override model / Ollama endpoint URL')
    .option('--ollama-url <url>', 'Alias for --model-url')
    .option('--timeout <ms>', 'Network request timeout in milliseconds', '2000')
    .option('-q, --quiet', 'Suppress terminal output and signal status via exit code', false)
    .action(async (opts) => {
      await healthCommand(opts);
    });

  // init [dir]
  program
    .command('init [dir]')
    .description('Initialize a new Carefold workspace')
    .option('-f, --force', 'Overwrite existing workspace configuration', false)
    .option('--bare', 'Skip copying bundled reference agents and skills', false)
    .option('--no-bundled', 'Skip copying bundled reference agents and skills')
    .option('--provider <name>', 'Default model provider (default: ollama)')
    .option('--model-url <url>', 'Ollama / OpenAI compatible endpoint URL')
    .option('--model-name <name>', 'Model name (default: llama3.2)')
    .action(async (dir, opts) => {
      if (opts.bare) {
        opts.bundled = false;
      }
      await initCommand(dir, opts);
    });

  // agent
  const agentCmd = program
    .command('agent')
    .description('Manage and inspect installed specialist agents');

  agentCmd
    .command('list')
    .description('List installed agents in workspace')
    .option('-w, --workspace <path>', 'Path to Carefold workspace root')
    .option('--json', 'Output agent list as JSON', false)
    .option('--allow-clinical', 'Show and permit clinical assist agents', false)
    .action(async (opts) => {
      await agentListCommand(opts);
    });

  agentCmd
    .command('add <name|path>')
    .description('Add a reference agent or local agent pack to workspace')
    .option('-w, --workspace <path>', 'Path to Carefold workspace root')
    .option('-f, --force', 'Overwrite existing destination directory', false)
    .action(async (nameOrPath, opts) => {
      await agentAddCommand(nameOrPath, opts);
    });

  agentCmd
    .command('inspect <id>')
    .description('Inspect agent manifest, persona, skills, and tools')
    .option('-w, --workspace <path>', 'Path to Carefold workspace root')
    .option('--json', 'Output inspection data as JSON', false)
    .action(async (id, opts) => {
      await agentInspectCommand(id, opts);
    });

  // skill
  const skillCmd = program
    .command('skill')
    .description('Manage and inspect installed specialist skills');

  skillCmd
    .command('list')
    .description('List installed skills in workspace')
    .option('-w, --workspace <path>', 'Path to Carefold workspace root')
    .option('--json', 'Output skill list as JSON', false)
    .option('--allow-clinical', 'Show and permit clinical assist skills', false)
    .action(async (opts) => {
      await skillListCommand(opts);
    });

  skillCmd
    .command('add <name|path>')
    .description('Add a reference skill or local skill pack to workspace')
    .option('-w, --workspace <path>', 'Path to Carefold workspace root')
    .option('-f, --force', 'Overwrite existing destination directory', false)
    .action(async (nameOrPath, opts) => {
      await skillAddCommand(nameOrPath, opts);
    });

  // run [prompt]
  program
    .command('run [prompt]')
    .allowExcessArguments(true)
    .description('Execute an agent or skill with a prompt')
    .option('-a, --agent <id>', 'Agent ID to execute')
    .option('-s, --skill <id>', 'Skill ID to execute')
    .option('-p, --provider <name>', 'Override model provider (ollama, google, anthropic, openai, custom)')
    .option('-m, --model <name>', 'Override model name')
    .option('-k, --key <key>', 'Direct API key (prefer environment variables)')
    .option('--mock', 'Use offline deterministic mock model client', false)
    .option('--allow-clinical', 'Allow clinical assist agents or skills', false)
    .option('-w, --workspace <path>', 'Carefold workspace root')
    .option('--endpoint <url>', 'Override model endpoint URL')
    .option('-j, --json', 'Output stream chunks as newline-delimited JSON', false)
    .action(async (prompt, opts, cmd) => {
      await runCommand(prompt, opts, cmd?.args);
    });

  // log
  program
    .command('log')
    .description('Inspect recent audit log events')
    .option('-n, --limit <number>', 'Number of recent events to display', '10')
    .option('-e, --event <type>', 'Filter events by type (run, tool, refuse, error)')
    .option('-f, --full', 'Show prompt and completion bodies if store_bodies is true', false)
    .option('-w, --workspace <path>', 'Carefold workspace root')
    .option('-j, --json', 'Output events as JSON', false)
    .action(async (opts) => {
      await logCommand(opts);
    });

  // eval
  program
    .command('eval')
    .description('Run offline deterministic golden prompt evaluations')
    .option('-a, --agent <id>', 'Evaluate specific agent')
    .option('-s, --skill <id>', 'Evaluate specific skill')
    .option('-p, --provider <name>', 'Provider to evaluate against (ollama, google, gemini, anthropic, claude, openai, custom, mock)', 'ollama')
    .option('-w, --workspace <path>', 'Carefold workspace root')
    .option('--python <path>', 'Path to python interpreter')
    .option('--engine <type>', 'Evaluation engine (python | node)')
    .action(async (opts) => {
      await evalCommand(opts);
    });

  // Wrap parseAsync to handle top-level --health and -H flag aliases
  const origParseAsync = program.parseAsync.bind(program);
  program.parseAsync = async (argv?: readonly string[], parseOptions?: any) => {
    const rawArgs = argv ? [...argv] : process.argv;
    const userArgs = rawArgs.slice(2);
    const isHealthFlag = userArgs.some((a) => a === '-H' || a === '--health');
    const knownCommands = program.commands
      .map((c) => c.name())
      .concat(program.commands.flatMap((c) => c.aliases()));
    const hasSubcommand = userArgs.some((a) => !a.startsWith('-') && knownCommands.includes(a));

    if (isHealthFlag && !hasSubcommand) {
      const healthCmd = program.commands.find((c) => c.name() === 'health');
      if (healthCmd) {
        const filteredArgs = userArgs.filter((a) => a !== '-H' && a !== '--health');
        healthCmd.parseOptions(filteredArgs);
        await healthCommand(healthCmd.opts());
      } else {
        await healthCommand();
      }
      return program;
    }

    return origParseAsync(argv, parseOptions);
  };

  const origParse = program.parse.bind(program);
  program.parse = (argv?: readonly string[], parseOptions?: any) => {
    const rawArgs = argv ? [...argv] : process.argv;
    const userArgs = rawArgs.slice(2);
    const isHealthFlag = userArgs.some((a) => a === '-H' || a === '--health');
    const knownCommands = program.commands
      .map((c) => c.name())
      .concat(program.commands.flatMap((c) => c.aliases()));
    const hasSubcommand = userArgs.some((a) => !a.startsWith('-') && knownCommands.includes(a));

    if (isHealthFlag && !hasSubcommand) {
      const healthCmd = program.commands.find((c) => c.name() === 'health');
      if (healthCmd) {
        const filteredArgs = userArgs.filter((a) => a !== '-H' && a !== '--health');
        healthCmd.parseOptions(filteredArgs);
        void healthCommand(healthCmd.opts());
      } else {
        void healthCommand();
      }
      return program;
    }

    return origParse(argv, parseOptions);
  };

  return program;
}
