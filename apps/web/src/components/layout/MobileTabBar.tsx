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
import { Home, MessageSquare, Sparkles, Users, Settings } from 'lucide-react';
import { cn } from '@/lib/utils';

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

  const profileId = React.useMemo(() => {
    if (activeProfileIdProp) return activeProfileIdProp;
    if (activeProfile?.id) return activeProfile.id;
    const match = pathname.match(/^\/p\/([^/]+)/);
    return match ? match[1] : 'me';
  }, [activeProfile?.id, activeProfileIdProp, pathname]);

  const tabs = [
    {
      id: 'home',
      label: 'Home',
      href: `/p/${profileId}`,
      icon: Home,
      exact: true
    },
    {
      id: 'chat',
      label: 'Chat',
      href: `/p/${profileId}/chat`,
      icon: MessageSquare,
      badge: badgeCounts?.chat
    },
    {
      id: 'agents',
      label: 'Agents',
      href: '/agents',
      icon: Sparkles,
      badge: badgeCounts?.agents ?? badgeCounts?.helpers,
      aliasPrefixes: ['/agents', '/helpers', '/skills']
    },
    {
      id: 'family',
      label: 'Family',
      href: '/family',
      icon: Users,
      badge: badgeCounts?.family
    },
    {
      id: 'settings',
      label: 'Settings',
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
