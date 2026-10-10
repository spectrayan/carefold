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
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Home,
  MessageSquare,
  BookOpen,
  Activity,
  Sparkles,
  Users,
  Settings,
  Shield,
  Info,
  Cpu,
  ShieldCheck,
  ShieldAlert,
  ChevronsUpDown,
  Sun,
  Moon,
  X,
  PanelLeftClose,
  PanelLeft,
  LogIn,
  LogOut
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Avatar, type MemberColorSlot } from '@/components/ui/Avatar';
import { ProfileSwitcher } from '@/components/layout/ProfileSwitcher';
import { useAuth, DEFAULT_STEWARD_USER } from '@/lib/auth';
import { useOptionalTheme } from '@/components/ThemeProvider';
import { getHouseholdProfile } from '@/lib/familyProfiles';
import {
  DEFAULT_USER_SETTINGS,
  loadSettings,
  getProviderPrivacyState,
  type CarefoldUserSettings
} from '@/lib/settings';

export interface CareProfileRailInfo {
  id: string;
  name: string;
  shortName?: string;
  relationship?: string;
  age?: number;
  role?: string;
  colorSlot?: MemberColorSlot;
}

export interface AppRailProps extends React.HTMLAttributes<HTMLElement> {
  activeProfile?: CareProfileRailInfo;
  counts?: {
    chat?: number;
    library?: number;
    family?: number;
    helpers?: number;
    agents?: number;
  };
  isCollapsed?: boolean;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onOpenProfileSwitcher?: () => void;
}

