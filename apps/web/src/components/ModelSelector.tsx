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

'use client';

import React, { useState, useEffect } from 'react';
import {
  Settings,
  ChevronDown,
  AlertCircle
} from 'lucide-react';
import {
  type ProviderType,
  type CarefoldUserSettings,
  type ModelOption,
  PROVIDER_METADATA,
  PREDEFINED_MODELS,
  hasApiKeyForProvider
} from '@/lib/settings';

export interface ModelSelectorProps {
  settings: CarefoldUserSettings;
  onSettingsChange?: (newSettings: CarefoldUserSettings) => void;
  onOpenSettings: () => void;
  disabled?: boolean;
  className?: string;

  // Optional individual property overrides
  selectedProvider?: ProviderType;
  selectedModel?: string;
  customModelName?: string;
  installedModels?: ModelOption[];
  onProviderChange?: (provider: ProviderType) => void;
  onModelChange?: (model: string) => void;
  onCustomModelChange?: (customModelName: string) => void;
}

export function ModelSelector({
  settings,
  onSettingsChange,
  onOpenSettings,
  disabled = false,
  className = '',
  selectedProvider,
  selectedModel,
  customModelName,
  installedModels,
  onProviderChange,
  onModelChange,
  onCustomModelChange
}: ModelSelectorProps) {
  const currentProvider = selectedProvider ?? settings.provider ?? 'ollama';
  const currentModel = selectedModel ?? settings.model ?? 'llama3.2';
  const currentCustomModel = customModelName ?? settings.customModelName ?? '';

  const [dynamicOllamaModels, setDynamicOllamaModels] = useState<ModelOption[]>(installedModels || []);

  useEffect(() => {
    if (installedModels && installedModels.length > 0) {
      setDynamicOllamaModels(installedModels);
      return;
    }
    if (currentProvider !== 'ollama') return;

    let mounted = true;
    async function fetchInstalledModels() {
      try {
        const endpoint = settings.endpoints?.ollamaUrl || 'http://127.0.0.1:11434';
        const res = await fetch(`/api/v1/models?provider=ollama&endpoint=${encodeURIComponent(endpoint)}`);
        if (res.ok) {
          const data = await res.json();
          if (mounted && Array.isArray(data.models) && data.models.length > 0) {
            setDynamicOllamaModels(data.models);
          }
        }
      } catch {
        // Fallback silently if offline or unqueried
      }
    }

    fetchInstalledModels();
    return () => {
      mounted = false;
    };
  }, [currentProvider, settings.endpoints?.ollamaUrl, installedModels]);

  const availableModels = currentProvider === 'ollama' && dynamicOllamaModels.length > 0
    ? dynamicOllamaModels
    : PREDEFINED_MODELS[currentProvider] || [];

  const isCustomMode = currentProvider === 'custom' || currentModel === 'custom';
  const isKeyMissing = !hasApiKeyForProvider(settings, currentProvider);

  // Match currentModel in availableModels, allowing matching with or without :latest
  const matchedOption = availableModels.find(
    (opt) => opt.id === currentModel ||
             opt.id.replace(/:latest$/, '') === currentModel.replace(/:latest$/, '')
  );
  const selectedDropdownValue = isCustomMode
    ? 'custom'
    : (matchedOption ? matchedOption.id : currentModel);

  const handleProviderSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const nextProvider = e.target.value as ProviderType;
    const defaultModel = PROVIDER_METADATA[nextProvider]?.defaultModel || 'llama3.2';

    if (onProviderChange) {
      onProviderChange(nextProvider);
    }
    if (onSettingsChange) {
      onSettingsChange({
        ...settings,
        provider: nextProvider,
        model: defaultModel
      });
    }
  };

  const handleModelSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const nextModel = e.target.value;
    if (onModelChange) {
      onModelChange(nextModel);
    }
    if (onSettingsChange) {
      onSettingsChange({
        ...settings,
        model: nextModel
      });
    }
  };

  const handleCustomModelNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const nextName = e.target.value;
    if (onCustomModelChange) {
      onCustomModelChange(nextName);
    }
    if (onSettingsChange) {
      onSettingsChange({
        ...settings,
        customModelName: nextName
      });
    }
  };

  return (
    <div className={`flex items-center flex-wrap gap-2 ${className}`}>
      {/* Provider Selector Dropdown */}
      <div className="relative">
        <label htmlFor="provider-selector" className="sr-only">
          Select AI Provider
        </label>
        <select
          id="provider-selector"
          data-testid="provider-selector"
          aria-label="Select AI Provider"
          value={currentProvider}
          onChange={handleProviderSelect}
          disabled={disabled}
          className="appearance-none bg-white dark:bg-zinc-800 border border-[#7f8ea3] dark:border-[#657895] rounded-xl pl-2.5 pr-7 py-1.5 text-xs font-semibold text-slate-800 dark:text-zinc-100 hover:border-slate-500 dark:hover:border-zinc-500 focus:border-emerald-700 dark:focus:border-emerald-400 cursor-pointer shadow-sm disabled:opacity-50 transition"
        >
          <option value="ollama">💻 Ollama (Local)</option>
          <option value="google">✨ Gemini (Cloud)</option>
          <option value="anthropic">🧠 Claude (Cloud)</option>
          <option value="openai">⚡ OpenAI (Cloud)</option>
          <option value="custom">🌐 Custom Endpoint</option>
        </select>
        <ChevronDown className="w-3.5 h-3.5 text-slate-400 dark:text-zinc-500 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
      </div>

      {/* Model Selector Dropdown (Hidden when custom provider) */}
      {currentProvider !== 'custom' && (
        <div className="relative hidden sm:block">
          <label htmlFor="model-selector" className="sr-only">
            Select Model
          </label>
          <select
            id="model-selector"
            data-testid="model-selector"
            aria-label="Select Model"
            value={selectedDropdownValue}
            onChange={handleModelSelect}
            disabled={disabled}
            className="appearance-none bg-white dark:bg-zinc-800 border border-[#7f8ea3] dark:border-[#657895] rounded-xl pl-2.5 pr-7 py-1.5 text-xs font-medium text-slate-800 dark:text-zinc-100 hover:border-slate-500 dark:hover:border-zinc-500 focus:border-emerald-700 dark:focus:border-emerald-400 cursor-pointer shadow-sm disabled:opacity-50 transition max-w-[170px] truncate"
          >
            {availableModels.map((opt) => (
              <option key={opt.id} value={opt.id} title={opt.description}>
                {opt.name}
              </option>
            ))}
            {!isCustomMode && !availableModels.some((m) => m.id === selectedDropdownValue) && (
              <option value={selectedDropdownValue}>{selectedDropdownValue}</option>
            )}
            <option value="custom">Custom Model Name...</option>
          </select>
          <ChevronDown className="w-3.5 h-3.5 text-slate-400 dark:text-zinc-500 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
      )}

      {/* Custom Model Name Input Field */}
      {isCustomMode && (
        <div className="relative">
          <label htmlFor="custom-model-input" className="sr-only">
            Custom Model Name
          </label>
          <div className="flex items-center">
            <input
              id="custom-model-input"
              data-testid="custom-model-input"
              type="text"
              placeholder="e.g. qwen2.5-coder:32b"
              value={currentCustomModel}
              onChange={handleCustomModelNameChange}
              disabled={disabled}
              className="bg-white dark:bg-zinc-800 border border-slate-300 dark:border-zinc-700 rounded-xl px-2.5 py-1.5 text-xs font-mono text-slate-800 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400 shadow-sm w-44 transition disabled:opacity-50 placeholder:font-sans placeholder:text-slate-400 dark:placeholder:text-zinc-500"
            />
          </div>
        </div>
      )}

      {/* Missing Key Warning Badge */}
      {isKeyMissing && (
        <button
          type="button"
          data-testid="missing-key-badge"
          onClick={onOpenSettings}
          title={`API key required for ${PROVIDER_METADATA[currentProvider]?.label}. Click to configure in Settings.`}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800/80 text-amber-800 dark:text-amber-300 text-xs font-semibold hover:bg-amber-100 dark:hover:bg-amber-900/50 hover:border-amber-400 dark:hover:border-amber-700 transition animate-pulse shadow-sm"
        >
          <AlertCircle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400 shrink-0" />
          <span>Key Required</span>
        </button>
      )}

      {/* Settings Modal Trigger Button */}
      <button
        type="button"
        data-testid="open-settings-button"
        onClick={onOpenSettings}
        title="Model & API Key Settings"
        aria-label="Open Model & API Key Settings"
        disabled={disabled}
        className="p-1.5 rounded-xl border border-slate-300 dark:border-zinc-700 hover:border-slate-400 dark:hover:border-zinc-600 text-slate-600 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-zinc-100 bg-white dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 shadow-sm transition disabled:opacity-50 cursor-pointer"
      >
        <span data-testid="settings-modal-trigger" className="sr-only">Settings</span>
        <Settings className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
