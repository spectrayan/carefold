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
  Cpu,
  ShieldCheck,
  Eye,
  EyeOff,
  Check,
  Key
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  type CarefoldUserSettings,
  DEFAULT_USER_SETTINGS,
  loadSettings,
  saveSettings
} from '@/lib/settings';

export default function ModelSettingsPage() {
  const [formData, setFormData] = useState<CarefoldUserSettings>(DEFAULT_USER_SETTINGS);
  const [showGeminiKey, setShowGeminiKey] = useState(false);
  const [showAnthropicKey, setShowAnthropicKey] = useState(false);
  const [showOpenAIKey, setShowOpenAIKey] = useState(false);
  const [showCustomKey, setShowCustomKey] = useState(false);
  const [ollamaStatus, setOllamaStatus] = useState<'idle' | 'checking' | 'connected' | 'error'>('idle');
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [savedSuccess, setSavedSuccess] = useState(false);

  useEffect(() => {
    const loaded = loadSettings();
    setFormData(loaded);
    checkOllama(loaded.endpoints?.ollamaUrl);
  }, []);

  const checkOllama = async (_url?: string) => {
    setOllamaStatus('checking');
    try {
      const res = await fetch('/api/v1/health');
      if (res.ok) {
        const data = await res.json();
        if (data?.modelReachable) {
          setOllamaStatus('connected');
          if (Array.isArray(data.availableModels)) {
            setOllamaModels(data.availableModels);
          }
        } else {
          setOllamaStatus('error');
        }
      } else {
        setOllamaStatus('error');
      }
    } catch {
      setOllamaStatus('error');
    }
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    saveSettings(formData);
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 2000);
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-[var(--cf-fg)] tracking-tight">
          Model & Provider Settings
        </h2>
        <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
          Configure local Ollama execution and optional cloud inference providers.
        </p>
      </div>

      {/* Local-First Privacy Notice */}
      <div
        data-testid="privacy-notice"
        className="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 flex items-start gap-3"
      >
        <ShieldCheck className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
        <div className="text-xs text-emerald-950 dark:text-emerald-200 leading-relaxed">
          <span className="font-bold block mb-1">Local-First Privacy Guarantee</span>
          Carefold runs AI models directly on your hardware via Ollama. Prompts, documents, notes, and health records never leave this machine.
        </div>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Section 1: Ollama Local Configuration */}
        <div className="space-y-3 pb-6 border-b border-[var(--cf-border)]">
          <div className="flex items-center justify-between">
            <label htmlFor="ollama-url-input" className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
              <Cpu className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>Ollama Local Host URL</span>
            </label>
            <span className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/60 px-2.5 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800">
              Zero Keys Required
            </span>
          </div>

          <div className="flex flex-col sm:flex-row gap-2">
            <input
              id="ollama-url-input"
              data-testid="ollama-url-input"
              type="text"
              value={formData.endpoints?.ollamaUrl || ''}
              onChange={(e) => setFormData({ ...formData, endpoints: { ...formData.endpoints, ollamaUrl: e.target.value } })}
              placeholder="http://127.0.0.1:11434"
              className="flex-1 px-3 py-2 text-xs font-mono rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
            />
            <button
              type="button"
              data-testid="check-connectivity-btn"
              onClick={() => checkOllama(formData.endpoints?.ollamaUrl)}
              disabled={ollamaStatus === 'checking'}
              className="px-4 py-2 text-xs font-semibold rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface-2)] text-[var(--cf-fg)] hover:bg-[var(--cf-surface-3)] transition-all min-h-[44px] shrink-0"
            >
              {ollamaStatus === 'checking' ? 'Checking…' : 'Check Connectivity'}
            </button>
          </div>

          {/* Status Indicator */}
          <div className="flex items-center gap-2 text-xs">
            <span
              className={cn(
                'w-2 h-2 rounded-full',
                ollamaStatus === 'connected' && 'bg-emerald-500',
                ollamaStatus === 'error' && 'bg-amber-500',
                ollamaStatus === 'checking' && 'bg-slate-400 animate-pulse',
                ollamaStatus === 'idle' && 'bg-slate-300'
              )}
            />
            <span className="text-[var(--cf-fg-muted)]">
              {ollamaStatus === 'connected'
                ? 'Connected to local Ollama runtime'
                : ollamaStatus === 'error'
                ? 'Ollama is unreachable. Ensure ollama serve is running locally.'
                : 'Ready'}
            </span>
          </div>
        </div>

        {/* Section 2: Optional Cloud AI Providers */}
        <div className="space-y-4 pb-6 border-b border-[var(--cf-border)]">
          <div>
            <h3 className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
              <Key className="w-4 h-4 text-[var(--cf-fg-subtle)]" />
              <span>Optional Cloud Inference API Keys</span>
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
              Keys are stored securely in browser storage and only used if explicitly selected.
            </p>
          </div>

          {/* Google Gemini */}
          <div className="space-y-1.5">
            <label htmlFor="gemini-key-input" className="text-xs font-semibold text-[var(--cf-fg)] block">
              Google Gemini API Key
            </label>
            <div className="relative">
              <input
                id="gemini-key-input"
                data-testid="gemini-key-input"
                type={showGeminiKey ? 'text' : 'password'}
                value={formData.keys.google || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    keys: { ...formData.keys, google: e.target.value }
                  })
                }
                placeholder="AIzaSy..."
                className="w-full pl-3 pr-10 py-2 text-xs font-mono rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
              />
              <button
                type="button"
                data-testid="toggle-gemini-key"
                aria-label={showGeminiKey ? 'Hide Gemini API key' : 'Show Gemini API key'}
                onClick={() => setShowGeminiKey(!showGeminiKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] p-1 min-h-[36px] min-w-[36px] flex items-center justify-center"
              >
                {showGeminiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* Anthropic Claude */}
          <div className="space-y-1.5">
            <label htmlFor="anthropic-key-input" className="text-xs font-semibold text-[var(--cf-fg)] block">
              Anthropic Claude API Key
            </label>
            <div className="relative">
              <input
                id="anthropic-key-input"
                data-testid="anthropic-key-input"
                type={showAnthropicKey ? 'text' : 'password'}
                value={formData.keys.anthropic || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    keys: { ...formData.keys, anthropic: e.target.value }
                  })
                }
                placeholder="sk-ant-api..."
                className="w-full pl-3 pr-10 py-2 text-xs font-mono rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
              />
              <button
                type="button"
                data-testid="toggle-anthropic-key"
                aria-label={showAnthropicKey ? 'Hide Anthropic API key' : 'Show Anthropic API key'}
                onClick={() => setShowAnthropicKey(!showAnthropicKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] p-1 min-h-[36px] min-w-[36px] flex items-center justify-center"
              >
                {showAnthropicKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* OpenAI */}
          <div className="space-y-1.5">
            <label htmlFor="openai-key-input" className="text-xs font-semibold text-[var(--cf-fg)] block">
              OpenAI API Key
            </label>
            <div className="relative">
              <input
                id="openai-key-input"
                data-testid="openai-key-input"
                type={showOpenAIKey ? 'text' : 'password'}
                value={formData.keys.openai || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    keys: { ...formData.keys, openai: e.target.value }
                  })
                }
                placeholder="sk-proj-..."
                className="w-full pl-3 pr-10 py-2 text-xs font-mono rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
              />
              <button
                type="button"
                data-testid="toggle-openai-key"
                aria-label={showOpenAIKey ? 'Hide OpenAI API key' : 'Show OpenAI API key'}
                onClick={() => setShowOpenAIKey(!showOpenAIKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] p-1 min-h-[36px] min-w-[36px] flex items-center justify-center"
              >
                {showOpenAIKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        {/* Section 3: Custom Endpoint */}
        <div className="space-y-4 pb-6 border-b border-[var(--cf-border)]">
          <div>
            <h3 className="text-sm font-semibold text-[var(--cf-fg)]">
              Custom OpenAI-Compatible Endpoint
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
              Supports LM Studio, vLLM, LocalAI, and private inference servers.
            </p>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="custom-url-input" className="text-xs font-semibold text-[var(--cf-fg)] block">
              Base URL
            </label>
            <input
              id="custom-url-input"
              data-testid="custom-url-input"
              type="text"
              value={formData.endpoints?.customUrl || ''}
              onChange={(e) => setFormData({ ...formData, endpoints: { ...formData.endpoints, customUrl: e.target.value } })}
              placeholder="http://localhost:1234/v1"
              className="w-full px-3 py-2 text-xs font-mono rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="custom-key-input" className="text-xs font-semibold text-[var(--cf-fg)] block">
              Custom API Key (Optional)
            </label>
            <div className="relative">
              <input
                id="custom-key-input"
                data-testid="custom-key-input"
                type={showCustomKey ? 'text' : 'password'}
                value={formData.keys.custom || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    keys: { ...formData.keys, custom: e.target.value }
                  })
                }
                placeholder="Optional (defaults to 'custom')"
                className="w-full pl-3 pr-10 py-2 text-xs font-mono rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
              />
              <button
                type="button"
                data-testid="toggle-custom-key"
                aria-label={showCustomKey ? 'Hide Custom API key' : 'Show Custom API key'}
                onClick={() => setShowCustomKey(!showCustomKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] p-1 min-h-[36px] min-w-[36px] flex items-center justify-center"
              >
                {showCustomKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        {/* Section 4: Personal Default Model */}
        <div className="space-y-2 pb-6 border-b border-[var(--cf-border)]">
          <label htmlFor="personal-default-model-select" className="text-sm font-semibold text-[var(--cf-fg)] block">
            Personal Default Model
          </label>
          <select
            id="personal-default-model-select"
            data-testid="personal-default-model-select"
            value={formData.model || 'llama3.2:3b'}
            onChange={(e) => setFormData({ ...formData, model: e.target.value })}
            className="w-full px-3 py-2 text-xs rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
          >
            <option value="llama3.2:3b">Ollama · llama3.2:3b (Recommended local)</option>
            <option value="llama3.2:latest">Ollama · llama3.2:latest</option>
            <option value="llama3.1:8b">Ollama · llama3.1:8b</option>
            <option value="gemini-2.5-flash">Google · gemini-2.5-flash (Cloud)</option>
            <option value="claude-3-7-sonnet-latest">Anthropic · claude-3-7-sonnet (Cloud)</option>
            <option value="gpt-4o">OpenAI · gpt-4o (Cloud)</option>
            {ollamaModels
              .filter((m) => !['llama3.2:3b', 'llama3.2:latest', 'llama3.1:8b'].includes(m))
              .map((m) => (
                <option key={m} value={m}>
                  Ollama · {m} (Installed)
                </option>
              ))}
          </select>
        </div>

        {/* Submit Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          {savedSuccess && (
            <span className="text-xs text-emerald-700 dark:text-emerald-400 font-semibold flex items-center gap-1.5">
              <Check className="w-4 h-4" /> Changes saved successfully
            </span>
          )}
          <button
            type="submit"
            data-testid="save-settings-btn"
            className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-[var(--cf-primary)] text-[var(--cf-fg-on-primary)] hover:bg-[var(--cf-primary-hover)] transition-all min-h-[44px] shadow-sm"
          >
            Save Changes
          </button>
        </div>
      </form>
    </div>
  );
}
