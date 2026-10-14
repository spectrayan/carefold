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
