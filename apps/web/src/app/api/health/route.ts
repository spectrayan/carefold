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

import { NextRequest, NextResponse } from 'next/server';
import fs from 'node:fs/promises';
import { findWorkspaceRoot, getWorkspacePaths, loadWorkspaceConfig } from '@/lib/workspace';
import { checkOllamaHealth } from '@/lib/ollama';
import type { HealthResponse, OllamaHealthStatus } from '@/types/api';
import pkg from '../../../../package.json';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(_req: Request | NextRequest): Promise<NextResponse<HealthResponse | { error: string }>> {
  try {
    const wsRoot = findWorkspaceRoot();
    const paths = getWorkspacePaths(wsRoot);
    const config = await loadWorkspaceConfig(wsRoot);

    // Count workspace agents
    let agentsCount = 0;
    try {
      const agentEntries = await fs.readdir(paths.agents, { withFileTypes: true });
      agentsCount = agentEntries.filter(
        (e) => e.isDirectory() && !e.name.startsWith('.') && !e.name.startsWith('_')
      ).length;
    } catch {}

    // Count workspace skills
    let skillsCount = 0;
    try {
      const skillEntries = await fs.readdir(paths.skills, { withFileTypes: true });
      skillsCount = skillEntries.filter(
        (e) => e.isDirectory() && !e.name.startsWith('.') && !e.name.startsWith('_')
      ).length;
    } catch {}

    // Try checking backend health if running
    let backendData: any = null;
    try {
      const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
      const backendRes = await fetch(`${backendUrl}/api/health`, {
        signal: AbortSignal.timeout(1500)
      });
      if (backendRes.ok) {
        backendData = await backendRes.json();
      }
    } catch {}

    // Check Ollama status
    const envEndpoint =
      process.env.OLLAMA_URL ||
      process.env.OLLAMA_BASE_URL ||
      process.env.CAREFOLD_OLLAMA_URL ||
      config.model?.baseUrl;
    const ollamaEndpoint = typeof envEndpoint === 'string' && envEndpoint ? envEndpoint : 'http://127.0.0.1:11434';
    const ollamaStatus: OllamaHealthStatus =
      backendData?.ollama || (await checkOllamaHealth(ollamaEndpoint));

    const isReachable = Boolean(backendData?.modelReachable ?? ollamaStatus.reachable);
    const overallStatus: 'ok' | 'degraded' = isReachable ? 'ok' : 'degraded';

    const healthData: HealthResponse = {
      status: overallStatus,
      version: pkg.version,
      uptime: Math.floor(process.uptime()),
      timestamp: new Date().toISOString(),
      modelReachable: isReachable,
      workspace: {
        root: wsRoot,
        agentsCount,
        skillsCount
      },
      ollama: ollamaStatus,
      backendReachable: Boolean(backendData)
    };

    return NextResponse.json(healthData, { status: 200 });
  } catch (err: any) {
    return NextResponse.json(
      {
        status: 'error',
        error: `Health check failed: ${err.message}`
      } as any,
      { status: 503 }
    );
  }
}
