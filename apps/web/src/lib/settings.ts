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

/**
 * Carefold User Settings & Model Configuration
 * 
 * Local-first settings management for model providers, API credentials,
 * and custom endpoints. Persisted in browser localStorage under 'carefold_user_settings_v1'.
 */

export type ProviderType = 'ollama' | 'google' | 'anthropic' | 'openai' | 'custom';

export interface ModelOption {
  id: string;
  name: string;
  recommended?: boolean;
  description?: string;
}

export interface ProviderMeta {
  id: ProviderType;
  label: string;
  badge: string;
  requiresKey: boolean;
  keyUrl?: string;
  defaultModel: string;
  description: string;
}

export const PROVIDER_METADATA: Record<ProviderType, ProviderMeta> = {
  ollama: {
    id: 'ollama',
    label: 'Ollama',
    badge: '💻 Local',
    requiresKey: false,
    defaultModel: 'llama3.2',
    description: 'Local OpenAI-compatible runner (Zero API keys)'
  },
  google: {
    id: 'google',
    label: 'Gemini',
    badge: '✨ Google',
    requiresKey: true,
    keyUrl: 'https://aistudio.google.com/app/apikey',
    defaultModel: 'gemini-2.0-flash',
    description: 'Google Gemini models via langchain-google-genai'
  },
  anthropic: {
    id: 'anthropic',
    label: 'Claude',
    badge: '🧠 Anthropic',
    requiresKey: true,
    keyUrl: 'https://console.anthropic.com/',
    defaultModel: 'claude-3-5-sonnet-latest',
    description: 'Anthropic Claude models via langchain-anthropic'
  },
  openai: {
    id: 'openai',
    label: 'OpenAI',
    badge: '⚡ OpenAI',
    requiresKey: true,
    keyUrl: 'https://platform.openai.com/api-keys',
    defaultModel: 'gpt-4o',
    description: 'OpenAI GPT models via langchain-openai'
  },
  custom: {
    id: 'custom',
    label: 'Custom',
    badge: '🌐 Endpoint',
    requiresKey: false,
    defaultModel: 'custom',
    description: 'Custom OpenAI-compatible endpoint (LM Studio, vLLM, LocalAI)'
  }
};

