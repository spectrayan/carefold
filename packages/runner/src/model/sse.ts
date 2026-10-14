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

import type { ModelStreamChunk } from './types.js';

/**
 * Parses a Server-Sent Events (SSE) stream into structured ModelStreamChunks
 */
export async function* parseSSEStream(
  stream: ReadableStream<Uint8Array>,
  fallbackModel: string = 'local-model'
): AsyncGenerator<ModelStreamChunk, void, void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder('utf8');
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(':')) {
          continue; // Keepalive or comment line
        }

        if (trimmed.startsWith('data:')) {
          const payload = trimmed.slice(5).trim();
          if (payload === '[DONE]') {
            return;
          }

          try {
            const parsed = JSON.parse(payload) as ModelStreamChunk;
            if (!parsed.model) {
              parsed.model = fallbackModel;
            }
            yield parsed;
          } catch (jsonErr) {
            // Ignore malformed chunk fragments
          }
        }
      }
    }

    // Process remainder of buffer
    if (buffer.trim().startsWith('data:')) {
      const payload = buffer.trim().slice(5).trim();
      if (payload !== '[DONE]') {
        try {
          const parsed = JSON.parse(payload) as ModelStreamChunk;
          if (!parsed.model) {
            parsed.model = fallbackModel;
          }
          yield parsed;
        } catch {}
      }
    }
  } finally {
    reader.releaseLock();
  }
}
