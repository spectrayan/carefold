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

import { NextRequest, NextResponse } from 'next/server';
import fs from 'node:fs/promises';
import path from 'node:path';
import { findWorkspaceRoot, getWorkspacePaths, loadWorkspaceConfig } from '@/lib/workspace';
import { checkOllamaHealth } from '@/lib/ollama';
import type { HealthResponse, OllamaHealthStatus, RuntimeMode } from '@/types/api';
import pkg from '../../../../package.json';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

async function detectIsGitWorkspace(wsRoot: string): Promise<boolean> {
  for (const candidate of [wsRoot, path.dirname(wsRoot)]) {
    try {
      await fs.stat(path.join(candidate, '.git'));
      return true;
    } catch {}
  }
  return false;
}

function classifyRuntimeMode(isGitWorkspace: boolean, backendMode?: unknown): RuntimeMode {
  const explicit = (
    process.env.CAREFOLD_RUNTIME_MODE ||
    process.env.NEXT_PUBLIC_CAREFOLD_RUNTIME_MODE ||
    process.env.CAREFOLD_MODE ||
    ''
  )
    .trim()
    .toLowerCase();
  if (explicit === 'desktop' || explicit === 'tauri') return 'desktop';
  if (explicit === 'server' || explicit === 'mode_s' || explicit === 's') return 'server';
  if (explicit === 'local' || explicit === 'mode_l' || explicit === 'l' || explicit === 'installed') {
    return 'local';
  }
  if (explicit === 'dev' || explicit === 'development') return 'dev';

  if (
    backendMode === 'desktop' ||
    backendMode === 'local' ||
    backendMode === 'server' ||
    backendMode === 'dev'
  ) {
    return backendMode === 'dev' && !isGitWorkspace ? 'local' : backendMode;
  }
  return isGitWorkspace ? 'dev' : 'local';
}

export async function GET(_req: Request | NextRequest): Promise<NextResponse<HealthResponse | { error: string }>> {
  try {
    const wsRoot = findWorkspaceRoot();
    const paths = getWorkspacePaths(wsRoot);
    const config = await loadWorkspaceConfig(wsRoot);
    const isGitWorkspace = await detectIsGitWorkspace(wsRoot);

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
      const backendRes = await fetch(`${backendUrl}/api/v1/health`, {
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
    const effectiveGitWs =
      typeof backendData?.isGitWorkspace === 'boolean'
        ? Boolean(isGitWorkspace && backendData.isGitWorkspace)
        : isGitWorkspace;
    const runtimeMode = classifyRuntimeMode(effectiveGitWs, backendData?.runtimeMode);

    const healthData: HealthResponse = {
      status: overallStatus,
      version: pkg.version,
      uptime: Math.floor(process.uptime()),
      timestamp: new Date().toISOString(),
      modelReachable: isReachable,
      runtimeMode,
      isGitWorkspace: effectiveGitWs,
      dataDirReady: backendData?.dataDirReady ?? Boolean(backendData),
      workspace: {
        root: wsRoot,
        agentsCount: agentsCount || backendData?.workspace?.agentsCount || 0,
        skillsCount: skillsCount || backendData?.workspace?.skillsCount || 0
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
