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

import { NextRequest, NextResponse } from 'next/server';
import { findWorkspaceRoot, loadWorkspaceConfig } from '@/lib/workspace';
import { PREDEFINED_MODELS, type ModelOption, type ProviderType } from '@/lib/settings';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface OllamaTagModel {
  name: string;
  model?: string;
  modified_at?: string;
  size?: number;
  digest?: string;
  details?: {
    parent_model?: string;
    format?: string;
    family?: string;
    families?: string[];
    parameter_size?: string;
    quantization_level?: string;
  };
  capabilities?: string[];
}

function isEmbeddingModel(m: OllamaTagModel): boolean {
  const name = (m.name || '').toLowerCase();
  if (name.includes('embed') || name.includes('embedding')) {
    return true;
  }
  if (m.capabilities && m.capabilities.length > 0) {
    if (m.capabilities.includes('embedding') && !m.capabilities.includes('completion')) {
      return true;
    }
  }
  return false;
}

function formatModelLabel(name: string, details?: OllamaTagModel['details']): string {
  const colonIdx = name.lastIndexOf(':');
  const baseName = colonIdx !== -1 ? name.slice(0, colonIdx) : name;
  const tag = colonIdx !== -1 ? name.slice(colonIdx + 1) : '';

  const slashIdx = baseName.lastIndexOf('/');
  const shortBase = slashIdx !== -1 ? baseName.slice(slashIdx + 1) : baseName;

  const formattedTitle = shortBase
    .replace(/^([a-zA-Z]+)(\d.*)$/, '$1 $2')
    .replace(/^([a-z])/, (c) => c.toUpperCase());

  const tagInfo = tag && tag !== 'latest' ? ` (${tag})` : (details?.parameter_size ? ` (${details.parameter_size})` : '');
  return `${formattedTitle}${tagInfo}`;
}

function getValidatedOllamaBase(rawUrl?: string | null): URL {
  const defaultUrl = new URL('http://127.0.0.1:11434');
  if (!rawUrl || typeof rawUrl !== 'string') return defaultUrl;
  try {
    const parsed = new URL(rawUrl.trim());
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

export async function GET(req: Request | NextRequest): Promise<NextResponse> {
  const url = new URL(req.url);
  const provider = (url.searchParams.get('provider') || 'ollama') as ProviderType;
  const endpointParam = url.searchParams.get('endpoint');

  // If not ollama, return predefined static models for cloud providers
  if (provider !== 'ollama') {
    const models = PREDEFINED_MODELS[provider] || [];
    return NextResponse.json({
      provider,
      models,
      reachable: true
    });
  }

  // Resolve Ollama Endpoint
  let endpoint = endpointParam?.trim();
  if (!endpoint) {
    try {
      const wsRoot = findWorkspaceRoot();
      const config = await loadWorkspaceConfig(wsRoot);
      endpoint = config.model?.baseUrl;
    } catch {}
  }

  const safeBase = getValidatedOllamaBase(endpoint);
  const tagsUrl = new URL('/api/tags', safeBase);

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);

    const res = await fetch(tagsUrl.toString(), {
      method: 'GET',
      signal: controller.signal
    });
    clearTimeout(timeout);

    if (res.ok) {
      const data = (await res.json().catch(() => ({}))) as { models?: OllamaTagModel[] };
      const rawModels = data.models || [];

      // Filter out embedding-only models
      const chatModels = rawModels.filter((m) => !isEmbeddingModel(m));

      const modelOptions: ModelOption[] = chatModels.map((m) => {
        const isDefault = m.name.startsWith('llama3.2');
        const descParts: string[] = [];
        if (m.details?.parameter_size) descParts.push(m.details.parameter_size);
        if (m.details?.quantization_level) descParts.push(m.details.quantization_level);
        descParts.push('Installed locally');

        return {
          id: m.name,
          name: formatModelLabel(m.name, m.details),
          recommended: isDefault,
          description: descParts.join(' • ')
        };
      });

      // Sort so recommended models (e.g. llama3.2) appear first
      modelOptions.sort((a, b) => {
        if (a.recommended && !b.recommended) return -1;
        if (!a.recommended && b.recommended) return 1;
        return a.name.localeCompare(b.name);
      });

      return NextResponse.json({
        provider: 'ollama',
        models: modelOptions,
        reachable: true,
        count: modelOptions.length
      });
    }

    // Fallback: try /v1/models if native /api/tags fails
    const v1Url = new URL('/v1/models', safeBase);
    const resV1 = await fetch(v1Url.toString(), {
      method: 'GET',
      signal: AbortSignal.timeout(2000)
    });

    if (resV1.ok) {
      const dataV1 = (await resV1.json().catch(() => ({}))) as { data?: Array<{ id: string }> };
      const v1Models = (dataV1.data || [])
        .filter((m) => !m.id.toLowerCase().includes('embed'))
        .map((m) => ({
          id: m.id,
          name: formatModelLabel(m.id),
          recommended: m.id.startsWith('llama3.2'),
          description: 'Installed locally'
        }));

      return NextResponse.json({
        provider: 'ollama',
        models: v1Models,
        reachable: true,
        count: v1Models.length
      });
    }

    // If endpoint responded with error, return default fallback models
    return NextResponse.json({
      provider: 'ollama',
      models: PREDEFINED_MODELS.ollama,
      reachable: false,
      error: `HTTP ${res.status}: ${res.statusText}`
    });
  } catch (err: any) {
    return NextResponse.json({
      provider: 'ollama',
      models: PREDEFINED_MODELS.ollama,
      reachable: false,
      error: err.name === 'AbortError' ? 'Ollama connection timed out' : 'Ollama not reachable'
    });
  }
}
