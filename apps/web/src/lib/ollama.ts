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

import type { OllamaHealthStatus } from '../types/api.js';

function getValidatedOllamaUrl(endpoint?: string): URL {
  const defaultUrl = new URL('http://127.0.0.1:11434');
  if (!endpoint || typeof endpoint !== 'string') return defaultUrl;
  try {
    const parsed = new URL(endpoint.trim());
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      parsed.username = '';
      parsed.password = '';
      parsed.search = '';
      parsed.hash = '';
      parsed.pathname = parsed.pathname.replace(/\/v1\/?$/, '').replace(/\/+$/, '');
      return parsed;
    }
  } catch {}
  return defaultUrl;
}

export async function checkOllamaHealth(
  endpoint = 'http://127.0.0.1:11434',
  timeoutMs = 2500
): Promise<OllamaHealthStatus> {
  const safeBase = getValidatedOllamaUrl(endpoint);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    // Probe Ollama /api/tags to get installed model tags
    const tagsUrl = new URL('/api/tags', safeBase);
    const res = await fetch(tagsUrl.toString(), {
      method: 'GET',
      signal: controller.signal
    });
    clearTimeout(timer);

    if (res.ok) {
      const data = (await res.json().catch(() => ({}))) as { models?: Array<{ name: string }> };
      const models = (data.models || []).map((m) => m.name);
      const activeModel = models.find((m) => m.startsWith('llama3.2')) || models[0] || 'default';
      return {
        status: 'connected',
        endpoint: safeBase.origin,
        reachable: true,
        activeModel,
        availableModels: models
      };
    }

    // Fallback: probe OpenAI compatible /v1/models
    const v1Url = new URL('/v1/models', safeBase);
    const resV1 = await fetch(v1Url.toString(), {
      method: 'GET',
      signal: AbortSignal.timeout(1500)
    });
    if (resV1.ok) {
      const dataV1 = (await resV1.json().catch(() => ({}))) as { data?: Array<{ id: string }> };
      const models = (dataV1.data || []).map((m) => m.id);
      return {
        status: 'connected',
        endpoint: safeBase.origin,
        reachable: true,
        activeModel: models[0] || 'default',
        availableModels: models
      };
    }

    return {
      status: 'error',
      endpoint: safeBase.origin,
      reachable: false,
      error: `HTTP ${res.status}: ${res.statusText}`
    };
  } catch (err: any) {
    clearTimeout(timer);
    return {
      status: 'unreachable',
      endpoint: safeBase.origin,
      reachable: false,
      error: err.name === 'AbortError' ? 'Connection timed out' : 'Ollama not reachable'
    };
  }
}
