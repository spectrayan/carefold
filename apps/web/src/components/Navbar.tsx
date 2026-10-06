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

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  HeartHandshake,
  LayoutGrid,
  MessageSquare,
  Sun,
  Moon,
  ShieldCheck,
  ShieldAlert,
  X,
  Cpu,
  Settings
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useOptionalTheme } from '@/components/ThemeProvider';
import { type Theme, getStoredTheme, setStoredTheme, resolveTheme, applyThemeToDOM } from '@/lib/theme';
import {
  DEFAULT_USER_SETTINGS,
  loadSettings,
  saveSettings,
  getProviderPrivacyState,
  type CarefoldUserSettings
} from '@/lib/settings';
import { SettingsModal } from '@/components/SettingsModal';

export function Navbar() {
  const pathname = usePathname();
  const [ollamaOnline, setOllamaOnline] = useState<boolean | null>(null);
  const [settings, setSettings] = useState<CarefoldUserSettings>(DEFAULT_USER_SETTINGS);
  const [showExplainer, setShowExplainer] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  const [mounted, setMounted] = useState(false);

  // Safely consume ThemeContext, falling back to local state if rendered without provider
  const themeContext = useOptionalTheme();
  const [fallbackTheme, setFallbackTheme] = useState<Theme>('system');

  useEffect(() => {
    setMounted(true);
    setFallbackTheme(getStoredTheme());
    setSettings(loadSettings());

    const handleSettingsChange = (e: Event) => {
      const customEvent = e as CustomEvent<CarefoldUserSettings>;
      if (customEvent.detail) {
        setSettings(customEvent.detail);
      } else {
        setSettings(loadSettings());
      }
    };

    window.addEventListener('carefold:settings-changed', handleSettingsChange);
    return () => {
      window.removeEventListener('carefold:settings-changed', handleSettingsChange);
    };
  }, []);

  const privacyState = getProviderPrivacyState(settings);

  const theme = themeContext ? themeContext.theme : fallbackTheme;
  const resolvedTheme = themeContext ? themeContext.resolvedTheme : resolveTheme(fallbackTheme);
  const effectiveTheme = mounted ? theme : 'system';
  const effectiveResolvedTheme = mounted ? resolvedTheme : 'light';

  const toggleTheme = () => {
    if (themeContext) {
      themeContext.toggleTheme();
    } else {
      const nextTheme: Theme = resolvedTheme === 'dark' ? 'light' : 'dark';
      setFallbackTheme(nextTheme);
      setStoredTheme(nextTheme);
      applyThemeToDOM(resolveTheme(nextTheme));
    }
  };

  useEffect(() => {
    let mounted = true;
    async function checkHealth() {
      try {
        const res = await fetch('/api/health');
        if (res.ok) {
          const data = await res.json();
          if (mounted) setOllamaOnline(Boolean(data.ollama?.reachable || data.modelReachable));
        } else {
          if (mounted) setOllamaOnline(false);
        }
      } catch {
        if (mounted) setOllamaOnline(false);
      }
    }
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const navLinks = [
    { href: '/', label: 'Marketplace', icon: LayoutGrid },
    { href: '/chat', label: 'Chat', icon: MessageSquare }
  ];

  return (
    <header className="bg-white dark:bg-zinc-900 border-b border-slate-200 dark:border-zinc-800 transition-colors">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center gap-8">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-9 h-9 rounded-lg bg-emerald-600 flex items-center justify-center text-white shadow-sm group-hover:bg-emerald-700 transition">
              <HeartHandshake className="w-5 h-5" />
            </div>
            <span className="font-bold text-lg text-slate-900 dark:text-white tracking-tight">Carefold</span>
          </Link>

          {/* Primary Nav */}
          <nav className="hidden sm:flex items-center gap-1">
            {navLinks.map((link) => {
              const Icon = link.icon;
              const isActive = pathname === link.href || (link.href !== '/' && pathname.startsWith(link.href));
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    'flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition',
                    isActive
                      ? 'bg-slate-100 dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 font-semibold'
                      : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 hover:bg-slate-50 dark:hover:bg-zinc-800'
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {link.label}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Runtime Status & Theme Toggle Cluster */}
        <div className="flex items-center gap-2.5">
          {/* Provider Data Residency Status & Explainer Popover */}
          <div className="relative">
            <button
              type="button"
              data-testid="provider-status-badge"
              aria-expanded={showExplainer}
              aria-haspopup="dialog"
              onClick={() => setShowExplainer((prev) => !prev)}
              className={cn(
                'min-h-[32px] px-2.5 sm:px-3 py-1 rounded-full text-xs font-medium border flex items-center gap-1.5 sm:gap-2 transition cursor-pointer shadow-sm',
                privacyState.isLocal
                  ? 'border-emerald-200 dark:border-emerald-800/80 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/50'
                  : 'border-amber-200 dark:border-amber-800/80 bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/50'
              )}
              title={
                privacyState.isLocal
                  ? settings.provider === 'ollama'
                    ? ollamaOnline === null
                      ? 'Checking local model (127.0.0.1:11434)...'
                      : ollamaOnline
                      ? 'Local Ollama endpoint active (127.0.0.1:11434)'
                      : 'Ollama offline (Mock/Offline mode active)'
                    : 'Local endpoint active'
                  : `${privacyState.providerLabel} inference active`
              }
            >
              {privacyState.isLocal ? (
                settings.provider === 'ollama' ? (
                  ollamaOnline === null ? (
                    <span className="inline-block w-2 h-2 rounded-full bg-slate-400 animate-pulse" />
                  ) : ollamaOnline ? (
                    <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" />
                  ) : (
                    <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
                  )
                ) : (
                  <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" />
                )
              ) : (
                <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
              )}

              <span data-testid="data-residency-badge" className="font-semibold">
                {privacyState.badgeText}
              </span>
            </button>

            {/* Accessible Explainer Popover */}
            {showExplainer && (
              <>
                <div
                  className="fixed inset-0 z-30"
                  onClick={() => setShowExplainer(false)}
                  aria-hidden="true"
                />
                <div
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="privacy-explainer-title"
                  data-testid="privacy-explainer-popover"
                  className="absolute right-0 mt-2 w-72 sm:w-80 rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-lg z-40 text-left transition-all"
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2">
                      {privacyState.isLocal ? (
                        <ShieldCheck className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                      ) : (
                        <ShieldAlert className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0" />
                      )}
                      <h3
                        id="privacy-explainer-title"
                        data-testid="privacy-explainer-title"
                        className="text-sm font-semibold text-slate-900 dark:text-zinc-100"
                      >
                        {privacyState.explainerTitle}
                      </h3>
                    </div>
                    <button
                      type="button"
                      data-testid="close-explainer-btn"
                      onClick={() => setShowExplainer(false)}
                      aria-label="Close"
                      className="text-slate-400 hover:text-slate-600 dark:hover:text-zinc-300 p-1 rounded-md"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>

                  <p
                    data-testid="privacy-explainer-description"
                    className="text-xs text-slate-600 dark:text-zinc-400 mb-3 leading-relaxed"
                  >
                    {privacyState.explainerDescription}
                  </p>

                  <div className="rounded-lg bg-slate-50 dark:bg-zinc-800/60 p-2.5 mb-3 border border-slate-100 dark:border-zinc-800 text-xs space-y-1">
                    <div className="text-slate-500 dark:text-zinc-400 font-medium">Data Destination:</div>
                    <div
                      data-testid="privacy-destination-label"
                      className="font-mono text-slate-800 dark:text-zinc-200 break-all"
                    >
                      {privacyState.destinationLabel}
                    </div>
                  </div>

                  <div className="flex flex-col gap-2 pt-1 border-t border-slate-100 dark:border-zinc-800">
                    {!privacyState.isLocal && (
                      <button
                        type="button"
                        data-testid="switch-to-local-btn"
                        onClick={() => {
                          saveSettings({ provider: 'ollama', model: 'llama3.2' });
                          setShowExplainer(false);
                        }}
                        className="w-full min-h-[32px] px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white transition flex items-center justify-center gap-1.5 shadow-sm"
                      >
                        <Cpu className="w-3.5 h-3.5" />
                        Switch to Local (Ollama)
                      </button>
                    )}
                    <button
                      type="button"
                      data-testid="configure-settings-btn"
                      onClick={() => {
                        setShowExplainer(false);
                        setShowSettingsModal(true);
                      }}
                      className="w-full min-h-[32px] px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 text-slate-700 dark:text-zinc-300 transition flex items-center justify-center gap-1.5"
                    >
                      <Settings className="w-3.5 h-3.5" />
                      Configure in Settings
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Accessible Theme Toggle Button */}
          <button
            type="button"
            data-testid="theme-toggle-btn"
            aria-label={`Switch to ${effectiveResolvedTheme === 'dark' ? 'light' : 'dark'} mode`}
            title={`Current theme: ${effectiveTheme} (${effectiveResolvedTheme}). Click to switch.`}
            onClick={toggleTheme}
            suppressHydrationWarning
            className="w-9 h-9 flex items-center justify-center rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 text-slate-600 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-zinc-700 transition cursor-pointer shadow-sm"
          >
            {mounted && effectiveResolvedTheme === 'dark' ? (
              <Sun data-testid="theme-icon-sun" className="w-4 h-4 text-amber-400" />
            ) : (
              <Moon data-testid="theme-icon-moon" className="w-4 h-4 text-slate-700" />
            )}
          </button>
        </div>
      </div>

      {showSettingsModal && (
        <SettingsModal
          isOpen={showSettingsModal}
          onClose={() => setShowSettingsModal(false)}
          settings={settings}
          onSave={(updated) => {
            setSettings(updated);
            setShowSettingsModal(false);
          }}
        />
      )}
    </header>
  );
}
