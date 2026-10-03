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
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { SettingsModal } from '@/components/SettingsModal';
import { DEFAULT_USER_SETTINGS, CAREFOLD_SETTINGS_STORAGE_KEY, type CarefoldUserSettings } from '@/lib/settings';

describe('SettingsModal Component', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('does not render dialog in DOM when isOpen is false', () => {
    render(
      <SettingsModal
        isOpen={false}
        onClose={vi.fn()}
        initialSettings={DEFAULT_USER_SETTINGS}
      />
    );

    expect(screen.queryByTestId('settings-modal')).not.toBeInTheDocument();
  });

  it('renders accessible dialog with privacy guarantee when isOpen is true', () => {
    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        initialSettings={DEFAULT_USER_SETTINGS}
      />
    );

    const dialog = screen.getByTestId('settings-modal');
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute('role', 'dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');

    expect(screen.getByTestId('privacy-notice')).toHaveTextContent('Local-First Privacy Guarantee');
  });

  it('pre-fills input fields with provided settings', () => {
    const existingSettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      keys: {
        google: 'AIzaSyExistingKey',
        anthropic: 'sk-ant-existing',
        openai: 'sk-proj-existing',
        custom: 'custom-tok'
      },
      endpoints: {
        ollamaUrl: 'http://localhost:11434',
        customUrl: 'http://localhost:8000/v1'
      }
    };

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        initialSettings={existingSettings}
      />
    );

    expect(screen.getByTestId('ollama-url-input')).toHaveValue('http://localhost:11434');
    expect(screen.getByTestId('gemini-key-input')).toHaveValue('AIzaSyExistingKey');
    expect(screen.getByTestId('anthropic-key-input')).toHaveValue('sk-ant-existing');
    expect(screen.getByTestId('openai-key-input')).toHaveValue('sk-proj-existing');
    expect(screen.getByTestId('custom-url-input')).toHaveValue('http://localhost:8000/v1');
    expect(screen.getByTestId('custom-key-input')).toHaveValue('custom-tok');
  });

  it('toggles password visibility when eye icon button is clicked', () => {
    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        initialSettings={DEFAULT_USER_SETTINGS}
      />
    );

    const geminiInput = screen.getByTestId('gemini-key-input');
    const toggleBtn = screen.getByTestId('toggle-gemini-key');

    // Initially masked
    expect(geminiInput).toHaveAttribute('type', 'password');

    // Click to show
    fireEvent.click(toggleBtn);
    expect(geminiInput).toHaveAttribute('type', 'text');

    // Click again to hide
    fireEvent.click(toggleBtn);
    expect(geminiInput).toHaveAttribute('type', 'password');
  });

  it('saves updated settings to localStorage and triggers onSave callback', () => {
    const handleSave = vi.fn();
    const handleClose = vi.fn();

    render(
      <SettingsModal
        isOpen={true}
        onClose={handleClose}
        initialSettings={DEFAULT_USER_SETTINGS}
        onSave={handleSave}
      />
    );

    const geminiInput = screen.getByTestId('gemini-key-input');
    fireEvent.change(geminiInput, { target: { value: 'AIzaSyNewSavedKey123' } });

    const saveBtn = screen.getByTestId('save-settings-btn');
    fireEvent.click(saveBtn);

    // Verify onSave invoked
    expect(handleSave).toHaveBeenCalledWith(
      expect.objectContaining({
        keys: expect.objectContaining({
          google: 'AIzaSyNewSavedKey123'
        })
      })
    );

    // Verify localStorage persistence
    const savedRaw = localStorage.getItem(CAREFOLD_SETTINGS_STORAGE_KEY);
    expect(savedRaw).toBeTruthy();
    expect(JSON.parse(savedRaw!).keys.google).toBe('AIzaSyNewSavedKey123');

    // Verify success banner visible
    expect(screen.getByTestId('save-success-badge')).toBeInTheDocument();
  });

  it('calls onClose without saving when cancel button is clicked', () => {
    const handleClose = vi.fn();
    const handleSave = vi.fn();

    render(
      <SettingsModal
        isOpen={true}
        onClose={handleClose}
        initialSettings={DEFAULT_USER_SETTINGS}
        onSave={handleSave}
      />
    );

    const cancelBtn = screen.getByTestId('cancel-settings-btn');
    fireEvent.click(cancelBtn);

    expect(handleClose).toHaveBeenCalledTimes(1);
    expect(handleSave).not.toHaveBeenCalled();
    expect(localStorage.getItem(CAREFOLD_SETTINGS_STORAGE_KEY)).toBeNull();
  });

  it('closes modal when Escape key is pressed', () => {
    const handleClose = vi.fn();

    render(
      <SettingsModal
        isOpen={true}
        onClose={handleClose}
        initialSettings={DEFAULT_USER_SETTINGS}
      />
    );

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(handleClose).toHaveBeenCalledTimes(1);
  });
});
