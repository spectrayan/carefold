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
  X,
  Eye,
  EyeOff,
  ShieldCheck,
  Check,
  ExternalLink,
  Cpu,
  Server,
  Key,
  Sun,
  Moon,
  Laptop,
  ShieldAlert
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  type CarefoldUserSettings,
  loadSettings,
  saveSettings
} from '@/lib/settings';
import type { AgentSummary } from '@/lib/types';
import { withdrawAllClinicalConsents, withdrawClinicalConsent } from '@/lib/clinicalConsent';
import { useClinicalConsents } from '@/lib/useClinicalConsents';
import { useOptionalTheme } from '@/components/ThemeProvider';
import {
  type Theme,
  getStoredTheme,
  setStoredTheme,
  resolveTheme,
  applyThemeToDOM
} from '@/lib/theme';

export interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialSettings?: CarefoldUserSettings;
  settings?: CarefoldUserSettings;
  onSave?: (savedSettings: CarefoldUserSettings) => void;
  /** Optional agent catalog used to show friendly titles for clinical consents. */
  agents?: Pick<AgentSummary, 'id' | 'title'>[];
}

export function SettingsModal({
  isOpen,
  onClose,
  initialSettings,
  settings,
  onSave,
  agents
}: SettingsModalProps) {
  const activeInitial = initialSettings || settings;
  const [formData, setFormData] = useState<CarefoldUserSettings>(() => activeInitial || loadSettings());
  const { consents: clinicalConsents } = useClinicalConsents();
  const consentEntries = Object.entries(clinicalConsents).sort(([a], [b]) => a.localeCompare(b));
  const agentTitle = (id: string) => agents?.find((a) => a.id === id)?.title || id;

  // Theme support: consume ThemeContext safely with fallback for isolated test environments
  const themeContext = useOptionalTheme();
  const [fallbackTheme, setFallbackTheme] = useState<Theme>(() => getStoredTheme());
  const theme = themeContext ? themeContext.theme : fallbackTheme;

  const handleThemeChange = (newTheme: Theme) => {
    if (themeContext) {
      themeContext.setTheme(newTheme);
    } else {
      setFallbackTheme(newTheme);
      setStoredTheme(newTheme);
      applyThemeToDOM(resolveTheme(newTheme));
    }
  };

  // Visibility toggles for masked password fields
  const [showGeminiKey, setShowGeminiKey] = useState(false);
  const [showAnthropicKey, setShowAnthropicKey] = useState(false);
  const [showOpenaiKey, setShowOpenaiKey] = useState(false);
  const [showCustomKey, setShowCustomKey] = useState(false);

  // Save confirmation banner state
  const [savedSuccess, setSavedSuccess] = useState(false);

  // Sync internal state when modal opens or initial settings change
  useEffect(() => {
    if (isOpen) {
      setFormData(activeInitial || loadSettings());
      setSavedSuccess(false);
    }
  }, [isOpen, activeInitial]);

  // Handle ESC key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    const updated = saveSettings(formData);
    setSavedSuccess(true);
    if (onSave) {
      onSave(updated);
    }
    setTimeout(() => {
      setSavedSuccess(false);
      onClose();
    }, 600);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-dialog-title"
      data-testid="settings-modal"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm overflow-y-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl shadow-xl w-full max-w-xl max-h-[90vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">

        {/* Modal Header */}
        <div className="px-5 py-4 border-b border-slate-200 dark:border-zinc-800 bg-slate-50 dark:bg-zinc-800/80 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 flex items-center justify-center">
              <Settings className="w-4 h-4" />
            </div>
            <div>
              <h2 id="settings-dialog-title" className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                Model & Provider Settings
              </h2>
              <p className="text-[11px] text-slate-500 dark:text-zinc-400">
                Configure local endpoints and optional cloud AI credentials
              </p>
            </div>
          </div>
          <button
            type="button"
            data-testid="close-settings-modal"
            aria-label="Close Settings Modal"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 dark:text-zinc-400 hover:text-slate-700 dark:hover:text-zinc-200 hover:bg-slate-200 dark:hover:bg-zinc-700 transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Scrollable Body */}
        <form onSubmit={handleSave} className="flex-1 overflow-y-auto p-5 space-y-5">

          {/* Local-First Privacy Notice */}
          <div
            data-testid="privacy-notice"
            className="p-3.5 rounded-xl bg-emerald-50/70 dark:bg-emerald-950/40 border border-emerald-200/80 dark:border-emerald-800/60 flex items-start gap-3"
          >
            <ShieldCheck className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
            <div className="text-xs text-emerald-950 dark:text-emerald-200 leading-relaxed">
              <span className="font-semibold text-emerald-900 dark:text-emerald-300 block mb-0.5">
                Local-First Privacy Guarantee
              </span>
              All API keys and endpoint URLs are saved strictly in your browser&apos;s local storage and sent directly to your local runner (127.0.0.1). Credentials are never shared with or sent to Carefold servers.
            </div>
          </div>

          {/* Section 1: Ollama Local Configuration */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label htmlFor="ollama-url-input" className="text-xs font-bold text-slate-800 dark:text-zinc-200 flex items-center gap-1.5">
                <Cpu className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400" />
                <span>Ollama Base URL (Default Local)</span>
              </label>
              <span className="text-[11px] font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-100/70 dark:bg-emerald-950/60 px-2 py-0.5 rounded-md">
                Zero Keys Required
              </span>
            </div>
            <input
              id="ollama-url-input"
              data-testid="ollama-url-input"
              type="text"
              value={formData.endpoints.ollamaUrl}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  endpoints: { ...formData.endpoints, ollamaUrl: e.target.value }
                })
              }
              placeholder="http://127.0.0.1:11434"
              className="w-full px-3 py-2 text-xs font-mono rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
            />
          </div>

          {/* Section 2: Cloud API Keys */}
          <div className="space-y-3 pt-2 border-t border-slate-200 dark:border-zinc-800">
            <h3 className="text-xs font-bold text-slate-900 dark:text-zinc-100 flex items-center gap-1.5">
              <Key className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400" />
              <span>Cloud Provider API Keys</span>
            </h3>

            {/* Google Gemini */}
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <label htmlFor="gemini-key-input" className="font-semibold text-slate-700 dark:text-zinc-300">
                  Google Gemini API Key
                </label>
                <a
                  href="https://aistudio.google.com/app/apikey"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[11px] text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 flex items-center gap-0.5 hover:underline"
                >
                  <span>Get API Key</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>
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
                  className="w-full pl-3 pr-9 py-2 text-xs font-mono rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
                />
                <button
                  type="button"
                  data-testid="toggle-gemini-key"
                  aria-label={showGeminiKey ? 'Hide Gemini API key' : 'Show Gemini API key'}
                  onClick={() => setShowGeminiKey(!showGeminiKey)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-zinc-400 hover:text-slate-600 dark:hover:text-zinc-200 p-1 cursor-pointer"
                >
                  {showGeminiKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* Anthropic Claude */}
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <label htmlFor="anthropic-key-input" className="font-semibold text-slate-700 dark:text-zinc-300">
                  Anthropic Claude API Key
                </label>
                <a
                  href="https://console.anthropic.com/"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[11px] text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 flex items-center gap-0.5 hover:underline"
                >
                  <span>Get API Key</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>
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
                  placeholder="sk-ant-..."
                  className="w-full pl-3 pr-9 py-2 text-xs font-mono rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
                />
                <button
                  type="button"
                  data-testid="toggle-anthropic-key"
                  aria-label={showAnthropicKey ? 'Hide Anthropic API key' : 'Show Anthropic API key'}
                  onClick={() => setShowAnthropicKey(!showAnthropicKey)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-zinc-400 hover:text-slate-600 dark:hover:text-zinc-200 p-1 cursor-pointer"
                >
                  {showAnthropicKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* OpenAI */}
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <label htmlFor="openai-key-input" className="font-semibold text-slate-700 dark:text-zinc-300">
                  OpenAI API Key
                </label>
                <a
                  href="https://platform.openai.com/api-keys"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[11px] text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 flex items-center gap-0.5 hover:underline"
                >
                  <span>Get API Key</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>
              <div className="relative">
                <input
                  id="openai-key-input"
                  data-testid="openai-key-input"
                  type={showOpenaiKey ? 'text' : 'password'}
                  value={formData.keys.openai || ''}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      keys: { ...formData.keys, openai: e.target.value }
                    })
                  }
                  placeholder="sk-proj-..."
                  className="w-full pl-3 pr-9 py-2 text-xs font-mono rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
                />
                <button
                  type="button"
                  data-testid="toggle-openai-key"
                  aria-label={showOpenaiKey ? 'Hide OpenAI API key' : 'Show OpenAI API key'}
                  onClick={() => setShowOpenaiKey(!showOpenaiKey)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-zinc-400 hover:text-slate-600 dark:hover:text-zinc-200 p-1 cursor-pointer"
                >
                  {showOpenaiKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
          </div>

          {/* Section 3: Custom Endpoint */}
          <div className="space-y-3 pt-2 border-t border-slate-200 dark:border-zinc-800">
            <h3 className="text-xs font-bold text-slate-900 dark:text-zinc-100 flex items-center gap-1.5">
              <Server className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400" />
              <span>Custom OpenAI-Compatible Endpoint</span>
            </h3>
            <p className="text-[11px] text-slate-500 dark:text-zinc-400">
              Compatible with LM Studio, vLLM, LocalAI, or custom OpenAI proxies.
            </p>

            <div className="space-y-1">
              <label htmlFor="custom-url-input" className="text-xs font-semibold text-slate-700 dark:text-zinc-300 block">
                Base URL
              </label>
              <input
                id="custom-url-input"
                data-testid="custom-url-input"
                type="text"
                value={formData.endpoints.customUrl}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    endpoints: { ...formData.endpoints, customUrl: e.target.value }
                  })
                }
                placeholder="http://127.0.0.1:8000/v1"
                className="w-full px-3 py-2 text-xs font-mono rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
              />
            </div>

            <div className="space-y-1">
              <label htmlFor="custom-key-input" className="text-xs font-semibold text-slate-700 dark:text-zinc-300 block">
                Custom Endpoint API Key (Optional)
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
                  className="w-full pl-3 pr-9 py-2 text-xs font-mono rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
                />
                <button
                  type="button"
                  data-testid="toggle-custom-key"
                  aria-label={showCustomKey ? 'Hide Custom API key' : 'Show Custom API key'}
                  onClick={() => setShowCustomKey(!showCustomKey)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-zinc-400 hover:text-slate-600 dark:hover:text-zinc-200 p-1 cursor-pointer"
                >
                  {showCustomKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
          </div>

          {/* Section 4: Clinical Assist Consent (#87) */}
          <div data-testid="clinical-consent-settings" className="space-y-2 pt-2 border-t border-slate-200 dark:border-zinc-800">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-slate-900 dark:text-zinc-100 flex items-center gap-1.5">
                <ShieldAlert className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400" />
                <span>Clinical Assist Consent</span>
              </h3>
              {consentEntries.length > 1 && (
                <button
                  type="button"
                  data-testid="withdraw-all-clinical-consent"
                  onClick={() => withdrawAllClinicalConsents()}
                  className="text-[11px] font-semibold text-rose-700 dark:text-rose-400 hover:underline cursor-pointer"
                >
                  Withdraw all
                </button>
              )}
            </div>
            <p className="text-[11px] text-slate-500 dark:text-zinc-400">
              Clinical assist agents only run after you give consent. Withdrawing takes effect on your next message.
            </p>
            {consentEntries.length === 0 ? (
              <p data-testid="clinical-consent-empty" className="text-xs text-slate-600 dark:text-zinc-400">
                You have not given consent to any clinical assist agents.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {consentEntries.map(([agentId, record]) => (
                  <li
                    key={agentId}
                    data-testid={`clinical-consent-entry-${agentId}`}
                    className="flex items-center justify-between gap-3 p-2.5 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800/60 text-xs"
                  >
                    <div className="min-w-0">
                      <div className="font-semibold text-slate-800 dark:text-zinc-200 truncate">{agentTitle(agentId)}</div>
                      <div className="text-[11px] text-slate-500 dark:text-zinc-400">
                        Consent given {new Date(record.grantedAt).toLocaleString()}
                      </div>
                    </div>
                    <button
                      type="button"
                      data-testid={`withdraw-clinical-consent-${agentId}`}
                      aria-label={`Withdraw consent for ${agentTitle(agentId)}`}
                      onClick={() => withdrawClinicalConsent(agentId)}
                      className="shrink-0 px-2.5 py-1 rounded-lg border border-rose-200 dark:border-rose-900/60 text-rose-700 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/40 font-semibold transition cursor-pointer"
                    >
                      Withdraw
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Section 5: Appearance & Theme */}
          <div className="space-y-2 pt-2 border-t border-slate-200 dark:border-zinc-800">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-slate-900 dark:text-zinc-100 flex items-center gap-1.5">
                <Sun className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400" />
                <span>Appearance & Theme</span>
              </label>
              <span className="text-[11px] text-slate-500 dark:text-zinc-400 capitalize">
                Current: {theme}
              </span>
            </div>

            <div
              data-testid="theme-selector-group"
              className="grid grid-cols-3 gap-2"
            >
              {(['light', 'dark', 'system'] as const).map((mode) => {
                const isSelected = theme === mode;
                const Icon = mode === 'light' ? Sun : mode === 'dark' ? Moon : Laptop;
                return (
                  <button
                    key={mode}
                    type="button"
                    data-testid={`theme-option-${mode}`}
                    onClick={() => handleThemeChange(mode)}
                    className={cn(
                      'flex items-center justify-center gap-1.5 py-2 px-3 rounded-xl border text-xs font-semibold capitalize transition cursor-pointer',
                      isSelected
                        ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-500 text-emerald-900 dark:text-emerald-300 ring-1 ring-emerald-500'
                        : 'bg-white dark:bg-zinc-800 border-slate-300 dark:border-zinc-700 text-slate-700 dark:text-zinc-300 hover:bg-slate-50 dark:hover:bg-zinc-700'
                    )}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span>{mode}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Footer Actions */}
          <div className="pt-4 border-t border-slate-200 dark:border-zinc-800 flex items-center justify-between">
            <div>
              {savedSuccess && (
                <span
                  data-testid="save-success-badge"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 dark:text-emerald-300 bg-emerald-100 dark:bg-emerald-950/60 px-2.5 py-1 rounded-lg animate-in fade-in"
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>Settings Saved</span>
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="cancel-settings-btn"
                onClick={onClose}
                className="px-3.5 py-2 text-xs font-medium text-slate-700 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-zinc-100 rounded-xl hover:bg-slate-100 dark:hover:bg-zinc-800 transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                data-testid="save-settings-btn"
                className="px-4 py-2 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-xl shadow-sm transition cursor-pointer"
              >
                Save Settings
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
