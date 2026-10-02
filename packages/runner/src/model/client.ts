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

import { parseSSEStream } from './sse.js';
import {
  type ModelClient,
  type ModelClientConfig,
  type ChatCompletionOptions,
  type ModelStreamChunk,
  CarefoldModelError
} from './types.js';

export class OpenAIModelClient implements ModelClient {
  private baseUrl: string;
  private primaryModel: string;
  private fallbackModels: string[];
  private activeModel: string;
  private apiKey?: string;
  private timeoutMs: number;

  constructor(config: ModelClientConfig = {}) {
    let base = config.baseUrl || 'http://127.0.0.1:11434/v1';
    while (base.endsWith('/')) {
      base = base.slice(0, -1);
    }
    if (!base.endsWith('/v1')) {
      base = `${base}/v1`;
    }
    this.baseUrl = base;
    this.primaryModel = config.model || 'llama3.2';
    this.fallbackModels = config.fallbackModels || ['llama3.2:latest', 'llama3.1:latest', 'llama3.1'];
    this.activeModel = this.primaryModel;
    this.apiKey = config.apiKey;
    this.timeoutMs = config.timeoutMs || 30000;
  }

  public getModelName(): string {
    return this.activeModel;
  }

  public async checkHealth(): Promise<{ reachable: boolean; model?: string; error?: string }> {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 4000);
      const res = await fetch(`${this.baseUrl}/models`, {
        headers: this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {},
        signal: controller.signal
      });
      clearTimeout(timer);

      if (!res.ok) {
        return { reachable: false, error: `HTTP ${res.status}: ${res.statusText}` };
      }

      const data = (await res.json()) as { data?: Array<{ id: string }> };
      const modelIds = (data.data || []).map((m) => m.id);

      // Select best available model
      if (modelIds.includes(this.primaryModel)) {
        this.activeModel = this.primaryModel;
      } else {
        const found = this.fallbackModels.find((m) => modelIds.includes(m));
        if (found) {
          this.activeModel = found;
        } else if (modelIds.length > 0) {
          this.activeModel = modelIds[0];
        }
      }

      return { reachable: true, model: this.activeModel };
    } catch (err: any) {
      return {
        reachable: false,
        error: `Ollama not reachable at ${this.baseUrl}`
      };
    }
  }

  public async *streamChat(options: ChatCompletionOptions): AsyncGenerator<ModelStreamChunk, void, void> {
    const candidateModels: string[] = [
      this.activeModel,
      ...(this.activeModel.endsWith(':latest')
        ? [this.activeModel.replace(/:latest$/, '')]
        : [`${this.activeModel}:latest`]),
      ...this.fallbackModels
    ];
    const modelsToTry = Array.from(new Set(candidateModels));
    let lastError: Error | null = null;

    for (const modelToAttempt of modelsToTry) {
      try {
        const url = `${this.baseUrl}/chat/completions`;
        const headers: Record<string, string> = {
          'Content-Type': 'application/json'
        };
        if (this.apiKey) {
          headers['Authorization'] = `Bearer ${this.apiKey}`;
        }

        const body = {
          model: modelToAttempt,
          messages: options.messages,
          tools: options.tools && options.tools.length > 0 ? options.tools : undefined,
          stream: true,
          temperature: options.temperature ?? 0.2
        };

        const res = await fetch(url, {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
          signal: options.signal || AbortSignal.timeout(this.timeoutMs)
        });

        if (res.status === 404) {
          // Model not found on host; try next candidate in fallback chain
          lastError = new CarefoldModelError(
            `Model '${this.primaryModel}' not found on server`,
            'MODEL_NOT_FOUND'
          );
          continue;
        }

        if (!res.ok) {
          const errText = await res.text().catch(() => '');
          throw new CarefoldModelError(
            `Inference server returned status ${res.status}: ${errText}`,
            'SERVER_ERROR'
          );
        }

        if (!res.body) {
          throw new CarefoldModelError('Response body is null', 'EMPTY_RESPONSE');
        }

        // Successfully streaming with this model
        this.activeModel = modelToAttempt;
        yield* parseSSEStream(res.body, modelToAttempt);
        return;
      } catch (err: any) {
        if (err.name === 'AbortError') throw err;
        if (
          err.cause?.code === 'ECONNREFUSED' ||
          err.message?.includes('fetch failed') ||
          err.message?.includes('ECONNREFUSED')
        ) {
          throw new CarefoldModelError(
            `Ollama not reachable at ${this.baseUrl}. Please verify Ollama is running or use mock mode.`,
            'CONNECTION_REFUSED',
            true
          );
        }
        if (err instanceof CarefoldModelError && err.code === 'MODEL_NOT_FOUND') {
          continue;
        }
        throw err;
      }
    }

    throw lastError || new CarefoldModelError(`Could not find a valid model at ${this.baseUrl}`, 'NO_MODEL');
  }
}
