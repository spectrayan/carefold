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

import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import fsSync from 'node:fs';
import path from 'node:path';

// Establish isolated temporary home and workspace directories for Vitest
const vitestHome = '/tmp/carefold-vitest-home';
process.env.CAREFOLD_HOME = vitestHome;
if (!fsSync.existsSync(vitestHome)) {
  fsSync.mkdirSync(vitestHome, { recursive: true });
  fsSync.mkdirSync(path.join(vitestHome, 'uploads'), { recursive: true });
  fsSync.mkdirSync(path.join(vitestHome, 'logs'), { recursive: true });
}

const vitestWs = '/tmp/carefold-vitest-ws';
process.env.CAREFOLD_WORKSPACE = vitestWs;
if (!fsSync.existsSync(vitestWs)) {
  fsSync.mkdirSync(vitestWs, { recursive: true });
  fsSync.mkdirSync(path.join(vitestWs, 'attachments'), { recursive: true });
  fsSync.mkdirSync(path.join(vitestWs, 'logs'), { recursive: true });
}

// Suppress false-positive React 19 script warning in test environment
const originalConsoleError = console.error;
console.error = (...args: unknown[]) => {
  if (typeof args[0] === 'string' && args[0].includes('Encountered a script tag')) {
    return;
  }
  originalConsoleError(...args);
};

// Mock next/navigation for App Router client components
vi.mock('next/navigation', () => {
  return {
    useRouter: () => ({
      push: vi.fn(),
      replace: vi.fn(),
      prefetch: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn()
    }),
    useSearchParams: () => new URLSearchParams(),
    usePathname: () => '/'
  };
});

// Mock next/font/local for Vitest component tests rendering RootLayout
vi.mock('next/font/local', () => {
  return {
    default: (options?: { variable?: string }) => ({
      className: options?.variable ? `font-${options.variable.replace('--', '')}` : 'font-local',
      variable: options?.variable || '--font-local',
      style: { fontFamily: 'mock-font' },
    }),
  };
});

class MockStorage implements Storage {
  private store: Record<string, string> = {};

  get length(): number {
    return Object.keys(this.store).length;
  }

  clear(): void {
    this.store = {};
  }

  getItem(key: string): string | null {
    return Object.prototype.hasOwnProperty.call(this.store, key) ? this.store[key] : null;
  }

  key(index: number): string | null {
    return Object.keys(this.store)[index] ?? null;
  }

  removeItem(key: string): void {
    delete this.store[key];
  }

  setItem(key: string, value: string): void {
    this.store[key] = String(value);
  }
}

const mockLocalStorage = new MockStorage();

if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'localStorage', {
    value: mockLocalStorage,
    writable: true,
    configurable: true
  });
}

Object.defineProperty(globalThis, 'localStorage', {
  value: mockLocalStorage,
  writable: true,
  configurable: true
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  mockLocalStorage.clear();
});

if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
  });

  // Ensure clipboard API exists in happy-dom with spyable methods
  if (!navigator.clipboard) {
    Object.defineProperty(navigator, 'clipboard', {
      writable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
        readText: vi.fn().mockResolvedValue('')
      }
    });
  }
}
