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

import fsSync from 'node:fs';
import { formatTable } from '../utils/format.js';
import { colors, formatStatusPill } from '../utils/colors.js';
import { getCliVersion } from '../utils/version.js';
import { findWorkspaceRoot, getWorkspacePaths } from '../utils/workspace.js';
import { resolveBundledAssets } from '../utils/assets.js';
import { ExitCodes } from '../utils/errors.js';

export type DiagnosticStatus = 'PASS' | 'WARN' | 'FAIL';
export type OverallStatus = 'healthy' | 'degraded' | 'unhealthy';

export interface DiagnosticCheckResult {
  id: 'node' | 'backend' | 'ollama' | 'memory' | 'catalog';
  name: string;
  status: DiagnosticStatus;
  target: string;
  details: string;
  meta?: Record<string, any>;
}

export interface HealthReport {
  status: OverallStatus;
  healthy: boolean;
  version: string;
  timestamp: string;
  checks: {
    node: {
      status: 'pass' | 'warn' | 'fail';
      version: string;
      required: string;
      message: string;
    };
    backend: {
      status: 'pass' | 'warn' | 'fail';
      url: string;
      reachable: boolean;
      version?: string;
      message: string;
    };
    ollama: {
      status: 'pass' | 'warn' | 'fail';
      url: string;
      reachable: boolean;
      models: string[];
      message: string;
    };
    memory: {
      status: 'pass' | 'warn' | 'fail';
      backend: string;
      healthy: boolean;
      message: string;
    };
    catalog: {
      status: 'pass' | 'warn' | 'fail';
      agentsCount: number;
      skillsCount: number;
      message: string;
    };
  };
  resultsList: DiagnosticCheckResult[];
}

export interface HealthOptions {
  workspace?: string;
  backendUrl?: string;
  modelUrl?: string;
  ollamaUrl?: string;
  timeout?: string | number;
  json?: boolean;
  quiet?: boolean;
}

export async function checkNodeVersion(): Promise<DiagnosticCheckResult> {
  const nodeVersion = process.version;
  const major = parseInt(nodeVersion.replace(/^v/, '').split('.')[0] || '0', 10);
  const pass = major >= 20;

  return {
    id: 'node',
    name: 'Node Runtime',
    status: pass ? 'PASS' : 'FAIL',
    target: '>= 20.0.0',
    details: pass
      ? `${nodeVersion} (>=20.0.0 required)`
      : `${nodeVersion} (incompatible: requires >=20.0.0)`,
    meta: {
      version: nodeVersion,
      required: '>=20.0.0'
    }
  };
}

export async function checkBackendApi(
  baseUrl?: string,
  timeoutMs = 2000
): Promise<DiagnosticCheckResult> {
  const rawBase =
    baseUrl ||
    process.env.CAREFOLD_BACKEND_URL ||
    process.env.CAREFOLD_API_URL ||
    process.env.BACKEND_URL ||
    'http://localhost:8010';
  const cleanBase = rawBase.replace(/\/$/, '');
  const endpoint = `${cleanBase}/api/health`;

  try {
    const res = await fetch(endpoint, {
      signal: AbortSignal.timeout(timeoutMs)
    });

    if (!res.ok) {
      return {
        id: 'backend',
        name: 'Backend API',
        status: 'FAIL',
        target: endpoint,
        details: `HTTP ${res.status} ${res.statusText}`,
        meta: { url: endpoint, reachable: false }
      };
    }

    const data = (await res.json()) as any;
    const version = data.version || '0.4.0-beta.1';
    const isOk = data.status === 'ok';
    const isDegraded = data.status === 'degraded';

    return {
      id: 'backend',
      name: 'Backend API',
      status: isOk ? 'PASS' : isDegraded ? 'WARN' : 'FAIL',
      target: endpoint,
      details: isOk
        ? `Connected (${endpoint}, ok)`
        : `Degraded (${endpoint}, ${data.ollama?.status || data.status || 'degraded'})`,
      meta: {
        url: endpoint,
        reachable: true,
        version,
        data
      }
    };
  } catch (err: any) {
    const msg = err.name === 'TimeoutError' ? `Request timed out after ${timeoutMs}ms` : err.message || 'connection failed';
    return {
      id: 'backend',
      name: 'Backend API',
      status: 'FAIL',
      target: endpoint,
      details: `Unreachable (${endpoint} - ${msg})`,
      meta: { url: endpoint, reachable: false }
    };
  }
}

