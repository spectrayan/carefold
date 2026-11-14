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

import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { SetupChecklist } from '@/components/setup/SetupChecklist';

describe('SetupChecklist desktop Mode L UX (#331)', () => {
  afterEach(() => {
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    vi.restoreAllMocks();
  });

  it('renders plain-language startup progress and one-click retry without terminal CLI boxes in desktop mode', async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};

    let attempt = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes('/api/v1/health')) {
        attempt += 1;
        if (attempt === 1) {
          return new Response(
            JSON.stringify({
              status: 'degraded',
              version: '0.5.0-beta.2',
              uptime: 1,
              timestamp: '2026-11-13T18:00:00.000Z',
              modelReachable: false,
              backendReachable: false,
              runtimeMode: 'desktop',
              isGitWorkspace: false,
              workspace: { root: '/app', agentsCount: 22, skillsCount: 24 },
              ollama: { status: 'unreachable', endpoint: 'http://127.0.0.1:11434', reachable: false }
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }
        return new Response(
          JSON.stringify({
            status: 'ok',
            version: '0.5.0-beta.2',
            uptime: 5,
            timestamp: '2026-11-13T18:00:04.000Z',
            modelReachable: true,
            backendReachable: true,
            runtimeMode: 'desktop',
            isGitWorkspace: false,
            workspace: { root: '/app', agentsCount: 22, skillsCount: 24 },
            ollama: {
              status: 'connected',
              endpoint: 'http://127.0.0.1:11434',
              reachable: true,
              availableModels: ['llama3.2']
            }
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }

      if (attempt >= 2) {
        return new Response(
          JSON.stringify({ reachable: true, models: [{ id: 'llama3.2', name: 'llama3.2' }] }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }
      return new Response(JSON.stringify({ reachable: false, models: [] }), { status: 200 });
    });

    render(<SetupChecklist initialStatus="ACTION_REQUIRED" />);

    const retryBtn = await screen.findByTestId('setup-step-backend-retry-btn');
    expect(retryBtn).toHaveTextContent('Retry connection');
    expect(screen.queryByText('pnpm dev:backend')).toBeNull();
    expect(screen.queryByText(/scripts\/start\.sh/)).toBeNull();

    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(
        screen.getByText('Local Carefold health runtime is online and ready on this device.')
      ).toBeInTheDocument();
    });
  });
});
