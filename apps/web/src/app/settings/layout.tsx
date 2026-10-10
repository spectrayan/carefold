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
import { Cpu, ShieldCheck, Server, KeyRound, Palette } from 'lucide-react';
import { cn } from '@/lib/utils';

const SETTINGS_NAV_ITEMS = [
  { href: '/settings/model', label: 'Model & Providers', icon: Cpu, testId: 'settings-nav-model' },
  { href: '/settings/privacy', label: 'Privacy & Data', icon: ShieldCheck, testId: 'settings-nav-privacy' },
  { href: '/settings/diagnostics', label: 'Diagnostics & Health', icon: Server, testId: 'settings-nav-diagnostics' },
  { href: '/settings/account', label: 'Account & Security', icon: KeyRound, testId: 'settings-nav-account' },
  { href: '/settings/display', label: 'Appearance & Display', icon: Palette, testId: 'settings-nav-display' },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="max-w-[var(--cf-content-wide)] mx-auto px-3.5 sm:px-6 lg:px-8 py-4 sm:py-6 lg:py-8">
      <div className="mb-4 sm:mb-6">
        <h1 className="text-2xl sm:text-3xl font-display font-bold text-[var(--cf-fg)] tracking-tight">Settings</h1>
        <p className="text-xs sm:text-sm text-[var(--cf-fg-muted)] mt-1">
          Manage local runtime endpoints, patient privacy, diagnostics, and account security.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6 md:gap-8 items-start">
        {/* Desktop Sidebar Navigation (256px / 240px) */}
        <aside className="hidden md:block sticky top-20 bg-[var(--cf-surface)] border border-[var(--cf-border)] rounded-2xl p-3 shadow-sm">
          <nav className="flex flex-col gap-1" aria-label="Settings subpages">
            {SETTINGS_NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href || (item.href === '/settings/model' && pathname === '/settings');
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  data-testid={item.testId}
                  aria-current={isActive ? 'page' : undefined}
                  className={cn(
                    'flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all min-h-[44px] focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)]',
                    isActive
                      ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] font-semibold shadow-sm'
                      : 'text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)]'
                  )}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </aside>

        {/* Mobile Horizontal Tab Navigation */}
        <div className="md:hidden flex overflow-x-auto no-scrollbar touch-pan-x gap-2 pb-2 -mx-3.5 px-3.5 border-b border-[var(--cf-border)] mb-4">
          {SETTINGS_NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href || (item.href === '/settings/model' && pathname === '/settings');
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold whitespace-nowrap min-h-[44px] transition-all focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)] shrink-0',
                  isActive
                    ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] shadow-sm'
                    : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)]'
                )}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>

        {/* Subpage Content Area */}
        <main className="bg-[var(--cf-surface)] border border-[var(--cf-border)] rounded-2xl p-4 sm:p-6 lg:p-8 shadow-sm min-w-0">
          {children}
        </main>
      </div>
    </div>
  );
}