export async function checkOllamaDaemon(
  baseUrl?: string,
  timeoutMs = 2000
): Promise<DiagnosticCheckResult> {
  const rawBase =
    baseUrl ||
    process.env.CAREFOLD_OLLAMA_URL ||
    process.env.OLLAMA_URL ||
    process.env.OLLAMA_BASE_URL ||
    'http://localhost:11434';
  const cleanBase = rawBase.replace(/\/$/, '');
  const endpoint = `${cleanBase}/api/tags`;

  try {
    const res = await fetch(endpoint, {
      signal: AbortSignal.timeout(timeoutMs)
    });

    if (!res.ok) {
      return handleOllamaFailure(endpoint, `HTTP ${res.status} ${res.statusText}`);
    }

    const data = (await res.json()) as any;
    const rawModels = Array.isArray(data.models) ? data.models : [];
    const models: string[] = rawModels
      .map((m: any) => m.name || m.model)
      .filter((n: any): n is string => Boolean(n));

    if (models.length > 0) {
      return {
        id: 'ollama',
        name: 'Ollama Daemon',
        status: 'PASS',
        target: endpoint,
        details: `Connected (${endpoint}, ${models.length} model(s) available)`,
        meta: { url: endpoint, reachable: true, models }
      };
    }

    return {
      id: 'ollama',
      name: 'Ollama Daemon',
      status: 'WARN',
      target: endpoint,
      details: "Reachable, but 0 models found (run 'ollama pull llama3.2')",
      meta: { url: endpoint, reachable: true, models: [] }
    };
  } catch (err: any) {
    const msg = err.name === 'TimeoutError' ? `Request timed out after ${timeoutMs}ms` : err.message || 'connection failed';
    return handleOllamaFailure(endpoint, msg);
  }
}

function handleOllamaFailure(endpoint: string, failureReason: string): DiagnosticCheckResult {
  const hasCloudKey = Boolean(
    process.env.OPENAI_API_KEY ||
      process.env.ANTHROPIC_API_KEY ||
      process.env.GEMINI_API_KEY ||
      process.env.GOOGLE_API_KEY
  );

  if (hasCloudKey) {
    return {
      id: 'ollama',
      name: 'Ollama Daemon',
      status: 'WARN',
      target: endpoint,
      details: 'Ollama offline, but cloud provider API key detected',
      meta: { url: endpoint, reachable: false, models: [], cloudFallback: true }
    };
  }

  return {
    id: 'ollama',
    name: 'Ollama Daemon',
    status: 'FAIL',
    target: endpoint,
    details: `Unreachable (${endpoint} - ${failureReason})`,
    meta: { url: endpoint, reachable: false, models: [] }
  };
}

export async function checkMemoryStore(
  backendUrl?: string,
  timeoutMs = 2000,
  workspaceDir?: string
): Promise<DiagnosticCheckResult> {
  const rawBase =
    backendUrl ||
    process.env.CAREFOLD_BACKEND_URL ||
    process.env.CAREFOLD_API_URL ||
    process.env.BACKEND_URL ||
    'http://localhost:8010';
  const cleanBase = rawBase.replace(/\/$/, '');
  const endpoint = `${cleanBase}/api/memory/status`;

  // Attempt backend probe if possible
  try {
    const res = await fetch(endpoint, {
      signal: AbortSignal.timeout(timeoutMs)
    });
    if (res.ok) {
      const data = (await res.json()) as any;
      const isHealthy = Boolean(data.healthy);
      const isFallback = Boolean(data.fallback_active);
      const backendType = data.backend || 'sqlite';

      if (isHealthy && !isFallback) {
        return {
          id: 'memory',
          name: 'Memory Store',
          status: 'PASS',
          target: backendType,
          details: `${backendType === 'spector' ? 'Spector' : 'SQLite FTS5'} store operational`,
          meta: { backend: backendType, healthy: true }
        };
      }

      if (isFallback) {
        return {
          id: 'memory',
          name: 'Memory Store',
          status: 'WARN',
          target: backendType,
          details: 'Spector memory degraded; fallback active',
          meta: { backend: backendType, healthy: false, fallback: true }
        };
      }
    }
  } catch {
    // Backend memory probe failed; fall back to local workspace validation
  }

  // Validate local workspace storage
  try {
    const root = findWorkspaceRoot(workspaceDir);
    const paths = getWorkspacePaths(root);

    // If workspace root exists, SQLite FTS5 store is available locally
    if (fsSync.existsSync(paths.root)) {
      return {
        id: 'memory',
        name: 'Memory Store',
        status: 'PASS',
        target: 'sqlite',
        details: 'SQLite FTS5 store operational',
        meta: { backend: 'sqlite', healthy: true }
      };
    }
  } catch {
    // Continue
  }

  return {
    id: 'memory',
    name: 'Memory Store',
    status: 'WARN',
    target: 'sqlite',
    details: 'Local workspace storage uninitialized',
    meta: { backend: 'sqlite', healthy: false }
  };
}

