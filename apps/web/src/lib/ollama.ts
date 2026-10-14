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