export function AppRail({
  activeProfile: activeProfileProp,
  counts,
  isCollapsed: isCollapsedProp,
  collapsed: collapsedProp,
  onToggleCollapse,
  onOpenProfileSwitcher,
  className,
  ...props
}: AppRailProps) {
  const [internalCollapsed, setInternalCollapsed] = useState<boolean>(false);

  const isControlled = isCollapsedProp !== undefined || collapsedProp !== undefined;
  const isCollapsed = isControlled ? (isCollapsedProp ?? collapsedProp ?? false) : internalCollapsed;

  const handleToggleCollapse = () => {
    if (onToggleCollapse) {
      onToggleCollapse();
    } else {
      setInternalCollapsed((prev) => {
        const next = !prev;
        try {
          localStorage.setItem('carefold_rail_collapsed', String(next));
        } catch {}
        return next;
      });
    }
  };

  const pathname = usePathname();
  const { user, isAdmin, logout } = useAuth();
  const isRealUserSignedIn = Boolean(user && user.id !== DEFAULT_STEWARD_USER.id);
  const themeContext = useOptionalTheme();
  const [settings, setSettings] = useState<CarefoldUserSettings>(DEFAULT_USER_SETTINGS);
  const [_ollamaOnline, setOllamaOnline] = useState<boolean | null>(null);
  const [showPrivacyExplainer, setShowPrivacyExplainer] = useState(false);
  const [isProfileSwitcherOpen, setIsProfileSwitcherOpen] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem('carefold_rail_collapsed') === 'true') {
        setInternalCollapsed(true);
      }
    } catch {}
  }, []);

  // Derive active profile dynamically from household store or URL pathname
  const derivedProfile: CareProfileRailInfo = React.useMemo(() => {
    if (activeProfileProp) return activeProfileProp;
    const match = pathname.match(/^\/p\/([^/]+)/);
    const profileId = match ? match[1] : 'me';

    const household = getHouseholdProfile(profileId);
    if (household) {
      return {
        id: household.id,
        name: household.name,
        shortName: household.shortName || household.name.split(' ')[0],
        relationship: household.relationship,
        age: household.age,
        role: household.role === 'self' ? 'Personal care' : 'You manage',
        colorSlot: household.colorSlot
      };
    }

    return {
      id: profileId,
      name: profileId === 'me' ? 'Me' : profileId,
      shortName: profileId === 'me' ? 'Me' : profileId,
      relationship: 'Self',
      role: 'Personal care',
      colorSlot: 1
    };
  }, [activeProfileProp, pathname]);

  useEffect(() => {
    const loaded = loadSettings();
    setSettings(loaded);

    if (loaded.provider === 'ollama') {
      fetch('/api/v1/health')
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (data?.modelReachable !== undefined) {
            setOllamaOnline(Boolean(data.modelReachable));
          } else if (data?.workspace) {
            setOllamaOnline(true);
          } else {
            setOllamaOnline(false);
          }
        })
        .catch(() => setOllamaOnline(false));
    }
  }, []);

  const privacyState = getProviderPrivacyState(settings);

  // Build sectioned navigation items
  const caringNavItems = [
    {
      href: `/p/${derivedProfile.id}`,
      label: 'Home',
      icon: Home,
      exact: true
    },
    {
      href: `/p/${derivedProfile.id}/chat`,
      label: 'Chats',
      icon: MessageSquare,
      badge: counts?.chat
    },
    {
      href: `/p/${derivedProfile.id}/library`,
      label: 'Library',
      icon: BookOpen,
      badge: counts?.library
    },
    {
      href: `/p/${derivedProfile.id}/activity`,
      label: 'Activity',
      icon: Activity
    }
  ];

  const householdNavItems = [
    {
      href: '/agents',
      label: 'Agents',
      icon: Sparkles,
      badge: counts?.agents ?? counts?.helpers,
      aliasPrefixes: ['/agents', '/helpers', '/skills']
    },
    {
      href: '/family',
      label: 'Family & Profiles',
      icon: Users,
      badge: counts?.family
    },
    {
      href: '/settings',
      label: 'Settings',
      icon: Settings,
      aliasPrefixes: ['/settings']
    },
    ...(isAdmin
      ? [
          {
            href: '/admin',
            label: 'Admin Console',
            icon: Shield
          }
        ]
      : [])
  ];

  // Helper for determining active route
  const isItemActive = (item: { href: string; exact?: boolean; aliasPrefixes?: string[] }) => {
    if (item.exact) {
      return pathname === item.href;
    }
    if (pathname === item.href) return true;
    if (item.aliasPrefixes?.some((prefix) => pathname.startsWith(prefix))) return true;
    return pathname.startsWith(`${item.href}/`);
  };

  // Determine width based on isCollapsed prop
  const railWidthClass =
    isCollapsed === true
      ? 'w-[72px]'
      : isCollapsed === false
      ? 'w-64'
      : 'w-[72px] xl:w-64';

  const isAlwaysCollapsed = isCollapsed === true;
  const isAlwaysExpanded = isCollapsed === false;

  return (
    <aside
      role="navigation"
      aria-label="Primary application navigation"
      data-testid="app-rail"
      className={cn(
        'sticky top-0 h-screen shrink-0 flex flex-col bg-[var(--cf-rail)] border-r border-[var(--cf-border)] p-3 transition-all duration-200 z-[var(--cf-z-rail)] overflow-y-auto overflow-x-hidden',
        railWidthClass,
        className
      )}
      {...props}
    >
      {/* Brand Header */}
      <div
        className={cn(
          'flex items-center mb-2 min-h-[44px]',
          isAlwaysCollapsed
            ? 'justify-center px-0 py-2'
            : isAlwaysExpanded
            ? 'justify-between px-2 py-2'
            : 'justify-center xl:justify-between px-0 xl:px-2 py-2'
        )}
      >
        <div
          className={cn(
            'items-center gap-2.5 min-w-0',
            isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'flex' : 'hidden xl:flex'
          )}
        >
          <div
            className="w-[30px] h-[30px] shrink-0 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center text-white font-bold text-sm shadow-sm ring-1 ring-white/20"
            aria-hidden="true"
          >
            C
          </div>
          <span className="font-bold text-lg text-[var(--cf-fg)] tracking-tight">Carefold</span>
          <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)] border border-[var(--cf-border)]">
            Local
          </span>
        </div>
        <button
          type="button"
          onClick={handleToggleCollapse}
          aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={cn(
            'min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface)] transition-all shrink-0 focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]',
            !isAlwaysCollapsed && (isAlwaysExpanded ? 'ml-auto' : 'xl:ml-auto')
          )}
        >
          {isCollapsed ? <PanelLeft className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
        </button>
      </div>

      {/* Profile Card Trigger */}
      <div className="mb-4">
        {/* Expanded Mode Profile Card */}
        <button
          type="button"
          onClick={onOpenProfileSwitcher ? onOpenProfileSwitcher : () => setIsProfileSwitcherOpen(true)}
          aria-haspopup="listbox"
          aria-label={`Switch person. Current: ${derivedProfile.name}`}
          className={cn(
            'w-full items-center gap-2.5 p-2.5 rounded-xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm text-left hover:bg-[var(--cf-surface-2)] hover:border-[var(--cf-border-strong)] transition-all min-h-[56px] focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]',
            isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'flex' : 'hidden xl:flex'
          )}
        >
          <Avatar
            name={derivedProfile.name}
            colorSlot={derivedProfile.colorSlot || 1}
            size="md"
            className="shrink-0"
          />
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-sm font-semibold text-[var(--cf-fg)] truncate">
              {derivedProfile.name}
            </span>
            <span className="text-xs text-[var(--cf-fg-subtle)] truncate">
              <span>{derivedProfile.relationship || 'Self'}</span>
              {derivedProfile.age ? ` · ${derivedProfile.age}` : ''}
              {derivedProfile.role ? ` · ${derivedProfile.role}` : ''}
            </span>
          </div>
          <ChevronsUpDown className="w-4 h-4 text-[var(--cf-fg-subtle)] shrink-0" />
        </button>

        {/* Collapsed Mode Avatar Button */}
        <button
          type="button"
          onClick={onOpenProfileSwitcher ? onOpenProfileSwitcher : () => setIsProfileSwitcherOpen(true)}
          aria-haspopup="listbox"
          aria-label={`Switch person. Current: ${derivedProfile.name}`}
          title={`Switch person. Current: ${derivedProfile.name}`}
          className={cn(
            'w-11 h-11 mx-auto flex items-center justify-center rounded-xl bg-[var(--cf-surface)] border border-[var(--cf-border)] hover:bg-[var(--cf-surface-2)] transition-all min-h-[44px] min-w-[44px]',
            isAlwaysCollapsed ? 'flex' : isAlwaysExpanded ? 'hidden' : 'flex xl:hidden'
          )}
        >
          <Avatar
            name={derivedProfile.name}
            colorSlot={derivedProfile.colorSlot || 1}
            size="sm"
          />
        </button>

        <ProfileSwitcher
          renderTrigger={false}
          isOpen={isProfileSwitcherOpen}
          onOpenChange={setIsProfileSwitcherOpen}
          activeProfileId={derivedProfile.id}
          className="hidden"
        />
      </div>

      {/* Nav Section 1: "Caring for [Person]" */}
      <nav aria-label={`Caring for ${derivedProfile.shortName || derivedProfile.name}`} className="flex flex-col gap-1 mb-4">
        <div
          className={cn(
            'text-[11px] font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] px-2.5 pt-1 pb-1 truncate',
            isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'block' : 'hidden xl:block'
          )}
        >
          Caring for {derivedProfile.shortName || derivedProfile.name}
        </div>
        {caringNavItems.map((item) => {
          const Icon = item.icon;
          const active = isItemActive(item);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? 'page' : undefined}
              title={item.label}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all min-h-[44px] focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]',
                isAlwaysCollapsed
                  ? 'justify-center px-0'
                  : isAlwaysExpanded
                  ? 'justify-start'
                  : 'justify-center xl:justify-start xl:px-3',
                active
                  ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] font-semibold shadow-sm'
                  : 'text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface)]'
              )}
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span
                className={cn(
                  'truncate',
                  isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'inline' : 'hidden xl:inline'
                )}
              >
                {item.label}
              </span>
              {item.badge !== undefined && item.badge > 0 && (
                <span
                  className={cn(
                    'ml-auto text-xs px-1.5 py-0.2 rounded-full font-semibold',
                    isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'inline-block' : 'hidden xl:inline-block',
                    active
                      ? 'bg-[var(--cf-surface)] text-[var(--cf-primary-soft-fg)]'
                      : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)]'
                  )}
                >
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Nav Section 2: "Household" */}
      <nav aria-label="Household" className="flex flex-col gap-1 mb-4">
        <div
          className={cn(
            'text-[11px] font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] px-2.5 pt-1 pb-1',
            isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'block' : 'hidden xl:block'
          )}
        >
          Household
        </div>
        {householdNavItems.map((item) => {
          const Icon = item.icon;
          const active = isItemActive(item);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? 'page' : undefined}
              title={item.label}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all min-h-[44px] focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]',
                isAlwaysCollapsed
                  ? 'justify-center px-0'
                  : isAlwaysExpanded
                  ? 'justify-start'
                  : 'justify-center xl:justify-start xl:px-3',
                active
                  ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] font-semibold shadow-sm'
                  : 'text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface)]'
              )}
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span
                className={cn(
                  'truncate',
                  isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'inline' : 'hidden xl:inline'
                )}
              >
                {item.label}
              </span>
              {item.badge !== undefined && item.badge > 0 && (
                <span
                  className={cn(
                    'ml-auto text-xs px-1.5 py-0.2 rounded-full font-semibold',
                    isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'inline-block' : 'hidden xl:inline-block',
                    active
                      ? 'bg-[var(--cf-surface)] text-[var(--cf-primary-soft-fg)]'
                      : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)]'
                  )}
                >
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Spacer to push footer to bottom */}
      <div className="flex-1 min-h-[16px]" />

      {/* Quiet Safety Disclaimer Note */}
      <div
        className={cn(
          'mb-3 px-2 text-xs text-[var(--cf-fg-subtle)] flex items-start gap-2 leading-relaxed',
          isAlwaysCollapsed ? 'justify-center' : isAlwaysExpanded ? 'justify-start' : 'justify-center xl:justify-start'
        )}
      >
        <Info className="w-3.5 h-3.5 shrink-0 mt-0.5 text-[var(--cf-fg-subtle)]" />
        <span
          className={cn(
            isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'inline' : 'hidden xl:inline'
          )}
        >
          Carefold helps you prepare. It doesn't diagnose. Emergency? Call 911.
        </span>
      </div>

      {/* Data Residency & Privacy Status Card */}
      <div className="relative mb-3">
        {/* Expanded Card */}
        <button
          type="button"
          data-testid="provider-status-badge"
          aria-expanded={showPrivacyExplainer}
          aria-haspopup="dialog"
          onClick={() => setShowPrivacyExplainer((prev) => !prev)}
          className={cn(
            'w-full text-left p-2.5 rounded-xl border transition-all shadow-sm min-h-[44px] flex items-center gap-2.5 focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]',
            isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'flex' : 'hidden xl:flex',
            privacyState.isLocal
              ? 'bg-[var(--cf-surface)] border-emerald-200 dark:border-emerald-900/60 text-[var(--cf-fg)] hover:border-emerald-400'
              : 'bg-[var(--cf-surface)] border-amber-200 dark:border-amber-900/60 text-[var(--cf-fg)] hover:border-amber-400'
          )}
        >
          <div
            className={cn(
              'w-7 h-7 rounded-lg flex items-center justify-center shrink-0',
              privacyState.isLocal
                ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300'
                : 'bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300'
            )}
          >
            {privacyState.isLocal ? <Cpu className="w-4 h-4" /> : <ShieldAlert className="w-4 h-4" />}
          </div>
          <div className="flex flex-col min-w-0 flex-1">
            <span
              data-testid="data-residency-badge"
              className="text-xs font-semibold text-[var(--cf-fg)] truncate"
            >
              {privacyState.badgeText}
            </span>
            <span className="text-[11px] text-[var(--cf-fg-subtle)] truncate">
              {privacyState.isLocal ? 'Ollama · llama3.2 · on-device' : privacyState.providerLabel}
            </span>
          </div>
        </button>

        {/* Collapsed Icon-Only Button */}
        <button
          type="button"
          data-testid="provider-status-badge-collapsed"
          aria-expanded={showPrivacyExplainer}
          aria-haspopup="dialog"
          onClick={() => setShowPrivacyExplainer((prev) => !prev)}
          title={privacyState.badgeText}
          className={cn(
            'w-11 h-11 mx-auto flex items-center justify-center rounded-xl border bg-[var(--cf-surface)] transition-all min-h-[44px] min-w-[44px]',
            isAlwaysCollapsed ? 'flex' : isAlwaysExpanded ? 'hidden' : 'flex xl:hidden',
            privacyState.isLocal
              ? 'border-emerald-200 dark:border-emerald-900/60 text-emerald-700 dark:text-emerald-300'
              : 'border-amber-200 dark:border-amber-900/60 text-amber-700 dark:text-amber-300'
          )}
        >
          {privacyState.isLocal ? <Cpu className="w-4 h-4" /> : <ShieldAlert className="w-4 h-4" />}
        </button>

        {/* Privacy Explainer Popover */}
        {showPrivacyExplainer && (
          <>
            <div
              className="fixed inset-0 z-30"
              onClick={() => setShowPrivacyExplainer(false)}
              aria-hidden="true"
            />
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby="rail-privacy-title"
              data-testid="privacy-explainer-popover"
              className="absolute bottom-full left-0 mb-2 w-72 rounded-2xl border border-[var(--cf-border)] bg-[var(--cf-surface)] p-4 shadow-xl z-40 text-left"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  {privacyState.isLocal ? (
                    <ShieldCheck className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  ) : (
                    <ShieldAlert className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0" />
                  )}
                  <h3
                    id="rail-privacy-title"
                    data-testid="data-residency-destination"
                    className="text-sm font-semibold text-[var(--cf-fg)]"
                  >
                    {privacyState.explainerTitle}
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={() => setShowPrivacyExplainer(false)}
                  className="text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] p-1 rounded-md"
                  aria-label="Close"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <p
                data-testid="data-residency-description"
                className="text-xs text-[var(--cf-fg-muted)] leading-relaxed mb-3"
              >
                {privacyState.explainerDescription}
              </p>
              <Link
                href="/settings/privacy"
                onClick={() => setShowPrivacyExplainer(false)}
                className="text-xs font-semibold text-[var(--cf-primary-hover)] hover:underline inline-flex items-center gap-1"
              >
                Configure privacy & data settings →
              </Link>
            </div>
          </>
        )}
      </div>

      {/* User Row, Auth Actions & Theme Switcher */}
      <div
        className={cn(
          'pt-2 border-t border-[var(--cf-border)] flex items-center min-h-[44px]',
          isAlwaysCollapsed
            ? 'flex-col justify-center gap-2 px-0'
            : isAlwaysExpanded
            ? 'flex-row justify-between gap-1.5'
            : 'flex-col xl:flex-row justify-center xl:justify-between gap-2 xl:gap-1.5'
        )}
      >
        {/* Expanded User Details */}
        <div
          className={cn(
            'items-center gap-2.5 min-w-0 flex-1',
            isAlwaysCollapsed ? 'hidden' : isAlwaysExpanded ? 'flex' : 'hidden xl:flex'
          )}
        >
          <Avatar
            name={user?.full_name || user?.username || 'User'}
            colorSlot={1}
            size="sm"
            className="shrink-0"
          />
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-sm font-semibold text-[var(--cf-fg)] truncate">
              {user?.full_name || user?.username || 'User'}
            </span>
            <span className="text-xs text-[var(--cf-fg-subtle)] truncate">
              {isRealUserSignedIn ? `Signed in · ${user?.role || 'user'}` : 'Local mode · single user'}
            </span>
          </div>
        </div>

        {/* Collapsed Avatar Icon */}
        <div className={cn('mx-auto shrink-0', isAlwaysCollapsed ? 'block' : isAlwaysExpanded ? 'hidden' : 'block xl:hidden')}>
          <Avatar
            name={user?.full_name || user?.username || 'User'}
            colorSlot={1}
            size="xs"
          />
        </div>

        {/* Auth Action: Sign Out or Sign In */}
        {isRealUserSignedIn ? (
          <button
            type="button"
            onClick={async () => {
              await logout();
            }}
            aria-label="Sign out"
            title="Sign out"
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-rose-600 hover:bg-[var(--cf-surface)] transition-all shrink-0 focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
          >
            <LogOut className="w-4 h-4" />
          </button>
        ) : (
          <Link
            href="/login"
            aria-label="Sign in"
            title="Sign in"
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-emerald-600 hover:bg-[var(--cf-surface)] transition-all shrink-0 focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
          >
            <LogIn className="w-4 h-4" />
          </Link>
        )}

        {/* Theme Toggle Button (44×44px touch target) */}
        <button
          type="button"
          onClick={() => themeContext?.toggleTheme()}
          aria-label="Switch to light or dark mode"
          title="Switch to light or dark mode"
          className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface)] transition-all shrink-0 focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
        >
          <Sun className="hidden dark:block w-4 h-4 text-amber-400" />
          <Moon className="block dark:hidden w-4 h-4 text-slate-600 dark:text-zinc-300" />
        </button>
      </div>
    </aside>
  );
}
