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
import { Home, MessageSquare, Sparkles, Users, Settings } from 'lucide-react';
import { cn } from '@/lib/utils';
import { profilePath } from '@/lib/routes';
import { useI18n } from '@/i18n';

export interface MobileTabBarProps extends React.HTMLAttributes<HTMLElement> {
  activeProfileId?: string;
  activeProfile?: { id: string };
  badgeCounts?: {
    chat?: number;
    agents?: number;
    helpers?: number;
    family?: number;
  };
}

export function MobileTabBar({
  activeProfileId: activeProfileIdProp,
  activeProfile,
  badgeCounts,
  className,
  ...props
}: MobileTabBarProps) {
  const pathname = usePathname();
  const { t } = useI18n();

  const profileId = React.useMemo(() => {
    if (activeProfileIdProp) return activeProfileIdProp;
    if (activeProfile?.id) return activeProfile.id;
    const match = pathname.match(/^\/p\/([^/]+)/);
    return match ? match[1] : 'me';
  }, [activeProfile?.id, activeProfileIdProp, pathname]);

  const tabs = [
    {
      id: 'home',
      label: t('nav.home'),
      href: profilePath(profileId),
      icon: Home,
      exact: true
    },
    {
      id: 'chat',
      label: t('nav.chatShort'),
      href: profilePath(profileId, '/chat'),
      icon: MessageSquare,
      badge: badgeCounts?.chat
    },
    {
      id: 'agents',
      label: t('nav.agents'),
      href: '/agents',
      icon: Sparkles,
      badge: badgeCounts?.agents ?? badgeCounts?.helpers,
      aliasPrefixes: ['/agents', '/helpers', '/skills']
    },
    {
      id: 'family',
      label: t('nav.familyShort'),
      href: '/family',
      icon: Users,
      badge: badgeCounts?.family
    },
    {
      id: 'settings',
      label: t('nav.settings'),
      href: '/settings',
      icon: Settings,
      aliasPrefixes: ['/settings']
    }
  ];

  const isTabActive = (tab: { href: string; exact?: boolean; aliasPrefixes?: string[] }) => {
    if (tab.exact) {
      return pathname === tab.href;
    }
    if (pathname === tab.href) return true;
    if (tab.aliasPrefixes?.some((prefix) => pathname.startsWith(prefix))) return true;
    return pathname.startsWith(`${tab.href}/`);
  };

  return (
    <nav
      aria-label="Mobile navigation"
      className={cn(
        'sticky bottom-0 left-0 right-0 h-16 shrink-0 bg-[var(--cf-surface)] border-t border-[var(--cf-border)] grid grid-cols-5 items-center px-1 pb-[env(safe-area-inset-bottom)] z-30 transition-colors',
        className
      )}
      {...props}
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const active = isTabActive(tab);
        return (
          <Link
            key={tab.id}
            href={tab.href}
            aria-current={active ? 'page' : undefined}
            className="flex flex-col items-center justify-center min-h-[44px] min-w-[44px] py-1 transition-opacity active:opacity-75 focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]"
          >
            <div
              className={cn(
                'w-12 h-7 rounded-full flex items-center justify-center transition-all',
                active
                  ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] shadow-sm'
                  : 'text-[var(--cf-fg-subtle)]'
              )}
            >
              <Icon className="w-4 h-4" />
            </div>
            <span
              className={cn(
                'text-xs mt-0.5 tracking-tight truncate max-w-[60px]',
                active
                  ? 'font-semibold text-[var(--cf-primary-soft-fg)]'
                  : 'font-medium text-[var(--cf-fg-subtle)]'
              )}
            >
              {tab.label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
