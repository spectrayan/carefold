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

export function isColorSupported(): boolean {
  if (process.env.NO_COLOR !== undefined) {
    return false;
  }
  if (process.env.FORCE_COLOR !== undefined && process.env.FORCE_COLOR !== '0') {
    return true;
  }
  if (process.env.TERM === 'dumb') {
    return false;
  }
  return Boolean(process.stdout?.isTTY);
}

export const colors = {
  green: (s: string): string => (isColorSupported() ? `\x1b[32m${s}\x1b[0m` : s),
  yellow: (s: string): string => (isColorSupported() ? `\x1b[33m${s}\x1b[0m` : s),
  red: (s: string): string => (isColorSupported() ? `\x1b[31m${s}\x1b[0m` : s),
  cyan: (s: string): string => (isColorSupported() ? `\x1b[36m${s}\x1b[0m` : s),
  bold: (s: string): string => (isColorSupported() ? `\x1b[1m${s}\x1b[0m` : s),
  dim: (s: string): string => (isColorSupported() ? `\x1b[2m${s}\x1b[0m` : s),
  reset: (s: string): string => (isColorSupported() ? `\x1b[0m${s}` : s)
};

export function formatStatusPill(status: 'PASS' | 'WARN' | 'FAIL'): string {
  switch (status) {
    case 'PASS':
      return colors.green('[PASS]');
    case 'WARN':
      return colors.yellow('[WARN]');
    case 'FAIL':
      return colors.red('[FAIL]');
    default:
      return `[${status}]`;
  }
}
