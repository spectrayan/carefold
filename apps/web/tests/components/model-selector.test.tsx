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

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ModelSelector } from '@/components/ModelSelector';
import { DEFAULT_USER_SETTINGS, type CarefoldUserSettings } from '@/lib/settings';

describe('ModelSelector Component', () => {
  it('renders provider and model dropdowns with default options', () => {
    render(
      <ModelSelector
        settings={DEFAULT_USER_SETTINGS}
        onSettingsChange={vi.fn()}
        onOpenSettings={vi.fn()}
      />
    );

    const providerSelect = screen.getByTestId('provider-selector');
    expect(providerSelect).toBeInTheDocument();
    expect(providerSelect).toHaveValue('ollama');

    const modelSelect = screen.getByTestId('model-selector');
    expect(modelSelect).toBeInTheDocument();
    expect(modelSelect).toHaveValue('llama3.2');
  });

  it('switches provider and auto-selects recommended default model', () => {
    const handleSettingsChange = vi.fn();
    render(
      <ModelSelector
        settings={DEFAULT_USER_SETTINGS}
        onSettingsChange={handleSettingsChange}
        onOpenSettings={vi.fn()}
      />
    );

    const providerSelect = screen.getByTestId('provider-selector');
    fireEvent.change(providerSelect, { target: { value: 'google' } });

    expect(handleSettingsChange).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: 'google',
        model: 'gemini-2.0-flash'
      })
    );
  });

  it('filters available models dynamically when provider changes', () => {
    const googleSettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      provider: 'google',
      model: 'gemini-2.0-flash'
    };

    render(
      <ModelSelector
        settings={googleSettings}
        onSettingsChange={vi.fn()}
        onOpenSettings={vi.fn()}
      />
    );

    const modelSelect = screen.getByTestId('model-selector');
    expect(modelSelect).toContainHTML('Gemini 2.0 Flash');
    expect(modelSelect).toContainHTML('Gemini 1.5 Pro');
    expect(modelSelect).not.toContainHTML('Llama 3.2');
  });

  it('renders custom model text input when provider is custom', () => {
    const customSettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      provider: 'custom',
      model: 'custom',
      customModelName: 'qwen2.5-coder:32b'
    };

    const handleSettingsChange = vi.fn();
    render(
      <ModelSelector
        settings={customSettings}
        onSettingsChange={handleSettingsChange}
        onOpenSettings={vi.fn()}
      />
    );

    const customInput = screen.getByTestId('custom-model-input');
    expect(customInput).toBeInTheDocument();
    expect(customInput).toHaveValue('qwen2.5-coder:32b');

    fireEvent.change(customInput, { target: { value: 'deepseek-coder:6.7b' } });
    expect(handleSettingsChange).toHaveBeenCalledWith(
      expect.objectContaining({
        customModelName: 'deepseek-coder:6.7b'
      })
    );
  });

  it('displays amber Key Required badge when cloud provider lacks API key', () => {
    const noKeySettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      provider: 'anthropic',
      model: 'claude-3-5-sonnet-latest',
      keys: { anthropic: '' }
    };

    const handleOpenSettings = vi.fn();
    render(
      <ModelSelector
        settings={noKeySettings}
        onSettingsChange={vi.fn()}
        onOpenSettings={handleOpenSettings}
      />
    );

    const keyBadge = screen.getByTestId('missing-key-badge');
    expect(keyBadge).toBeInTheDocument();
    expect(keyBadge).toHaveTextContent('Key Required');

    fireEvent.click(keyBadge);
    expect(handleOpenSettings).toHaveBeenCalledTimes(1);
  });

  it('hides Key Required badge when cloud provider has configured API key', () => {
    const keyedSettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      provider: 'anthropic',
      model: 'claude-3-5-sonnet-latest',
      keys: { anthropic: 'sk-ant-test-key-configured' }
    };

    render(
      <ModelSelector
        settings={keyedSettings}
        onSettingsChange={vi.fn()}
        onOpenSettings={vi.fn()}
      />
    );

    expect(screen.queryByTestId('missing-key-badge')).not.toBeInTheDocument();
  });

  it('never displays Key Required badge for Ollama provider', () => {
    render(
      <ModelSelector
        settings={DEFAULT_USER_SETTINGS}
        onSettingsChange={vi.fn()}
        onOpenSettings={vi.fn()}
      />
    );

    expect(screen.queryByTestId('missing-key-badge')).not.toBeInTheDocument();
  });

  it('opens Settings Modal when settings button is clicked', () => {
    const handleOpenSettings = vi.fn();
    render(
      <ModelSelector
        settings={DEFAULT_USER_SETTINGS}
        onSettingsChange={vi.fn()}
        onOpenSettings={handleOpenSettings}
      />
    );

    const settingsBtn = screen.getByTestId('open-settings-button');
    fireEvent.click(settingsBtn);
    expect(handleOpenSettings).toHaveBeenCalledTimes(1);
  });

  it('disables controls when disabled prop is true', () => {
    render(
      <ModelSelector
        settings={DEFAULT_USER_SETTINGS}
        onSettingsChange={vi.fn()}
        onOpenSettings={vi.fn()}
        disabled={true}
      />
    );

    expect(screen.getByTestId('provider-selector')).toBeDisabled();
    expect(screen.getByTestId('model-selector')).toBeDisabled();
    expect(screen.getByTestId('open-settings-button')).toBeDisabled();
  });
});
