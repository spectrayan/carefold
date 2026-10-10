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

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ChevronDown, Search, Settings, Sun, Moon, LogIn, LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Avatar, type MemberColorSlot } from '@/components/ui/Avatar';
import { ProfileSwitcher } from '@/components/layout/ProfileSwitcher';
import { useOptionalTheme } from '@/components/ThemeProvider';
import { useAuth } from '@/lib/auth';
import { getHouseholdProfile } from '@/lib/familyProfiles';

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
  const { isAuthenticated, logout } = useAuth();
  const [isProfileSwitcherOpen, setIsProfileSwitcherOpen] = React.useState(false);

  // Derive active profile dynamically from household store or URL pathname
  const derivedProfile = React.useMemo(() => {
    if (activeProfileProp) return activeProfileProp;
    const match = pathname.match(/^\/p\/([^/]+)/);
    const profileId = match ? match[1] : 'me';

    const household = getHouseholdProfile(profileId);
    if (household) {
      return {
        id: household.id,
        name: household.name,
        shortName: household.shortName || household.name.split(' ')[0],
        colorSlot: (household.colorSlot || 1) as MemberColorSlot
      };
    }

    return {
      id: profileId,
      name: profileId === 'me' ? 'Me' : profileId,
      shortName: profileId === 'me' ? 'Me' : profileId,
      colorSlot: 1 as MemberColorSlot
    };
  }, [activeProfileProp, pathname]);

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
        href={`/p/${derivedProfile.id}`}
        aria-label="Carefold Home"
        className="min-h-[44px] flex items-center gap-1.5 focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
      >
        <div
          className="w-7 h-7 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center text-white font-bold text-xs shadow-sm shrink-0"
          aria-hidden="true"
        >
          C
        </div>
        <span className="hidden min-[380px]:inline font-bold text-sm text-[var(--cf-fg)] tracking-tight">Carefold</span>
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
        className="flex items-center gap-1.5 min-[380px]:gap-2 h-10 px-2 min-[380px]:px-2.5 py-1 rounded-full bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm hover:bg-[var(--cf-surface-2)] transition-all min-h-[44px] focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)] shrink-0"
      >
        <Avatar
          name={derivedProfile.name}
          colorSlot={derivedProfile.colorSlot || 1}
          size="xs"
        />
        <span className="text-xs min-[380px]:text-sm font-semibold text-[var(--cf-fg)] truncate max-w-[80px] min-[380px]:max-w-[120px]">
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
            aria-label="Search"
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
            aria-label="Sign out"
            title="Sign out"
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-rose-600 hover:bg-[var(--cf-surface)] transition-all focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
          >
            <LogOut className="w-4 h-4" />
          </button>
        ) : (
          <Link
            href="/login"
            aria-label="Sign in"
            title="Sign in"
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-emerald-600 hover:bg-[var(--cf-surface)] transition-all focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
          >
            <LogIn className="w-4 h-4" />
          </Link>
        )}

        {/* Accessible Theme Toggle Button */}
        <button
          type="button"
          onClick={() => themeContext?.toggleTheme()}
          aria-label="Switch to light or dark mode"
          title="Switch to light or dark mode"
          className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface)] transition-all focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
        >
          <Sun className="hidden dark:block w-4 h-4 text-amber-400" />
          <Moon className="block dark:hidden w-4 h-4 text-slate-600 dark:text-zinc-300" />
        </button>
      </div>
    </header>
  );
}
