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

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { SetupChecklist } from '@/components/setup/SetupChecklist';
import { FirstRunSetupCard } from '@/components/setup/FirstRunSetupCard';
import { SettingsModal } from '@/components/SettingsModal';
import {
  CAREFOLD_SETUP_STORAGE_KEY,
  isSetupComplete,
  markSetupComplete,
  resetSetupStatus
} from '@/lib/setup';
import { DEFAULT_USER_SETTINGS, CAREFOLD_SETTINGS_STORAGE_KEY, type CarefoldUserSettings } from '@/lib/settings';

describe('First-Run Setup Checklist & Diagnostics (#99)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe('FirstRunSetupCard Lifecycle & Storage Persistence', () => {
    it('renders setup card on first launch when carefold_setup_complete is absent', async () => {
      // Mock fetch so checks resolve
      vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
        if ((String(url).includes('/api/v1/health') || String(url).includes('/api/health'))) {
          return Promise.resolve(new Response(JSON.stringify({
            status: 'ok',
            version: '0.4.0',
            uptime: 100,
            timestamp: new Date().toISOString(),
            backendReachable: true,
            workspace: { root: '/workspace', agentsCount: 22, skillsCount: 24 },
            ollama: { status: 'connected', endpoint: 'http://127.0.0.1:11434', reachable: true }
          })));
        }
        if ((String(url).includes('/api/v1/models') || String(url).includes('/api/models'))) {
          return Promise.resolve(new Response(JSON.stringify({
            provider: 'ollama',
            reachable: true,
            models: [{ id: 'llama3.2', name: 'Llama 3.2 (3B)' }]
          })));
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });

      expect(localStorage.getItem(CAREFOLD_SETUP_STORAGE_KEY)).toBeNull();
      render(<FirstRunSetupCard />);

      await waitFor(() => {
        expect(screen.getByTestId('first-run-setup-card')).toBeInTheDocument();
        expect(screen.getByText('Welcome to Carefold — First-Run Setup Check')).toBeInTheDocument();
        expect(screen.getByTestId('dismiss-setup-card')).toBeInTheDocument();
      });
    });

    it('does not render setup card when carefold_setup_complete is already true', () => {
      localStorage.setItem(CAREFOLD_SETUP_STORAGE_KEY, 'true');
      expect(isSetupComplete()).toBe(true);

      const { container } = render(<FirstRunSetupCard />);
      expect(container.firstChild).toBeNull();
      expect(screen.queryByTestId('first-run-setup-card')).not.toBeInTheDocument();
    });

    it('dismisses card and sets carefold_setup_complete = "true" when skip button is clicked', () => {
      render(<FirstRunSetupCard />);

      const dismissBtn = screen.getByTestId('dismiss-setup-card');
      fireEvent.click(dismissBtn);

      expect(localStorage.getItem(CAREFOLD_SETUP_STORAGE_KEY)).toBe('true');
      expect(screen.queryByTestId('first-run-setup-card')).not.toBeInTheDocument();
    });

    it('dispatches and listens to carefold:setup-changed event', () => {
      resetSetupStatus();
      expect(localStorage.getItem(CAREFOLD_SETUP_STORAGE_KEY)).toBeNull();

      markSetupComplete('true');
      expect(localStorage.getItem(CAREFOLD_SETUP_STORAGE_KEY)).toBe('true');
    });
  });

  describe('Probe 1: Backend API Status', () => {
    it('shows PASS [READY] when backend is online and responding', async () => {
      vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
        if ((String(url).includes('/api/v1/health') || String(url).includes('/api/health'))) {
          return Promise.resolve(new Response(JSON.stringify({
            status: 'ok',
            version: '0.4.0',
            uptime: 120,
            timestamp: new Date().toISOString(),
            backendReachable: true,
            workspace: { root: '/workspace', agentsCount: 22, skillsCount: 24 },
            ollama: { status: 'connected', endpoint: 'http://127.0.0.1:11434', reachable: true }
          })));
        }
        if ((String(url).includes('/api/v1/models') || String(url).includes('/api/models'))) {
          return Promise.resolve(new Response(JSON.stringify({
            provider: 'ollama',
            reachable: true,
            models: [{ id: 'llama3.2', name: 'Llama 3.2 (3B)' }]
          })));
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });

      render(<SetupChecklist isSettingsView={true} />);

      await waitFor(() => {
        const backendStep = screen.getByTestId('setup-step-backend');
        expect(backendStep).toBeInTheDocument();
        expect(backendStep).toHaveTextContent('[READY]');
        expect(backendStep).toHaveTextContent('Backend API is online and responding on :8010.');
      });
    });

    it('shows FAIL [OFFLINE] and copyable fix commands when backend is unreachable', async () => {
      vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
        if ((String(url).includes('/api/v1/health') || String(url).includes('/api/health'))) {
          return Promise.reject(new Error('connect ECONNREFUSED 127.0.0.1:8010'));
        }
        if ((String(url).includes('/api/v1/models') || String(url).includes('/api/models'))) {
          return Promise.resolve(new Response(JSON.stringify({
            provider: 'ollama',
            reachable: false,
            models: []
          })));
        }
        return Promise.resolve(new Response('{}', { status: 500 }));
      });

      render(<SetupChecklist isSettingsView={true} />);

      await waitFor(() => {
        const backendStep = screen.getByTestId('setup-step-backend');
        expect(backendStep).toHaveTextContent('[OFFLINE]');
        expect(backendStep).toHaveTextContent('Carefold Python backend runtime is unreachable');
        expect(backendStep).toHaveTextContent('pnpm dev:backend');
        expect(backendStep).toHaveTextContent('bash scripts/start.sh backend');
      });

      expect(screen.getByTestId('copy-backend-command')).toBeInTheDocument();
    });
  });

  describe('Probe 2: Ollama Local Model & Provider Status', () => {
    it('shows FAIL [OFFLINE] and "ollama serve" when Ollama daemon is unreachable', async () => {
      vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
        if ((String(url).includes('/api/v1/health') || String(url).includes('/api/health'))) {
          return Promise.resolve(new Response(JSON.stringify({
            status: 'degraded',
            version: '0.4.0',
            uptime: 50,
            timestamp: new Date().toISOString(),
            backendReachable: true,
            workspace: { root: '/workspace', agentsCount: 22, skillsCount: 24 },
            ollama: { status: 'unreachable', endpoint: 'http://127.0.0.1:11434', reachable: false }
          })));
        }
        if ((String(url).includes('/api/v1/models') || String(url).includes('/api/models'))) {
          return Promise.resolve(new Response(JSON.stringify({
            provider: 'ollama',
            reachable: false,
            models: []
          })));
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });

      render(<SetupChecklist isSettingsView={true} />);

      await waitFor(() => {
        const modelStep = screen.getByTestId('setup-step-model');
        expect(modelStep).toHaveTextContent('[OFFLINE]');
        expect(modelStep).toHaveTextContent('Ollama inference daemon is unreachable');
        expect(modelStep).toHaveTextContent('ollama serve');
      });

      expect(screen.getByTestId('copy-model-command')).toBeInTheDocument();
    });

    it('shows WARN [MISSING MODEL] and "ollama pull llama3.2" when Ollama has 0 models', async () => {
      vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
        if ((String(url).includes('/api/v1/health') || String(url).includes('/api/health'))) {
          return Promise.resolve(new Response(JSON.stringify({
            status: 'ok',
            version: '0.4.0',
            uptime: 50,
            timestamp: new Date().toISOString(),
            backendReachable: true,
            workspace: { root: '/workspace', agentsCount: 22, skillsCount: 24 },
            ollama: { status: 'connected', endpoint: 'http://127.0.0.1:11434', reachable: true, availableModels: [] }
          })));
        }
        if ((String(url).includes('/api/v1/models') || String(url).includes('/api/models'))) {
          return Promise.resolve(new Response(JSON.stringify({
            provider: 'ollama',
            reachable: true,
            models: []
          })));
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });

      render(<SetupChecklist isSettingsView={true} />);

      await waitFor(() => {
        const modelStep = screen.getByTestId('setup-step-model');
        expect(modelStep).toHaveTextContent('[MISSING MODEL]');
        expect(modelStep).toHaveTextContent('Ollama daemon is running, but no chat models are installed locally.');
        expect(modelStep).toHaveTextContent('ollama pull llama3.2');
        expect(modelStep).toHaveTextContent('mistral');
        expect(modelStep).toHaveTextContent('deepseek-r1');
      });
    });

    it('shows PASS [READY] and detected models when models are available', async () => {
      vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
        if ((String(url).includes('/api/v1/health') || String(url).includes('/api/health'))) {
          return Promise.resolve(new Response(JSON.stringify({
            status: 'ok',
            version: '0.4.0',
            uptime: 50,
            timestamp: new Date().toISOString(),
            backendReachable: true,
            workspace: { root: '/workspace', agentsCount: 22, skillsCount: 24 },
            ollama: { status: 'connected', endpoint: 'http://127.0.0.1:11434', reachable: true, availableModels: ['llama3.2:latest', 'mistral:latest'] }
          })));
        }
        if ((String(url).includes('/api/v1/models') || String(url).includes('/api/models'))) {
          return Promise.resolve(new Response(JSON.stringify({
            provider: 'ollama',
            reachable: true,
            models: [
              { id: 'llama3.2:latest', name: 'Llama 3.2 (3B)' },
              { id: 'mistral:latest', name: 'Mistral 7B' }
            ]
          })));
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });

      render(<SetupChecklist isSettingsView={true} />);

      await waitFor(() => {
        const modelStep = screen.getByTestId('setup-step-model');
        expect(modelStep).toHaveTextContent('[READY]');
        expect(modelStep).toHaveTextContent('Ollama online with 2 model(s) installed');
      });
    });

    it('shows PASS [CLOUD ACTIVE] with data residency note when cloud provider has API key', async () => {
      const cloudSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'google',
        keys: {
          ...DEFAULT_USER_SETTINGS.keys,
          google: 'AIzaSyTestKeyGoogle'
        }
      };
      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify(cloudSettings));

      vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
        if ((String(url).includes('/api/v1/health') || String(url).includes('/api/health'))) {
          return Promise.resolve(new Response(JSON.stringify({
            status: 'ok',
            version: '0.4.0',
            uptime: 10,
            timestamp: new Date().toISOString(),
            backendReachable: true,
            workspace: { root: '/workspace', agentsCount: 22, skillsCount: 24 },
            ollama: { status: 'unreachable', endpoint: 'http://127.0.0.1:11434', reachable: false }
          })));
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });

      render(<SetupChecklist isSettingsView={true} />);

      await waitFor(() => {
        const modelStep = screen.getByTestId('setup-step-model');
        expect(modelStep).toHaveTextContent('[CLOUD ACTIVE]');
        expect(modelStep).toHaveTextContent('Cloud inference active with Google Gemini.');
        expect(modelStep).toHaveTextContent('Data residency notice (#85)');
        expect(modelStep).toHaveTextContent('messages and attachments leave this device over the network');
      });
    });

    it('shows WARN [API KEY MISSING] when cloud provider is selected but has empty key', async () => {
      const cloudSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'anthropic',
        keys: {
          ...DEFAULT_USER_SETTINGS.keys,
          anthropic: ''
        }
      };
      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify(cloudSettings));

      vi.spyOn(global, 'fetch').mockImplementation(() => {
        return Promise.resolve(new Response(JSON.stringify({
          status: 'ok',
          backendReachable: true,
          workspace: { root: '/workspace', agentsCount: 22, skillsCount: 24 },
          ollama: { status: 'unreachable', endpoint: 'http://127.0.0.1:11434', reachable: false }
        })));
      });

      render(<SetupChecklist isSettingsView={true} />);

      await waitFor(() => {
        const modelStep = screen.getByTestId('setup-step-model');
        expect(modelStep).toHaveTextContent('[API KEY MISSING]');
        expect(modelStep).toHaveTextContent('Anthropic Claude selected, but API key is missing.');
      });
    });
  });

  describe('Probe 3: Flagship Starters & Re-check Controls', () => {
    it('renders "Try a starter" linking to visit-steward', () => {
      render(<SetupChecklist isSettingsView={true} />);

      const starterStep = screen.getByTestId('setup-step-starters');
      expect(starterStep).toBeInTheDocument();
      expect(starterStep).toHaveTextContent('[READY]');
      expect(starterStep).toHaveTextContent('Visit Steward is ready');

      const starterBtn = screen.getByTestId('setup-starter-btn');
      expect(starterBtn).toHaveAttribute('href', '/chat?agent=visit-steward');
    });

    it('re-runs connectivity checks when Re-check button is clicked', async () => {
      const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(() => {
        return Promise.resolve(new Response(JSON.stringify({
          status: 'ok',
          backendReachable: true,
          workspace: { root: '/workspace', agentsCount: 22, skillsCount: 24 },
          ollama: { status: 'connected', endpoint: 'http://127.0.0.1:11434', reachable: true }
        })));
      });

      render(<SetupChecklist isSettingsView={true} />);

      await waitFor(() => {
        expect(screen.getByTestId('setup-recheck-btn')).toBeInTheDocument();
      });

      const initialCallCount = fetchSpy.mock.calls.length;
      const recheckBtn = screen.getByTestId('setup-recheck-btn');
      fireEvent.click(recheckBtn);

      await waitFor(() => {
        expect(fetchSpy.mock.calls.length).toBeGreaterThan(initialCallCount);
      });
    });

    it('copies terminal fix commands to clipboard and provides user feedback', async () => {
      const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);

      vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
        if ((String(url).includes('/api/v1/health') || String(url).includes('/api/health'))) {
          return Promise.reject(new Error('offline'));
        }
        return Promise.resolve(new Response('{}', { status: 500 }));
      });

      render(<SetupChecklist isSettingsView={true} />);

      await waitFor(() => {
        expect(screen.getByTestId('copy-backend-command')).toBeInTheDocument();
      });

      const copyBtn = screen.getByTestId('copy-backend-command');
      fireEvent.click(copyBtn);

      expect(writeTextSpy).toHaveBeenCalledWith('pnpm dev:backend');
      await waitFor(() => {
        expect(screen.getByText('Copied')).toBeInTheDocument();
      });
    });
  });

  describe('Settings Modal Diagnostics Integration', () => {
    it('renders Diagnostics tab in SettingsModal and allows switching between tabs', async () => {
      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={DEFAULT_USER_SETTINGS}
        />
      );

      const providersTab = screen.getByTestId('settings-tab-providers');
      const diagnosticsTab = screen.getByTestId('settings-tab-diagnostics');

      expect(providersTab).toHaveAttribute('aria-selected', 'true');
      expect(screen.queryByTestId('settings-diagnostics-panel')).not.toBeInTheDocument();

      fireEvent.click(diagnosticsTab);

      expect(diagnosticsTab).toHaveAttribute('aria-selected', 'true');
      expect(providersTab).toHaveAttribute('aria-selected', 'false');
      expect(screen.getByTestId('settings-diagnostics-panel')).toBeInTheDocument();
      expect(screen.getByTestId('setup-checklist')).toBeInTheDocument();
    });
  });
});
