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

'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ChevronDown, Search, Settings, Sun, Moon, LogIn, LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Avatar, type MemberColorSlot } from '@/components/ui/Avatar';
import { CarefoldLogo } from '@/components/ui/CarefoldLogo';
import { ProfileSwitcher } from '@/components/layout/ProfileSwitcher';
import { useOptionalTheme } from '@/components/ThemeProvider';
import { useAuth } from '@/lib/auth';
import { getHouseholdProfile, HOUSEHOLD_PROFILES_CHANGED_EVENT } from '@/lib/familyProfiles';
import { profilePath } from '@/lib/routes';
import { useI18n } from '@/i18n';

export interface MobileTopBarProps extends React.HTMLAttributes<HTMLElement> {
  activeProfile?: {
    id: string;
    name: string;
    shortName?: string;
    colorSlot?: MemberColorSlot;
  };
  onOpenProfileSwitcher?: () => void;
  onProfileClick?: () => void;
  onOpenSearch?: () => void;
}

export function MobileTopBar({
  activeProfile: activeProfileProp,
  onOpenProfileSwitcher,
  onProfileClick,
  onOpenSearch,
  className,
  ...props
}: MobileTopBarProps) {
  const pathname = usePathname();
  const themeContext = useOptionalTheme();
  const { isAuthenticated, user, logout } = useAuth();
  const { t } = useI18n();
  const [isProfileSwitcherOpen, setIsProfileSwitcherOpen] = React.useState(false);
  const [hasMounted, setHasMounted] = React.useState(false);
  const [profileRev, setProfileRev] = React.useState(0);

  React.useEffect(() => {
    setHasMounted(true);
    const handleProfilesChanged = () => setProfileRev((r) => r + 1);
    window.addEventListener(HOUSEHOLD_PROFILES_CHANGED_EVENT, handleProfilesChanged);
    return () => {
      window.removeEventListener(HOUSEHOLD_PROFILES_CHANGED_EVENT, handleProfilesChanged);
    };
  }, []);

  // Derive active profile dynamically from household store or URL pathname
  const derivedProfile = React.useMemo(() => {
    if (activeProfileProp) return activeProfileProp;
    const match = pathname.match(/^\/p\/([^/]+)/);
    const profileId = match ? match[1] : 'me';

    const userFallbackName = hasMounted
      ? (user?.full_name?.trim() || user?.username?.trim() || 'Me')
      : 'Me';
    const userShortName = hasMounted
      ? (user?.full_name ? user.full_name.trim().split(/\s+/)[0] : (user?.username || 'Me'))
      : 'Me';

    const household = hasMounted ? getHouseholdProfile(profileId) : null;
    if (household) {
      const isSelf = household.role === 'self' || household.relationship?.toLowerCase() === 'self' || profileId === 'me';
      const resolvedName = (isSelf && (household.name === 'Me' || !household.name)) ? userFallbackName : household.name;
      const resolvedShortName = household.shortName || (resolvedName ? resolvedName.split(/\s+/)[0] : userShortName);
      return {
        id: household.id,
        name: resolvedName,
        shortName: resolvedShortName,
        colorSlot: (household.colorSlot || 1) as MemberColorSlot
      };
    }

    const isGenericId =
      !profileId ||
      profileId.toLowerCase() === 'me' ||
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(profileId);

    return {
      id: profileId,
      name: isGenericId ? userFallbackName : profileId,
      shortName: isGenericId ? userShortName : profileId,
      colorSlot: 1 as MemberColorSlot
    };
  }, [activeProfileProp, pathname, user, hasMounted, profileRev]);

  return (
    <header
      aria-label="Mobile header"
      className={cn(
        'h-14 shrink-0 flex items-center justify-between px-3.5 bg-[var(--cf-canvas)] border-b border-[var(--cf-border)] z-30 transition-colors',
        className
      )}
      {...props}
    >
      {/* Brand Logo Mark */}
      <Link
        href={profilePath(derivedProfile.id)}
        aria-label="Carefold Home"
        className="min-h-[44px] flex items-center gap-1.5 focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
      >
        <CarefoldLogo size={20} />
        <span className="hidden min-[380px]:inline font-bold text-sm text-[var(--cf-fg)] tracking-tight">{t('common.appName')}</span>
      </Link>

      {/* Profile Switcher Pill Trigger */}
      <button
        type="button"
        onClick={
          onOpenProfileSwitcher ||
          onProfileClick ||
          (() => setIsProfileSwitcherOpen(true))
        }
        aria-haspopup="dialog"
        aria-label={`Switch care profile. Current: ${derivedProfile.name}`}
        suppressHydrationWarning
        className="flex items-center gap-1.5 min-[380px]:gap-2 h-10 px-2 min-[380px]:px-2.5 py-1 rounded-full bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm hover:bg-[var(--cf-surface-2)] transition-all min-h-[44px] focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)] shrink-0"
      >
        <Avatar
          name={derivedProfile.name}
          colorSlot={derivedProfile.colorSlot || 1}
          size="xs"
        />
        <span
          suppressHydrationWarning
          className="text-xs min-[380px]:text-sm font-semibold text-[var(--cf-fg)] truncate max-w-[80px] min-[380px]:max-w-[120px]"
        >
          {derivedProfile.shortName || derivedProfile.name.split(' ')[0]}
        </span>
        <ChevronDown className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)] shrink-0" />
      </button>

      <ProfileSwitcher
        renderTrigger={false}
        isOpen={isProfileSwitcherOpen}
        onOpenChange={setIsProfileSwitcherOpen}
        activeProfileId={derivedProfile.id}
        mode="mobile-sheet"
        className="hidden"
      />

      {/* Action Cluster (Search / Settings / Auth / Theme) */}
      <div className="flex items-center gap-0.5 min-[380px]:gap-1 shrink-0">
        {onOpenSearch ? (
          <button
            type="button"
            onClick={onOpenSearch}
            aria-label={t('common.search')}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface)] transition-all focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
          >
            <Search className="w-4 h-4" />
          </button>
        ) : null}

        <Link
          href="/settings"
          aria-label="Open settings"
          className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface)] transition-all focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
        >
          <Settings className="w-4 h-4" />
        </Link>

        {/* Auth action: Sign out or Sign in */}
        {isAuthenticated ? (
          <button
            type="button"
            onClick={async () => {
              await logout();
            }}
            aria-label={t('common.signOut')}
            title={t('common.signOut')}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-rose-600 hover:bg-[var(--cf-surface)] transition-all focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
          >
            <LogOut className="w-4 h-4" />
          </button>
        ) : (
          <Link
            href="/login"
            aria-label={t('common.signIn')}
            title={t('common.signIn')}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-emerald-600 hover:bg-[var(--cf-surface)] transition-all focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
          >
            <LogIn className="w-4 h-4" />
          </Link>
        )}

        {/* Accessible Theme Toggle Button */}
        <button
          type="button"
          onClick={() => themeContext?.toggleTheme()}
          aria-label={t('nav.switchTheme')}
          title={t('nav.switchTheme')}
          className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface)] transition-all focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
        >
          <Sun className="hidden dark:block w-4 h-4 text-amber-400" />
          <Moon className="block dark:hidden w-4 h-4 text-slate-600 dark:text-zinc-300" />
        </button>
      </div>
    </header>
  );
}
