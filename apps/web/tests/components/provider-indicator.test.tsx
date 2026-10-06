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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { Navbar } from '@/components/Navbar';
import { FooterPrivacyNotice } from '@/components/FooterPrivacyNotice';
import { ThemeProvider } from '@/components/ThemeProvider';
import {
  DEFAULT_USER_SETTINGS,
  saveSettings,
  CAREFOLD_SETTINGS_STORAGE_KEY
} from '@/lib/settings';

// Mock Next.js navigation hooks
vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));

describe('Provider Data Residency Indicator & Explainer Popover', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ollama: { reachable: true } })
    }));
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders emerald on-device badge for default loopback Ollama', () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    const badgeBtn = screen.getByTestId('provider-status-badge');
    expect(badgeBtn).toBeInTheDocument();
    expect(badgeBtn).toHaveTextContent('On-Device');

    const residencySpan = screen.getByTestId('data-residency-badge');
    expect(residencySpan).toHaveTextContent('On-Device');

    // Emerald styling classes
    expect(badgeBtn.className).toContain('border-emerald-200');
    expect(badgeBtn.className).toContain('text-emerald-800');
  });

  it('renders amber badge for OpenAI cloud provider', () => {
    localStorage.setItem(
      CAREFOLD_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_USER_SETTINGS,
        provider: 'openai',
        model: 'gpt-4o'
      })
    );

    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    const badgeBtn = screen.getByTestId('provider-status-badge');
    expect(badgeBtn).toHaveTextContent('Cloud (OpenAI)');
    expect(badgeBtn.className).toContain('border-amber-200');
    expect(badgeBtn.className).toContain('text-amber-800');
  });

  it('renders amber badge for Anthropic Claude provider', () => {
    localStorage.setItem(
      CAREFOLD_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_USER_SETTINGS,
        provider: 'anthropic',
        model: 'claude-3-5-sonnet-latest'
      })
    );

    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    const badgeBtn = screen.getByTestId('provider-status-badge');
    expect(badgeBtn).toHaveTextContent('Cloud (Claude)');
    expect(badgeBtn.className).toContain('border-amber-200');
  });

  it('renders amber badge for Google Gemini provider', () => {
    localStorage.setItem(
      CAREFOLD_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_USER_SETTINGS,
        provider: 'google',
        model: 'gemini-2.0-flash'
      })
    );

    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    const badgeBtn = screen.getByTestId('provider-status-badge');
    expect(badgeBtn).toHaveTextContent('Cloud (Gemini)');
    expect(badgeBtn.className).toContain('border-amber-200');
  });

  it('renders amber Remote (Ollama) badge for non-loopback LAN Ollama endpoint', () => {
    localStorage.setItem(
      CAREFOLD_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_USER_SETTINGS,
        provider: 'ollama',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          ollamaUrl: 'http://192.168.1.100:11434'
        }
      })
    );

    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    const badgeBtn = screen.getByTestId('provider-status-badge');
    expect(badgeBtn).toHaveTextContent('Remote (Ollama)');
    expect(badgeBtn.className).toContain('border-amber-200');
  });

  it('fails closed to amber badge when Ollama endpoint is unparseable', () => {
    localStorage.setItem(
      CAREFOLD_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_USER_SETTINGS,
        provider: 'ollama',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          ollamaUrl: '://invalid-scheme-unparseable'
        }
      })
    );

    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    const badgeBtn = screen.getByTestId('provider-status-badge');
    expect(badgeBtn).toHaveTextContent('Remote (Ollama)');
    expect(badgeBtn.className).toContain('border-amber-200');
  });

  it('updates reactively when carefold:settings-changed event is dispatched', async () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    const badgeBtn = screen.getByTestId('provider-status-badge');
    expect(badgeBtn).toHaveTextContent('On-Device');

    // Simulate switching to OpenAI in Settings or ModelSelector
    saveSettings({
      provider: 'openai',
      model: 'gpt-4o'
    });

    await waitFor(() => {
      expect(badgeBtn).toHaveTextContent('Cloud (OpenAI)');
    });
    expect(badgeBtn.className).toContain('border-amber-200');
  });

  it('opens and closes accessible explainer popover on badge click', () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    expect(screen.queryByTestId('privacy-explainer-popover')).not.toBeInTheDocument();

    const badgeBtn = screen.getByTestId('provider-status-badge');
    fireEvent.click(badgeBtn);

    const popover = screen.getByTestId('privacy-explainer-popover');
    expect(popover).toBeInTheDocument();
    expect(screen.getByTestId('privacy-explainer-title')).toHaveTextContent('On-Device Data Residency');
    expect(screen.getByTestId('privacy-explainer-description')).toHaveTextContent('strictly on your local machine');
    expect(screen.getByTestId('privacy-destination-label')).toHaveTextContent(/127\.0\.0\.1/);

    // Dismiss via close button
    const closeBtn = screen.getByTestId('close-explainer-btn');
    fireEvent.click(closeBtn);
    expect(screen.queryByTestId('privacy-explainer-popover')).not.toBeInTheDocument();
  });

  it('allows switching to Local (Ollama) directly from explainer popover', async () => {
    localStorage.setItem(
      CAREFOLD_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_USER_SETTINGS,
        provider: 'openai',
        model: 'gpt-4o'
      })
    );

    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    const badgeBtn = screen.getByTestId('provider-status-badge');
    expect(badgeBtn).toHaveTextContent('Cloud (OpenAI)');

    // Open popover
    fireEvent.click(badgeBtn);

    const switchBtn = screen.getByTestId('switch-to-local-btn');
    expect(switchBtn).toBeInTheDocument();
    expect(switchBtn).toHaveTextContent('Switch to Local (Ollama)');

    fireEvent.click(switchBtn);

    // Popover closes and badge switches to On-Device
    expect(screen.queryByTestId('privacy-explainer-popover')).not.toBeInTheDocument();
    await waitFor(() => {
      expect(badgeBtn).toHaveTextContent('On-Device');
    });
    expect(badgeBtn.className).toContain('border-emerald-200');
  });

  it('opens SettingsModal when Configure in Settings is clicked from popover', () => {
    render(
      <ThemeProvider defaultTheme="light">
        <Navbar />
      </ThemeProvider>
    );

    const badgeBtn = screen.getByTestId('provider-status-badge');
    fireEvent.click(badgeBtn);

    const configureBtn = screen.getByTestId('configure-settings-btn');
    expect(configureBtn).toBeInTheDocument();

    fireEvent.click(configureBtn);

    // Popover is closed and Settings modal is visible
    expect(screen.queryByTestId('privacy-explainer-popover')).not.toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: /Settings/i })).toBeInTheDocument();
  });

  it('renders dynamic footer copy via FooterPrivacyNotice', async () => {
    render(<FooterPrivacyNotice />);

    const notice = screen.getByTestId('footer-privacy-notice');
    expect(notice).toHaveTextContent('Zero cloud sync • No prompt telemetry • 100% on-device');

    // Switch to cloud provider
    saveSettings({ provider: 'anthropic', model: 'claude-3-5-sonnet-latest' });

    await waitFor(() => {
      expect(notice).toHaveTextContent('Cloud inference active (Claude) • Zero Carefold telemetry');
    });
    expect(notice).not.toHaveTextContent('100% on-device');

    // Switch to remote Ollama
    saveSettings({
      provider: 'ollama',
      endpoints: {
        ...DEFAULT_USER_SETTINGS.endpoints,
        ollamaUrl: 'http://192.168.1.80:11434'
      }
    });

    await waitFor(() => {
      expect(notice).toHaveTextContent('Remote inference active (Ollama) • Zero Carefold telemetry');
    });
    expect(notice).not.toHaveTextContent('100% on-device');
  });
});
