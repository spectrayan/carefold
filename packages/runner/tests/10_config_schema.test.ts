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

import { describe, it, expect } from 'vitest';
import { CarefoldConfigSchema } from '../src/manifest/schema.js';

describe('10: CarefoldConfigSchema Validation & Defaults', () => {
  it('parses empty object and populates complete default configuration', () => {
    const parsed = CarefoldConfigSchema.parse({});

    expect(parsed.version).toBe('0.1.0');
    expect(parsed.model.provider).toBe('ollama');
    expect(parsed.model.baseUrl).toBe('http://127.0.0.1:11434/v1');
    expect(parsed.model.model).toBe('llama3.2');
    expect(parsed.model.apiKey).toBe('');
    expect(parsed.audit.enabled).toBe(true);
    expect(parsed.audit.store_bodies).toBe(false);
    expect(parsed.audit.log_path).toBe('logs/audit.jsonl');
    expect(parsed.allow_clinical).toBe(false);
    expect(parsed.telemetry).toBe(false);
  });

  it('guarantees backwards compatibility for legacy config omitting provider and temperature', () => {
    const legacyConfig = {
      model: {
        baseUrl: 'http://127.0.0.1:11434/v1',
        model: 'llama3.2'
      },
      audit: {
        store_bodies: true,
        log_path: 'custom/audit.jsonl'
      },
      allow_clinical: true
    };

    const parsed = CarefoldConfigSchema.parse(legacyConfig);

    expect(parsed.version).toBe('0.1.0');
    expect(parsed.model.provider).toBe('ollama'); // Default injected
    expect(parsed.model.baseUrl).toBe('http://127.0.0.1:11434/v1');
    expect(parsed.model.model).toBe('llama3.2'); // Preserved legacy value
    expect(parsed.model.apiKey).toBe(''); // Default injected
    expect(parsed.audit.enabled).toBe(true); // Default injected
    expect(parsed.audit.store_bodies).toBe(true); // Preserved legacy value
    expect(parsed.audit.log_path).toBe('custom/audit.jsonl');
    expect(parsed.allow_clinical).toBe(true);
    expect(parsed.telemetry).toBe(false);
  });

  it('correctly parses custom provider configuration (google, anthropic, openai, custom)', () => {
    const providers = ['google', 'gemini', 'anthropic', 'claude', 'openai', 'custom', 'ollama'];
    for (const provider of providers) {
      const customConfig = {
        version: '0.2.0',
        model: {
          provider,
          baseUrl: 'https://custom-endpoint.example.com/v1',
          model: 'custom-model-v1',
          apiKey: 'secret-key-123',
          temperature: 0.7
        },
        audit: {
          enabled: false,
          store_bodies: true,
          log_path: 'logs/audit.jsonl'
        }
      };

      const parsed = CarefoldConfigSchema.parse(customConfig);

      expect(parsed.version).toBe('0.2.0');
      expect(parsed.model.provider).toBe(provider);
      expect(parsed.model.baseUrl).toBe('https://custom-endpoint.example.com/v1');
      expect(parsed.model.model).toBe('custom-model-v1');
      expect(parsed.model.apiKey).toBe('secret-key-123');
      expect(parsed.model.temperature).toBe(0.7);
      expect(parsed.audit.enabled).toBe(false);
    }
  });

  it('rejects invalid provider type (non-string)', () => {
    const invalidConfig = {
      model: {
        provider: 12345 as any
      }
    };

    const res = CarefoldConfigSchema.safeParse(invalidConfig);
    expect(res.success).toBe(false);
  });

  it('rejects invalid temperature values with validation error', () => {
    const invalidConfig = {
      model: {
        temperature: 'not-a-number' as any
      }
    };

    const res = CarefoldConfigSchema.safeParse(invalidConfig);
    expect(res.success).toBe(false);
  });
});