export function checkCatalog(workspaceDir?: string): DiagnosticCheckResult {
  let agentsCount = 0;
  let skillsCount = 0;
  let catalogSource = 'workspace';

  try {
    const root = findWorkspaceRoot(workspaceDir);
    const paths = getWorkspacePaths(root);

    if (fsSync.existsSync(paths.agents) && fsSync.existsSync(paths.skills)) {
      const agentEntries = fsSync.readdirSync(paths.agents, { withFileTypes: true });
      agentsCount = agentEntries.filter(
        (e) => e.isDirectory() && !e.name.startsWith('.') && !e.name.startsWith('_')
      ).length;

      const skillEntries = fsSync.readdirSync(paths.skills, { withFileTypes: true });
      skillsCount = skillEntries.filter(
        (e) => e.isDirectory() && !e.name.startsWith('.') && !e.name.startsWith('_')
      ).length;
    }
  } catch {
    // Continue to bundled fallback
  }

  if (agentsCount === 0 || skillsCount === 0) {
    try {
      const bundled = resolveBundledAssets();
      if (fsSync.existsSync(bundled.agentsDir) && fsSync.existsSync(bundled.skillsDir)) {
        catalogSource = 'bundled';
        const agentEntries = fsSync.readdirSync(bundled.agentsDir, { withFileTypes: true });
        agentsCount = agentEntries.filter(
          (e) => e.isDirectory() && !e.name.startsWith('.') && !e.name.startsWith('_')
        ).length;

        const skillEntries = fsSync.readdirSync(bundled.skillsDir, { withFileTypes: true });
        skillsCount = skillEntries.filter(
          (e) => e.isDirectory() && !e.name.startsWith('.') && !e.name.startsWith('_')
        ).length;
      }
    } catch {
      // Bundled assets not found
    }
  }

  if (agentsCount > 0 && skillsCount > 0) {
    return {
      id: 'catalog',
      name: 'Agent Catalog',
      status: 'PASS',
      target: catalogSource,
      details: `${agentsCount} specialist agent(s), ${skillsCount} skill pack(s) available`,
      meta: { agentsCount, skillsCount, source: catalogSource }
    };
  }

  return {
    id: 'catalog',
    name: 'Agent Catalog',
    status: 'WARN',
    target: 'uninitialized',
    details: "Workspace uninitialized (run 'carefold init')",
    meta: { agentsCount: 0, skillsCount: 0 }
  };
}

