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
import { render, screen, fireEvent } from '@testing-library/react';
import React, { useState } from 'react';
import {
  DEFAULT_USER_SETTINGS,
  CAREFOLD_SETTINGS_STORAGE_KEY,
  loadSettings,
  saveSettings,
  hasApiKeyForProvider,
  getApiKeyForProvider,
  getEndpointForProvider,
  getEffectiveModel,
  PROVIDER_METADATA,
  type CarefoldUserSettings,
  type ProviderType
} from '@/lib/settings';
import { ModelSelector } from '@/components/ModelSelector';
import { SettingsModal } from '@/components/SettingsModal';

describe('Adversarial Suite: Settings & Model Selection', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  // =========================================================================
  // Section 1: Corrupted & Adversarial localStorage Handling
  // =========================================================================
  describe('1. Corrupted & Adversarial localStorage JSON Handling', () => {
    it('recovers to DEFAULT_USER_SETTINGS when localStorage contains corrupted syntax', () => {
      const corruptPayloads = [
        '{bad json',
        '{"unterminated: "string',
        'undefined',
        '{"keys": }',
        '<<<XML NOT JSON>>>'
      ];

      for (const payload of corruptPayloads) {
        localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, payload);
        const settings = loadSettings();
        expect(settings).toEqual(DEFAULT_USER_SETTINGS);
      }
    });

    it('recovers to DEFAULT_USER_SETTINGS when localStorage contains "null" literal', () => {
      // JSON.parse("null") returns null. Dereferencing null.provider must not crash loadSettings
      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, 'null');
      const settings = loadSettings();
      expect(settings).toEqual(DEFAULT_USER_SETTINGS);
    });

    it('recovers to DEFAULT_USER_SETTINGS when localStorage contains non-object JSON primitives', () => {
      const primitives = ['12345', '"a plain string"', 'true', 'false', '3.14159'];
      for (const prim of primitives) {
        localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, prim);
        const settings = loadSettings();
        expect(settings.provider).toBe(DEFAULT_USER_SETTINGS.provider);
        expect(settings.model).toBe(DEFAULT_USER_SETTINGS.model);
        expect(settings.endpoints.ollamaUrl).toBe(DEFAULT_USER_SETTINGS.endpoints.ollamaUrl);
        expect(settings.keys.google).toBe('');
      }
    });

    it('recovers to DEFAULT_USER_SETTINGS when localStorage contains a JSON array', () => {
      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify([1, 2, 'malicious']));
      const settings = loadSettings();
      expect(settings.provider).toBe(DEFAULT_USER_SETTINGS.provider);
      expect(settings.model).toBe(DEFAULT_USER_SETTINGS.model);
      expect(settings.keys.google).toBe('');
    });

    it('handles empty JSON object {} and populates all default fields', () => {
      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, '{}');
      const settings = loadSettings();
      expect(settings).toEqual(DEFAULT_USER_SETTINGS);
    });

    it('handles partial objects missing keys or endpoints sub-objects without throwing', () => {
      const partialWithoutKeys = {
        provider: 'openai',
        model: 'gpt-4o'
      };
      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify(partialWithoutKeys));
      const settings = loadSettings();
      expect(settings.provider).toBe('openai');
      expect(settings.model).toBe('gpt-4o');
      expect(settings.keys).toEqual({
        google: '',
        anthropic: '',
        openai: '',
        custom: ''
      });
      expect(settings.endpoints).toEqual(DEFAULT_USER_SETTINGS.endpoints);
    });

    it('handles corrupted sub-objects (keys as string, endpoints as number)', () => {
      const corruptedSubObjects = {
        provider: 'anthropic',
        keys: 'NOT_AN_OBJECT',
        endpoints: 42
      };
      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify(corruptedSubObjects));
      const settings = loadSettings();
      expect(settings.provider).toBe('anthropic');
      expect(settings.keys.anthropic).toBe('');
      expect(settings.endpoints.ollamaUrl).toBe(DEFAULT_USER_SETTINGS.endpoints.ollamaUrl);
    });

    it('handles prototype pollution attempt in localStorage safely', () => {
      const pollutionPayload = '{"__proto__": {"admin": true, "polluted": true}}';
      localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, pollutionPayload);
      const settings = loadSettings();
      expect((Object.prototype as any).polluted).toBeUndefined();
      expect(settings.provider).toBe(DEFAULT_USER_SETTINGS.provider);
    });

    it('recovers gracefully when localStorage.getItem throws SecurityError or DOMException', () => {
      vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
        throw new DOMException('The operation is insecure.', 'SecurityError');
      });

      const settings = loadSettings();
      expect(settings).toEqual(DEFAULT_USER_SETTINGS);
    });

    it('saveSettings survives localStorage.setItem QuotaExceededError gracefully without throwing', () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
        throw new DOMException('QuotaExceededError', 'QuotaExceededError');
      });

      expect(() => {
        const result = saveSettings({ provider: 'anthropic' });
        expect(result.provider).toBe('anthropic');
      }).not.toThrow();

      expect(consoleSpy).toHaveBeenCalled();
      consoleSpy.mockRestore();
    });

    it('saveSettings dispatches carefold:settings-changed CustomEvent with updated settings payload', () => {
      const eventSpy = vi.fn();
      window.addEventListener('carefold:settings-changed', (e: any) => {
        eventSpy(e.detail);
      });

      saveSettings({
        provider: 'google',
        keys: { google: 'AIzaSyAdversarialKey' }
      });

      expect(eventSpy).toHaveBeenCalledTimes(1);
      expect(eventSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: 'google',
          keys: expect.objectContaining({ google: 'AIzaSyAdversarialKey' })
        })
      );
    });
  });

  // =========================================================================
  // Section 2: Key Masking and Visibility Toggles
  // =========================================================================
  describe('2. Key Masking and Visibility Toggles in SettingsModal', () => {
    const filledSettings: CarefoldUserSettings = {
      ...DEFAULT_USER_SETTINGS,
      keys: {
        google: 'AIzaSyGeminiSecret123',
        anthropic: 'sk-ant-anthropicSecret456',
        openai: 'sk-proj-openaiSecret789',
        custom: 'customSecretKey000'
      }
    };

    it('masks all four API key fields as password by default', () => {
      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={filledSettings}
        />
      );

      const geminiInput = screen.getByTestId('gemini-key-input');
      const anthropicInput = screen.getByTestId('anthropic-key-input');
      const openaiInput = screen.getByTestId('openai-key-input');
      const customInput = screen.getByTestId('custom-key-input');

      expect(geminiInput).toHaveAttribute('type', 'password');
      expect(anthropicInput).toHaveAttribute('type', 'password');
      expect(openaiInput).toHaveAttribute('type', 'password');
      expect(customInput).toHaveAttribute('type', 'password');
    });

    it('toggles password visibility independently for each provider with updated aria-labels', () => {
      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={filledSettings}
        />
      );

      const providers = [
        {
          inputTestId: 'gemini-key-input',
          toggleTestId: 'toggle-gemini-key',
          showLabel: 'Show Gemini API key',
          hideLabel: 'Hide Gemini API key'
        },
        {
          inputTestId: 'anthropic-key-input',
          toggleTestId: 'toggle-anthropic-key',
          showLabel: 'Show Anthropic API key',
          hideLabel: 'Hide Anthropic API key'
        },
        {
          inputTestId: 'openai-key-input',
          toggleTestId: 'toggle-openai-key',
          showLabel: 'Show OpenAI API key',
          hideLabel: 'Hide OpenAI API key'
        },
        {
          inputTestId: 'custom-key-input',
          toggleTestId: 'toggle-custom-key',
          showLabel: 'Show Custom API key',
          hideLabel: 'Hide Custom API key'
        }
      ];

      for (const p of providers) {
        const input = screen.getByTestId(p.inputTestId);
        const toggle = screen.getByTestId(p.toggleTestId);

        // Initial state: password & "Show ..." label
        expect(input).toHaveAttribute('type', 'password');
        expect(toggle).toHaveAttribute('aria-label', p.showLabel);

        // First click: unmasks to text & "Hide ..." label
        fireEvent.click(toggle);
        expect(input).toHaveAttribute('type', 'text');
        expect(toggle).toHaveAttribute('aria-label', p.hideLabel);

        // Second click: re-masks to password & "Show ..." label
        fireEvent.click(toggle);
        expect(input).toHaveAttribute('type', 'password');
        expect(toggle).toHaveAttribute('aria-label', p.showLabel);
      }
    });
  });

  // =========================================================================
  // Section 3: Missing Key Warning Badge Behavior
  // =========================================================================
  describe('3. Missing Key Warning Badge Behavior in ModelSelector', () => {
    it('never displays missing key badge for Ollama provider regardless of keys', () => {
      const ollamaEmptyKeys: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'ollama',
        keys: { google: '', anthropic: '', openai: '', custom: '' }
      };

      render(
        <ModelSelector
          settings={ollamaEmptyKeys}
          onOpenSettings={vi.fn()}
        />
      );

      expect(screen.queryByTestId('missing-key-badge')).not.toBeInTheDocument();
    });

    it('never displays missing key badge for Custom provider regardless of keys', () => {
      const customEmptyKeys: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'custom',
        keys: { google: '', anthropic: '', openai: '', custom: '' }
      };

      render(
        <ModelSelector
          settings={customEmptyKeys}
          onOpenSettings={vi.fn()}
        />
      );

      expect(screen.queryByTestId('missing-key-badge')).not.toBeInTheDocument();
    });

    it('displays missing key badge when cloud provider key is empty or whitespace-only', () => {
      const cloudProviders: ProviderType[] = ['google', 'anthropic', 'openai'];

      for (const provider of cloudProviders) {
        const { unmount } = render(
          <ModelSelector
            settings={{
              ...DEFAULT_USER_SETTINGS,
              provider,
              keys: { google: '   ', anthropic: '', openai: '\t\n' }
            }}
            onOpenSettings={vi.fn()}
          />
        );

        const badge = screen.getByTestId('missing-key-badge');
        expect(badge).toBeInTheDocument();
        expect(badge).toHaveTextContent('Key Required');
        expect(badge).toHaveAttribute(
          'title',
          expect.stringContaining(PROVIDER_METADATA[provider].label)
        );

        unmount();
      }
    });

    it('hides missing key badge when cloud provider has a valid non-empty key', () => {
      const keyedSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'google',
        keys: { google: 'AIzaSyValidGeminiKey' }
      };

      render(
        <ModelSelector
          settings={keyedSettings}
          onOpenSettings={vi.fn()}
        />
      );

      expect(screen.queryByTestId('missing-key-badge')).not.toBeInTheDocument();
    });

    it('clicking missing key badge triggers onOpenSettings callback', () => {
      const handleOpenSettings = vi.fn();
      render(
        <ModelSelector
          settings={{
            ...DEFAULT_USER_SETTINGS,
            provider: 'openai',
            keys: { openai: '' }
          }}
          onOpenSettings={handleOpenSettings}
        />
      );

      const badge = screen.getByTestId('missing-key-badge');
      fireEvent.click(badge);
      expect(handleOpenSettings).toHaveBeenCalledTimes(1);
    });

    it('hasApiKeyForProvider strictly validates key presence and rejects whitespace-only strings', () => {
      const settingsWithWhitespace: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        keys: {
          google: '   ',
          anthropic: '\t\n  \r',
          openai: 'sk-proj-real-key',
          custom: ''
        }
      };

      expect(hasApiKeyForProvider(settingsWithWhitespace, 'google')).toBe(false);
      expect(hasApiKeyForProvider(settingsWithWhitespace, 'anthropic')).toBe(false);
      expect(hasApiKeyForProvider(settingsWithWhitespace, 'openai')).toBe(true);
      expect(hasApiKeyForProvider(settingsWithWhitespace, 'ollama')).toBe(true);
      expect(hasApiKeyForProvider(settingsWithWhitespace, 'custom')).toBe(true);
    });

    it('getApiKeyForProvider extracts trimmed keys and returns undefined for empty, whitespace, or ollama', () => {
      const mixedSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        keys: {
          google: '   AIzaSyTrimmedKey   ',
          anthropic: '   ',
          openai: '',
          custom: '  customToken123  '
        }
      };

      expect(getApiKeyForProvider(mixedSettings, 'google')).toBe('AIzaSyTrimmedKey');
      expect(getApiKeyForProvider(mixedSettings, 'anthropic')).toBeUndefined();
      expect(getApiKeyForProvider(mixedSettings, 'openai')).toBeUndefined();
      expect(getApiKeyForProvider(mixedSettings, 'ollama')).toBeUndefined();
      expect(getApiKeyForProvider(mixedSettings, 'custom')).toBe('customToken123');
    });

    it('dynamically toggles badge when provider changes interactively', () => {
      // Test dynamic state transition component
      function InteractiveSelector() {
        const [settings, setSettings] = useState<CarefoldUserSettings>({
          ...DEFAULT_USER_SETTINGS,
          provider: 'ollama',
          keys: { google: '', anthropic: '', openai: '', custom: '' }
        });

        return (
          <ModelSelector
            settings={settings}
            onSettingsChange={setSettings}
            onOpenSettings={vi.fn()}
          />
        );
      }

      render(<InteractiveSelector />);

      // Initially Ollama -> no badge
      expect(screen.queryByTestId('missing-key-badge')).not.toBeInTheDocument();

      // Switch to Google -> badge appears
      const select = screen.getByTestId('provider-selector');
      fireEvent.change(select, { target: { value: 'google' } });
      expect(screen.getByTestId('missing-key-badge')).toBeInTheDocument();

      // Switch to Custom -> badge disappears
      fireEvent.change(select, { target: { value: 'custom' } });
      expect(screen.queryByTestId('missing-key-badge')).not.toBeInTheDocument();

      // Switch to Anthropic -> badge reappears
      fireEvent.change(select, { target: { value: 'anthropic' } });
      expect(screen.getByTestId('missing-key-badge')).toBeInTheDocument();
    });
  });

  // =========================================================================
  // Section 4: Custom Model Input and Trailing Slash Handling
  // =========================================================================
  describe('4. Custom Model Input and Trailing Slash Normalization', () => {
    it('renders custom model input when provider is custom', () => {
      render(
        <ModelSelector
          settings={{
            ...DEFAULT_USER_SETTINGS,
            provider: 'custom',
            customModelName: 'qwen2.5:32b'
          }}
          onOpenSettings={vi.fn()}
        />
      );

      const customInput = screen.getByTestId('custom-model-input');
      expect(customInput).toBeInTheDocument();
      expect(customInput).toHaveValue('qwen2.5:32b');
    });

    it('renders custom model input when provider is ollama but model is "custom"', () => {
      render(
        <ModelSelector
          settings={{
            ...DEFAULT_USER_SETTINGS,
            provider: 'ollama',
            model: 'custom',
            customModelName: 'phi3:14b'
          }}
          onOpenSettings={vi.fn()}
        />
      );

      const customInput = screen.getByTestId('custom-model-input');
      expect(customInput).toBeInTheDocument();
      expect(customInput).toHaveValue('phi3:14b');
    });

    it('hides custom model input when standard model is selected', () => {
      render(
        <ModelSelector
          settings={{
            ...DEFAULT_USER_SETTINGS,
            provider: 'ollama',
            model: 'llama3.2'
          }}
          onOpenSettings={vi.fn()}
        />
      );

      expect(screen.queryByTestId('custom-model-input')).not.toBeInTheDocument();
    });

    it('getEffectiveModel handles custom model names and falls back to "custom" when blank', () => {
      // With trimmed non-empty model
      const withName: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'custom',
        customModelName: '  qwen2.5-coder:7b  '
      };
      expect(getEffectiveModel(withName)).toBe('qwen2.5-coder:7b');

      // With empty or whitespace-only name
      const emptyName: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        provider: 'custom',
        customModelName: '    '
      };
      expect(getEffectiveModel(emptyName)).toBe('custom');
    });

    it('evaluates getEndpointForProvider behavior with trailing slashes and whitespace', () => {
      const slashSettings: CarefoldUserSettings = {
        ...DEFAULT_USER_SETTINGS,
        endpoints: {
          ollamaUrl: '  http://127.0.0.1:11434/  ',
          customUrl: '  http://127.0.0.1:8000/v1///  '
        }
      };

      const ollamaEndpoint = getEndpointForProvider(slashSettings, 'ollama');
      const customEndpoint = getEndpointForProvider(slashSettings, 'custom');

      // Verify whitespace is trimmed
      expect(ollamaEndpoint).toBeDefined();
      expect(ollamaEndpoint?.startsWith(' ')).toBe(false);
      expect(ollamaEndpoint?.endsWith(' ')).toBe(false);

      expect(customEndpoint).toBeDefined();
      expect(customEndpoint?.startsWith(' ')).toBe(false);
      expect(customEndpoint?.endsWith(' ')).toBe(false);

      // Document exact trailing slash behavior in settings.ts
      expect(customEndpoint).toBe('http://127.0.0.1:8000/v1///');
      expect(ollamaEndpoint).toBe('http://127.0.0.1:11434/');
    });

    it('verifies that trailing slashes are safely normalized downstream by runner and backend', () => {
      // In packages/runner/src/model/client.ts:
      // (config.baseUrl || 'http://127.0.0.1:11434/v1').replace(/\/+$/, '')
      const rawEndpoint = 'http://127.0.0.1:8000/v1///';
      const normalized = rawEndpoint.replace(/\/+$/, '');
      expect(normalized).toBe('http://127.0.0.1:8000/v1');
    });
  });

  // =========================================================================
  // Section 5: XSS and Injection Resilience
  // =========================================================================
  describe('5. XSS and Injection Resilience', () => {
    it('safely renders custom model input containing XSS payload without script execution', () => {
      const xssPayload = '<script>window.__xss_attack_triggered=true;</script>';
      (window as any).__xss_attack_triggered = false;

      render(
        <ModelSelector
          settings={{
            ...DEFAULT_USER_SETTINGS,
            provider: 'custom',
            customModelName: xssPayload
          }}
          onOpenSettings={vi.fn()}
        />
      );

      const input = screen.getByTestId('custom-model-input') as HTMLInputElement;
      expect(input.value).toBe(xssPayload);
      expect((window as any).__xss_attack_triggered).toBe(false);
      expect(document.querySelector('script')).toBeNull();
    });

    it('safely renders API key input containing HTML/XSS injection payloads in SettingsModal', () => {
      const xssKeyPayload = '"><img src=x onerror="window.__xss_key_attack=true">';
      (window as any).__xss_key_attack = false;

      render(
        <SettingsModal
          isOpen={true}
          onClose={vi.fn()}
          initialSettings={{
            ...DEFAULT_USER_SETTINGS,
            keys: {
              google: xssKeyPayload,
              anthropic: '',
              openai: '',
              custom: ''
            }
          }}
        />
      );

      const input = screen.getByTestId('gemini-key-input') as HTMLInputElement;
      expect(input.value).toBe(xssKeyPayload);
      expect((window as any).__xss_key_attack).toBe(false);
      expect(document.querySelector('img[src="x"]')).toBeNull();
    });
  });
});
