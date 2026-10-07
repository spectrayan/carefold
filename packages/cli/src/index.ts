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

import { createProgram } from './program.js';
import { CliError, ExitCodes } from './utils/errors.js';

// Export Programmatic API
export { createProgram } from './program.js';
export { initCommand, type InitOptions } from './commands/init.js';
export {
  agentListCommand,
  agentAddCommand,
  agentInspectCommand,
  type AgentListOptions,
  type AgentAddOptions,
  type AgentInspectOptions
} from './commands/agent.js';
export {
  skillListCommand,
  skillAddCommand,
  type SkillListOptions,
  type SkillAddOptions
} from './commands/skill.js';
export { runCommand, type RunCommandOptions } from './commands/run.js';
export { logCommand, type LogCommandOptions } from './commands/log.js';
export { evalCommand, type EvalOptions } from './commands/eval.js';
export {
  healthCommand,
  runDiagnostics,
  checkNodeVersion,
  checkBackendApi,
  checkOllamaDaemon,
  checkMemoryStore,
  checkCatalog,
  type HealthOptions,
  type HealthReport,
  type DiagnosticCheckResult,
  type DiagnosticStatus,
  type OverallStatus
} from './commands/health.js';
export { CliError, ExitCodes } from './utils/errors.js';
export { findWorkspaceRoot, getWorkspacePaths, loadWorkspaceConfig } from './utils/workspace.js';
export { getCliVersion } from './utils/version.js';
export { colors, formatStatusPill, isColorSupported } from './utils/colors.js';
export { formatTable, formatRiskBadge, stripAnsi, visibleLength, padAnsiEnd } from './utils/format.js';

// Execute binary if run from CLI
const isCliEntry =
  Boolean(
    process.argv[1] &&
      (process.argv[1].endsWith('carefold.js') ||
        process.argv[1].endsWith('carefold') ||
        process.argv[1].endsWith('dist/index.js'))
  ) || !process.env.VITEST;

if (isCliEntry) {
  const program = createProgram();
  program.parseAsync(process.argv).catch((err: any) => {
    if (err instanceof CliError) {
      process.stderr.write(`Error: ${err.message}\n`);
      process.exit(err.exitCode);
    }
    process.stderr.write(`Error: ${err.message || String(err)}\n`);
    process.exit(ExitCodes.USER_ERROR);
  });
}
