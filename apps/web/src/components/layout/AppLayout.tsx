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
import { usePathname } from 'next/navigation';
import { AppRail } from './AppRail';
import { MobileTopBar } from './MobileTopBar';
import { MobileTabBar } from './MobileTabBar';
import { cn } from '@/lib/utils';
import { useI18n } from '@/i18n';

export interface AppLayoutProps {
  children: React.ReactNode;
}

const AUTH_ROUTES = ['/login', '/register', '/forgot-password', '/reset-password'];

export function AppLayout({ children }: AppLayoutProps) {
  const pathname = usePathname();
  const { t } = useI18n();
  const isAuthRoute = AUTH_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`));
  const isChatRoute = pathname === '/chat' || pathname.includes('/chat');

  // Auth pages render without shell chrome
  if (isAuthRoute) {
    return (
      <div className="min-h-screen w-full flex flex-col justify-center items-center bg-[var(--cf-canvas)] p-4 text-[var(--cf-fg)]">
        {children}
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[var(--cf-canvas)] text-[var(--cf-fg)]">
      {/* Accessible skip link */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:px-4 focus:py-2 focus:bg-[var(--cf-surface)] focus:text-[var(--cf-fg)] focus:border focus:border-[var(--cf-border-strong)] focus:rounded-md focus:shadow-md focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 text-sm font-semibold transition-all"
      >
        {t('common.skipToMain') || 'Skip to main content'}
      </a>

      {/* Desktop & Tablet Navigation Rail */}
      <AppRail className="hidden md:flex shrink-0 z-[var(--cf-z-rail)]" />

      {/* Main Content Viewport Area */}
      <div className="flex flex-col flex-1 min-w-0 min-h-0 overflow-hidden">
        {/* Mobile Sticky Top Bar */}
        <MobileTopBar className="md:hidden shrink-0 z-30" />

        {/* Scrollable Main Area (or full-height flex area for chat) */}
        <main
          id="main-content"
          tabIndex={-1}
          className={cn(
            'flex-1 min-h-0 focus:outline-none',
            isChatRoute
              ? 'p-0 overflow-hidden flex flex-col h-full'
              : 'overflow-y-auto px-4 sm:px-6 lg:px-8 py-6'
          )}
        >
          <div className={cn('w-full', isChatRoute ? 'h-full flex flex-col flex-1 min-h-0' : 'mx-auto max-w-7xl')}>
            {children}
          </div>
        </main>

        {/* Mobile Sticky Bottom Tab Bar */}
        <MobileTabBar className="md:hidden shrink-0 z-30" />
      </div>
    </div>
  );
}