export const PREDEFINED_MODELS: Record<ProviderType, ModelOption[]> = {
  ollama: [
    { id: 'llama3.2', name: 'Llama 3.2 (Default)', recommended: true, description: 'Meta lightweight state-of-the-art model' },
    { id: 'llama3.1', name: 'Llama 3.1 8B', description: 'Meta general-purpose reasoning model' }
  ],
  google: [
    { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash (Fastest)', recommended: true, description: 'Next-gen multimodal high-speed model' },
    { id: 'gemini-1.5-pro', name: 'Gemini 1.5 Pro', description: 'Long-context complex reasoning model' },
    { id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash', description: 'Fast, lightweight multimodal model' }
  ],
  anthropic: [
    { id: 'claude-3-5-sonnet-latest', name: 'Claude 3.5 Sonnet (Recommended)', recommended: true, description: 'Industry-leading intelligence and coding' },
    { id: 'claude-3-5-haiku-latest', name: 'Claude 3.5 Haiku (Fast)', description: 'Ultra-fast, responsive assistant' },
    { id: 'claude-3-opus-20240229', name: 'Claude 3 Opus', description: 'Deep reasoning for complex inquiries' }
  ],
  openai: [
    { id: 'gpt-4o', name: 'GPT-4o (Omni)', recommended: true, description: 'Flagship omni-model for chat and reasoning' },
    { id: 'gpt-4o-mini', name: 'GPT-4o Mini (Fast)', description: 'Affordable, low-latency intelligent model' },
    { id: 'o1-mini', name: 'o1-mini (Reasoning)', description: 'Specialized STEM and step-by-step reasoning' }
  ],
  custom: [
    { id: 'custom', name: 'Custom Model...', recommended: true, description: 'Specify any model identifier hosted by your endpoint' }
  ]
};

export interface CarefoldUserSettings {
  provider: ProviderType;
  model: string;
  customModelName: string;
  keys: {
    google?: string;
    anthropic?: string;
    openai?: string;
    custom?: string;
  };
  endpoints: {
    ollamaUrl: string;
    customUrl: string;
  };
}

import { getScopedStorageKey, getStorageUserId } from '@/lib/storageNamespace';

export const CAREFOLD_SETTINGS_STORAGE_KEY = 'carefold_user_settings_v1';

export const DEFAULT_USER_SETTINGS: CarefoldUserSettings = {
  provider: 'ollama',
  model: 'llama3.2',
  customModelName: '',
  keys: {
    google: '',
    anthropic: '',
    openai: '',
    custom: ''
  },
  endpoints: {
    ollamaUrl: 'http://127.0.0.1:11434',
    customUrl: 'http://127.0.0.1:8000/v1'
  }
};

/**
 * Safely loads user settings from browser localStorage scoped to user.
 * Returns default settings if running on server or if stored data is invalid.
 */
export function loadSettings(userId?: string | null): CarefoldUserSettings {
  if (typeof window === 'undefined' || !window.localStorage) {
    return { ...DEFAULT_USER_SETTINGS };
  }

  try {
    const effectiveUserId = userId !== undefined ? userId : getStorageUserId();
    const key = getScopedStorageKey(effectiveUserId, CAREFOLD_SETTINGS_STORAGE_KEY);
    const raw = window.localStorage.getItem(key) || (!effectiveUserId ? window.localStorage.getItem(CAREFOLD_SETTINGS_STORAGE_KEY) : null);
    if (!raw) {
      return { ...DEFAULT_USER_SETTINGS };
    }

    const parsed = JSON.parse(raw);
    return {
      provider: parsed.provider || DEFAULT_USER_SETTINGS.provider,
      model: parsed.model || DEFAULT_USER_SETTINGS.model,
      customModelName: parsed.customModelName ?? DEFAULT_USER_SETTINGS.customModelName,
      keys: {
        google: parsed.keys?.google ?? '',
        anthropic: parsed.keys?.anthropic ?? '',
        openai: parsed.keys?.openai ?? '',
        custom: parsed.keys?.custom ?? ''
      },
      endpoints: {
        ollamaUrl: parsed.endpoints?.ollamaUrl || DEFAULT_USER_SETTINGS.endpoints.ollamaUrl,
        customUrl: parsed.endpoints?.customUrl || DEFAULT_USER_SETTINGS.endpoints.customUrl
      }
    };
  } catch {
    return { ...DEFAULT_USER_SETTINGS };
  }
}

/**
 * Saves updated user settings to browser localStorage and dispatches a change event.
 */
export function saveSettings(
  partialSettings: Partial<CarefoldUserSettings>,
  userId?: string | null
): CarefoldUserSettings {
  const current = loadSettings(userId);
  const updated: CarefoldUserSettings = {
    ...current,
    ...partialSettings,
    keys: {
      ...current.keys,
      ...(partialSettings.keys || {})
    },
    endpoints: {
      ...current.endpoints,
      ...(partialSettings.endpoints || {})
    }
  };

  if (typeof window !== 'undefined' && window.localStorage) {
    try {
      const effectiveUserId = userId !== undefined ? userId : getStorageUserId();
      const key = getScopedStorageKey(effectiveUserId, CAREFOLD_SETTINGS_STORAGE_KEY);
      window.localStorage.setItem(key, JSON.stringify(updated));
      if (!effectiveUserId) {
        window.localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify(updated));
      }
      window.dispatchEvent(new CustomEvent('carefold:settings-changed', { detail: updated }));
    } catch (err) {
      console.error('Failed to save Carefold settings to localStorage:', err);
    }
  }

  return updated;
}

/**
 * Checks whether the required API key exists for a given provider.
 * Ollama and Custom endpoints do not strictly require API keys.
 */
export function hasApiKeyForProvider(settings: CarefoldUserSettings, provider: ProviderType): boolean {
  if (provider === 'ollama' || provider === 'custom') {
    return true;
  }
  const key = settings.keys[provider];
  return Boolean(key && key.trim().length > 0);
}

/**
 * Retrieves the API key for the specified provider, or undefined if not present.
 */
export function getApiKeyForProvider(settings: CarefoldUserSettings, provider: ProviderType): string | undefined {
  if (provider === 'ollama') return undefined;
  const key = settings.keys[provider];
  return key && key.trim().length > 0 ? key.trim() : undefined;
}

/**
 * Returns the effective model string to be transmitted in the chat request.
 */
export function getEffectiveModel(settings: CarefoldUserSettings): string {
  if (settings.provider === 'custom' || settings.model === 'custom') {
    return settings.customModelName.trim() || 'custom';
  }
  return settings.model || PROVIDER_METADATA[settings.provider]?.defaultModel || 'llama3.2';
}

/**
 * Returns the appropriate base URL endpoint for the selected provider.
 */
export function getEndpointForProvider(settings: CarefoldUserSettings, provider: ProviderType): string | undefined {
  if (provider === 'ollama') {
    return settings.endpoints.ollamaUrl?.trim() || 'http://127.0.0.1:11434';
  }
  if (provider === 'custom') {
    return settings.endpoints.customUrl?.trim() || 'http://127.0.0.1:8000/v1';
  }
  return undefined;
}

export interface ProviderPrivacyState {
  isLocal: boolean;
  provider: ProviderType;
  providerLabel: string;
  badgeText: string;
  badgeVariant: 'emerald' | 'amber';
  emptyStateText: string;
  footerText: string;
  explainerTitle: string;
  explainerDescription: string;
  destinationLabel: string;
}

/**
 * Checks whether an endpoint URL or hostname points strictly to a loopback host.
 * Matches:
 *  - 'localhost' and 'localhost.'
 *  - IPv4 loopback block 127.0.0.0/8 (127.0.0.1 through 127.255.255.254)
 *  - IPv6 loopback '::1', '[::1]', and fully expanded '0:0:0:0:0:0:0:1'
 * Fails closed (returns false) on:
 *  - Non-loopback LAN/WAN hosts (192.168.x.x, 10.x.x.x, 172.16-31.x.x, external hostnames/IPs)
 *  - Null, undefined, empty, whitespace-only, or malformed/unparseable URLs.
 */
export function isLoopbackHost(urlStr?: string | null): boolean {
  if (!urlStr || typeof urlStr !== 'string') {
    return false;
  }
  const trimmed = urlStr.trim();
  if (!trimmed) {
    return false;
  }

  let host: string | null = null;
  try {
    const parsed = new URL(trimmed.includes('://') ? trimmed : `http://${trimmed}`);
    host = parsed.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  } catch {
    // Fallback for raw IPv6 without brackets or protocol
    const noProto = trimmed.replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//, '');
    if (noProto.startsWith('[') && noProto.includes(']')) {
      host = noProto.slice(1, noProto.indexOf(']')).toLowerCase();
    } else if (noProto.includes(':')) {
      try {
        const bracketed = new URL(`http://[${noProto}]`);
        host = bracketed.hostname.replace(/^\[|\]$/g, '').toLowerCase();
      } catch {
        if (noProto === '::1' || noProto === '0:0:0:0:0:0:0:1') {
          host = noProto.toLowerCase();
        }
      }
    }
  }

  if (!host) {
    return false;
  }

  if (host === 'localhost' || host === 'localhost.') {
    return true;
  }

  if (host === '::1' || host === '0:0:0:0:0:0:0:1' || host === '0000:0000:0000:0000:0000:0000:0001') {
    return true;
  }

  const parts = host.split('.');
  if (parts.length === 4 && parts[0] === '127') {
    const validOctets = parts.every(
      (part) => /^(0|[1-9]\d{0,2})$/.test(part) && Number(part) >= 0 && Number(part) <= 255
    );
    if (validOctets) {
      return true;
    }
  }

  return false;
}

/**
 * Determines whether the currently configured provider runs on-device.
 * Returns false for all cloud providers (google, anthropic, openai).
 * For ollama and custom, resolves the configured endpoint and requires loopback host.
 * Fails closed (returns false) if endpoint is unknown or unparseable.
 */
export function isLocalProvider(settings: CarefoldUserSettings): boolean {
  if (!settings || !settings.provider) {
    return false;
  }
  if (settings.provider === 'google' || settings.provider === 'anthropic' || settings.provider === 'openai') {
    return false;
  }
  const endpoint = getEndpointForProvider(settings, settings.provider);
  return isLoopbackHost(endpoint);
}

/**
 * Derives comprehensive data residency descriptors and copy for UI indicators,
 * empty-state text, explainer popover, and footer notice.
 */
export function getProviderPrivacyState(settings: CarefoldUserSettings): ProviderPrivacyState {
  const safeSettings = settings || DEFAULT_USER_SETTINGS;
  const isLocal = isLocalProvider(safeSettings);
  const provider = safeSettings.provider || 'ollama';
  const meta = PROVIDER_METADATA[provider];
  const providerLabel = meta?.label || provider;
  const endpoint = getEndpointForProvider(safeSettings, provider);

  if (isLocal) {
    return {
      isLocal: true,
      provider,
      providerLabel,
      badgeText: 'On-Device',
      badgeVariant: 'emerald',
      emptyStateText: 'All data remains exclusively on your device.',
      footerText: 'Zero cloud sync • No prompt telemetry • 100% on-device',
      explainerTitle: 'On-Device Data Residency',
      explainerDescription:
        'All prompt text, attachments, and model inference remain strictly on your local machine. No data is transmitted to cloud APIs or external servers.',
      destinationLabel: `Local (${endpoint || '127.0.0.1'})`
    };
  }

  // Non-local: cloud or remote network host
  const isCloud = provider === 'google' || provider === 'anthropic' || provider === 'openai';
  const badgeText = isCloud
    ? `Cloud (${providerLabel})`
    : provider === 'ollama'
    ? 'Remote (Ollama)'
    : 'Remote (Custom)';

  const emptyStateText = `Your messages are sent to ${providerLabel} to generate replies.`;
  const footerText = isCloud
    ? `Cloud inference active (${providerLabel}) • Zero Carefold telemetry`
    : `Remote inference active (${providerLabel}) • Zero Carefold telemetry`;

  const explainerTitle = isCloud
    ? 'Cloud Provider Data Residency'
    : provider === 'ollama'
    ? 'Remote Ollama Data Residency'
    : 'Remote Endpoint Data Residency';

  const explainerDescription = isCloud
    ? `Your messages and attachments are transmitted to ${providerLabel} cloud servers to generate replies. Carefold does not collect telemetry or store prompts externally.`
    : `Your inference endpoint is configured to an external network host (${endpoint || 'remote'}). Prompts and attachments leave this machine over the network.`;

  const destinationLabel = isCloud
    ? `${providerLabel} Cloud API`
    : `${providerLabel} (${endpoint || 'network'})`;

  return {
    isLocal: false,
    provider,
    providerLabel,
    badgeText,
    badgeVariant: 'amber',
    emptyStateText,
    footerText,
    explainerTitle,
    explainerDescription,
    destinationLabel
  };
}

export interface BrowserStorageSummary {
  conversationCount: number;
  approximateSizeBytes: number;
  formattedSize: string;
  hasStoredApiKeys: boolean;
  storedKeyProviders: string[];
}

export function formatStorageSize(bytes: number): string {
  if (bytes <= 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Calculates current conversation count, approximate byte footprint,
 * and status of stored API keys in the browser's localStorage.
 */
export function getBrowserStorageSummary(settings?: CarefoldUserSettings): BrowserStorageSummary {
  if (typeof window === 'undefined' || !window.localStorage) {
    return {
      conversationCount: 0,
      approximateSizeBytes: 0,
      formattedSize: '0 B',
      hasStoredApiKeys: false,
      storedKeyProviders: []
    };
  }

  let conversationCount = 0;
  let approximateSizeBytes = 0;

  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (!key) continue;
      if (key.startsWith('carefold_msgs_')) {
        conversationCount++;
        const val = window.localStorage.getItem(key) || '';
        approximateSizeBytes += (key.length + val.length) * 2; // UTF-16 approximate bytes
      } else if (key.startsWith('carefold_thread_')) {
        const val = window.localStorage.getItem(key) || '';
        approximateSizeBytes += (key.length + val.length) * 2;
      }
    }
  } catch {
    // Graceful storage failure recovery
  }

  const currentSettings = settings || loadSettings();
  const storedKeyProviders: string[] = [];
  if (currentSettings.keys.google?.trim()) storedKeyProviders.push('Google Gemini');
  if (currentSettings.keys.anthropic?.trim()) storedKeyProviders.push('Anthropic Claude');
  if (currentSettings.keys.openai?.trim()) storedKeyProviders.push('OpenAI');
  if (currentSettings.keys.custom?.trim()) storedKeyProviders.push('Custom');

  return {
    conversationCount,
    approximateSizeBytes,
    formattedSize: formatStorageSize(approximateSizeBytes),
    hasStoredApiKeys: storedKeyProviders.length > 0,
    storedKeyProviders
  };
}

/**
 * Deletes the conversation associated with the specified thread ID and/or agent ID.
 * Dispatches 'carefold:conversation-deleted'.
 */
export function deleteCurrentConversation(threadId?: string, agentId?: string): boolean {
  if (typeof window === 'undefined' || !window.localStorage) return false;
  try {
    if (threadId) {
      window.localStorage.removeItem(`carefold_msgs_${threadId}`);
    }
    if (agentId) {
      const storedThread = window.localStorage.getItem(`carefold_thread_${agentId}`);
      if (storedThread && !threadId) {
        window.localStorage.removeItem(`carefold_msgs_${storedThread}`);
      }
      window.localStorage.removeItem(`carefold_thread_${agentId}`);
    }
    window.dispatchEvent(
      new CustomEvent('carefold:conversation-deleted', {
        detail: { threadId, agentId }
      })
    );
    return true;
  } catch {
    return false;
  }
}

/**
 * Permanently removes all cached conversations and threads from localStorage.
 * Leaves theme, consents, and non-secret user settings intact.
 * Dispatches 'carefold:conversations-cleared'.
 */
export function deleteAllConversations(): { deletedCount: number } {
  if (typeof window === 'undefined' || !window.localStorage) return { deletedCount: 0 };
  let deletedCount = 0;
  try {
    const keysToRemove: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key && (key.startsWith('carefold_msgs_') || key.startsWith('carefold_thread_'))) {
        keysToRemove.push(key);
      }
    }
    for (const key of keysToRemove) {
      if (key.startsWith('carefold_msgs_')) deletedCount++;
      window.localStorage.removeItem(key);
    }
    window.dispatchEvent(new CustomEvent('carefold:conversations-cleared'));
  } catch {
    // Storage access protection
  }
  return { deletedCount };
}

/**
 * Removes all stored API keys from settings while preserving provider, model, and endpoints.
 * Dispatches 'carefold:settings-changed'.
 */
export function clearStoredApiKeys(userId?: string | null): CarefoldUserSettings {
  const current = loadSettings(userId);
  const cleared: CarefoldUserSettings = {
    ...current,
    keys: {
      google: '',
      anthropic: '',
      openai: '',
      custom: ''
    }
  };
  if (typeof window !== 'undefined' && window.localStorage) {
    try {
      const effectiveUserId = userId !== undefined ? userId : getStorageUserId();
      const key = getScopedStorageKey(effectiveUserId, CAREFOLD_SETTINGS_STORAGE_KEY);
      window.localStorage.setItem(key, JSON.stringify(cleared));
      if (!effectiveUserId) {
        window.localStorage.setItem(CAREFOLD_SETTINGS_STORAGE_KEY, JSON.stringify(cleared));
      }
      window.dispatchEvent(new CustomEvent('carefold:settings-changed', { detail: cleared }));
    } catch {
      // Storage access protection
    }
  }
  return loadSettings(userId);
}


