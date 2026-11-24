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

import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  OpenAIModelClient,
  sanitizeApiKey,
  sanitizeBaseUrl,
  sanitizeModelName
} from '../src/model/client.js';

describe('13: OpenAIModelClient Configuration Sanitization', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('sanitizeBaseUrl', () => {
    it('normalizes valid http and https endpoints with /v1 suffix', () => {
      expect(sanitizeBaseUrl('http://127.0.0.1:11434')).toBe('http://127.0.0.1:11434/v1');
      expect(sanitizeBaseUrl('https://api.openai.com/v1///')).toBe('https://api.openai.com/v1');
    });

    it('falls back to local Ollama default for non-http schemes or malformed URLs', () => {
      expect(sanitizeBaseUrl('file:///etc/passwd')).toBe('http://127.0.0.1:11434/v1');
      expect(sanitizeBaseUrl('not-a-valid-url')).toBe('http://127.0.0.1:11434/v1');
    });
  });

  describe('sanitizeModelName', () => {
    it('accepts standard local and cloud model identifiers', () => {
      expect(sanitizeModelName('llama3.2:latest')).toBe('llama3.2:latest');
      expect(sanitizeModelName('gpt-4o')).toBe('gpt-4o');
      expect(sanitizeModelName('claude-3-5-sonnet-latest')).toBe('claude-3-5-sonnet-latest');
      expect(sanitizeModelName('hf.co/org/model_v1:q4_k_m')).toBe('hf.co/org/model_v1:q4_k_m');
      expect(sanitizeModelName('model@sha256:abcdef01')).toBe('model@sha256:abcdef01');
    });

    it('rejects control characters, whitespace, and oversized strings with fallback', () => {
      expect(sanitizeModelName('model\nX-Injected: true')).toBe('llama3.2');
      expect(sanitizeModelName('model with spaces')).toBe('llama3.2');
      expect(sanitizeModelName('a'.repeat(200))).toBe('llama3.2');
      expect(sanitizeModelName('   ')).toBe('llama3.2');
    });
  });

  describe('sanitizeApiKey', () => {
    it('accepts printable non-whitespace ASCII bearer tokens', () => {
      expect(sanitizeApiKey('sk-proj-abc123_XYZ+=/')).toBe('sk-proj-abc123_XYZ+=/');
      expect(sanitizeApiKey('  secret-key-123\r\n')).toBe('secret-key-123');
    });

    it('rejects embedded whitespace, control chars, non-ASCII, and oversized payloads', () => {
      expect(sanitizeApiKey('')).toBeUndefined();
      expect(sanitizeApiKey('   ')).toBeUndefined();
      expect(sanitizeApiKey('key with spaces')).toBeUndefined();
      expect(sanitizeApiKey('key\twith\ttab')).toBeUndefined();
      expect(sanitizeApiKey('key\u0000null')).toBeUndefined();
      expect(sanitizeApiKey('non-ascii-é')).toBeUndefined();
      expect(sanitizeApiKey('k'.repeat(600))).toBeUndefined();
    });
  });

  describe('OpenAIModelClient outbound request sanitization', () => {
    it('sends validated model name and Authorization header on streamChat', async () => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(
            encoder.encode(
              'data: {"id":"1","object":"chat.completion.chunk","created":1,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            )
          );
          controller.close();
        }
      });

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
      );

      const client = new OpenAIModelClient({
        baseUrl: 'https://api.openai.com/v1',
        model: 'gpt-4o',
        apiKey: 'sk-test-token-123'
      });

      const chunks = [];
      for await (const c of client.streamChat({
        messages: [{ role: 'user', content: 'hello' }]
      })) {
        chunks.push(c);
      }

      expect(chunks).toHaveLength(1);
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const [url, init] = fetchSpy.mock.calls[0];
      expect(url).toBe('https://api.openai.com/v1/chat/completions');
      expect((init?.headers as Record<string, string>)['Authorization']).toBe('Bearer sk-test-token-123');
      expect(JSON.parse(init?.body as string).model).toBe('gpt-4o');
    });

    it('omits Authorization header and falls back to default model for invalid config values', async () => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(
            encoder.encode(
              'data: {"id":"1","object":"chat.completion.chunk","created":1,"model":"llama3.2","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            )
          );
          controller.close();
        }
      });

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
      );

      const client = new OpenAIModelClient({
        baseUrl: 'http://127.0.0.1:11434/v1',
        model: 'invalid model\nwith newline',
        apiKey: 'not a valid bearer token with spaces'
      });

      for await (const _ of client.streamChat({
        messages: [{ role: 'user', content: 'hello' }]
      })) {
        // consume
      }

      const [, init] = fetchSpy.mock.calls[0];
      expect((init?.headers as Record<string, string>)['Authorization']).toBeUndefined();
      expect(JSON.parse(init?.body as string).model).toBe('llama3.2');
    });
  });
});
