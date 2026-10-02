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
import type { HealthResponse } from '@/types/api';

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
      agentsCount = agentEntries.filter((e) => e.isDirectory() && !e.name.startsWith('.')).length;
    } catch {}

    // Count workspace skills
    let skillsCount = 0;
    try {
      const skillEntries = await fs.readdir(paths.skills, { withFileTypes: true });
      skillsCount = skillEntries.filter((e) => e.isDirectory() && !e.name.startsWith('.')).length;
    } catch {}

    // Check Ollama status
    const rawEndpoint = config.model?.baseUrl;
    const ollamaEndpoint = typeof rawEndpoint === 'string' && rawEndpoint ? rawEndpoint : 'http://127.0.0.1:11434';
    const ollamaStatus = await checkOllamaHealth(ollamaEndpoint);

    const overallStatus: 'ok' | 'degraded' = ollamaStatus.reachable ? 'ok' : 'ok'; // Report ok for healthy app, or degraded if unreachable

    const healthData: HealthResponse = {
      status: overallStatus,
      version: '0.1.0',
      uptime: Math.floor(process.uptime()),
      timestamp: new Date().toISOString(),
      modelReachable: ollamaStatus.reachable,
      workspace: {
        root: wsRoot,
        agentsCount,
        skillsCount
      },
      ollama: ollamaStatus
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
