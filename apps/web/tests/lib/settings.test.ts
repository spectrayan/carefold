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
import {
  DEFAULT_USER_SETTINGS,
  CAREFOLD_SETTINGS_STORAGE_KEY,
  loadSettings,
  saveSettings,
  hasApiKeyForProvider,
  getApiKeyForProvider,
  getEndpointForProvider,
  getEffectiveModel,
  type CarefoldUserSettings
} from '@/lib/settings';

describe('User Settings & Local Storage Persistence', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('provides sensible default settings with Ollama and zero keys', () => {
    expect(DEFAULT_USER_SETTINGS.provider).toBe('ollama');
    expect(DEFAULT_USER_SETTINGS.model).toBe('llama3.2');
    expect(DEFAULT_USER_SETTINGS.endpoints.ollamaUrl).toBe('http://127.0.0.1:11434');
    expect(DEFAULT_USER_SETTINGS.keys.google).toBe('');
    expect(DEFAULT_USER_SETTINGS.keys.anthropic).toBe('');
    expect(DEFAULT_USER_SETTINGS.keys.openai).toBe('');
  });

  it('loadSettings returns DEFAULT_USER_SETTINGS when localStorage is empty', () => {
    const settings = loadSettings();
    expect(settings).toEqual(DEFAULT_USER_SETTINGS);
  });

  it('loadSettings recovers gracefully from corrupted JSON in localStorage', () => {
    localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, '{invalid json');
    const settings = loadSettings();
    expect(settings).toEqual(DEFAULT_USER_SETTINGS);
  });

  it('saveSettings serializes settings to localStorage and dispatches change event', () => {
    const listener = vi.fn();
    window.addEventListener('carefold:settings-changed', listener);

    const updated: Partial<CarefoldUserSettings> = {
      provider: 'google',
      model: 'gemini-2.0-flash',
      keys: { google: 'AIzaSyTestKey123' }
    };

    const saved = saveSettings(updated);
    expect(saved.provider).toBe('google');
    expect(saved.model).toBe('gemini-2.0-flash');
    expect(saved.keys.google).toBe('AIzaSyTestKey123');

    // Verify localStorage item
    const raw = localStorage.getItem(CAREFOLD_SETTINGS_STORAGE_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.provider).toBe('google');
    expect(parsed.keys.google).toBe('AIzaSyTestKey123');

    // Verify event dispatch
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener('carefold:settings-changed', listener);
  });

  it('loadSettings properly merges partial stored data with defaults', () => {
    const stored = {
      provider: 'anthropic',
      keys: { anthropic: 'sk-ant-test-key' }
    };
    localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify(stored));

    const loaded = loadSettings();
    expect(loaded.provider).toBe('anthropic');
    expect(loaded.keys.anthropic).toBe('sk-ant-test-key');
    expect(loaded.endpoints.ollamaUrl).toBe('http://127.0.0.1:11434'); // fallback to default
  });

  it('hasApiKeyForProvider correctly identifies required credentials', () => {
    const settings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      provider: 'google',
      keys: { google: 'AIzaSy123', anthropic: '', openai: '' }
    };

    // Ollama and Custom always return true
    expect(hasApiKeyForProvider(settings, 'ollama')).toBe(true);
    expect(hasApiKeyForProvider(settings, 'custom')).toBe(true);

    // Configured cloud provider
    expect(hasApiKeyForProvider(settings, 'google')).toBe(true);

    // Unconfigured cloud providers
    expect(hasApiKeyForProvider(settings, 'anthropic')).toBe(false);
    expect(hasApiKeyForProvider(settings, 'openai')).toBe(false);
  });

  it('getApiKeyForProvider extracts trimmed key or undefined', () => {
    const settings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      keys: { google: '   AIzaSyTrimMe   ', anthropic: '' }
    };

    expect(getApiKeyForProvider(settings, 'google')).toBe('AIzaSyTrimMe');
    expect(getApiKeyForProvider(settings, 'anthropic')).toBeUndefined();
    expect(getApiKeyForProvider(settings, 'ollama')).toBeUndefined();
  });

  it('getEndpointForProvider returns correct URL based on provider', () => {
    const settings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      endpoints: {
        ollamaUrl: 'http://custom-ollama:11434',
        customUrl: 'http://my-vllm:8000/v1'
      }
    };

    expect(getEndpointForProvider(settings, 'ollama')).toBe('http://custom-ollama:11434');
    expect(getEndpointForProvider(settings, 'custom')).toBe('http://my-vllm:8000/v1');
    expect(getEndpointForProvider(settings, 'google')).toBeUndefined();
  });

  it('getEffectiveModel handles custom model strings', () => {
    const customProviderSettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      provider: 'custom',
      customModelName: 'deepseek-r1:70b'
    };
    expect(getEffectiveModel(customProviderSettings)).toBe('deepseek-r1:70b');

    const customModelSettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      provider: 'ollama',
      model: 'custom',
      customModelName: 'qwen2.5-coder:32b'
    };
    expect(getEffectiveModel(customModelSettings)).toBe('qwen2.5-coder:32b');

    const standardSettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      provider: 'openai',
      model: 'gpt-4o'
    };
    expect(getEffectiveModel(standardSettings)).toBe('gpt-4o');
  });
});
