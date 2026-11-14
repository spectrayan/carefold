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

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { isDesktopOrInstalledMode, runSetupDiagnostics } from '@/lib/setup';
import type { CarefoldUserSettings } from '@/lib/settings';
import type { HealthResponse } from '@/types/api';

const baseSettings: CarefoldUserSettings = {
  provider: 'ollama',
  model: 'llama3.2',
  customModelName: '',
  keys: {
    google: '',
    anthropic: '',
    openai: '',
    custom: ''
  },
  endpoints: {
    ollamaUrl: 'http://127.0.0.1:11434',
    customUrl: ''
  }
};

function makeHealthResponse(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: 'degraded',
    version: '0.5.0-beta.2',
    uptime: 4,
    timestamp: '2026-11-13T18:00:00.000Z',
    modelReachable: false,
    backendReachable: false,
    runtimeMode: 'dev',
    isGitWorkspace: true,
    dataDirReady: false,
    workspace: {
      root: '/tmp/carefold',
      agentsCount: 22,
      skillsCount: 24
    },
    ollama: {
      status: 'unreachable',
      endpoint: 'http://127.0.0.1:11434',
      reachable: false
    },
    ...overrides
  };
}

describe('First-run setup diagnostics Mode L vs dev mode (#331)', () => {
  const originalEnv = process.env.NEXT_PUBLIC_CAREFOLD_RUNTIME_MODE;

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_CAREFOLD_RUNTIME_MODE;
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  });

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.NEXT_PUBLIC_CAREFOLD_RUNTIME_MODE;
    } else {
      process.env.NEXT_PUBLIC_CAREFOLD_RUNTIME_MODE = originalEnv;
    }
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    vi.restoreAllMocks();
  });

  it('detects desktop or installed Mode L from Tauri globals, env, or health metadata', () => {
    expect(isDesktopOrInstalledMode(makeHealthResponse({ runtimeMode: 'dev', isGitWorkspace: true }))).toBe(false);
    expect(isDesktopOrInstalledMode(makeHealthResponse({ runtimeMode: 'desktop', isGitWorkspace: false }))).toBe(true);
    expect(isDesktopOrInstalledMode(makeHealthResponse({ runtimeMode: 'local', isGitWorkspace: false }))).toBe(true);

    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    expect(isDesktopOrInstalledMode(null)).toBe(true);
  });

  it('omits developer CLI commands and exposes one-click retry in desktop Mode L', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes('/api/v1/health')) {
        return new Response(
          JSON.stringify(
            makeHealthResponse({
              backendReachable: false,
              runtimeMode: 'desktop',
              isGitWorkspace: false
            })
          ),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }
      return new Response(JSON.stringify({ reachable: false, models: [] }), { status: 200 });
    });

    const diag = await runSetupDiagnostics(baseSettings);
    expect(diag.isDesktopMode).toBe(true);
    expect(diag.runtimeMode).toBe('desktop');
    expect(diag.backend.status).toBe('fail');
    expect(diag.backend.badge).toBe('[STARTING]');
    expect(diag.backend.fixCommand).toBeUndefined();
    expect(diag.backend.secondaryCommand).toBeUndefined();
    expect(diag.backend.retryLabel).toBe('Retry connection');
    expect(diag.backend.message).not.toContain('pnpm dev:backend');

    expect(diag.model.fixCommand).toBeUndefined();
    expect(diag.model.retryLabel).toBe('Retry connection');
    expect(diag.model.ctaLink).toBe('/settings/model');
  });

  it('preserves developer CLI remediation commands in a source-checkout git workspace', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes('/api/v1/health')) {
        return new Response(
          JSON.stringify(
            makeHealthResponse({
              backendReachable: false,
              runtimeMode: 'dev',
              isGitWorkspace: true
            })
          ),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }
      return new Response(JSON.stringify({ reachable: false, models: [] }), { status: 200 });
    });

    const diag = await runSetupDiagnostics(baseSettings);
    expect(diag.isDesktopMode).toBe(false);
    expect(diag.backend.fixCommand).toBe('pnpm dev:backend');
    expect(diag.backend.secondaryCommand).toBe('bash scripts/start.sh backend');
    expect(diag.model.fixCommand).toBe('ollama serve');
  });
});
