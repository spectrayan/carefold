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
import { usePathname } from 'next/navigation';
import { AppRail } from './AppRail';
import { MobileTopBar } from './MobileTopBar';
import { MobileTabBar } from './MobileTabBar';
import { cn } from '@/lib/utils';

export interface AppLayoutProps {
  children: React.ReactNode;
}

const AUTH_ROUTES = ['/login', '/register', '/forgot-password', '/reset-password'];

export function AppLayout({ children }: AppLayoutProps) {
  const pathname = usePathname();
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
        Skip to main content
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
