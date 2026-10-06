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
  isLoopbackHost,
  isLocalProvider,
  getProviderPrivacyState,
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

describe('Data Residency & Loopback Resolution', () => {
  describe('isLoopbackHost', () => {
    it('identifies localhost with and without port or protocol as loopback', () => {
      expect(isLoopbackHost('localhost')).toBe(true);
      expect(isLoopbackHost('localhost:11434')).toBe(true);
      expect(isLoopbackHost('http://localhost:11434')).toBe(true);
      expect(isLoopbackHost('https://localhost:8000/v1')).toBe(true);
      expect(isLoopbackHost('localhost.')).toBe(true);
      expect(isLoopbackHost('http://localhost.')).toBe(true);
    });

    it('identifies IPv4 127.0.0.0/8 range as loopback', () => {
      expect(isLoopbackHost('127.0.0.1')).toBe(true);
      expect(isLoopbackHost('127.0.0.1:11434')).toBe(true);
      expect(isLoopbackHost('http://127.0.0.1:11434')).toBe(true);
      expect(isLoopbackHost('http://127.0.0.2:8000')).toBe(true);
      expect(isLoopbackHost('127.255.255.254')).toBe(true);
      expect(isLoopbackHost('http://127.255.255.254:8080/v1')).toBe(true);
    });

    it('identifies IPv6 loopback addresses as loopback', () => {
      expect(isLoopbackHost('::1')).toBe(true);
      expect(isLoopbackHost('[::1]')).toBe(true);
      expect(isLoopbackHost('[::1]:11434')).toBe(true);
      expect(isLoopbackHost('http://[::1]:11434')).toBe(true);
      expect(isLoopbackHost('0:0:0:0:0:0:0:1')).toBe(true);
      expect(isLoopbackHost('0000:0000:0000:0000:0000:0000:0000:0001')).toBe(true);
    });

    it('fails closed (returns false) on LAN and WAN hosts', () => {
      expect(isLoopbackHost('192.168.1.100')).toBe(false);
      expect(isLoopbackHost('http://192.168.1.100:11434')).toBe(false);
      expect(isLoopbackHost('10.0.0.1')).toBe(false);
      expect(isLoopbackHost('http://10.0.0.5:8000')).toBe(false);
      expect(isLoopbackHost('http://172.16.0.1:11434')).toBe(false);
      expect(isLoopbackHost('http://172.31.255.254:11434')).toBe(false);
      expect(isLoopbackHost('http://example.com')).toBe(false);
      expect(isLoopbackHost('http://ollama.internal:11434')).toBe(false);
    });

    it('fails closed on wildcard bind address 0.0.0.0', () => {
      expect(isLoopbackHost('0.0.0.0')).toBe(false);
      expect(isLoopbackHost('http://0.0.0.0:11434')).toBe(false);
    });

    it('fails closed on null, undefined, empty, whitespace, and unparseable URLs', () => {
      expect(isLoopbackHost(null)).toBe(false);
      expect(isLoopbackHost(undefined)).toBe(false);
      expect(isLoopbackHost('')).toBe(false);
      expect(isLoopbackHost('   ')).toBe(false);
      expect(isLoopbackHost('://invalid')).toBe(false);
      expect(isLoopbackHost('http://')).toBe(false);
      expect(isLoopbackHost('not a valid url with spaces')).toBe(false);
    });
  });

  describe('isLocalProvider', () => {
    it('returns true for Ollama pointing to loopback endpoint', () => {
      const settings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'ollama',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          ollamaUrl: 'http://127.0.0.1:11434'
        }
      };
      expect(isLocalProvider(settings)).toBe(true);
    });

    it('returns false for Ollama pointing to remote LAN machine', () => {
      const settings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'ollama',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          ollamaUrl: 'http://192.168.1.100:11434'
        }
      };
      expect(isLocalProvider(settings)).toBe(false);
    });

    it('fails closed (returns false) for Ollama with malformed or empty endpoint', () => {
      const malformedSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'ollama',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          ollamaUrl: '://invalid-host'
        }
      };
      expect(isLocalProvider(malformedSettings)).toBe(false);
    });

    it('returns true for Custom provider pointing to localhost', () => {
      const settings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'custom',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          customUrl: 'http://localhost:8000/v1'
        }
      };
      expect(isLocalProvider(settings)).toBe(true);
    });

    it('returns false for Custom provider pointing to remote URL', () => {
      const settings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'custom',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          customUrl: 'https://api.together.xyz/v1'
        }
      };
      expect(isLocalProvider(settings)).toBe(false);
    });

    it('returns false unconditionally for cloud providers (google, anthropic, openai)', () => {
      expect(isLocalProvider({ ...DEFAULT_USER_SETTINGS, provider: 'google' })).toBe(false);
      expect(isLocalProvider({ ...DEFAULT_USER_SETTINGS, provider: 'anthropic' })).toBe(false);
      expect(isLocalProvider({ ...DEFAULT_USER_SETTINGS, provider: 'openai' })).toBe(false);
    });
  });

  describe('getProviderPrivacyState', () => {
    it('returns on-device residency descriptor for loopback Ollama', () => {
      const state = getProviderPrivacyState(DEFAULT_USER_SETTINGS);
      expect(state.isLocal).toBe(true);
      expect(state.provider).toBe('ollama');
      expect(state.providerLabel).toBe('Ollama');
      expect(state.badgeText).toBe('On-Device');
      expect(state.badgeVariant).toBe('emerald');
      expect(state.emptyStateText).toBe('All data remains exclusively on your device.');
      expect(state.footerText).toBe('Zero cloud sync • No prompt telemetry • 100% on-device');
      expect(state.explainerTitle).toBe('On-Device Data Residency');
      expect(state.explainerDescription).toContain('remain strictly on your local machine');
      expect(state.destinationLabel).toContain('127.0.0.1');
    });

    it('returns remote residency descriptor for remote LAN Ollama', () => {
      const remoteSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'ollama',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          ollamaUrl: 'http://192.168.1.50:11434'
        }
      };
      const state = getProviderPrivacyState(remoteSettings);
      expect(state.isLocal).toBe(false);
      expect(state.badgeText).toBe('Remote (Ollama)');
      expect(state.badgeVariant).toBe('amber');
      expect(state.emptyStateText).toBe('Your messages are sent to Ollama to generate replies.');
      expect(state.footerText).toBe('Remote inference active (Ollama) • Zero Carefold telemetry');
      expect(state.explainerTitle).toBe('Remote Ollama Data Residency');
      expect(state.destinationLabel).toContain('192.168.1.50:11434');
    });

    it('returns cloud residency descriptor for Google Gemini', () => {
      const state = getProviderPrivacyState({ ...DEFAULT_USER_SETTINGS, provider: 'google' });
      expect(state.isLocal).toBe(false);
      expect(state.badgeText).toBe('Cloud (Gemini)');
      expect(state.badgeVariant).toBe('amber');
      expect(state.emptyStateText).toBe('Your messages are sent to Gemini to generate replies.');
      expect(state.footerText).toBe('Cloud inference active (Gemini) • Zero Carefold telemetry');
      expect(state.explainerTitle).toBe('Cloud Provider Data Residency');
      expect(state.destinationLabel).toBe('Gemini Cloud API');
    });

    it('returns cloud residency descriptor for Anthropic Claude', () => {
      const state = getProviderPrivacyState({ ...DEFAULT_USER_SETTINGS, provider: 'anthropic' });
      expect(state.isLocal).toBe(false);
      expect(state.badgeText).toBe('Cloud (Claude)');
      expect(state.badgeVariant).toBe('amber');
      expect(state.emptyStateText).toBe('Your messages are sent to Claude to generate replies.');
      expect(state.footerText).toBe('Cloud inference active (Claude) • Zero Carefold telemetry');
      expect(state.destinationLabel).toBe('Claude Cloud API');
    });

    it('returns cloud residency descriptor for OpenAI', () => {
      const state = getProviderPrivacyState({ ...DEFAULT_USER_SETTINGS, provider: 'openai' });
      expect(state.isLocal).toBe(false);
      expect(state.badgeText).toBe('Cloud (OpenAI)');
      expect(state.badgeVariant).toBe('amber');
      expect(state.emptyStateText).toBe('Your messages are sent to OpenAI to generate replies.');
      expect(state.footerText).toBe('Cloud inference active (OpenAI) • Zero Carefold telemetry');
      expect(state.destinationLabel).toBe('OpenAI Cloud API');
    });

    it('returns remote residency descriptor for remote Custom endpoint', () => {
      const customSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'custom',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          customUrl: 'https://vllm.internal.corp/v1'
        }
      };
      const state = getProviderPrivacyState(customSettings);
      expect(state.isLocal).toBe(false);
      expect(state.badgeText).toBe('Remote (Custom)');
      expect(state.badgeVariant).toBe('amber');
      expect(state.emptyStateText).toBe('Your messages are sent to Custom to generate replies.');
      expect(state.footerText).toBe('Remote inference active (Custom) • Zero Carefold telemetry');
    });

    it('fails closed to amber badge for unparseable or malformed URLs', () => {
      const malformedSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'ollama',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          ollamaUrl: '://unparseable'
        }
      };
      const state = getProviderPrivacyState(malformedSettings);
      expect(state.isLocal).toBe(false);
      expect(state.badgeVariant).toBe('amber');
      expect(state.emptyStateText).not.toContain('exclusively on your device');
    });
  });
});