export async function runDiagnostics(options: HealthOptions = {}): Promise<HealthReport> {
  const timeoutMs = options.timeout ? Number(options.timeout) || 2000 : 2000;
  const backendUrl = options.backendUrl;
  const modelUrl = options.modelUrl || options.ollamaUrl;
  const workspaceDir = options.workspace;

  const [nodeRes, backendRes, ollamaRes, memoryRes] = await Promise.all([
    checkNodeVersion(),
    checkBackendApi(backendUrl, timeoutMs),
    checkOllamaDaemon(modelUrl, timeoutMs),
    checkMemoryStore(backendUrl, timeoutMs, workspaceDir)
  ]);

  const catalogRes = checkCatalog(workspaceDir);

  const resultsList = [nodeRes, backendRes, ollamaRes, memoryRes, catalogRes];

  const hasFail = resultsList.some((r) => r.status === 'FAIL');
  const hasWarn = resultsList.some((r) => r.status === 'WARN');

  const status: OverallStatus = hasFail ? 'unhealthy' : hasWarn ? 'degraded' : 'healthy';
  const healthy = status === 'healthy';

  const toCheckStatus = (s: DiagnosticStatus): 'pass' | 'warn' | 'fail' =>
    s === 'PASS' ? 'pass' : s === 'WARN' ? 'warn' : 'fail';

  const report: HealthReport = {
    status,
    healthy,
    version: getCliVersion(),
    timestamp: new Date().toISOString(),
    checks: {
      node: {
        status: toCheckStatus(nodeRes.status),
        version: nodeRes.meta?.version || process.version,
        required: nodeRes.meta?.required || '>=20.0.0',
        message: nodeRes.details
      },
      backend: {
        status: toCheckStatus(backendRes.status),
        url: backendRes.target,
        reachable: Boolean(backendRes.meta?.reachable),
        version: backendRes.meta?.version,
        message: backendRes.details
      },
      ollama: {
        status: toCheckStatus(ollamaRes.status),
        url: ollamaRes.target,
        reachable: Boolean(ollamaRes.meta?.reachable),
        models: ollamaRes.meta?.models || [],
        message: ollamaRes.details
      },
      memory: {
        status: toCheckStatus(memoryRes.status),
        backend: memoryRes.meta?.backend || 'sqlite',
        healthy: Boolean(memoryRes.meta?.healthy),
        message: memoryRes.details
      },
      catalog: {
        status: toCheckStatus(catalogRes.status),
        agentsCount: catalogRes.meta?.agentsCount || 0,
        skillsCount: catalogRes.meta?.skillsCount || 0,
        message: catalogRes.details
      }
    },
    resultsList
  };

  return report;
}

export async function healthCommand(options: HealthOptions = {}): Promise<HealthReport> {
  const report = await runDiagnostics(options);

  if (options.json) {
    // Machine-readable output
    console.log(JSON.stringify(report, null, 2));
  } else if (!options.quiet) {
    // Colorized human-readable table output
    const cliVersion = report.version;
    console.log(colors.bold(`\nCarefold System Diagnostics (v${cliVersion})\n`));

    const headers = ['Check', 'Status', 'Target / Details'];
    const rows = report.resultsList.map((c) => [
      c.name,
      formatStatusPill(c.status),
      c.details
    ]);

    console.log(formatTable(headers, rows));
    console.log('');

    const passedCount = report.resultsList.filter((r) => r.status === 'PASS').length;
    const warnCount = report.resultsList.filter((r) => r.status === 'WARN').length;
    const failCount = report.resultsList.filter((r) => r.status === 'FAIL').length;
    const totalCount = report.resultsList.length;

    if (report.status === 'healthy') {
      console.log(
        colors.green(`Overall Status: HEALTHY (${passedCount}/${totalCount} checks passed)\n`)
      );
    } else if (report.status === 'degraded') {
      console.log(
        colors.yellow(
          `Overall Status: DEGRADED (${warnCount} warning, ${passedCount} passed)\n`
        )
      );
    } else {
      console.log(
        colors.red(
          `Overall Status: UNHEALTHY (${failCount} failed, ${warnCount} warning, ${passedCount} passed)\n`
        )
      );
    }

    // Print actionable remediation steps if not healthy
    if (!report.healthy) {
      const remediations: string[] = [];
      const backendCheck = report.resultsList.find((r) => r.id === 'backend');
      const ollamaCheck = report.resultsList.find((r) => r.id === 'ollama');
      const catalogCheck = report.resultsList.find((r) => r.id === 'catalog');

      if (backendCheck && backendCheck.status === 'FAIL') {
        remediations.push('Start backend API: bash scripts/start.sh backend');
      }
      if (ollamaCheck && ollamaCheck.status !== 'PASS') {
        remediations.push('Start Ollama daemon: ollama serve (or export OPENAI_API_KEY / GEMINI_API_KEY)');
      }
      if (catalogCheck && catalogCheck.status !== 'PASS') {
        remediations.push("Initialize workspace: carefold init");
      }

      if (remediations.length > 0) {
        console.log(colors.bold('Remediation:'));
        for (const rem of remediations) {
          console.log(`  • ${rem}`);
        }
        console.log('');
      }
    }
  }

  // Set exit code
  if (!report.healthy) {
    process.exitCode = ExitCodes.USER_ERROR;
  } else {
    process.exitCode = ExitCodes.SUCCESS;
  }

  return report;
}
