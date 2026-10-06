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

import type { Metadata } from 'next';
import './globals.css';
import { SafetyDisclaimerBanner } from '@/components/SafetyDisclaimerBanner';
import { Navbar } from '@/components/Navbar';
import { FooterPrivacyNotice } from '@/components/FooterPrivacyNotice';
import { ThemeProvider } from '@/components/ThemeProvider';
import { ThemeScript } from '@/components/ThemeScript';

export const metadata: Metadata = {
  title: 'Carefold — Specialist Health Agents',
  description: 'Local-first runtime and marketplace for specialist health agents (wellness, care navigation, clinic-admin).'
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body className="antialiased min-h-screen flex flex-col bg-slate-50 dark:bg-zinc-950 text-slate-900 dark:text-zinc-100 transition-colors">
        <ThemeProvider>
          <div className="sticky top-0 z-40">
            <SafetyDisclaimerBanner />
            <Navbar />
          </div>
          <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            {children}
          </main>
          <footer className="border-t border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 py-6 mt-auto transition-colors">
            <div className="max-w-7xl mx-auto px-4 text-center text-xs text-slate-500 dark:text-zinc-400 flex flex-col sm:flex-row items-center justify-between gap-3">
              <div>Carefold • Healthcare AI Agent Marketplace • Apache-2.0</div>
              <FooterPrivacyNotice />
            </div>
          </footer>
        </ThemeProvider>
      </body>
    </html>
  );
}
