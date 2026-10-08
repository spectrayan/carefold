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

import React, { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  HeartHandshake,
  LayoutGrid,
  Library,
  MessageSquare,
  Menu,
  Sun,
  Moon,
  ShieldCheck,
  ShieldAlert,
  X,
  Cpu,
  Settings,
  Sparkles,
  Activity,
  Shield,
  LogOut
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
import { useAuth } from '@/lib/auth';

export function Navbar() {
  const pathname = usePathname();
  const { user, isAuthenticated, isAdmin, authProvider, allowRegistration, needsAdminSetup, logout } = useAuth();
  const [ollamaOnline, setOllamaOnline] = useState<boolean | null>(null);
  const [settings, setSettings] = useState<CarefoldUserSettings>(DEFAULT_USER_SETTINGS);
  const [showExplainer, setShowExplainer] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [settingsModalTab, setSettingsModalTab] = useState<'settings' | 'diagnostics' | 'memory' | 'security'>('settings');
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const toggleButtonRef = useRef<HTMLButtonElement>(null);
  const mobileNavRef = useRef<HTMLElement>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  const openSettingsModal = (tab: 'settings' | 'diagnostics' | 'memory' | 'security' = 'settings') => {
    setSettingsModalTab(tab);
    setShowSettingsModal(true);
  };

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

  // Auto-close mobile navigation and user menu on route change
  useEffect(() => {
    setIsMobileOpen(false);
    setShowUserMenu(false);
  }, [pathname]);

  // Auto-close mobile navigation on viewport resize to >= 640px (sm breakpoint)
  useEffect(() => {
    if (!isMobileOpen) return;
    const handleResize = () => {
      if (window.innerWidth >= 640) {
        setIsMobileOpen(false);
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [isMobileOpen]);

  // Handle Escape key and focus trap when mobile navigation is open
  useEffect(() => {
    if (!isMobileOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setIsMobileOpen(false);
        toggleButtonRef.current?.focus();
        return;
      }

      if (e.key === 'Tab') {
        const focusableElements: HTMLElement[] = [];
        if (toggleButtonRef.current) focusableElements.push(toggleButtonRef.current);
        if (mobileNavRef.current) {
          const interactive = mobileNavRef.current.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
          );
          focusableElements.push(...Array.from(interactive));
        }

        if (focusableElements.length === 0) return;

        const first = focusableElements[0];
        const last = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first || !focusableElements.includes(document.activeElement as HTMLElement)) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last || !focusableElements.includes(document.activeElement as HTMLElement)) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isMobileOpen]);

  const navLinks = [
    { href: '/', label: 'Marketplace', icon: LayoutGrid },
    { href: '/skills', label: 'Skills', icon: Sparkles },
    { href: '/library', label: 'Library', icon: Library },
    { href: '/activity', label: 'Activity', icon: Activity },
    { href: '/chat', label: 'Chat', icon: MessageSquare },
    ...(isAdmin ? [{ href: '/admin', label: 'Admin', icon: Shield }] : [])
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
              onClick={() => {
                setIsMobileOpen(false);
                setShowExplainer((prev) => !prev);
              }}
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

          {/* User Profile & Auth Integration */}
          {authProvider === 'disabled' ? (
            <div
              data-testid="local-steward-badge"
              className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border border-purple-200/80 dark:border-purple-800/80 bg-purple-50 dark:bg-purple-950/40 text-purple-800 dark:text-purple-300 shadow-sm"
              title="Single-user local steward mode"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />
              <span className="font-semibold">Local Steward</span>
            </div>
          ) : isAuthenticated && user ? (
            <div className="relative hidden sm:block" ref={userMenuRef}>
              <button
                type="button"
                data-testid="user-profile-button"
                aria-expanded={showUserMenu}
                aria-haspopup="menu"
                aria-label="User profile menu"
                onClick={() => setShowUserMenu((prev) => !prev)}
                className="flex items-center gap-2 px-2.5 py-1 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-700 transition cursor-pointer text-xs shadow-sm"
              >
                <div className="w-6 h-6 rounded-full bg-emerald-600 text-white font-bold flex items-center justify-center text-[10px]">
                  {user.full_name
                    ? user.full_name.split(' ').map((n) => n[0]).slice(0, 2).join('').toUpperCase()
                    : user.username.slice(0, 2).toUpperCase()}
                </div>
                <span className="font-semibold text-slate-800 dark:text-zinc-200 max-w-[110px] truncate">
                  {user.full_name || user.username}
                </span>
                <span
                  data-testid="user-nav-role-badge"
                  className={cn(
                    'text-[10px] font-semibold px-1.5 py-0.5 rounded-full border',
                    user.role === 'admin'
                      ? 'border-purple-200 bg-purple-50 text-purple-700 dark:border-purple-900/60 dark:bg-purple-950/40 dark:text-purple-300'
                      : user.role === 'steward'
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300'
                      : 'border-slate-200 bg-slate-100 text-slate-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'
                  )}
                >
                  {user.role}
                </span>
              </button>

              {showUserMenu && (
                <>
                  <div
                    className="fixed inset-0 z-30"
                    onClick={() => setShowUserMenu(false)}
                    aria-hidden="true"
                  />
                  <div
                    role="menu"
                    data-testid="user-profile-dropdown"
                    className="absolute right-0 mt-2 w-56 rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-2 shadow-xl z-40 text-xs animate-in fade-in zoom-in-95"
                  >
                    <div className="px-3 py-2 border-b border-slate-100 dark:border-zinc-800 mb-1">
                      <div className="font-bold text-slate-900 dark:text-zinc-100 truncate">
                        {user.full_name || user.username}
                      </div>
                      <div className="text-[11px] text-slate-500 dark:text-zinc-400 font-mono truncate">
                        {user.email}
                      </div>
                    </div>

                    {isAdmin && (
                      <Link
                        href="/admin"
                        role="menuitem"
                        data-testid="nav-dropdown-admin-link"
                        onClick={() => setShowUserMenu(false)}
                        className="flex items-center gap-2 px-3 py-2 rounded-lg text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition font-medium"
                      >
                        <Shield className="w-4 h-4 text-purple-600 dark:text-purple-400" />
                        <span>Admin Console</span>
                      </Link>
                    )}

                    <button
                      type="button"
                      role="menuitem"
                      data-testid="nav-dropdown-settings-btn"
                      onClick={() => {
                        setShowUserMenu(false);
                        openSettingsModal('security');
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition font-medium text-left cursor-pointer"
                    >
                      <Settings className="w-4 h-4 text-slate-500" />
                      <span>Account & Security</span>
                    </button>

                    <div className="pt-1 mt-1 border-t border-slate-100 dark:border-zinc-800">
                      <button
                        type="button"
                        role="menuitem"
                        data-testid="nav-dropdown-sign-out-btn"
                        onClick={() => {
                          setShowUserMenu(false);
                          logout();
                        }}
                        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition font-semibold text-left cursor-pointer"
                      >
                        <LogOut className="w-4 h-4" />
                        <span>Sign Out</span>
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          ) : needsAdminSetup ? (
            <div className="hidden sm:flex items-center gap-1.5">
              <Link
                href="/register?mode=admin-setup"
                data-testid="nav-admin-setup-btn"
                className="px-3 py-1.5 text-xs font-semibold rounded-xl text-white bg-purple-600 hover:bg-purple-700 transition shadow-sm flex items-center gap-1.5"
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>Admin Setup</span>
              </Link>
            </div>
          ) : (
            <div className="hidden sm:flex items-center gap-1.5">
              <Link
                href="/login"
                data-testid="nav-sign-in-btn"
                className="px-3 py-1.5 text-xs font-semibold rounded-xl text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
              >
                Sign In
              </Link>
              {allowRegistration && (
                <Link
                  href="/register"
                  data-testid="nav-register-btn"
                  className="px-3 py-1.5 text-xs font-semibold rounded-xl text-white bg-emerald-600 hover:bg-emerald-700 transition shadow-sm"
                >
                  Register
                </Link>
              )}
            </div>
          )}

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

          {/* Mobile Menu Toggle Button */}
          <button
            ref={toggleButtonRef}
            type="button"
            data-testid="mobile-menu-toggle"
            aria-label="Toggle navigation menu"
            aria-expanded={isMobileOpen}
            aria-controls="mobile-navigation"
            onClick={() => {
              setShowExplainer(false);
              setIsMobileOpen((prev) => !prev);
            }}
            className="sm:hidden w-9 h-9 flex items-center justify-center rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 text-slate-600 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-zinc-700 transition cursor-pointer shadow-sm shrink-0"
          >
            {isMobileOpen ? (
              <X className="w-4 h-4" />
            ) : (
              <Menu className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Mobile Backdrop */}
      {isMobileOpen && (
        <div
          className="fixed inset-0 bg-black/20 dark:bg-black/40 z-30 sm:hidden"
          onClick={() => setIsMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Mobile Navigation Panel */}
      {isMobileOpen && (
        <nav
          id="mobile-navigation"
          ref={mobileNavRef}
          data-testid="mobile-navigation"
          aria-label="Mobile navigation"
          className="relative z-40 sm:hidden border-t border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-4 py-3 space-y-1 shadow-lg"
        >
          {navLinks.map((link) => {
            const Icon = link.icon;
            const isActive = pathname === link.href || (link.href !== '/' && pathname.startsWith(link.href));
            return (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setIsMobileOpen(false)}
                className={cn(
                  'flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition min-h-[44px]',
                  isActive
                    ? 'bg-slate-100 dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 font-semibold'
                    : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 hover:bg-slate-50 dark:hover:bg-zinc-800'
                )}
              >
                <Icon className="w-5 h-5 shrink-0" />
                <span>{link.label}</span>
              </Link>
            );
          })}

          {/* Mobile Auth / Profile Section */}
          <div className="pt-2 mt-2 border-t border-slate-200 dark:border-zinc-800 space-y-1">
            {authProvider === 'disabled' ? (
              <div className="px-3.5 py-2 text-xs font-semibold text-purple-700 dark:text-purple-300 flex items-center gap-2">
                <ShieldCheck className="w-4 h-4" />
                <span>Local Steward Active</span>
              </div>
            ) : isAuthenticated && user ? (
              <div className="space-y-1">
                <div className="px-3.5 py-2 text-xs font-semibold text-slate-800 dark:text-zinc-200 flex items-center justify-between">
                  <span>{user.full_name || user.username}</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full border border-slate-200 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 capitalize">
                    {user.role}
                  </span>
                </div>
                {isAdmin && (
                  <Link
                    href="/admin"
                    onClick={() => setIsMobileOpen(false)}
                    className="flex items-center gap-3 px-3.5 py-2 rounded-lg text-sm font-medium text-purple-700 dark:text-purple-300 hover:bg-purple-50 dark:hover:bg-purple-950/40"
                  >
                    <Shield className="w-4 h-4" />
                    <span>Admin Console</span>
                  </Link>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setIsMobileOpen(false);
                    openSettingsModal('security');
                  }}
                  className="w-full flex items-center gap-3 px-3.5 py-2 rounded-lg text-sm font-medium text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 text-left"
                >
                  <Settings className="w-4 h-4" />
                  <span>Account & Security</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setIsMobileOpen(false);
                    logout();
                  }}
                  className="w-full flex items-center gap-3 px-3.5 py-2 rounded-lg text-sm font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-left"
                >
                  <LogOut className="w-4 h-4" />
                  <span>Sign Out</span>
                </button>
              </div>
            ) : needsAdminSetup ? (
              <div className="pt-1">
                <Link
                  href="/register?mode=admin-setup"
                  onClick={() => setIsMobileOpen(false)}
                  data-testid="mobile-admin-setup-link"
                  className="w-full py-2 text-center text-xs font-semibold rounded-lg bg-purple-600 hover:bg-purple-700 text-white shadow-sm flex items-center justify-center gap-1.5"
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>Set Up Administrator</span>
                </Link>
              </div>
            ) : (
              <div className="flex items-center gap-2 pt-1">
                <Link
                  href="/login"
                  onClick={() => setIsMobileOpen(false)}
                  data-testid="mobile-sign-in-link"
                  className="flex-1 py-2 text-center text-xs font-semibold rounded-lg border border-slate-300 dark:border-zinc-700 text-slate-700 dark:text-zinc-300 hover:bg-slate-50 dark:hover:bg-zinc-800"
                >
                  Sign In
                </Link>
                {allowRegistration && (
                  <Link
                    href="/register"
                    onClick={() => setIsMobileOpen(false)}
                    data-testid="mobile-register-link"
                    className="flex-1 py-2 text-center text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm"
                  >
                    Register
                  </Link>
                )}
              </div>
            )}
          </div>
        </nav>
      )}

      {showSettingsModal && (
        <SettingsModal
          isOpen={showSettingsModal}
          onClose={() => setShowSettingsModal(false)}
          settings={settings}
          initialTab={settingsModalTab}
          onSave={(updated) => {
            setSettings(updated);
            setShowSettingsModal(false);
          }}
        />
      )}
    </header>
  );
}
